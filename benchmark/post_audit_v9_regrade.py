"""Task 8 sweep: CPU-only regrade of the audited v2 trajectories (post-audit v9).

This derived collection tool re-grades every snapshot-bearing trajectory from
the 2026-10-23 full-result audit census with the corrected graders.  It never
starts a model server, never rewrites a record, snapshot, or an earlier
verdict, and never claims a verdict for history the audit did not cover:

- The census is the audit's ``inventory.json`` run list; nothing outside it is
  graded.  Records the audit marked non-regradable stay out of scope.
- Each record is re-verified against the audit's recorded evidence hashes and
  its output manifest's frozen ``immutable`` section.  Any mismatch or unknown
  protocol is reported as review-required instead of being graded.
- Verified legacy records resolve to the historical contract through this
  hash-verified map (Task 5's documented "mapa verificado de hashes"); the
  per-run ``runtime.regrade_episode`` gate stays untouched and stricter.
- Verdicts are appended through ``runtime._regrade_record`` ->
  ``practical_evidence.append_verdict`` under the current grader-source
  version directory, so a crash and a re-run add no duplicate verdicts.
- The legacy v1 evaluations are reused only while their recorded grader
  hashes still match this repository byte for byte.

Outputs: a derived collection directory (never a historical output):
``regrades-j2.jsonl``, ``out-of-scope-records.json``, ``review-required.json``,
``counterexamples-confirmation.json``, ``legacy-v1-reuse.json``, and a
``collection.json`` envelope with full provenance hashes.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import time
from collections import Counter
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark import practical_campaign_v2 as campaign
from benchmark import practical_tasks_v2 as tasks
from benchmark import practical_runtime_v2 as runtime
from benchmark.practical_evidence import verdict_grader_hashes, verdict_version

ROOT = runtime.ROOT
AUDIT_REPORT_DIR = ROOT / "results/reports/full-result-audit-20261023"
CENSUS_PATH = AUDIT_REPORT_DIR / "inventory.json"
PRIOR_REGRADES_PATH = AUDIT_REPORT_DIR / "regrades.jsonl"
SUMMARY_PATH = AUDIT_REPORT_DIR / "summary.json"
LEGACY_PATH = AUDIT_REPORT_DIR / "legacy-v1.json"
COLLECTION_DIR = ROOT / "results/reports/post-audit-v9-repaired-20261024-v2"
PRODUCER_ID = 'post-audit-repaired-v3'

SWEEP_SCHEMA = "post-audit-v9-regrade-sweep-v1"
CONFIRMATION_SCHEMA = "post-audit-v9-counterexamples-v1"
LEGACY_SCHEMA = "post-audit-v9-legacy-reuse-v1"


def _canonical(value: Any) -> str:
    """Compact deterministic JSON, identical to the campaign's hash form."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(text)
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def output_lock(output_dir: Path):
    """One flock per campaign output, mirroring the review-replay lock."""
    output_dir = Path(output_dir)
    with (output_dir / "review-replay.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"output is locked by another session: {output_dir}") from exc
        yield


def load_census(census_path: Path = CENSUS_PATH) -> tuple[dict[str, dict], list[dict]]:
    """The audit inventory: verified outputs by name plus the run list."""
    inventory = json.loads(Path(census_path).read_text(encoding="utf-8"))
    outputs = {Path(item["output"]).name: item for item in inventory.get("outputs", [])}
    return outputs, list(inventory.get("runs", []))


def _output_for_entry(entry: Mapping[str, Any],
                      outputs: Mapping[str, Mapping[str, Any]]) -> tuple[str | None, str | None]:
    """Output name behind a census entry, or a review reason."""
    names = sorted({str(reference.get("output")) for reference in entry.get("references", [])})
    if not names:
        return None, "census entry references no campaign output"
    unknown = [name for name in names if name not in outputs]
    if unknown:
        return None, f"referenced output is outside the audited inventory: {unknown[0]}"
    run_dir = str(entry["run_dir"])
    physical = [name for name in names
                if str(outputs[name].get("output", "")).rstrip("/")
                and run_dir.startswith(str(outputs[name]["output"]).rstrip("/") + "/")]
    if len(physical) == 1:
        return physical[0], None
    return None, f"run_dir does not live under exactly one referenced output: {names}"


def _protocol_note(row: Mapping[str, Any], output: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Verified protocol id: the record's own or the pinned output manifest."""
    recorded = row.get("protocol")
    manifest = _output_manifest(output)
    expected = output.get("protocol") or (manifest or {}).get("protocol_id")
    if recorded is None:
        return expected, "record.json carries no protocol; using the pinned output protocol"
    if str(recorded) != str(expected):
        return None, (f"recorded protocol {recorded!r} does not match the output manifest "
                      f"{expected!r}")
    return str(recorded), None


def _output_manifest(output: Mapping[str, Any]) -> Mapping[str, Any] | None:
    path = Path(output.get("output", ".")) / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verify_census_entry(entry: Mapping[str, Any],
                        outputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Hash-verified grading target for one census run, or a review reason.

    Statuses: ``ok`` (grade it), ``review`` (never grade; problem recorded),
    ``out_of_scope`` (the audit itself marked the run not regradable).
    """
    run_dir = Path(str(entry["run_dir"]))
    if not entry.get("regradable"):
        statuses = {str(reference.get("status")) for reference in entry.get("references", [])}
        failures = {str(reference.get("failure")) for reference in entry.get("references", [])}
        return {"status": "out_of_scope", "run_dir": str(run_dir),
                "census_status": sorted(statuses), "census_failures": sorted(failures)}

    missing_record = None
    evidence_map = entry.get("evidence") or {}
    if not evidence_map:
        return {"status": "review", "run_dir": str(run_dir),
                "problem": "census entry lists no evidence hashes"}
    required = {'record.json','native.jsonl'} | {path.name for path in run_dir.glob('.snapshot*.zip')}
    required |= {name for name in ('execution.json','mcp-journal.json') if (run_dir/name).is_file()}
    if not required <= set(evidence_map):
        return {'status':'review','run_dir':str(run_dir),
                'problem':'grading input missing from census fingerprint map'}
    for name, meta in evidence_map.items():
        if Path(name).name != name or '\\' in name or not isinstance(meta,dict) or not meta.get('sha256'):
            return {'status':'review','run_dir':str(run_dir),'problem':'unsafe census fingerprint entry'}
        if _sha256_file(run_dir / name) != meta.get("sha256"):
            missing_record = name
            break
    if missing_record is not None:
        return {"status": "review", "run_dir": str(run_dir),
                "problem": f"evidence changed since the audit: {missing_record}"}

    try:
        row = json.loads((run_dir / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "review", "run_dir": str(run_dir),
                "problem": f"record.json unreadable: {type(exc).__name__}"}
    recorded_run = row.get("run_dir")
    if recorded_run is not None and str(recorded_run) != str(entry["run_dir"]):
        return {"status": "review", "run_dir": str(run_dir),
                "problem": "record run_dir disagrees with the census"}

    output_name, reason = _output_for_entry(entry, outputs)
    if output_name is None:
        return {"status": "review", "run_dir": str(run_dir), "problem": reason}
    output = outputs[output_name]
    manifest = _output_manifest(output)
    if manifest is None:
        return {"status": "review", "run_dir": str(run_dir),
                "problem": f"manifest.json unreadable for {output_name}"}
    if output.get('manifest_sha256') and _sha256_file(Path(output['output'])/'manifest.json') != output['manifest_sha256']:
        return {'status':'review','run_dir':str(run_dir),'problem':'output manifest differs from audited fingerprint'}
    if output.get("immutable_hash_valid") is not True:
        return {"status": "review", "run_dir": str(run_dir),
                "problem": f"output {output_name} was inventoried with an invalid immutable hash"}
    expected_immutable = campaign._hash_value(manifest.get("immutable", {}))
    if manifest.get("immutable_sha256") != expected_immutable:
        return {"status": "review", "run_dir": str(run_dir),
                "problem": f"output {output_name} immutable section no longer matches its sha256"}

    protocol, note = _protocol_note(row, output)
    if protocol is None:
        return {"status": "review", "run_dir": str(run_dir), "problem": note}

    task = row.get("task")
    if task not in tasks.ALL_TASKS:
        return {"status": "review", "run_dir": str(run_dir),
                "problem": f"record task {task!r} is outside the v2 task catalog"}
    if not list(run_dir.glob(".snapshot*.zip")):
        return {"status": "review", "run_dir": str(run_dir),
                "problem": "no snapshot on disk despite the census marking it regradable"}

    return {"status": "ok", "run_dir": str(run_dir), "row": row, "task": str(task),
            "output_name": output_name, "protocol": str(protocol), "note": note,
            "reference": (entry.get("references") or [{}])[0],
            "output_path": str(output.get("output")), 'census_entry':entry,
            'evidence_hashes':{name:meta['sha256'] for name,meta in evidence_map.items()}}


def _existing_round_verdict(run_dir: Path, *, expected_sources=None,
                            evaluation_producer=None, record=None) -> dict[str, Any] | None:
    """A verdict already appended by this sweep under the current grader set.

    Enables crash-safe resume: the version directory changes whenever a
    grader source changes, so nothing outside this sweep qualifies.
    """
    if expected_sources is None or evaluation_producer is None or record is None:
        return None
    evaluation_dir = Path(run_dir) / "evaluations" / verdict_version()
    try:
        existing = sorted(evaluation_dir.glob("*.json"))
    except OSError:
        return None
    newest = None
    for path in existing:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        verdict = payload.get('verdict')
        if not isinstance(verdict,dict):
            continue
        if (payload.get('grader_hashes') != verdict_grader_hashes()
                or payload.get('source_hashes') != expected_sources
                or payload.get('evaluation_producer') != evaluation_producer
                or verdict.get('task_contract_id') != tasks.HISTORICAL_CONTRACT
                or verdict.get('verdict_profile') != 'main'
                or verdict.get('task') != record.get('task')
                or verdict.get('model') != record.get('model')):
            continue
        if newest is None or payload.get("evaluated_at_utc", "") >= (
                newest[1].get("evaluated_at_utc", "")):
            newest = (path, payload)
    return {"evaluation_path": str(newest[0]), "verdict": newest[1].get("verdict", {})} if newest else None


def _phase_summary(phases: Any) -> list[dict[str, Any]]:
    summary = []
    for phase in phases or []:
        hidden = phase.get("hidden", {}) or {}
        authored = phase.get("authored_tests", {}) or {}
        summary.append({
            "phase": phase.get("phase"),
            "hidden_passed": hidden.get("passed"),
            "hidden_reason": hidden.get("reason"),
            "authored_passed": authored.get("passed"),
            "authored_additional": authored.get("additional_count"),
        })
    return summary


def _ledger_row(entry: Mapping[str, Any], result: Mapping[str, Any],
                prior: Mapping[str, Any] | None) -> dict[str, Any]:
    verdict = result["verdict"]
    correct = verdict.get("correct")
    reference = entry.get("reference") or {}
    return {
        "run_dir": str(entry["run_dir"]),
        "output": entry["output_name"],
        "output_path": entry["output_path"],
        "protocol": entry["protocol"],
        "task": entry["task"],
        "model": verdict.get("model") or reference.get("model"),
        "profile": reference.get("profile"),
        "repetition": reference.get("repetition"),
        "census_status_failure": reference.get("failure"),
        "census_status": reference.get("status"),
        "original_correct": reference.get("correct"),
        "original_autonomous": reference.get("autonomous"),
        "original_failure": reference.get("failure"),
        "task_contract_id": verdict.get("task_contract_id"),
        "verdict_profile": verdict.get("verdict_profile"),
        "regraded_correct": correct,
        "mcp_grade_passed": (verdict.get("mcp_grade") or {}).get("passed"),
        "mcp_grade_reason": (verdict.get("mcp_grade") or {}).get("reason"),
        "phases": _phase_summary(verdict.get("phases")),
        "evaluation_path": result["evaluation_path"],
        "evidence_note": entry.get("note"),
        # Judgments stay derived: the historical record is never rewritten.
        "functional_change_from_original": None if correct is None else (
            None if reference.get("correct") is None
            else bool(correct) != bool(reference.get("correct"))),
        "prior_audit": None if prior is None else {
            "regraded_correct": prior.get("regraded_correct"),
            "evaluation_path": prior.get("evaluation_path"),
            "change_from_prior": None if correct is None else (
                None if prior.get("regraded_correct") is None
                else bool(correct) != bool(prior.get("regraded_correct"))),
        },
    }


def _active_model_servers() -> list[str]:
    servers = []
    for path in Path('/proc').glob('[0-9]*/comm'):
        try:
            if path.read_text().strip() in {'llama-server','llama-server.exe'}:
                servers.append(str(path.parent))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return servers


@contextmanager
def laboratory_admission(*, dry_run=False):
    """Share the runners' global admission, before any evaluation mutation."""
    path = runtime.LAB/'state/practical-round.lock'
    if not path.exists() and dry_run:
        if _active_model_servers():
            raise BlockingIOError('a model server is active')
        yield
        return
    if not dry_run:
        path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('rb' if dry_run else 'a') as admission:
        fcntl.flock(admission,fcntl.LOCK_EX | fcntl.LOCK_NB)
        if _active_model_servers():
            raise BlockingIOError('a model server is active')
        yield


def run_sweep(dry_run: bool = False, census_path: Path = CENSUS_PATH,
              collection_dir: Path | None = COLLECTION_DIR) -> dict[str, Any]:
    try:
        with laboratory_admission(dry_run=dry_run):
            return _run_sweep_admitted(dry_run,census_path,collection_dir)
    except BlockingIOError as exc:
        return {'schema':SWEEP_SCHEMA,'census_run_dirs':0,'counters':{'blocked':1},
                'regraded':[],'review_required':[],'out_of_scope':[],'errors':[],
                'locked_outputs':[f'laboratory admission denied: {exc}'],
                'inference_started':False}


def _run_sweep_admitted(dry_run: bool, census_path: Path,
                        collection_dir: Path | None) -> dict[str, Any]:
    """Verify the audited census and append one verdict per regradable run."""
    started = time.monotonic()
    outputs, runs = load_census(census_path)
    prior = _prior_regrades()
    producer = {'id':PRODUCER_ID, 'module_sha256':_sha256_file(Path(__file__)),
                'census_sha256':_sha256_file(Path(census_path))}
    if collection_dir is not None and (Path(collection_dir)/'collection.json').exists():
        old = json.loads((Path(collection_dir)/'collection.json').read_text())
        if old.get('sealed') and not dry_run:
            raise ValueError('derived collection is sealed; use a new output')
        if old.get('verdict_version') != verdict_version() or old.get('evaluation_producer') != producer:
            raise ValueError('collection is frozen to another grading/producer context; use a new output')

    results: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    out_of_scope: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    locked: list[str] = []
    by_output: dict[str, list[dict[str, Any]]] = {}
    counted: Counter[str] = Counter()

    for entry in runs:
        outcome = verify_census_entry(entry, outputs)
        if outcome["status"] == "ok":
            by_output.setdefault(outcome["output_name"], []).append(outcome)
        elif outcome["status"] == "review":
            reviews.append(outcome)
            counted["review"] += 1
        else:
            out_of_scope.append(outcome)
            counted["out_of_scope"] += 1

    if not dry_run:
        for output_name in sorted(by_output):
            group = by_output[output_name]
            try:
                with output_lock(outputs[output_name]["output"]):
                    for outcome in group:
                        try:
                            outcome = verify_census_entry(outcome['census_entry'],outputs)
                            if outcome['status'] != 'ok':
                                reviews.append(outcome)
                                counted['review'] += 1
                                continue
                            outcome['evaluation_producer'] = producer
                            row = _regrade_and_record(outcome, prior)
                            if row.get('review_required'):
                                reviews.append(row)
                                counted['review'] += 1
                                continue
                            results.append(row)
                            counted["regraded"] += 1
                            if row.get("recovered"):
                                counted["recovered"] += 1
                        except Exception as exc:  # one bad record never stops the sweep
                            errors.append({"run_dir": outcome["run_dir"],
                                           "error": f"{type(exc).__name__}: {exc}"[:400]})
            except (RuntimeError, OSError, ValueError) as exc:
                locked.append(f"{output_name}: {exc}")
    else:
        counted["would_regrade"] = sum(len(group) for group in by_output.values())

    summary = {
        "schema": SWEEP_SCHEMA,
        "recorded_at_utc": _now(),
        "census_path": str(census_path),
        "census_run_dirs": len(runs),
        "outputs_verified_immutables": sorted(outputs),
        "verdict_version": verdict_version(),
        "verdict_grader_hashes": verdict_grader_hashes(),
        "counters": dict(counted),
        "review_required": reviews,
        "out_of_scope": out_of_scope,
        "regraded": results,
        "errors": errors,
        "locked_outputs": locked,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "inference_started": False,
        'evaluation_producer':producer,
    }
    if (not dry_run and collection_dir is not None
            and not ((locked or errors) and (Path(collection_dir)/'collection.json').exists())):
        _write_collection(collection_dir, summary)
    return summary


def _regrade_and_record(outcome: Mapping[str, Any],
                        prior: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    run_dir = Path(outcome["run_dir"])
    existing = _existing_round_verdict(run_dir,
        expected_sources=outcome.get('evidence_hashes'),
        evaluation_producer=outcome.get('evaluation_producer'),record=outcome['row'])
    if existing is not None:
        collected = True
        result = {"run_dir": run_dir, "output_name": outcome["output_name"],
                  "task": outcome["task"], "outcome": outcome,
                  "evaluation_path": existing["evaluation_path"],
                  "verdict": existing["verdict"]}
    else:
        collected = False
        verdict = runtime._regrade_record(
            run_dir, outcome["row"], task_contract_id=tasks.HISTORICAL_CONTRACT,
            verdict_profile="main",evaluation_producer=outcome['evaluation_producer'])
        result = {"run_dir": run_dir, "output_name": outcome["output_name"],
                  "task": outcome["task"], "outcome": outcome,
                  "evaluation_path": verdict.get("evaluation_path"),
                  "verdict": verdict}
    row = _ledger_row(outcome, result, prior.get(str(outcome["run_dir"])))
    verdict = result['verdict']
    invalid = [phase for phase in verdict.get('phases',[]) if
        phase.get('hidden',{}).get('infrastructure') or phase.get('hidden',{}).get('contract_invalid')]
    incomplete = len(verdict.get('phases',[])) != tasks.TASK_SPECS[outcome['task']]['phases']
    if verdict.get('review_required') or verdict.get('correct') is None or invalid or incomplete:
        row.update(review_required=True,regraded_correct=None,
            problem='functional observation incomplete or grader invalid',
            grader_issues=[phase.get('hidden',{}).get('reason') for phase in invalid],
            incomplete_phases=incomplete)
    row["recovered"] = collected
    return row


def _prior_regrades(path: Path = PRIOR_REGRADES_PATH) -> dict[str, Mapping[str, Any]]:
    """The audit's earlier regrade verdicts, keyed by run directory."""
    if not Path(path).is_file():
        return {}
    prior: dict[str, Mapping[str, Any]] = {}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if line:
                row = json.loads(line)
                prior[str(row.get("run_dir"))] = row
    return prior


def _write_collection(collection_dir: Path, summary: Mapping[str, Any]) -> None:
    """Persist sweep ledger and scope files, then register the envelope."""
    collection_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(summary["regraded"], key=lambda row: (row["output"], row["run_dir"]))
    _atomic_write(collection_dir / "regrades-j2.jsonl",
                  "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                          for row in ordered))
    _atomic_write(collection_dir / "out-of-scope-records.json",
                  json.dumps(summary["out_of_scope"], ensure_ascii=False, indent=2,
                             sort_keys=True) + "\n")
    _atomic_write(collection_dir / "review-required.json",
                  json.dumps(summary["review_required"], ensure_ascii=False, indent=2,
                             sort_keys=True) + "\n")
    envelope = {
        "schema": "post-audit-v9-collection-v1",
        "created_at_utc": summary["recorded_at_utc"],
        "census_path": summary["census_path"],
        "census_run_dirs": summary["census_run_dirs"],
        "outputs_verified_immutables": summary["outputs_verified_immutables"],
        "verdict_version": summary["verdict_version"],
        "verdict_grader_hashes": summary["verdict_grader_hashes"],
        "counters": summary["counters"],
        "errors": summary["errors"],
        "locked_outputs": summary["locked_outputs"],
        "elapsed_seconds": summary["elapsed_seconds"],
        "inference_started": False,
        'evaluation_producer':summary['evaluation_producer'],
    }
    _write_envelope(collection_dir, envelope)


def _write_envelope(collection_dir: Path, envelope: Mapping[str, Any]) -> None:
    existing = Path(collection_dir)/'collection.json'
    if existing.exists() and json.loads(existing.read_text()).get('sealed'):
        raise ValueError('derived collection is sealed')
    payload = dict(envelope)
    payload["updated_at_utc"] = _now()
    payload["module_sha256"] = _sha256_file(Path(__file__))
    payload["artifacts"] = _artifact_registry(collection_dir)
    _atomic_write(collection_dir / "collection.json",
                  json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _artifact_registry(collection_dir: Path) -> dict[str, dict[str, Any]]:
    """sha256 and record count of every derived file except the envelope."""
    registry = {}
    for path in sorted(Path(collection_dir).glob("*")):
        if path.name == "collection.json" or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        info: dict[str, Any] = {"sha256": digest}
        try:
            if path.suffix == ".jsonl":
                info["rows"] = sum(1 for line in path.open(encoding="utf-8") if line.strip())
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
                info["records"] = len(payload) if isinstance(payload, list) else 1
        except (OSError, ValueError):
            pass
        registry[path.name] = info
    return registry


def confirm_counterexamples(summary_path: Path = SUMMARY_PATH,
                            collection_dir: Path = COLLECTION_DIR,
                            ledger_name: str = "regrades-j2.jsonl") -> dict[str, Any]:
    """Check the audit's 46 historical positive flags against this regrade.

    Each affected episode should now fail canonical functional grading; the
    historical record keeps its original verdict, and a counterexample the
    corrected graders accept becomes a divergence to explain explicitly.
    """
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    affected = summary.get("affected_positive_episodes") or []
    ledger = Path(collection_dir) / ledger_name
    ledger_rows = _read_ledger(ledger)
    report = {"schema": CONFIRMATION_SCHEMA, "recorded_at_utc": _now(),
              "affected_episode_census": len(affected),
              "confirmed": [], "divergent": [], "unmatched": []}
    for item in affected:
        run_dir = str(item.get("run_dir"))
        row = ledger_rows.get(run_dir)
        if row is None:
            report["unmatched"].append({"run_dir": run_dir, "reasons": item.get("reasons"),
                                        "problem": "no regrade row for this episode"})
            continue
        verdict = {
            "run_dir": run_dir, "task": item.get("task"), "model": item.get("model"),
            "protocol": item.get("protocol"), "repetition": item.get("repetition"),
            "audit_reasons": item.get("reasons"),
            "original_correct": item.get("original_correct",
                                          row.get("original_correct")),
            "original_autonomous": row.get("original_autonomous")
            if item.get("original_autonomous") is None else item.get("original_autonomous"),
            "regraded_correct": row.get("regraded_correct"),
            "mcp_grade_pass": row.get("mcp_grade_passed"),
            "mcp_grade_reason": row.get("mcp_grade_reason"),
            "phase_failures": [phase.get("hidden_reason")
                               for phase in row.get("phases", [])
                               if not phase.get("hidden_passed")],
            "evaluation_path": row.get("evaluation_path"),
        }
        if row.get("regraded_correct") is False:
            report["confirmed"].append(verdict)
        else:
            verdict["needs_explanation"] = (
                "corrected graders still accept this historical positive flag")
            report["divergent"].append(verdict)
    report["counts"] = {"affected": len(affected), "confirmed": len(report["confirmed"]),
                        "divergent": len(report["divergent"]),
                        "unmatched": len(report["unmatched"])}
    _atomic_write(Path(collection_dir) / "counterexamples-confirmation.json",
                  json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if (Path(collection_dir) / "collection.json").is_file():
        envelope = json.loads((Path(collection_dir) / "collection.json").read_text(
            encoding="utf-8"))
        envelope["counterexamples"] = report["counts"]
        _write_envelope(collection_dir, envelope)
    return report


def legacy_v1_reuse_report(legacy_path: Path = LEGACY_PATH,
                           collection_dir: Path = COLLECTION_DIR) -> dict[str, Any]:
    """Reuse the four v1 legacy verdicts only while hashes stay identical.

    The legacy grader sources and every evidence file listed by the audit are
    re-hashed against the audit's records; reuse is refused if any byte moved.
    """
    legacy = json.loads(Path(legacy_path).read_text(encoding="utf-8"))
    wanted = legacy.get("grader_sha256") or {}
    grader_ids = {"practical_selection.py", "practical_tasks.py"} & set(wanted)
    grader_check = {}
    for name in sorted(grader_ids):
        current = _sha256_file(ROOT / "benchmark" / name)
        grader_check[name] = {"recorded": wanted.get(name), "current": current,
                              "identical": current is not None and current == wanted.get(name)}
    grader_identical = (grader_ids == {'practical_selection.py','practical_tasks.py'}
                        and all(value["identical"] for value in grader_check.values()))

    records = []
    for item in legacy.get("records", []):
        evidence_current = {}
        evidence_identical = bool(item.get('evidence_sha256'))
        for rel_path, expected in (item.get("evidence_sha256") or {}).items():
            current = _sha256_file(rel_path)
            match = current is not None and current == expected
            evidence_identical = evidence_identical and match
            evidence_current[rel_path] = match
        reuse = grader_identical and evidence_identical
        records.append({"task": item.get("task"), "model": item.get("model"),
                        "run_dir": item.get("run_dir"),
                        "source_output": item.get("source_output"),
                        "original_correct": item.get("correct"),
                        "original_failure": item.get("failure"),
                        "evidence_hashes": evidence_current,
                        "evidence_identical": evidence_identical,
                        "reused": reuse})
    report = {"schema": LEGACY_SCHEMA, "recorded_at_utc": _now(),
              "legacy_v1_separate_protocol": legacy.get("legacy_v1_separate_protocol"),
              "note": legacy.get("note"),
              "grader_hashes": grader_check,
              "grader_identical": grader_identical,
              "decision": ("reused audited v1 verdicts; no new v1 evaluation"
                           if grader_identical and all(row["evidence_identical"]
                                                       for row in records)
                           else "not reused; would require a new legacy v1 regrade"),
              "records": records}
    _atomic_write(Path(collection_dir) / "legacy-v1-reuse.json",
                  json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if (Path(collection_dir) / "collection.json").is_file():
        envelope = json.loads((Path(collection_dir) / "collection.json").read_text(
            encoding="utf-8"))
        envelope["legacy_v1"] = {
            "decision": report["decision"], "grader_identical": grader_identical,
            "records": len(records),
            "evidence_identical": all(row["evidence_identical"] for row in records)}
        _write_envelope(collection_dir, envelope)
    return report


def _read_ledger(path: Path) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    if not Path(path).is_file():
        return rows
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            rows[str(row.get("run_dir"))] = row
    return rows


TRANSPORT_TARGETS = (
    {"case_id": "qwen-4b-c1-r1-sigterm", "model": "qwen3.5-4b", "task": "C1",
     "repetition": 1, "output": "practical-selection-v2-r1"},
    {"case_id": "bonsai-9b-d2-r1-transport", "model": "bonsai-2-9b", "task": "D2",
     "repetition": 1, "output": "practical-selection-7bplus-repair-r2"},
)

TRANSPORT_SCHEMA = "post-audit-v9-transport-qualifications-v1"


def transport_qualifications(census_path: Path = CENSUS_PATH,
                             collection_dir: Path = COLLECTION_DIR) -> dict[str, Any]:
    """Qualify the audit's two transport-flagged trajectories without inference.

    The audit left two open causes: a Qwen 4B C1 r1 ending by an unrecorded
    SIGTERM and a Bonsai 9B D2 r1 ending in an API socket outage the record
    mislabeled as configuration.  This report re-checks each claim against the
    preserved evidence, renders a derived qualification, and announces no
    success: records keep their original labels.
    """
    _, runs = load_census(census_path)
    episodes: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for target in TRANSPORT_TARGETS:
        episodes[target["case_id"]] = {}
    for entry in runs:
        for reference in entry.get("references", []):
            for target in TRANSPORT_TARGETS:
                # Siblings live in other campaign outputs; identity is
                # model+task+repetition, and the primary is chosen by output.
                # The census lists identical references twice per run: keep one.
                if (reference.get("model"), reference.get("task"),
                        reference.get("repetition")) == (target["model"], target["task"],
                                                         target["repetition"]):
                    episodes[target["case_id"]].setdefault(
                        (str(entry["run_dir"]), str(reference.get("output"))),
                        {"census_entry": entry, "reference": reference})

    report = {"schema": TRANSPORT_SCHEMA, "recorded_at_utc": _now(),
              "inference_started": False,
              "method": ("Derived qualification from hash-verified evidence only; "
                         "no record is reclassified and no success is conferred."),
              "episodes": []}
    for target in TRANSPORT_TARGETS:
        found = list(episodes[target["case_id"]].values())
        primary = next((item for item in found
                        if item["reference"].get("output") == target["output"]), None)
        siblings = [item for item in found
                    if primary is None or item["reference"].get("output") != target["output"]]
        if primary is None:
            episode = {"case_id": target["case_id"], "problem": "census entry not found"}
        else:
            episode = _transport_case(target, primary["reference"], primary["census_entry"])
        episode["sibling_executions"] = [
            {"output": item["reference"].get("output"),
             "run_dir": item["census_entry"]["run_dir"],
             "record_failure": item["reference"].get("failure"),
             "model_calls": item["reference"].get("model_calls"),
             "evidence_files": sorted(item["census_entry"].get("evidence", {}))}
            for item in siblings]
        report["episodes"].append(episode)

    report["counts"] = {"episodes": len(report["episodes"])}
    _atomic_write(Path(collection_dir) / "transport-qualifications.json",
                  json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    envelope_path = Path(collection_dir) / "collection.json"
    envelope = (json.loads(envelope_path.read_text(encoding="utf-8"))
                if envelope_path.is_file() else {"schema": "post-audit-v9-collection-v1"})
    envelope["transport_qualifications"] = report["counts"]
    _write_envelope(collection_dir, envelope)
    return report


def _transport_case(target: Mapping[str, Any], reference: Mapping[str, Any],
                    entry: Mapping[str, Any] | None) -> dict[str, Any]:
    run_dir = Path(str(entry["run_dir"])) if entry else None
    drift = _evidence_matches(entry) if entry is not None else "no census entry"
    record = {} if drift is not None else (_read_json(run_dir / "record.json") or {})
    case = {
        "case_id": target["case_id"],
        "task": target["task"], "model": target["model"], "repetition": target["repetition"],
        "output": target["output"],
        "run_dir": None if run_dir is None else str(run_dir),
        "census_regradable": None if entry is None else bool(entry.get("regradable")),
        "evidence_verified": drift is None,
        "evidence_drift": drift,
        "record_failure": record.get("failure", reference.get("failure")),
        "record_correct": record.get("correct", reference.get("correct")),
        "model_calls": record.get("model_calls", reference.get("model_calls")),
        "agent_finished": record.get("agent_finished"),
        "environment_passed": record.get("environment_passed"),
    }
    if drift is not None:
        return case  # a qualification is never rendered over drifted evidence
    case.update(_transport_facts(target["case_id"], run_dir, record))
    return case


def _transport_facts(case_id: str, run_dir: Path | None,
                     record: Mapping[str, Any]) -> dict[str, Any]:
    """Evidence-shaped measurements for one qualification episode."""
    if run_dir is None or not Path(run_dir).is_dir():
        return {"problem": "episode directory unavailable"}
    facts: dict[str, Any] = {}
    if case_id == "qwen-4b-c1-r1-sigterm":
        native = (Path(run_dir) / "native.jsonl")
        native_bytes = native.stat().st_size if native.is_file() else None
        posts = _broker_posts(run_dir)
        # The record keeps the process resources inside its sandbox section:
        # sandbox.resource_evidence.candidate_returncode (with the sandbox
        # root itself as a tolerated variant).
        sandbox = record.get("sandbox") if isinstance(record.get("sandbox"), dict) else {}
        resources = sandbox.get("resource_evidence")
        resources = resources if isinstance(resources, dict) else sandbox
        snapshots = sorted(path.name for path in Path(run_dir).glob(".snapshot*.zip"))
        facts.update({
            "candidate_returncode": resources.get("candidate_returncode"),
            "recorded_signal_name": ("SIGTERM" if resources.get("candidate_returncode") == -15
                                     else None),
            "native_capture_bytes": native_bytes,
            "broker_chat_posts": posts["posts"],
            "broker_chat_posts_status_200": posts["status_200"],
            "broker_window_utc": posts["window"] or None,
            "snapshots_present": snapshots,
            "deadline_exceeded": record.get("deadline_exceeded"),
            "qualification": ("inconclusive_on_model_code; the agent process ended by "
                              "SIGTERM without a recorded timeout, the native capture "
                              "is empty, and no snapshot exists, so wrong_result never "
                              "had a functional observation"),
        })
        return facts
    events = _native_events(run_dir)
    api_errors = [event.get("error", {}) for event in events if event.get("type") == "error"]
    snapshot_facts = _snapshot_files(run_dir)
    phases = record.get("phases") or []
    authored = (phases[0].get("authored_tests") or {}) if phases else {}
    facts.update({
        "api_error_events": [{
            "name": error.get("name"),
            "message": None if not error.get("data", {}).get("message")
            else str(error["data"]["message"])[:160],
            "retryable": error.get("data", {}).get("isRetryable"),
        } for error in api_errors],
        "native_mcp_tool_events": sum(
            1 for event in events
            if event.get("tool") and "lab_" in str(event.get("tool"))),
        "snapshot_files": snapshot_facts["names"],
        "snapshot_stub_markers": snapshot_facts["stub_markers"],
        "authored_test_count": authored.get("count"),
        "qualification": ("transport_severed_mislabeled_configuration; the episode ended "
                          "when the model API socket closed and was recorded as "
                          "configuration. The preserved snapshot contains unchanged "
                          "stubs and no artifact, and no MCP call was observed, so this "
                          "run never produced a functional result either way"),
        "sibling_note": ("the same identity's other attempts ended at call_limit and "
                         "stay functionally negative; transport explains the missing "
                         "cause of this run only, never a success"),
    })
    return facts


def _broker_posts(run_dir: Path) -> dict[str, Any]:
    """Count the model chat posts that reached the broker upstream."""
    transcript = run_dir / "broker" / "transcript.jsonl"
    posts = status_200 = 0
    first_started: str | None = None
    last_completed: str | None = None
    try:
        for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
            if "/v1/chat/completions" not in line:
                continue
            event = json.loads(line)
            posts += 1
            if event.get("status") == 200:
                status_200 += 1
            started = event.get("upstream_started_utc")
            completed = event.get("completed_utc")
            # Transcript lines are not guaranteed chronological; the window is
            # the earliest post start and the latest post completion.
            if (started is not None and (first_started is None
                                         or str(started) < first_started)):
                first_started = str(started)
            if (completed is not None and (last_completed is None
                                           or str(completed) > last_completed)):
                last_completed = str(completed)
    except (OSError, ValueError):
        return {"posts": posts, "status_200": status_200, "window": []}
    window = [bound for bound in (first_started, last_completed) if bound is not None]
    return {"posts": posts, "status_200": status_200, "window": window}


def _native_events(run_dir: Path) -> list[Mapping[str, Any]]:
    native = run_dir / "native.jsonl"
    if not native.is_file():
        return []
    events = []
    try:
        for line in native.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return events


def _snapshot_files(run_dir: Path) -> dict[str, Any]:
    import zipfile

    names: list[str] = []
    stub_markers = {}
    for path in sorted(Path(run_dir).glob(".snapshot*.zip")):
        try:
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    names.append(name)
                    try:
                        text = archive.read(name).decode("utf-8", errors="replace")
                    except (OSError, ValueError):
                        continue
                    if "not implemented" in text:
                        stub_markers.setdefault(name, []).append(path.name)
        except (OSError, ValueError, zipfile.BadZipFile):
            continue
    return {"names": names, "stub_markers": sorted(stub_markers)}


def _read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _evidence_matches(entry: Mapping[str, Any]) -> str | None:
    """The first census evidence file whose bytes no longer match, or None."""
    run_dir = Path(str(entry["run_dir"]))
    for name, meta in (entry.get("evidence") or {}).items():
        if _sha256_file(run_dir / name) != meta.get("sha256"):
            return str(name)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Post-audit v9 CPU regrade sweep (Task 8); no inference is started.")
    sub = parser.add_subparsers(dest="command")
    sweep = sub.add_parser("sweep", help="verify census, append verdicts, write collection")
    sweep.add_argument("--dry-run", action="store_true",
                       help="verify and count only; write nothing")
    sweep.add_argument("--census", type=Path, default=CENSUS_PATH)
    sweep.add_argument("--collection", type=Path, default=COLLECTION_DIR)
    confirmation_parser = sub.add_parser(
        "counterexamples", help="check the audit's 46 positive flags against this regrade")
    confirmation_parser.add_argument("--collection", type=Path, default=COLLECTION_DIR)
    legacy_parser = sub.add_parser(
        "legacy-v1", help="record the v1 legacy verdict reuse decision")
    legacy_parser.add_argument("--collection", type=Path, default=COLLECTION_DIR)
    transport_parser = sub.add_parser(
        "transport-qualifications",
        help="qualify the two transport-sensitive episodes from preserved evidence")
    transport_parser.add_argument("--census", type=Path, default=CENSUS_PATH)
    transport_parser.add_argument("--collection", type=Path, default=COLLECTION_DIR)
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.error('choose an explicit command (use sweep --dry-run for verification only)')
    command = arguments.command or "sweep"
    if command == "sweep":
        outcome = run_sweep(dry_run=arguments.dry_run, census_path=arguments.census,
                            collection_dir=None if arguments.dry_run else arguments.collection)
    elif command == "counterexamples":
        outcome = confirm_counterexamples(collection_dir=arguments.collection)
    elif command == "legacy-v1":
        outcome = legacy_v1_reuse_report(collection_dir=arguments.collection)
    elif command == "transport-qualifications":
        outcome = transport_qualifications(census_path=arguments.census,
                                           collection_dir=arguments.collection)
    else:
        parser.error(f"unknown command {command!r}")
    print(json.dumps(outcome, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
