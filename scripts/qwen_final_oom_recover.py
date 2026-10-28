"""Prepare a distinct Qwen recovery after a GPU reserve policy change."""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
from pathlib import Path

from benchmark.qwen_optimization import fingerprint, now, write_json


def _reserve_only(attempt):
    result = attempt.get("result") or {}
    error = str(result.get("error", ""))
    return (
        attempt.get("status") == "finished"
        and result.get("status") == "blocked"
        and result.get("failure") == "fixed_profile_capacity_unavailable"
        and ("model loaded but leaves less than 512 MiB GPU reserve" in error
             or "warmup left less than the frozen 512 MiB GPU reserve" in error)
    ) or (
        attempt.get("status") == "resource_waiting"
        and result.get("failure") == "gpu_reserve_breached_during_episode"
    )


def prepare_recovery(source, destination, protocol_id):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists():
        raise FileExistsError(destination)
    if destination == source:
        raise ValueError("source and destination must differ")
    with (source / "supervisor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads((source / "manifest.json").read_text())
        immutable = manifest["immutable"]
        if manifest.get("input_digest") != fingerprint(immutable):
            raise ValueError("source manifest digest mismatch")
        source_protocol = immutable["protocol_id"]
        if protocol_id == source_protocol:
            raise ValueError("new protocol must differ")
        state_bytes = (source / "state.json").read_bytes()
        state = json.loads(state_bytes)
        by_unit = {}
        for attempt in state["attempts"]:
            by_unit.setdefault(attempt["unit_id"], []).append(attempt)
        requeued = sorted(
            unit_id for unit_id, attempts in by_unit.items()
            if any(_reserve_only(a) for a in attempts)
            and not any(a.get("status") == "finished" and not _reserve_only(a) for a in attempts)
        )
        if not requeued:
            raise ValueError("no reserve-only blocks to requeue")
        archived = [copy.deepcopy(a) for a in state["attempts"] if a["unit_id"] in requeued]
        recovered = copy.deepcopy(state)
        recovered["attempts"] = [a for a in recovered["attempts"] if a["unit_id"] not in requeued]
        for a in recovered["attempts"]:
            a.setdefault("protocol_id", source_protocol)
            a.setdefault("source_output", str(source))
            if a.get("status") == "running":
                a.update(status="interrupted", ended_at=now(), reason="supervisor stopped for new memory policy")
        for unit_id in requeued:
            recovered.setdefault("resource_wait", {}).pop(unit_id, None)
        recovered["status"] = "recovery_prepared"
        origin = {"source_protocol_id": source_protocol, "recovery_protocol_id": protocol_id,
                  "source_output": str(source), "source_manifest_input_digest": manifest["input_digest"],
                  "source_state_sha256": hashlib.sha256(state_bytes).hexdigest(),
                  "requeued_unit_ids": requeued, "requeued_attempts": len(archived),
                  "policy": "only artificial 512 MiB reserve blocks requeued; original attempts remain unchanged",
                  "protocols_are_distinct": True}
        recovered["recovery_origin"] = origin
        destination.mkdir(parents=True, exist_ok=False)
        write_json(destination / "state.json", recovered)
        write_json(destination / "reserve-requeued-history.json", archived)
        write_json(destination / "recovery-origin.json", origin)
        return origin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("protocol_id")
    args = parser.parse_args()
    print(json.dumps(prepare_recovery(args.source, args.destination, args.protocol_id), indent=2))


if __name__ == "__main__":
    main()
