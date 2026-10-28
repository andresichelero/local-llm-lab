"""Persistent, source-bound Qwen optimization schedule and evidence-only selection.

No inference at import. A single supervisor must own the output lock before
using Campaign; completed model failures are terminal, never retry candidates.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, allow_nan=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def make_units(
    artifacts,
    stage,
    *,
    contexts=(16384,),
    seeds=(101,),
    tasks=("",),
    harness="direct",
    output_tokens=None,
):
    if output_tokens is not None and (type(output_tokens) is not int or output_tokens < 1):
        raise ValueError("output_tokens must be a positive integer")
    units = []
    for artifact in artifacts:
        for context in contexts:
            for seed in seeds:
                for task in tasks:
                    unit = dict(
                        stage=stage,
                        artifact_id=artifact["artifact_id"],
                        model_id=artifact["model_id"],
                        engine=artifact["engine"],
                        context=context,
                        seed=seed,
                        task=task,
                        harness=harness,
                    )
                    if output_tokens is not None:
                        unit["output_tokens"] = output_tokens
                    unit["unit_id"] = fingerprint(unit)
                    units.append(unit)
    return units


class Campaign:
    def __init__(self, output, immutable):
        self.output = Path(output)
        self.protocol_id = immutable.get("protocol_id")
        self.output.mkdir(parents=True, exist_ok=True)
        self.path = self.output / "state.json"
        manifest = self.output / "manifest.json"
        if manifest.exists():
            prior = json.loads(manifest.read_text())
            if prior.get("input_digest") != fingerprint(prior["immutable"]):
                raise ValueError("manifest digest mismatch")
            if prior["immutable"] != immutable:
                raise ValueError(
                    "immutable campaign inputs changed; use a new protocol/output"
                )
        else:
            write_json(
                manifest,
                dict(
                    immutable=immutable,
                    created_at=now(),
                    input_digest=fingerprint(immutable),
                ),
            )
        self.state = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else dict(units=[], attempts=[], status="prepared")
        )
        for attempt in self.state["attempts"]:
            if attempt["status"] == "running":
                attempt.update(
                    status="interrupted",
                    ended_at=now(),
                    reason="supervisor interrupted; retained evidence",
                )
        for unit in self.state["units"]:
            attempts = [
                a for a in self.state["attempts"] if a["unit_id"] == unit["unit_id"]
            ]
            if len(attempts) >= 3 and not any(
                a["status"] == "finished" for a in attempts
            ):
                self.state["attempts"].append(
                    dict(
                        unit_id=unit["unit_id"],
                        unit=unit,
                        number=len(attempts) + 1,
                        status="finished",
                        ended_at=now(),
                        result={
                            "status": "blocked",
                            "failure": "infrastructure_restart_limit",
                            "model_failure": False,
                            "reason": "three interrupted attempts preserved",
                        },
                    )
                )
        self.save()

    def save(self):
        self.state["updated_at"] = now()
        write_json(self.path, self.state)

    def add(self, units):
        known = {row["unit_id"] for row in self.state["units"]}
        for unit in units:
            if unit["unit_id"] not in known:
                self.state["units"].append(unit)
                known.add(unit["unit_id"])
        self.save()

    def records(self):
        return [row for row in self.state["attempts"] if row["status"] == "finished"]

    def pending(self):
        done = {row["unit_id"] for row in self.records()}
        return [row for row in self.state["units"] if row["unit_id"] not in done]

    def begin(self, unit):
        if any(x["status"] == "running" for x in self.state["attempts"]):
            raise RuntimeError("only one measurement may run at a time")
        if unit not in self.pending():
            raise ValueError("unit is not pending")
        attempt = dict(
            unit_id=unit["unit_id"],
            unit=unit,
            protocol_id=self.protocol_id,
            status="running",
            number=1
            + sum(x["unit_id"] == unit["unit_id"] for x in self.state["attempts"]),
            started_at=now(),
        )
        self.state["attempts"].append(attempt)
        self.state.setdefault("resource_wait", {}).pop(unit["unit_id"], None)
        self.state["status"] = "running"
        self.save()
        return self.output / "units" / unit["unit_id"] / str(attempt["number"])

    def finish(self, unit, result):
        active = self.state["attempts"][-1]
        if active["unit_id"] != unit["unit_id"] or active["status"] != "running":
            raise ValueError("no matching running attempt")
        if result.get("status") not in {
            "complete",
            "model_failure",
            "blocked",
            "resource_blocked",
        }:
            raise ValueError("unclassified unit result")
        active.update(status="finished", result=result, ended_at=now())
        self.save()

    def defer(self, unit, result):
        """Only confirmed transient infrastructure may retry, at most twice."""
        active = self.state["attempts"][-1]
        if active["unit_id"] != unit["unit_id"] or active["status"] != "running":
            raise ValueError("no matching running attempt")
        if active["number"] >= 3:
            return self.finish(
                unit,
                dict(result, status="blocked", failure="infrastructure_restart_limit"),
            )
        active.update(status="retryable_infrastructure", result=result, ended_at=now())
        self.save()

    def wait_resources(self, unit, result, resources):
        active = self.state["attempts"][-1]
        if active["unit_id"] != unit["unit_id"] or active["status"] != "running":
            raise ValueError("no matching running attempt")
        if active["number"] >= 3:
            return self.finish(
                unit,
                dict(result, status="blocked", failure="infrastructure_restart_limit"),
            )
        active.update(status="resource_waiting", result=result, ended_at=now())
        self.state.setdefault("resource_wait", {})[unit["unit_id"]] = resources
        self.save()


def seed_recovery_state(
    source_output,
    recovery_output,
    recovery_protocol_id,
    *,
    requeue_dns_failures=False,
):
    """Seed a fresh output from a stopped queue without rewriting its source."""
    source = Path(source_output).resolve()
    output = Path(recovery_output).absolute()
    manifest_path = source / "manifest.json"
    state_path = source / "state.json"
    if not manifest_path.is_file() or not state_path.is_file():
        raise FileNotFoundError("recovery source must contain manifest.json and state.json")
    if output.exists():
        raise FileExistsError(f"recovery output already exists: {output}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    immutable = manifest.get("immutable")
    if not isinstance(immutable, dict):
        raise ValueError("recovery source manifest has no immutable inputs")
    if manifest.get("input_digest") != fingerprint(immutable):
        raise ValueError("recovery source manifest digest mismatch")
    source_protocol = immutable.get("protocol_id")
    if not source_protocol or source_protocol == recovery_protocol_id:
        raise ValueError("recovery must use a distinct protocol_id")

    source_state_bytes = state_path.read_bytes()
    source_state = json.loads(source_state_bytes)
    if any(row.get("status") == "running" for row in source_state.get("attempts", [])):
        raise ValueError("cannot recover while a source attempt is running")
    if not isinstance(source_state.get("units"), list) or not isinstance(
        source_state.get("attempts"), list
    ):
        raise ValueError("recovery source state is missing units or attempts")

    recovered = copy.deepcopy(source_state)
    requeued_unit_ids = []
    if requeue_dns_failures:
        def is_dns_failure(attempt):
            result = attempt.get("result", {})
            return (
                attempt.get("status") == "finished"
                and result.get("status") == "blocked"
                and result.get("failure") == "unattributed_review"
                and result.get("model_failure") is False
                and "Temporary failure in name resolution"
                in str(result.get("error", ""))
            )

        finished_by_unit = {}
        for attempt in recovered["attempts"]:
            if attempt.get("status") == "finished":
                finished_by_unit.setdefault(attempt["unit_id"], []).append(attempt)
        requeued_unit_ids = sorted(
            unit_id
            for unit_id, attempts in finished_by_unit.items()
            if attempts and all(is_dns_failure(attempt) for attempt in attempts)
        )
        if not requeued_unit_ids:
            raise ValueError("no DNS-only infrastructure attempts are eligible to requeue")
        requeued = set(requeued_unit_ids)
        for attempt in recovered["attempts"]:
            if attempt["unit_id"] in requeued and is_dns_failure(attempt):
                attempt["source_status"] = attempt["status"]
                attempt["recovery_disposition"] = (
                    "requeued_in_distinct_protocol_after_wsl_dns_repair"
                )
                attempt["status"] = "retryable_infrastructure"

    for attempt in recovered["attempts"]:
        attempt.setdefault("protocol_id", source_protocol)
        attempt.setdefault("source_output", str(source))
    recovered["status"] = "recovery_prepared"
    origin = {
        "source_protocol_id": source_protocol,
        "recovery_protocol_id": recovery_protocol_id,
        "source_output": str(source),
        "source_manifest_input_digest": manifest["input_digest"],
        "source_state_sha256": hashlib.sha256(source_state_bytes).hexdigest(),
        "imported_units": len(source_state["units"]),
        "imported_attempts": len(source_state["attempts"]),
        "source_finished_attempts": sum(
            row.get("status") == "finished" for row in source_state["attempts"]
        ),
        "imported_finished_attempts": sum(
            row.get("status") == "finished" for row in recovered["attempts"]
        ),
        "requeued_dns_unit_ids": requeued_unit_ids,
        "requeued_dns_attempts": sum(
            row.get("recovery_disposition")
            == "requeued_in_distinct_protocol_after_wsl_dns_repair"
            for row in recovered["attempts"]
        ),
        "raw_evidence_remains_at_source": True,
        "protocols_are_distinct": True,
    }
    recovered["recovery_origin"] = origin

    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=False, exist_ok=False)
    try:
        write_json(output / "state.json", recovered)
        write_json(output / "recovery-origin.json", origin)
    except Exception:
        for path in output.iterdir():
            if path.is_file():
                path.unlink()
        output.rmdir()
        raise
    return origin


def _finite(row, field):
    value = row.get(field)
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def choose_finalists(rows):
    result = {}
    for model in ("4B", "9B"):
        valid = [
            row
            for row in rows
            if row.get("model_id") == model
            and type(row.get("qualification_passed")) is int
            and 10 <= row["qualification_passed"] <= 12
            and row.get("protocol_valid") is True
            and row.get("context_verified") is True
            and row.get("development_total") == 6
            and type(row.get("development_complete")) is int
            and 1 <= row["development_complete"] <= 6
            and all(
                _finite(row, f)
                for f in (
                    "development_complete",
                    "median_seconds",
                    "max_context",
                    "peak_vram_mib",
                )
            )
            and row["median_seconds"] > 0
            and row["max_context"] >= 16384
        ]
        if not valid:
            result[model] = dict(status="insufficient_evidence")
            continue
        best = max(row["development_complete"] for row in valid)
        efficiency = min(
            (row for row in valid if row["development_complete"] == best),
            key=lambda row: (
                row["median_seconds"],
                row["peak_vram_mib"],
                row["artifact_id"],
            ),
        )
        others = [
            row
            for row in valid
            if row["artifact_id"] != efficiency["artifact_id"]
            and row["development_complete"] >= best - 1
        ]
        context = (
            min(
                others,
                key=lambda row: (
                    -row["max_context"],
                    -row["development_complete"],
                    row["median_seconds"],
                    row["artifact_id"],
                ),
            )
            if others
            else None
        )
        result[model] = dict(
            status="selected" if context else "only_one_eligible",
            efficiency=efficiency,
            context=context,
        )
    return result
