"""Source-bound short comparison of a new model against the local Qwen 9B control."""
from __future__ import annotations

import argparse
import json
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from benchmark import campaign_readiness, model_quality_paired, safe_campaign

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "benchmark/configs/granite-4.2-short-screen-v1.json"
DEFAULT_BENCHMARK_ROOT = Path("/home/foxtrot/local-llm-benchmark")
REQUIRED_MODELS = ("granite-4.2-8b", "qwen3.5-9b")
REQUIRED_TASKS = ("calculator_division", "whitespace_normalization", "dotenv_line_parser")
REQUIRED_BLOCKS = ("granite-4.2-8b", "qwen3.5-9b", "qwen3.5-9b", "granite-4.2-8b")


def validate_screen_config(config: dict[str, Any]) -> None:
    """Fail closed if the candidate, reference, runtime, resources, or schedule drift."""
    if config.get("schema_version") != 1:
        raise ValueError("unsupported candidate-screen schema")
    if config.get("experiment") != "granite-4.2-8b-short-screen-20261017-r1":
        raise ValueError("candidate-screen protocol id is not frozen")
    if config.get("candidate_model") != REQUIRED_MODELS[0] or config.get("reference_model") != REQUIRED_MODELS[1]:
        raise ValueError("candidate-screen model roles changed")
    models = config.get("models")
    if not isinstance(models, dict) or tuple(models) != REQUIRED_MODELS:
        raise ValueError("candidate-screen model contracts changed")
    required_fields = {"role", "alias", "revision", "path", "size_bytes", "sha256"}
    for key, role in zip(REQUIRED_MODELS, ("candidate", "reference"), strict=True):
        contract = models[key]
        if not isinstance(contract, dict) or set(contract) != required_fields or contract.get("role") != role:
            raise ValueError(f"incomplete or unexpected model contract: {key}")
        if (not isinstance(contract["path"], str) or Path(contract["path"]).is_absolute()
                or ".." in Path(contract["path"]).parts):
            raise ValueError(f"model path is not a safe benchmark-root-relative path: {key}")
        if (not isinstance(contract["revision"], str) or len(contract["revision"]) != 40
                or any(char not in "0123456789abcdef" for char in contract["revision"])):
            raise ValueError(f"invalid pinned model revision: {key}")
        if (not isinstance(contract["sha256"], str) or len(contract["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in contract["sha256"])):
            raise ValueError(f"invalid pinned model SHA-256: {key}")
        if type(contract["size_bytes"]) is not int or contract["size_bytes"] <= 0:
            raise ValueError(f"invalid pinned model size: {key}")
    if config["tasks"] != list(REQUIRED_TASKS):
        raise ValueError("candidate-screen task set changed")
    schedule = config.get("schedule", {})
    if (schedule.get("seed") != 1234 or schedule.get("block_models") != list(REQUIRED_BLOCKS)
            or schedule.get("repeats_per_model_task") != 2
            or schedule.get("warmup_count_per_model_session") != 1
            or schedule.get("warmup_excluded_from_denominator") is not True):
        raise ValueError("frozen screen schedule changed")
    generation = config.get("generation", {})
    expected_generation = {
        "temperature": 0, "seed": 1234, "max_output_tokens": 1024,
        "context_tokens": 16384, "kv_cache": "q4_0", "flash_attention": True,
        "reasoning": "off", "prompt_cache": False, "mtp": False, "parallel_slots": 1,
    }
    if generation != expected_generation:
        raise ValueError("candidate-screen generation settings changed")
    runtime = config.get("runtime", {})
    if (runtime.get("harness") != model_quality_paired.HARNESS
            or runtime.get("harness_version") != model_quality_paired.HARNESS_VERSION
            or runtime.get("llama_cpp_revision") != model_quality_paired.RUNTIME_REVISION):
        raise ValueError("candidate-screen runtime pin differs from the installed benchmark runtime")
    base_requirements = json.loads(campaign_readiness.CAMPAIGN_CONFIG.read_text(encoding="utf-8"))[
        "resource_requirements"]
    if config.get("resource_requirements") != base_requirements:
        raise ValueError("candidate-screen resource requirements differ from the approved 7 GiB gate")
    if config.get("round_limit_seconds") != 90 * 60:
        raise ValueError("candidate-screen round limit changed")
    if any(config.get("claims", {}).values()):
        raise ValueError("short-screen claims must remain explicitly limited")


def load_screen_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    validate_screen_config(config)
    return config


def build_screen_schedule(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build 12 rows: three tasks, two repeats, and four ABBA model sessions."""
    validate_screen_config(config)
    repeats_by_model = {model: 0 for model in REQUIRED_MODELS}
    rows: list[dict[str, Any]] = []
    for block, model in enumerate(config["schedule"]["block_models"], start=1):
        repeats_by_model[model] += 1
        repeat = repeats_by_model[model]
        for task in config["tasks"]:
            rows.append({"block": block, "model": model, "task": task,
                         "repeat": repeat, "stage": "measurement"})
    return rows


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


@contextmanager
def _using_model_contracts(contracts: Mapping[str, Mapping[str, Any]]) -> Iterator[None]:
    original = model_quality_paired.MODELS
    model_quality_paired.MODELS = {key: dict(value) for key, value in contracts.items()}
    try:
        yield
    finally:
        model_quality_paired.MODELS = original


def _start_screen_server(benchmark_root: Path, model: str, output_root: Path,
                         contract: Mapping[str, Any]) -> tuple[Any, Path]:
    """Use the canonical server launcher with only this screen's pinned model contract."""
    with _using_model_contracts({model: contract}):
        return safe_campaign._start_server(benchmark_root, model, output_root)


def _profile_for_model(model: str, contracts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    with _using_model_contracts(contracts):
        return model_quality_paired.build_profile(model)


def build_screen_protocol(config: dict[str, Any], *, input_digest: str,
                          readiness_report_path: Path) -> dict[str, Any]:
    validate_screen_config(config)
    source_paths = (
        Path(__file__), CONFIG_PATH, REPO_ROOT / "benchmark/safe_campaign.py",
        REPO_ROOT / "benchmark/campaign_readiness.py", REPO_ROOT / "benchmark/model_quality_paired.py",
        REPO_ROOT / "benchmark/linux_sandbox.py", REPO_ROOT / "benchmark/pristine_grading.py",
    )
    source_sha, dirty = safe_campaign.git_provenance(REPO_ROOT)
    return {
        "schema_version": 1,
        "experiment": config["experiment"],
        "screen_scope": config["screen_scope"],
        "candidate_model": config["candidate_model"],
        "reference_model": config["reference_model"],
        "models": config["models"],
        "tasks": config["tasks"],
        "schedule": build_screen_schedule(config),
        "seed": config["schedule"]["seed"],
        "measured_repeats_per_model_task": config["schedule"]["repeats_per_model_task"],
        "generation": config["generation"],
        "runtime": config["runtime"],
        "resource_requirements": config["resource_requirements"],
        "round_limit_seconds": config["round_limit_seconds"],
        "failure_categories": config["failure_categories"],
        "claims": config["claims"],
        "grader_protocol_version": safe_campaign.GRADER_PROTOCOL_VERSION,
        "candidate_language_contract": safe_campaign.GRADER_PROTOCOL_VERSION,
        "readiness_gate": "READY",
        "readiness_input_digest": input_digest,
        "readiness_report_path": str(readiness_report_path),
        "candidate_config_sha256": campaign_readiness._sha256_file(CONFIG_PATH),
        "source_git_sha": source_sha,
        "source_tree_dirty": dirty,
        "source_file_sha256": {
            path.relative_to(REPO_ROOT).as_posix(): campaign_readiness._sha256_file(path)
            for path in source_paths
        },
        "single_agent_release": "authorized_by_user_request_to_continue_through_inference",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _port_is_free(port: int) -> bool:
    return campaign_readiness._loopback_port_is_free(port)


def execute_candidate_screen(*, benchmark_root: Path = DEFAULT_BENCHMARK_ROOT,
                             output_root: Path, evidence_root: Path) -> dict[str, Any]:
    """Run the fresh no-model gates, then the short ABBA screen on the canonical executor."""
    config = load_screen_config()
    models = config["models"]
    benchmark_root, output_root, evidence_root = (
        Path(benchmark_root).resolve(), Path(output_root).resolve(), Path(evidence_root).resolve()
    )
    if output_root.exists() or evidence_root.exists():
        raise FileExistsError("candidate-screen output and readiness paths must be new")
    ports = (safe_campaign.SERVER_PORT, safe_campaign.BROKER_PORT)
    if not all(_port_is_free(port) for port in ports):
        return {"started": False, "status": "port_occupied", "ports": list(ports)}

    readiness = campaign_readiness.run_current_readiness(
        evidence_dir=evidence_root, benchmark_root=benchmark_root, model_contracts=models)
    current = campaign_readiness.input_hash_manifest(benchmark_root=benchmark_root)
    validation = campaign_readiness.validate_readiness_report(
        readiness, current_input_digest=current["digest"])
    readiness_report_path = evidence_root / "candidate-screen-readiness.json"
    _write_json(readiness_report_path, readiness)
    if not current["complete"] or not validation["ready"] or readiness.get("ready") is not True:
        return {"started": False, "status": "not_ready", "readiness": readiness,
                "validation": validation, "readiness_report_path": str(readiness_report_path)}

    bundle = campaign_readiness._model_bundle_audit(benchmark_root, model_contracts=models)
    if bundle.get("passed") is not True:
        return {"started": False, "status": "model_bundle_or_resource_audit_failed",
                "audit": bundle, "readiness_report_path": str(readiness_report_path)}
    if not all(_port_is_free(port) for port in ports):
        return {"started": False, "status": "port_occupied", "ports": list(ports)}
    fresh = campaign_readiness.input_hash_manifest(benchmark_root=benchmark_root)
    if not fresh["complete"] or fresh["digest"] != current["digest"]:
        return {"started": False, "status": "readiness_stale", "current_input_digest": fresh["digest"]}
    if (not safe_campaign._is_ext4(REPO_ROOT) or not safe_campaign._is_ext4(benchmark_root)
            or not safe_campaign._is_ext4(output_root.parent)):
        return {"started": False, "status": "source_runtime_or_output_not_ext4"}
    output_root.parent.mkdir(parents=True, exist_ok=True)
    disk_reserve = config["resource_requirements"]["minimum_benchmark_disk_bytes"]
    if shutil.disk_usage(output_root.parent).free < disk_reserve:
        return {"started": False, "status": "output_disk_reserve_unavailable"}

    output_root.mkdir(parents=False, exist_ok=False, mode=0o700)
    protocol = build_screen_protocol(config, input_digest=current["digest"],
                                     readiness_report_path=readiness_report_path)
    safe_campaign._json_write(output_root / "protocol.json", protocol)
    safe_campaign._json_write(output_root / "readiness-report.json", readiness)
    records_path = output_root / "records.jsonl"
    records_path.touch(exist_ok=False)
    schedule = build_screen_schedule(config)
    task_count = len(config["tasks"])
    blocks = [schedule[index:index + task_count] for index in range(0, len(schedule), task_count)]
    deadline = time.monotonic() + config["round_limit_seconds"]
    binary = benchmark_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    generation_policy = {
        "temperature": config["generation"]["temperature"],
        "seed": config["generation"]["seed"],
        "max_tokens": config["generation"]["max_output_tokens"],
    }
    profiles = {model: _profile_for_model(model, models) for model in config["models"]}
    model_sessions_started = 0
    for block_index, rows in enumerate(blocks, start=1):
        model = rows[0]["model"]
        contract = models[model]
        session_monitor, session_resource = safe_campaign._resource_monitor_start(
            output_root / "resource-sessions" / f"block-{block_index}",
            run_id=f"{config['experiment']}-block-{block_index}",
            phase_id="model_session", agent_id="llama-server")
        server_process = None
        server_log = output_root / f"server-load-failed-{block_index}.log"
        completed: set[tuple[int, str, str, int]] = set()
        try:
            live_bundle = campaign_readiness._model_bundle_audit(benchmark_root, model_contracts=models)
            if live_bundle.get("passed") is not True:
                raise RuntimeError("model bundle or 7 GiB resource gate changed before model load")
            server_process, server_log = _start_screen_server(
                benchmark_root, model, output_root, contract)
            model_sessions_started += 1
            warmup = {"block": block_index, "model": model, "task": rows[0]["task"],
                      "repeat": 0, "stage": "warmup"}
            safe_campaign._execute_task(
                warmup, install_root=benchmark_root, binary=binary, server_log=server_log,
                output_root=output_root, experiment=config["experiment"],
                session_resource=session_resource, model_contract=contract,
                profile_override=profiles[model], generation_policy=generation_policy)
            for row in rows:
                if time.monotonic() >= deadline:
                    record = {**row, "experiment": config["experiment"], "attempted": False,
                              "denominator_eligible": True, "failure_category": "resource",
                              "infrastructure_error": "screen_round_deadline", "strict_pass": False}
                    safe_campaign._record_jsonl(records_path, record)
                    completed.add((row["block"], row["model"], row["task"], row["repeat"]))
                    continue
                record = safe_campaign._execute_task(
                    row, install_root=benchmark_root, binary=binary, server_log=server_log,
                    output_root=output_root, experiment=config["experiment"],
                    session_resource=session_resource, model_contract=contract,
                    profile_override=profiles[model], generation_policy=generation_policy)
                completed.add((row["block"], row["model"], row["task"], row["repeat"]))
        except Exception as exc:
            for row in rows:
                key = (int(row["block"]), str(row["model"]), str(row["task"]), int(row["repeat"]))
                if key not in completed:
                    safe_campaign._record_jsonl(records_path, {
                        **row, "experiment": config["experiment"], "attempted": False,
                        "denominator_eligible": True, "failure_category": "infrastructure",
                        "infrastructure_error": f"session_{type(exc).__name__}:{str(exc)[:400]}",
                        "strict_pass": False,
                    })
        finally:
            if server_process is not None:
                safe_campaign._stop_server(server_process)
            session_resource = safe_campaign._resource_monitor_stop(session_monitor, session_resource)
            safe_campaign._finalize_session_resource_records(
                records_path, block=block_index, resource=session_resource)
            session_summary = output_root / "resource-sessions" / f"block-{block_index}" / "summary.json"
            session_summary.parent.mkdir(parents=True, exist_ok=True)
            safe_campaign._json_write(session_summary, session_resource)

    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line]
    measured = [row for row in records if row.get("denominator_eligible")]
    summary = {
        "experiment": config["experiment"], "input_digest": current["digest"],
        "measurement_rows": len(measured),
        "strict_passes": sum(row.get("strict_pass") is True for row in measured),
        "failure_categories": {
            category: sum(row.get("failure_category") == category for row in measured)
            for category in config["failure_categories"] + ["passed"]
        },
        "models_loaded": model_sessions_started > 0,
        "model_sessions_started": model_sessions_started,
        "inference_performed": any(int(row.get("model_requests", 0) or 0) > 0 for row in records),
        "model_requests": sum(int(row.get("model_requests", 0) or 0) for row in records),
        "successful_model_responses": sum(
            int(row.get("successful_model_responses", 0) or 0) for row in records),
        "records_path": str(records_path),
        "readiness_report_path": str(readiness_report_path),
    }
    safe_campaign._json_write(output_root / "summary.json", summary)
    return {"started": True, "status": "completed", **summary, "output_root": str(output_root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, default=DEFAULT_BENCHMARK_ROOT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--execute", action="store_true", help="run fresh readiness and the short model screen")
    args = parser.parse_args(argv)
    config = load_screen_config()
    if not args.execute:
        print(json.dumps({"mode": "dry-run", "protocol": config,
                          "schedule": build_screen_schedule(config), "inference_started": False}, indent=2))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = args.output_root or args.benchmark_root / "results/raw" / f"{config['experiment']}-{stamp}"
    evidence_root = args.evidence_root or args.benchmark_root / "results" / f"readiness-{config['experiment']}-{stamp}"
    result = execute_candidate_screen(benchmark_root=args.benchmark_root,
                                      output_root=output_root, evidence_root=evidence_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
