"""Five-task MiniCPM5 exploratory screen; not a comparative quality campaign."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark import campaign_readiness, safe_campaign  # noqa: E402
from benchmark.provenance import git_provenance  # noqa: E402

EXPERIMENT = "minicpm5-2b-five-task-screen-20261016-v1"
MODEL_KEY = "minicpm5-2b"
MODEL = {
    "alias": "MiniCPM5-2B-Q4_K_M",
    "revision": "2079a22f3beaa4e306449978533478fe0522f4b3",
    "path": "models/gguf/minicpm5-2b/MiniCPM5-2B-Q4_K_M.gguf",
    "sha256": "ec2d5801640099e97d8d7e8003ad4d81f336e757811f03a26173dddf386602fd",
    "size_bytes": 1561318368,
}
GENERATION = {
    "temperature": 1.0,
    "top_p": 0.95,
    "min_p": 0.0,
    "seed": 1234,
    "max_tokens": 1024,
}
CONTEXT_TOKENS = 8192
TASKS = (
    "config_precedence",
    "dotenv_line_parser",
    "package_refactor",
    "retry_policy",
    "whitespace_normalization",
)
WARMUP_TASK = "whitespace_normalization"
AGENT_STEPS = 20
SERVER_PORT = 8080
BROKER_PORT = 18888
MINIMUM_FREE_VRAM_MIB = 7168
DEFAULT_BENCHMARK_ROOT = Path("/home/foxtrot/local-llm-benchmark")
SERVER_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
    "HOME": str(DEFAULT_BENCHMARK_ROOT),
    "TMPDIR": "/tmp",
    "LANG": "C.UTF-8",
}


def build_rows() -> list[dict[str, Any]]:
    """One excluded warmup followed by one exploratory measurement per task."""
    rows = [{"block": 1, "stage": "warmup", "model": MODEL_KEY,
             "task": WARMUP_TASK, "repeat": 0}]
    for block, task in enumerate(TASKS, start=2):
        rows.append({"block": block, "stage": "measurement", "model": MODEL_KEY,
                     "task": task, "repeat": 1})
    return rows


def build_profile() -> dict[str, Any]:
    """Use the already-reviewed isolated OpenCode permissions with MiniCPM settings."""
    from benchmark.model_quality_paired import build_profile as build_qwen_profile

    profile = build_qwen_profile("qwen3.5-4b")
    profile["agent"]["build"]["steps"] = AGENT_STEPS
    alias = MODEL["alias"]
    profile["model"] = f"local/{alias}"
    profile["provider"]["local"]["options"]["baseURL"] = f"http://127.0.0.1:{BROKER_PORT}/v1"
    profile["provider"]["local"]["models"] = {
        alias: {
            "name": alias,
            "limit": {"context": CONTEXT_TOKENS, "output": GENERATION["max_tokens"]},
            "options": {key: value for key, value in GENERATION.items() if key != "max_tokens"},
        }
    }
    return profile


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                                allow_nan=False) + "\n", encoding="utf-8")


def _assert_no_symlink_path(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    for item in (absolute, *absolute.parents):
        if item.is_symlink():
            raise RuntimeError(f"symlink_path_refused: {item}")


def _gpu_free_mib() -> int:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10, check=True,
    )
    values = [int(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    if not values:
        raise RuntimeError("gpu_memory_unavailable")
    return max(values)


def _verify_model(benchmark_root: Path) -> Path:
    path = benchmark_root / MODEL["path"]
    _assert_no_symlink_path(path)
    if not path.is_file() or path.stat().st_size != MODEL["size_bytes"]:
        raise RuntimeError("pinned_model_file_missing_or_wrong_size")
    if campaign_readiness._sha256_file(path) != MODEL["sha256"]:
        raise RuntimeError("pinned_model_sha256_mismatch")
    return path


def _verify_effective_profile(binary: Path, install_root: Path, profile: dict[str, Any],
                              output_root: Path) -> dict[str, Any]:
    from benchmark.harness_runner import _isolated_environment
    from benchmark.model_quality_paired import _permission_profile_checks

    run_dir = output_root / "profile-preflight"
    home = run_dir / "home"
    temp = run_dir / "tmp"
    workspace = run_dir / "workspace"
    config_dir = home / ".config/opencode"
    for directory in (config_dir, temp, workspace):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile_path = config_dir / "opencode.json"
    _write_json(profile_path, profile)
    env = _isolated_environment("opencode", run_dir, install_root, workspace)
    env["OPENCODE_CONFIG"] = str(profile_path)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    config = subprocess.run([str(binary), "debug", "config", "--pure"], env=env,
                            capture_output=True, text=True, timeout=25, check=False)
    agent = subprocess.run([str(binary), "debug", "agent", "build", "--pure"], env=env,
                           capture_output=True, text=True, timeout=25, check=False)
    if config.returncode or agent.returncode:
        raise RuntimeError("opencode_profile_inspection_failed")
    effective = json.loads(config.stdout)
    effective_agent = json.loads(agent.stdout)
    local = effective.get("provider", {}).get("local", {})
    models = local.get("models", {})
    options = models.get(MODEL["alias"], {}).get("options", {})
    expected_options = {key: value for key, value in GENERATION.items() if key != "max_tokens"}
    option_checks = {key: options.get(key) == value for key, value in expected_options.items()}
    permission_checks = _permission_profile_checks(
        effective_agent.get("permission", []), str(home), str(temp))
    checks = {
        "broker_endpoint": local.get("options", {}).get("baseURL") == f"http://127.0.0.1:{BROKER_PORT}/v1",
        "contracted_model_only": set(models) == {MODEL["alias"]},
        "context_tokens": models.get(MODEL["alias"], {}).get("limit", {}).get("context") == CONTEXT_TOKENS,
        "output_token_cap": models.get(MODEL["alias"], {}).get("limit", {}).get("output") == GENERATION["max_tokens"],
        "autoupdate_disabled": effective.get("autoupdate") is False,
        "single_agent_only": effective.get("subagent_depth") == 0 and set(effective.get("agent", {})) == {"build"},
        "primary_agent": effective_agent.get("mode") == "primary",
        "primary_agent_step_cap": effective_agent.get("steps") == AGENT_STEPS,
        "generation_options": all(option_checks.values()),
        **permission_checks,
    }
    evidence = {"passed": all(checks.values()), "checks": checks,
                "effective_generation": {key: options.get(key) for key in expected_options},
                "effective_model": models.get(MODEL["alias"], {}).get("name")}
    _write_json(output_root / "effective-profile.json", evidence)
    if not evidence["passed"]:
        raise RuntimeError("opencode_effective_profile_does_not_match_frozen_policy")
    return evidence


def _server_command(server: Path, model_path: Path) -> list[str]:
    return [
        str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(SERVER_PORT),
        "--alias", MODEL["alias"], "--n-gpu-layers", "99", "--ctx-size", str(CONTEXT_TOKENS),
        "--batch-size", "512", "--ubatch-size", "256", "--jinja", "--reasoning", "off",
        "--flash-attn", "on", "--cache-type-k", "q4_0", "--cache-type-v", "q4_0",
        "--no-cache-prompt", "--parallel", "1", "--temp", str(GENERATION["temperature"]),
        "--top-p", str(GENERATION["top_p"]), "--min-p", str(GENERATION["min_p"]),
        "--seed", str(GENERATION["seed"]), "--no-webui", "--log-timestamps",
    ]


def _wait_model(alias: str, deadline: float) -> bool:
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{SERVER_PORT}/v1/models", timeout=2) as response:
                payload = json.loads(response.read(256 * 1024))
            if response.status == 200 and any(item.get("id") == alias for item in payload.get("data", [])):
                return True
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.5)
    return False


def _start_server(benchmark_root: Path, output_root: Path, model_path: Path) -> tuple[subprocess.Popen[bytes], Path, list[str]]:
    from benchmark.model_quality_paired import RUNTIME_REVISION
    from benchmark.opencode_controlled_probe import _assert_server_bundle, require_runtime_revision

    if not all(safe_campaign._port_is_free(port) for port in (SERVER_PORT, BROKER_PORT)):
        raise RuntimeError("required_server_or_broker_port_occupied")
    server = benchmark_root / "tools/llama-bin/llama-server"
    server_env = {**SERVER_ENV, "LD_LIBRARY_PATH": str(benchmark_root / "tools/llama-bin")}
    _assert_no_symlink_path(server)
    _assert_server_bundle(server, benchmark_root / "tools/llama-bin")
    version = subprocess.run([str(server), "--version"], env=server_env,
                             capture_output=True, text=True, timeout=10, check=False)
    if version.returncode:
        raise RuntimeError("pinned_llama_server_version_query_failed")
    require_runtime_revision(version.stdout, version.stderr, RUNTIME_REVISION[:9])
    argv = _server_command(server, model_path)
    command_path = output_root / "server-command.json"
    _write_json(command_path, {"argv": argv, "runtime_revision": RUNTIME_REVISION,
                               "model_sha256": MODEL["sha256"], "context_tokens": CONTEXT_TOKENS})
    log_path = output_root / "llama-server.log"
    with log_path.open("xb") as log:
        process = subprocess.Popen(argv, env=server_env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, close_fds=True,
                                   start_new_session=True, cwd=benchmark_root)
    try:
        if not _wait_model(MODEL["alias"], time.monotonic() + 150):
            raise TimeoutError("pinned_minicpm_server_not_ready_within_150_seconds")
        return process, log_path, argv
    except BaseException:
        safe_campaign._stop_server(process)
        raise


def _preflight(benchmark_root: Path, output_root: Path) -> tuple[Path, Path]:
    from benchmark.opencode_controlled_probe import _assert_free_resources

    _assert_no_symlink_path(benchmark_root)
    _assert_no_symlink_path(output_root)
    if not benchmark_root.is_dir() or not safe_campaign._is_ext4(benchmark_root):
        raise RuntimeError("benchmark_root_must_be_ext4")
    if output_root.exists() or not output_root.parent.is_dir() or not safe_campaign._is_ext4(output_root.parent):
        raise RuntimeError("output_must_be_new_and_on_ext4")
    if shutil_disk_free(output_root.parent) < 8 * 1024**3:
        raise RuntimeError("eight_gib_disk_reserve_unavailable")
    _assert_free_resources(output_root.parent)
    gpu_free = _gpu_free_mib()
    if gpu_free < MINIMUM_FREE_VRAM_MIB:
        raise RuntimeError(f"minimum_free_vram_not_met:{gpu_free}MiB")
    if not all(safe_campaign._port_is_free(port) for port in (SERVER_PORT, BROKER_PORT)):
        raise RuntimeError("required_server_or_broker_port_occupied")
    model_path = _verify_model(benchmark_root)
    binary = benchmark_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    if not binary.is_file():
        raise RuntimeError("pinned_opencode_binary_missing")
    return model_path, binary


def shutil_disk_free(path: Path) -> int:
    import shutil

    return shutil.disk_usage(path).free


def execute(*, benchmark_root: Path, output_root: Path) -> dict[str, Any]:
    """Run fresh no-model gates, then a warmup and five sandboxed tasks."""
    benchmark_root, output_root = Path(benchmark_root).absolute(), Path(output_root).absolute()
    model_path, binary = _preflight(benchmark_root, output_root)
    output_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    output_root.chmod(0o700)
    source_sha, dirty = git_provenance(REPO_ROOT)
    initial_inputs = campaign_readiness.input_hash_manifest(benchmark_root=benchmark_root)
    input_files = {}
    for path in (
        Path(__file__), REPO_ROOT / "benchmark/safe_campaign.py",
        REPO_ROOT / "benchmark/campaign_readiness.py", REPO_ROOT / "benchmark/model_broker.py",
        REPO_ROOT / "benchmark/linux_sandbox.py", REPO_ROOT / "benchmark/model_quality_paired.py",
        REPO_ROOT / "benchmark/pristine_grading.py", REPO_ROOT / "benchmark/harness_runner.py",
        REPO_ROOT / "benchmark/run_observer.py", REPO_ROOT / "tests/test_campaign_readiness.py",
        REPO_ROOT / "tests/test_model_broker.py", REPO_ROOT / "tests/test_minicpm5_2b_coding_probe.py",
    ):
        input_files[path.relative_to(REPO_ROOT).as_posix()] = campaign_readiness._sha256_file(path)
    protocol = {
        "schema_version": 1, "experiment": EXPERIMENT, "campaign_enabled": False,
        "scope_note": "five remaining protected tasks with one excluded warmup; exploratory screen only, not a comparative score",
        "models": {MODEL_KEY: MODEL}, "tasks": list(TASKS), "warmup_task": WARMUP_TASK,
        "rows": build_rows(), "context_tokens": CONTEXT_TOKENS,
        "max_primary_steps": AGENT_STEPS,
        "generation": GENERATION, "grader_protocol_version": safe_campaign.GRADER_PROTOCOL_VERSION,
        "source_git_sha": source_sha, "source_tree_dirty": dirty,
        "code_sha256": input_files, "readiness_input_digest": initial_inputs["digest"],
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "resource_requirements": {"minimum_free_vram_mib": MINIMUM_FREE_VRAM_MIB,
                                  "minimum_free_ext4_bytes": 8 * 1024**3},
    }
    _write_json(output_root / "protocol.json", protocol)
    profile = build_profile()
    profile_evidence = _verify_effective_profile(binary, benchmark_root, profile, output_root)
    readiness = safe_campaign.run_current_readiness(
        evidence_dir=output_root / "readiness", benchmark_root=benchmark_root,
        model_contracts={MODEL_KEY: MODEL})
    fresh_inputs = campaign_readiness.input_hash_manifest(benchmark_root=benchmark_root)
    validation = campaign_readiness.validate_readiness_report(
        readiness, current_input_digest=fresh_inputs["digest"])
    _write_json(output_root / "readiness-validation.json", validation)
    if not initial_inputs.get("complete") or initial_inputs["digest"] != fresh_inputs["digest"]:
        raise RuntimeError("source_bound_inputs_changed_during_readiness")
    if not validation.get("ready"):
        result = {"started": False, "status": "readiness_blocked", "readiness": readiness,
                  "validation": validation, "output_root": str(output_root)}
        _write_json(output_root / "result.json", result)
        return result
    _verify_model(benchmark_root)
    if shutil_disk_free(output_root) < 8 * 1024**3 or _gpu_free_mib() < MINIMUM_FREE_VRAM_MIB:
        raise RuntimeError("resource_reserve_changed_after_readiness")

    profile_bytes = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()
    protocol.update(readiness_input_digest=fresh_inputs["digest"],
                    profile_sha256=hashlib.sha256(profile_bytes).hexdigest(),
                    profile_preflight=profile_evidence)
    _write_json(output_root / "protocol.json", protocol)

    from benchmark.safe_campaign import _resource_monitor_start, _resource_monitor_stop

    monitor, session_resource = _resource_monitor_start(
        output_root / "resources-server", run_id=EXPERIMENT,
        phase_id="model_session", agent_id="llama-server")
    if monitor is None or session_resource.get("status") != "running":
        raise RuntimeError("required_server_resource_monitor_unavailable")
    server_process: subprocess.Popen[bytes] | None = None
    record: dict[str, Any] | None = None
    started = time.monotonic()
    try:
        server_process, server_log, argv = _start_server(benchmark_root, output_root, model_path)
        protocol["server_command_sha256"] = hashlib.sha256(
            json.dumps(argv, separators=(",", ":")).encode()).hexdigest()
        protocol["model_loaded"] = True
        protocol["server_ready_utc"] = datetime.now(timezone.utc).isoformat()
        _write_json(output_root / "protocol.json", protocol)
        records: list[dict[str, Any]] = []
        stopped_reason: str | None = None
        for row in build_rows():
            if shutil_disk_free(output_root) < 8 * 1024**3:
                stopped_reason = "eight_gib_disk_reserve_lost_between_tasks"
                break
            if server_process.poll() is not None or not _wait_model(MODEL["alias"], time.monotonic() + 3):
                stopped_reason = "model_server_unavailable_between_tasks"
                break
            record = safe_campaign._execute_task(
                row, install_root=benchmark_root, binary=binary, server_log=server_log,
                output_root=output_root, experiment=EXPERIMENT, session_resource=session_resource,
                model_api_port=SERVER_PORT, model_contract=MODEL,
                profile_override=profile, generation_policy=GENERATION,
            )
            records.append(record)
            if record.get("cleanup_verified") is not True:
                stopped_reason = "task_sandbox_cleanup_unverified"
                break
            if record.get("infrastructure_error") is not None:
                stopped_reason = "task_infrastructure_error"
                break
    finally:
        if server_process is not None:
            safe_campaign._stop_server(server_process)
        session_resource = _resource_monitor_stop(monitor, session_resource)

    free_after = _gpu_free_mib()
    ports_free = {str(port): safe_campaign._port_is_free(port) for port in (SERVER_PORT, BROKER_PORT)}
    measurement_records = [record for record in records if record.get("stage") == "measurement"]
    completed_rows = len(records)
    expected_rows = len(build_rows())
    result = {
        "started": True,
        "status": "completed" if completed_rows == expected_rows else "partial",
        "experiment": EXPERIMENT,
        "campaign_enabled": False,
        "inference_performed": any(record.get("model_requests", 0) > 0 for record in records),
        "model_loaded": True,
        "warmup_excluded": next((record.get("strict_pass") for record in records
                                  if record.get("stage") == "warmup"), None),
        "expected_rows": expected_rows,
        "completed_rows": completed_rows,
        "completed_measurements": len(measurement_records),
        "strict_pass_count": sum(record.get("strict_pass") is True for record in measurement_records),
        "strict_pass_all_measurements": (
            all(record.get("strict_pass") is True for record in measurement_records)
            if len(measurement_records) == len(TASKS) else None
        ),
        "task_results": [
            {"stage": record.get("stage"), "task": record.get("task"),
             "strict_pass": record.get("strict_pass"),
             "failure_category": record.get("failure_category"),
             "task_wall_seconds": record.get("task_wall_seconds"),
             "model_requests": record.get("model_requests", 0),
             "record_path": str(Path(record["run_dir"]) / "record.json")
             if record.get("run_dir") else None}
            for record in records
        ],
        "stopped_reason": stopped_reason,
        "resource_sampling": session_resource,
        "gpu_free_mib_after": free_after,
        "ports_free_after": ports_free,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "output_root": str(output_root),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(output_root / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, default=DEFAULT_BENCHMARK_ROOT)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = execute(benchmark_root=args.benchmark_root, output_root=args.output_root)
    except Exception as exc:
        result = {"started": False, "status": "preflight_or_execution_error",
                  "error": f"{type(exc).__name__}: {str(exc)[:500]}",
                  "output_root": str(args.output_root)}
        if args.output_root.exists() and not (args.output_root / "result.json").exists():
            _write_json(args.output_root / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("started") is True and result.get("inference_performed") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
