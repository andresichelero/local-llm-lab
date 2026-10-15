"""Canonical source-bound campaign for the six public restricted-Python tasks.

The default command is a no-model dry run. A fresh readiness run is required
before the explicit execute path can launch a pinned model server.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark import campaign_readiness  # noqa: E402
from benchmark.model_quality_paired import MODELS as PINNED_MODELS  # noqa: E402
from benchmark.pristine_grading import GRADER_PROTOCOL_VERSION, TASK_POLICIES  # noqa: E402
from benchmark.provenance import git_provenance  # noqa: E402
from benchmark.run_observer import RunObserver  # noqa: E402

CONFIG_PATH = REPO_ROOT / "benchmark/configs/safe-model-campaign-v1.json"
LANGUAGE_CONTRACT_PATH = REPO_ROOT / "docs/restricted-python-v2.md"
DEFAULT_BENCHMARK_ROOT = Path(os.environ.get("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark"))
TASKS = (
    "calculator_division", "whitespace_normalization", "dotenv_line_parser",
    "config_precedence", "retry_policy", "package_refactor",
)
MODELS = ("qwen3.5-4b", "qwen3.5-9b")
BLOCK_MODELS = ("qwen3.5-4b", "qwen3.5-9b", "qwen3.5-9b", "qwen3.5-4b") * 2
SERVER_PORT = 8080
BROKER_PORT = 18888
CONTEXT_TOKENS = 16384
SEED = 1234
OUTPUT_TOKENS = 1024
TASK_LIMIT_SECONDS = 240
SERVER_LOAD_SECONDS = 180


def _load_config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("grader_protocol_version") != GRADER_PROTOCOL_VERSION:
        raise ValueError("campaign grader protocol does not match trusted grader")
    if payload.get("candidate_language_contract") != GRADER_PROTOCOL_VERSION:
        raise ValueError("campaign language contract does not match trusted grader")
    configured_models = payload.get("models")
    if not isinstance(configured_models, dict) or tuple(configured_models) != MODELS:
        raise ValueError("campaign model order or count is not canonical")
    for key, expected in configured_models.items():
        actual = PINNED_MODELS.get(key)
        if actual is None or any(actual.get(field) != expected.get(field)
                                 for field in ("alias", "revision", "path", "sha256")):
            raise ValueError(f"campaign model contract differs from pinned source: {key}")
    if set(TASK_POLICIES) != set(TASKS):
        raise ValueError("trusted grader task set differs from canonical campaign")
    configured_schedule = payload.get("schedule", {})
    if (configured_schedule.get("block_models") != list(BLOCK_MODELS)
            or configured_schedule.get("repeats_per_model_task") != 4):
        raise ValueError("campaign schedule does not match the frozen four-repeat ABBA design")
    return payload


def build_schedule(*, seed: int = SEED) -> list[dict[str, Any]]:
    """Return 48 measured rows, with one seeded task order repeated in two ABBA cycles."""
    order = list(TASKS)
    random.Random(seed).shuffle(order)
    rows: list[dict[str, Any]] = []
    repeat_by_model = {model: 0 for model in MODELS}
    for block_index, model in enumerate(BLOCK_MODELS, start=1):
        repeat_by_model[model] += 1
        repeat = repeat_by_model[model]
        for task in order:
            rows.append({"block": block_index, "model": model, "task": task,
                         "repeat": repeat, "stage": "measurement"})
    return rows


def frozen_protocol(*, seed: int = SEED,
                    benchmark_root: Path = DEFAULT_BENCHMARK_ROOT) -> dict[str, Any]:
    config = _load_config()
    inputs = campaign_readiness.input_hash_manifest(benchmark_root=benchmark_root)
    source_sha, dirty = git_provenance(REPO_ROOT)
    return {
        "schema_version": 1,
        "experiment": config["experiment"],
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
        "candidate_language_contract": GRADER_PROTOCOL_VERSION,
        "language_contract_document": {
            "path": LANGUAGE_CONTRACT_PATH.relative_to(REPO_ROOT).as_posix(),
            "sha256": campaign_readiness._sha256_file(LANGUAGE_CONTRACT_PATH),
        },
        "scope_note": "six public regression tasks; no generalized CPython claim",
        "models": config["models"], "tasks": list(TASKS),
        "schedule": build_schedule(seed=seed),
        "seed": seed,
        "generation": {"temperature": 0, "seed": seed, "max_output_tokens": OUTPUT_TOKENS},
        "context_tokens": CONTEXT_TOKENS,
        "kv_cache": "q4_0", "flash_attention": True, "reasoning": "off",
        "prompt_cache": False, "mtp": False, "parallel_slots": 1,
        "measured_repeats_per_model_task": 4,
        "warmup": {"count_per_model_session": 1, "excluded_from_denominator": True},
        "runtime": config["runtime"],
        "failure_categories": list(config["failure_categories"]),
        "claims": dict(config["claims"]),
        "input_digest": inputs["digest"], "source_git_sha": source_sha,
        "source_tree_dirty": dirty,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_task_prompt(task: str) -> str:
    if task not in TASKS:
        raise ValueError(f"Unknown canonical task: {task}")
    from benchmark.harness_runner import resolve_task

    _fixture, task_file = resolve_task(task)
    original = task_file.read_text(encoding="utf-8").strip()
    contract = LANGUAGE_CONTRACT_PATH.read_text(encoding="utf-8").strip()
    return original + "\n\n" + contract


def classify_failure(record: dict[str, Any]) -> str:
    if record.get("protocol_error"):
        return "protocol"
    grade = record.get("grade") if isinstance(record.get("grade"), dict) else {}
    evaluation = grade.get("evaluation_status", record.get("evaluation_status"))
    if evaluation in {"unsupported_syntax", "unsupported_language"}:
        return "unsupported_language"
    if evaluation in {"execution_limit", "resource_limit"} or record.get("timed_out") or record.get("output_limited"):
        return "resource"
    if record.get("infrastructure_error") or record.get("infrastructure_failure"):
        return "infrastructure"
    if record.get("agent_exit_code") not in (None, 0):
        return "agent"
    if record.get("workflow_complete") is False and grade.get("success") is True:
        return "agent"
    if record.get("integrity_failure"):
        return "grade"
    if grade.get("success") is not True:
        return "grade"
    return "passed"


def run_current_readiness(*, evidence_dir: Path | None = None,
                          benchmark_root: Path = DEFAULT_BENCHMARK_ROOT) -> dict[str, Any]:
    """Run all current controls against the exact bundle used for execution."""
    return campaign_readiness.run_current_readiness(evidence_dir=evidence_dir,
                                                    benchmark_root=benchmark_root)


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _resource_monitor_start(output_dir: Path, *, run_id: str, phase_id: str,
                            agent_id: str, parent_agent_id: str | None = None) -> tuple[Any, dict[str, Any]]:
    try:
        from benchmark.campaign_observer import ResourceMonitor

        monitor = ResourceMonitor.start(output_dir, run_id=run_id, phase_id=phase_id,
                                        agent_id=agent_id, parent_agent_id=parent_agent_id,
                                        interval=1.0)
        return monitor, {"status": "running", "scope": "system_wide"}
    except Exception as exc:
        return None, {"status": "unavailable", "scope": "system_wide",
                      "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _resource_monitor_stop(monitor: Any, startup: dict[str, Any]) -> dict[str, Any]:
    if monitor is None:
        return startup
    try:
        return monitor.stop()
    except Exception as exc:
        return {"status": "unavailable", "scope": "system_wide",
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    path.chmod(0o700)
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise OSError("observer transcript directory is not private")
    return path


def _record_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        output.flush()
        os.fsync(output.fileno())


def _broker_transcript_status(evidence: dict[str, Any], expected_requests: int) -> str:
    if evidence.get("complete") is True and evidence.get("request_count") == expected_requests:
        return "measured"
    return "unavailable"


def _finalize_session_resource_records(records_path: Path, *, block: int,
                                       resource: dict[str, Any]) -> None:
    """Attach final session-sampler cleanup evidence to each row exactly once."""
    if not records_path.exists():
        return
    rows = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    changed = False
    for row in rows:
        if row.get("block") != block:
            continue
        sampling = row.setdefault("resource_sampling", {})
        if sampling.get("server_session") != resource:
            sampling["server_session"] = resource
            changed = True
        if resource.get("status") != "measured":
            row["failure_category"] = "infrastructure"
            row["strict_pass"] = False
            row["infrastructure_error"] = row.get("infrastructure_error") or "server_session_observation_unavailable"
            changed = True
        run_dir_value = row.get("run_dir")
        if isinstance(run_dir_value, str):
            run_dir = Path(run_dir_value)
            record_path = run_dir / "record.json"
            if record_path.is_file():
                _json_write(record_path, row)
    if not changed:
        return
    temporary = records_path.with_name(f".{records_path.name}.{time.time_ns()}.tmp")
    with temporary.open("x", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, records_path)


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _seed_workspace(task: str, workspace: Path) -> Path:
    from benchmark.harness_runner import resolve_task

    fixture, task_file = resolve_task(task)
    shutil.copytree(fixture, workspace, symlinks=False)
    for path in workspace.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("task fixture contains a symlink")
    return task_file


def _task_prompt_hash_record(task_file: Path) -> dict[str, Any]:
    """Bind the exact trusted task prompt under its repository-relative path."""
    path = task_file.resolve(strict=True)
    return {"category": "task_prompt", "path": path.relative_to(REPO_ROOT.resolve()).as_posix(),
            "file": path}


@contextmanager
def _temporary_profile_copy(profile_path: Path) -> Iterator[Path]:
    """Expose a private generated profile without widening the approved home binds."""
    with tempfile.TemporaryDirectory(prefix="safe-campaign-profile-") as temporary:
        root = Path(temporary).resolve(strict=True)
        home = Path.home().resolve(strict=True)
        repo = REPO_ROOT.resolve(strict=True)
        if (root == home or home in root.parents or root == repo or repo in root.parents):
            raise RuntimeError("generated OpenCode profile temp must be outside home and repository")
        profile_copy = root / "opencode.json"
        profile_copy.write_bytes(profile_path.read_bytes())
        profile_copy.chmod(0o600)
        yield profile_copy.resolve(strict=True)


def _safe_runtime_binds(binary: Path, benchmark_root: Path) -> tuple[Any, ...]:
    return campaign_readiness._runtime_binds(benchmark_root=benchmark_root,
                                              opencode_binary=binary,
                                              include_provider=True)


def _task_source_exports(task: str) -> tuple[str, ...]:
    return tuple(TASK_POLICIES[task]["source_files"] + TASK_POLICIES[task]["test_files"])


def _parse_native_events(raw: bytes, observer: RunObserver, *, model: str, task: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            payload = {"type": "unparsed_output", "text": line[:4000]}
        if not isinstance(payload, dict):
            payload = {"type": "unparsed_output", "value": str(payload)[:4000]}
        name = str(payload.get("type", "unknown"))[:80]
        part = payload.get("part") if isinstance(payload.get("part"), dict) else {}
        tool_name = str(part.get("tool", ""))[:80] or None
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        event_id = observer.record(
            "native_event", source="agent_process",
            details={"event_name": name, "tool_name": tool_name,
                     "event_index": index, "payload_sha256": hashlib.sha256(encoded).hexdigest()[:64]},
        )
        events.append({"observer_event_id": event_id, "event_index": index, "event": payload})
    return events


def _apply_workspace_exports(workspace: Path, outputs: Any, modes: Any,
                              allowed: tuple[str, ...]) -> None:
    if (not isinstance(outputs, dict) or not isinstance(modes, dict)
            or set(outputs) - set(allowed) or set(modes) != set(outputs)):
        raise RuntimeError("sandbox returned workspace paths outside the declared task export allowlist")
    for relative in allowed:
        path = workspace.joinpath(*Path(relative).parts)
        if relative not in outputs:
            # The post-agent state is authoritative: an omitted path may have
            # been removed or refused for an unsafe export. In either case the
            # seeded host copy must not silently survive grading.
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            continue
        content = outputs[relative]
        mode = modes.get(relative)
        if (not isinstance(content, bytes) or type(mode) is not int or not 0 <= mode <= 0o777):
            raise RuntimeError("sandbox workspace export bytes or mode evidence was invalid")
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)


def _workspace_audit_result(audit: Any) -> dict[str, Any]:
    """Require a complete trusted tree comparison and unchanged non-exported files."""
    if isinstance(audit, Mapping):
        audit = dict(audit)
    if not isinstance(audit, dict) or audit.get("complete") is not True:
        return {"status": "unavailable", "passed": False, "reason": "trusted_workspace_audit_unavailable"}
    lists = ("protected_changed", "protected_missing", "unauthorized_extra_paths",
             "missing_exports", "unsafe_paths")
    if any(not isinstance(audit.get(name), list) for name in lists):
        return {"status": "unavailable", "passed": False, "reason": "workspace_audit_schema_invalid"}
    seed = audit.get("seed_inventory")
    final = audit.get("final_inventory")
    if not isinstance(seed, list) or not isinstance(final, list):
        return {"status": "unavailable", "passed": False, "reason": "workspace_inventory_missing"}
    try:
        seed_by_path = {entry["path"]: entry for entry in seed}
        final_by_path = {entry["path"]: entry for entry in final}
        if len(seed_by_path) != len(seed) or len(final_by_path) != len(final):
            raise ValueError("duplicate_path")
    except (KeyError, TypeError, ValueError):
        return {"status": "unavailable", "passed": False, "reason": "workspace_inventory_schema_invalid"}
    failures = {
        name: list(audit[name]) for name in lists if audit[name]
    }
    passed = not failures
    return {"status": "measured", "passed": passed,
            "reason": "workspace_tree_matches_allowed_changes" if passed else "workspace_integrity_violation",
            "failures": failures, "entry_count": audit.get("entry_count"),
            "workspace_audit": audit}


def _grade_row(workspace: Path, task: str, run_dir: Path) -> dict[str, Any]:
    from benchmark.campaign_readiness import run_scoped_grade

    (run_dir / "grade-artifacts").mkdir(exist_ok=False)
    scoped = run_scoped_grade(workspace, task, artifact_dir=run_dir / "grade-artifacts")
    _json_write(run_dir / "trusted-grade.json", scoped)
    return scoped


def _execute_task(row: dict[str, Any], *, install_root: Path, binary: Path,
                  server_log: Path, output_root: Path, experiment: str,
                  session_resource: dict[str, Any] | None = None,
                  model_api_port: int = SERVER_PORT) -> dict[str, Any]:
    from benchmark.linux_sandbox import BrokerPolicy, SandboxSpec, SandboxSupervisor
    from benchmark.model_quality_paired import MODELS as MODEL_CONTRACTS, build_profile

    model_key, task = str(row["model"]), str(row["task"])
    info = MODEL_CONTRACTS[model_key]
    run_name = f"block-{row['block']}-{row['stage']}-{model_key}-{task}-r{row['repeat']}"
    run_dir = output_root / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    workspace = run_dir / "workspace"
    task_file = _seed_workspace(task, workspace)
    profile = build_profile(model_key)
    profile["provider"]["local"]["options"]["baseURL"] = f"http://127.0.0.1:{BROKER_PORT}/v1"
    profile_path = run_dir / "opencode.json"
    _json_write(profile_path, profile)
    prompt = build_task_prompt(task)
    prompt_path = run_dir / "prompt.txt"
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    source_allowlist = list(_task_source_exports(task))
    manifest = {
        "experiment": experiment, "model": model_key, "model_revision": info["revision"],
        "task": task, "repeat": row["repeat"], "stage": row["stage"],
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
        "candidate_language_contract": GRADER_PROTOCOL_VERSION,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "hash_allowlist": [
            _task_prompt_hash_record(task_file),
            {"category": "profile", "path": "opencode.json", "file": profile_path},
            {"category": "prompt", "path": "prompt.txt", "file": prompt_path},
        ],
        "snapshot_hash_allowlist": source_allowlist,
    }
    observer = RunObserver(run_dir, manifest)
    phase = observer.start_phase("initial_agent", source="agent_process")
    observer.snapshot("before_initial_agent", workspace, source="observer")
    task_deadline = time.monotonic() + TASK_LIMIT_SECONDS
    server_offset = server_log.stat().st_size if server_log.exists() else 0
    limits = _agent_limits()
    broker = BrokerPolicy(
        upstream_port=model_api_port, model_allowlist=(info["alias"],),
        output_token_cap=OUTPUT_TOKENS,
        frozen_generation={"temperature": 0, "seed": SEED, "max_tokens": OUTPUT_TOKENS},
        deadline_seconds=min(TASK_LIMIT_SECONDS, 60), max_requests=24,
    )
    from benchmark.linux_sandbox import RuntimeBind

    spec = SandboxSpec(
        argv=("/opt/opencode", "run", "--format", "json", "--pure", "--agent", "build",
              "--model", f"local/{info['alias']}", "--dir", "/workspace", prompt),
        workspace=workspace,
        workspace_exports=_task_source_exports(task),
        runtime_ro=_safe_runtime_binds(binary, install_root),
        env={"OPENCODE_CONFIG": "/opt/opencode.json", "OPENCODE_DISABLE_AUTOUPDATE": "1"},
        limits=limits,
        broker=broker,
        broker_transcript_dir=_private_directory(run_dir / "broker-transcript"),
    )
    agent_monitor, agent_resource = _resource_monitor_start(
        run_dir / "resources-agent", run_id=observer.run_id,
        phase_id="initial_agent", agent_id="opencode")
    grade_monitor = None
    grade_resource: dict[str, Any] = {"status": "unavailable", "reason": "grading_not_started"}
    record_persisted = False
    result: Any = None
    model_requests = 0
    successful_model_responses = 0
    sandbox_evidence_path = run_dir / "sandbox-evidence.json"
    try:
        try:
            with _temporary_profile_copy(profile_path) as profile_bind_path:
                bound_spec = SandboxSpec(
                    argv=spec.argv, workspace=spec.workspace, workspace_exports=spec.workspace_exports,
                    runtime_ro=spec.runtime_ro + (RuntimeBind(profile_bind_path, "/opt/opencode.json"),),
                    env=spec.env, limits=spec.limits, broker=spec.broker,
                    broker_transcript_dir=spec.broker_transcript_dir,
                )
                result = SandboxSupervisor().run(bound_spec)
        finally:
            agent_resource = _resource_monitor_stop(agent_monitor, agent_resource)
        model_requests = sum(event.method == "POST" and event.path == "/v1/chat/completions"
                             and event.outcome == "allowed" for event in result.broker_events)
        successful_model_responses = sum(
            event.method == "POST" and event.path == "/v1/chat/completions"
            and event.outcome == "allowed" and 200 <= event.status < 300
            for event in result.broker_events)
        # Persist the complete supervisor result before audit, export, event parse,
        # or grading can fail. This keeps request counts and raw evidence for every
        # attempted run, including incomplete workspaces and infrastructure faults.
        _json_write(sandbox_evidence_path, {
            "returncode": result.returncode, "timed_out": result.timed_out,
            "cleanup_verified": result.cleanup_verified, "output_limited": result.output_limited,
            "output_bytes": len(result.output), "namespace_evidence": dict(result.namespace_evidence),
            "file_evidence": dict(result.file_evidence), "network_evidence": dict(result.network_evidence),
            "resource_evidence": dict(result.resource_evidence),
            "broker_events": [event.__dict__ for event in result.broker_events],
            "broker_transcript_evidence": dict(result.broker_transcript_evidence),
            "workspace_output_modes": dict(result.workspace_output_modes),
            "workspace_audit": dict(result.workspace_audit),
            "infrastructure_error": result.infrastructure_error,
        })
        (run_dir / "stdout.jsonl").write_bytes(result.output)
        workspace_audit = _workspace_audit_result(dict(result.workspace_audit))
        if workspace_audit.get("status") != "measured":
            raise RuntimeError(str(workspace_audit.get("reason", "workspace_audit_unavailable")))
        _apply_workspace_exports(workspace, result.workspace_outputs,
                                 result.workspace_output_modes, _task_source_exports(task))
        native_events = _parse_native_events(result.output, observer, model=model_key, task=task)
        raw_events = b"".join((json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
                              for item in native_events)
        (run_dir / "native-events.jsonl").write_bytes(raw_events)
        returncode = result.returncode
        sandbox_failed = bool(result.infrastructure_error or result.timed_out or result.output_limited
                              or not result.cleanup_verified or returncode != 0)
        observer.end_phase(phase, "failed" if sandbox_failed else "completed", source="agent_process",
                           details={"exit_code": returncode, "timed_out": result.timed_out,
                                    "evidence_status": "measured" if result.cleanup_verified else "unavailable"})
        observer.snapshot("after_initial_agent", workspace, source="observer")
        grade_phase = observer.start_phase("grading", source="final_grader")
        grade_monitor, grade_resource = _resource_monitor_start(
            run_dir / "resources-grade", run_id=observer.run_id,
            phase_id="grading", agent_id="trusted-grade-worker")
        try:
            grade_scope = _grade_row(workspace, task, run_dir)
        finally:
            grade_resource = _resource_monitor_stop(grade_monitor, grade_resource)
        grade = grade_scope.get("grade", {}) if isinstance(grade_scope.get("grade"), dict) else {}
        observer.end_phase(grade_phase, "completed" if grade_scope.get("status") == "completed" else "failed",
                           source="final_grader", details={"passed": grade.get("success") is True,
                                                           "evidence_status": grade_scope.get("status", "unavailable")})
        protocol_denials = [event.outcome for event in result.broker_events if event.outcome != "allowed"]
        resource_sampling = {"agent": agent_resource, "grading": grade_resource,
                             "server_session": session_resource or
                             {"status": "unavailable", "reason": "session_sampler_not_started"}}
        observer.record("resource_sampling", source="observer",
                        details={"status": "measured" if agent_resource.get("status") == "measured"
                                 and grade_resource.get("status") == "measured" else "unavailable",
                                 "sample_count": int(agent_resource.get("sample_count", 0))
                                 + int(grade_resource.get("sample_count", 0))})
        broker_transcript = dict(result.broker_transcript_evidence)
        transcript_status = _broker_transcript_status(broker_transcript, len(result.broker_events))
        has_model_request = any(event.method == "POST" and event.path == "/v1/chat/completions"
                                for event in result.broker_events)
        observability_incomplete = (
            agent_resource.get("status") != "measured"
            or grade_resource.get("status") != "measured"
            or not session_resource or session_resource.get("status") not in {"running", "measured"}
            or (bool(result.broker_events) and transcript_status != "measured")
        )
        failure_record = {
            "protocol_error": ",".join(protocol_denials) if protocol_denials else None,
            "evaluation_status": ("execution_limit" if grade_scope.get("status") == "resource_limit"
                                  else grade.get("evaluation_status")),
            "timed_out": result.timed_out, "output_limited": result.output_limited,
            "infrastructure_error": result.infrastructure_error or (grade_scope.get("reason")
                                     if grade_scope.get("status") == "infrastructure_failure" else None),
            "agent_exit_code": returncode, "grade": grade,
            "integrity_failure": workspace_audit.get("passed") is not True,
        }
        if workspace_audit.get("passed") is not True:
            grade["success"] = False
            grade["workspace_integrity_passed"] = False
        else:
            grade["workspace_integrity_passed"] = True
        if workspace_audit.get("status") != "measured":
            failure_record["infrastructure_error"] = "trusted_workspace_audit_unavailable"
        if observability_incomplete:
            failure_record["infrastructure_error"] = (failure_record.get("infrastructure_error")
                                                       or "required_observation_unavailable")
        if grade_scope.get("status") != "completed":
            failure_record["infrastructure_failure"] = True
        from benchmark.model_quality_paired import (
            _primary_final_text, _successful_event, _successful_test_event, strict_quality_pass,
        )

        events = [item["event"] for item in native_events]
        usage_evidence = campaign_readiness._opencode_usage_evidence(events)
        tool_events = [event for event in events if event.get("type") == "tool_use"]
        completed_tools = [event for event in tool_events
                           if event.get("part", {}).get("state", {}).get("status") == "completed"]
        completed_bash = [event for event in completed_tools
                          if str(event.get("part", {}).get("tool", "")).lower() in {"bash", "shell"}]
        edit_indices = [index for index, event in enumerate(events)
                        if event.get("type") == "tool_use"
                        and str(event.get("part", {}).get("tool", "")).lower() in {"edit", "write"}
                        and _successful_event(event)]
        test_indices = [index for index, event in enumerate(events)
                        if event.get("type") == "tool_use"
                        and str(event.get("part", {}).get("tool", "")).lower() in {"bash", "shell"}
                        and "unittest" in json.dumps(event.get("part", {}).get("state", {}).get("input", {})).lower()
                        and _successful_test_event(event)]
        last_tool_index = max((index for index, event in enumerate(events)
                               if event.get("type") == "tool_use"), default=-1)
        final_text = _primary_final_text(events)
        final_answer_separate = bool(final_text.strip()) and any(
            index > last_tool_index and event.get("type") == "text"
            and str(event.get("part", {}).get("text", "")).strip()
            for index, event in enumerate(events))
        workflow_complete = (bool(edit_indices) and bool(completed_bash) and bool(test_indices)
                             and max(edit_indices) < max(test_indices) and final_answer_separate
                             and returncode == 0 and not result.timed_out)
        failure_record["workflow_complete"] = workflow_complete
        failure_category = classify_failure(failure_record)
        mode_changes = grade.get("integrity_details", {}).get("mode_changes")
        modes_preserved = isinstance(mode_changes, list) and not mode_changes
        strict_pass = strict_quality_pass(
            grade, modes_preserved=modes_preserved, workflow_complete=workflow_complete,
            tool_round_trip=bool(completed_tools), command_ok=returncode == 0 and not result.timed_out,
        ) and failure_category == "passed" and workspace_audit.get("passed") is True \
            and not observability_incomplete
        source_digest = hashlib.sha256(b"".join(
            (workspace / relative).read_bytes() for relative in _task_source_exports(task)
            if (workspace / relative).is_file())).hexdigest()
        record = {
            **row,
            "experiment": experiment, "attempted": True, "denominator_eligible": row["stage"] == "measurement",
            "model_alias": info["alias"], "model_revision": info["revision"],
            "model_sha256": info["sha256"], "grader_protocol_version": GRADER_PROTOCOL_VERSION,
            "candidate_language_contract": GRADER_PROTOCOL_VERSION,
            "native_event_authority": "untrusted_process_stream",
            "workflow_evidence_not_execution_attestation": True,
            "usage_evidence": usage_evidence,
            "agent_exit_code": returncode, "timed_out": result.timed_out,
            "output_limited": result.output_limited, "cleanup_verified": result.cleanup_verified,
            "infrastructure_error": failure_record.get("infrastructure_error"),
            "grade": grade, "evaluation_status": grade.get("evaluation_status"),
            "failure_category": failure_category,
            "resource_sampling": resource_sampling,
            "broker_transcript_evidence": broker_transcript,
            "broker_transcript_status": transcript_status if has_model_request else "no_model_request",
            "workspace_integrity": workspace_audit,
            "strict_pass": bool(strict_pass), "workflow_complete": workflow_complete,
            "final_answer_separate": final_answer_separate, "modes_preserved": modes_preserved,
            "tool_calls": len(tool_events), "completed_tool_calls": len(completed_tools),
            "model_requests": model_requests,
            "successful_model_responses": successful_model_responses,
            "sandbox_evidence_path": str(sandbox_evidence_path),
            "native_event_count": len(native_events), "native_events_sha256": hashlib.sha256(raw_events).hexdigest(),
            "candidate_workspace_sha256": source_digest,
            "task_wall_seconds": round(time.monotonic() - (task_deadline - TASK_LIMIT_SECONDS), 3),
            "run_dir": str(run_dir), "server_log_path": str(server_log),
            "server_log_segment_sha256": hashlib.sha256(server_log.read_bytes()[server_offset:]).hexdigest()
                if server_log.exists() else None,
        }
        _json_write(run_dir / "record.json", record)
        _record_jsonl(output_root / "records.jsonl", record)
        record_persisted = True
        observer.record("grader_result", source="final_grader",
                        details={"passed": grade.get("success") is True, "result": failure_category,
                                 "evidence_status": grade_scope.get("status", "unavailable")})
        observer.finalize("pass" if record["strict_pass"] else "fail",
                          "complete" if result.cleanup_verified else "incomplete")
        return record
    except Exception as exc:
        agent_resource = _resource_monitor_stop(agent_monitor, agent_resource)
        grade_resource = _resource_monitor_stop(grade_monitor, grade_resource)
        if record_persisted:
            return record
        try:
            observer.end_phase(phase, "failed", source="agent_process",
                               details={"error_type": type(exc).__name__, "evidence_status": "unavailable"})
        except BaseException:
            pass
        failed_output = getattr(result, "output", b"") if result is not None else b""
        record = {**row, "experiment": experiment, "attempted": True,
                  "denominator_eligible": row["stage"] == "measurement", "failure_category": "infrastructure",
                  "infrastructure_error": (getattr(result, "infrastructure_error", None)
                                            or f"{type(exc).__name__}: {str(exc)[:400]}"),
                  "strict_pass": False, "run_dir": str(run_dir),
                  "agent_exit_code": getattr(result, "returncode", None),
                  "timed_out": getattr(result, "timed_out", None),
                  "output_limited": getattr(result, "output_limited", None),
                  "cleanup_verified": getattr(result, "cleanup_verified", None),
                  "model_requests": model_requests,
                  "successful_model_responses": successful_model_responses,
                  "broker_transcript_evidence": (dict(result.broker_transcript_evidence)
                                                 if result is not None else {}),
                  "native_event_count": sum(bool(line.strip()) for line in failed_output.splitlines()),
                  "native_stdout_bytes": len(failed_output),
                  "native_stdout_sha256": hashlib.sha256(failed_output).hexdigest(),
                  "native_stdout_path": str(run_dir / "stdout.jsonl") if (run_dir / "stdout.jsonl").is_file() else None,
                  "sandbox_evidence_path": str(sandbox_evidence_path) if sandbox_evidence_path.is_file() else None,
                  "native_event_authority": "untrusted_process_stream",
                  "workflow_evidence_not_execution_attestation": True,
                  "resource_sampling": {"agent": agent_resource, "grading": grade_resource,
                                        "server_session": session_resource}}
        _json_write(run_dir / "record.json", record)
        _record_jsonl(output_root / "records.jsonl", record)
        try:
            observer.finalize("error", "incomplete", error=type(exc).__name__)
        except BaseException:
            pass
        return record


def _agent_limits() -> Any:
    from benchmark.linux_sandbox import ResourceLimits

    return ResourceLimits(memory_bytes=2 * 1024**3, swap_bytes=512 * 1024**2,
                          cpu_quota_percent=100, cpu_seconds=TASK_LIMIT_SECONDS + 30,
                          pids=96, wall_seconds=TASK_LIMIT_SECONDS, output_bytes=256 * 1024,
                          workspace_bytes=256 * 1024**2, workspace_files=5000,
                          workspace_file_bytes=64 * 1024**2, scratch_bytes=256 * 1024**2,
                          file_bytes=128 * 1024**2, open_files=1024,
                          export_file_bytes=2 * 1024**2, export_total_bytes=8 * 1024**2,
                          rootfs_bytes=32 * 1024**2, startup_seconds=10, stop_grace_seconds=3)


def _start_server(benchmark_root: Path, model: str, output_root: Path) -> tuple[subprocess.Popen[bytes], Path]:
    from benchmark.model_quality_paired import MODELS as MODEL_CONTRACTS, RUNTIME_REVISION, _server_command
    from benchmark.opencode_controlled_probe import _assert_server_bundle, require_runtime_revision

    if not _port_is_free(SERVER_PORT) or not _port_is_free(BROKER_PORT):
        raise RuntimeError("canonical server or broker port is occupied; refusing to attach")
    server = benchmark_root / "tools/llama-bin/llama-server"
    model_path = benchmark_root / MODEL_CONTRACTS[model]["path"]
    model_contract = MODEL_CONTRACTS[model]
    if (model_path.is_symlink() or not model_path.is_file()
            or campaign_readiness._sha256_file(model_path) != model_contract["sha256"]):
        raise RuntimeError(f"pinned model asset failed its content hash: {model}")
    _assert_server_bundle(server, benchmark_root / "tools/llama-bin")
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
           "LD_LIBRARY_PATH": str(benchmark_root / "tools/llama-bin"),
           "HOME": str(benchmark_root), "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
    version = subprocess.run([str(server), "--version"], env=env, capture_output=True,
                             text=True, timeout=10, check=False)
    if version.returncode != 0:
        raise RuntimeError("pinned llama-server version query failed")
    require_runtime_revision(version.stdout, version.stderr, RUNTIME_REVISION[:10])
    log_path = output_root / f"llama-server-{model}-{time.time_ns()}.log"
    output = log_path.open("xb")
    try:
        process = subprocess.Popen(_server_command(server, model_path, model), env=env,
                                   stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                   close_fds=True, start_new_session=True)
    except BaseException:
        output.close()
        raise
    deadline = time.monotonic() + SERVER_LOAD_SECONDS
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"owned llama-server exited during model load: {process.returncode}")
            if _port_has_model(model, timeout=1):
                return process, log_path
            time.sleep(1)
        raise TimeoutError("owned llama-server did not load the pinned model before its deadline")
    except BaseException:
        _stop_server(process)
        raise
    finally:
        output.close()


def _port_has_model(model: str, *, timeout: float) -> bool:
    from benchmark.model_quality_paired import MODELS as MODEL_CONTRACTS

    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{SERVER_PORT}/v1/models", timeout=timeout) as response:
            payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
        return response.status == 200 and any(item.get("id") == MODEL_CONTRACTS[model]["alias"]
                                              for item in payload.get("data", []))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def _stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, 15)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, 9)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def _is_ext4(path: Path) -> bool:
    probe = path if path.exists() else path.parent
    try:
        result = subprocess.run(["findmnt", "-n", "-o", "FSTYPE", "-T", str(probe)],
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "ext4"


def execute_campaign(*, benchmark_root: Path = DEFAULT_BENCHMARK_ROOT,
                     output_root: Path, readiness_runner: Any = None) -> dict[str, Any]:
    """Run fresh gates, then execute the frozen 4-session ABBA campaign."""
    benchmark_root = Path(benchmark_root).resolve()
    output_root = Path(output_root).resolve()
    if output_root.exists():
        raise FileExistsError(f"Refusing to overwrite existing campaign output: {output_root}")
    if not _port_is_free(SERVER_PORT) or not _port_is_free(BROKER_PORT):
        return {"started": False, "status": "port_occupied", "ports": [SERVER_PORT, BROKER_PORT]}
    readiness = (readiness_runner or run_current_readiness)(benchmark_root=benchmark_root)
    current = campaign_readiness.input_hash_manifest(benchmark_root=benchmark_root)
    validated = campaign_readiness.validate_readiness_report(readiness, current_input_digest=current["digest"])
    if not validated["ready"]:
        return {"started": False, "status": "not_ready", "readiness": readiness,
                "validation": validated, "current_input_digest": current["digest"]}
    bundle = campaign_readiness._model_bundle_audit(benchmark_root)
    if bundle.get("passed") is not True:
        return {"started": False, "status": "model_bundle_or_resource_audit_failed", "audit": bundle}
    # Recheck once more after the full no-model gate and immediately before any server load.
    if not _port_is_free(SERVER_PORT) or not _port_is_free(BROKER_PORT):
        return {"started": False, "status": "port_occupied", "ports": [SERVER_PORT, BROKER_PORT]}
    fresh = campaign_readiness.input_hash_manifest(benchmark_root=benchmark_root)
    if not fresh["complete"] or fresh["digest"] != current["digest"]:
        return {"started": False, "status": "readiness_stale", "current_input_digest": fresh["digest"]}
    output_root.parent.mkdir(parents=True, exist_ok=True)
    if not _is_ext4(output_root.parent):
        return {"started": False, "status": "output_filesystem_not_ext4"}
    if shutil.disk_usage(output_root.parent).free < 8 * 1024**3:
        return {"started": False, "status": "output_disk_reserve_unavailable"}
    output_root.mkdir(parents=False, exist_ok=False)
    protocol = frozen_protocol(seed=SEED, benchmark_root=benchmark_root)
    protocol["readiness_input_digest"] = current["digest"]
    protocol["readiness_gate"] = "READY"
    protocol["started_at_utc"] = datetime.now(timezone.utc).isoformat()
    _json_write(output_root / "protocol.json", protocol)
    _json_write(output_root / "readiness-report.json", readiness)
    records_path = output_root / "records.jsonl"
    records_path.touch(exist_ok=False)
    experiment = protocol["experiment"]
    schedule = build_schedule(seed=SEED)
    block_rows = [schedule[index * len(TASKS):(index + 1) * len(TASKS)]
                  for index in range(len(BLOCK_MODELS))]
    model_sessions_started = 0
    model_requests = 0
    for block_index, rows in enumerate(block_rows, start=1):
        model = rows[0]["model"]
        server_process: subprocess.Popen[bytes] | None = None
        server_log = output_root / f"server-load-failed-{block_index}.log"
        session_monitor, session_resource = _resource_monitor_start(
            output_root / "resource-sessions" / f"block-{block_index}",
            run_id=f"{experiment}-block-{block_index}", phase_id="model_session",
            agent_id="llama-server")
        completed_rows: set[tuple[int, str, str, int]] = set()
        try:
            server_process, server_log = _start_server(benchmark_root, model, output_root)
            model_sessions_started += 1
            warmup = {"block": block_index, "model": model, "task": rows[0]["task"],
                      "repeat": 0, "stage": "warmup"}
            warmup_record = _execute_task(warmup, install_root=benchmark_root,
                                          binary=benchmark_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode",
                                          server_log=server_log, output_root=output_root, experiment=experiment,
                                          session_resource=session_resource)
            model_requests += int(warmup_record.get("model_requests", 0))
            for row in rows:
                record = _execute_task(row, install_root=benchmark_root,
                                       binary=benchmark_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode",
                                       server_log=server_log, output_root=output_root, experiment=experiment,
                                       session_resource=session_resource)
                completed_rows.add((int(row["block"]), str(row["model"]), str(row["task"]), int(row["repeat"])))
                model_requests += int(record.get("model_requests", 0))
        except Exception as exc:
            for row in rows:
                key = (int(row["block"]), str(row["model"]), str(row["task"]), int(row["repeat"]))
                if key in completed_rows:
                    continue
                fail = {**row, "experiment": experiment, "attempted": False,
                        "denominator_eligible": True, "failure_category": "infrastructure",
                        "infrastructure_error": f"session_{type(exc).__name__}: {str(exc)[:400]}",
                        "strict_pass": False}
                _record_jsonl(records_path, fail)
        finally:
            if server_process is not None:
                _stop_server(server_process)
            session_resource = _resource_monitor_stop(session_monitor, session_resource)
            _finalize_session_resource_records(records_path, block=block_index, resource=session_resource)
            (output_root / "resource-sessions" / f"block-{block_index}").mkdir(
                parents=True, exist_ok=True)
            _json_write(output_root / "resource-sessions" / f"block-{block_index}" / "summary.json",
                        session_resource)
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    measured = [row for row in records if row.get("denominator_eligible")]
    summary = {"experiment": experiment, "input_digest": current["digest"],
               "measurement_rows": len(measured),
               "strict_passes": sum(row.get("strict_pass") is True for row in measured),
               "failure_categories": {category: sum(row.get("failure_category") == category for row in measured)
                                      for category in protocol["failure_categories"] + ["passed"]},
               "models_loaded": model_sessions_started > 0,
               "model_sessions_started": model_sessions_started,
               "inference_performed": model_requests > 0,
               "model_requests": model_requests,
               "successful_model_responses": sum(
                   int(row.get("successful_model_responses", 0) or 0) for row in records),
               "records_path": str(records_path)}
    _json_write(output_root / "summary.json", summary)
    return {"started": True, "status": "completed", **summary, "output_root": str(output_root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="show the frozen campaign without model execution")
    mode.add_argument("--readiness", action="store_true", help="run fresh no-model readiness controls")
    mode.add_argument("--execute", action="store_true", help="run readiness, then explicitly execute the campaign")
    parser.add_argument("--benchmark-root", type=Path, default=DEFAULT_BENCHMARK_ROOT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args(argv)
    if args.readiness:
        report = run_current_readiness(evidence_dir=args.evidence_root, benchmark_root=args.benchmark_root)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report.get("ready") else 2
    if args.execute:
        if args.output_root is None:
            parser.error("--execute requires --output-root")
        result = execute_campaign(benchmark_root=args.benchmark_root, output_root=args.output_root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("status") == "completed" else 2
    protocol = frozen_protocol(benchmark_root=args.benchmark_root)
    print(json.dumps({"mode": "dry-run", "ready_check_required_before_execute": True,
                      "protocol": protocol}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
