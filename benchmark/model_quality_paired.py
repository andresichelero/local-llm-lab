"""Frozen paired OpenCode quality protocol for the existing Qwen3.5 4B/9B models.

The default entry point is ``--dry-run``. Inference requires an explicit
``--execute`` and a working C-backed WSL ext4 installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import stat
import socket
import statistics
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

from benchmark.opencode_controlled_probe import _assert_free_resources, _assert_server_bundle, require_runtime_revision  # noqa: E402  # Project-root bootstrap above enables direct module execution.
from benchmark.harness_runner import (  # noqa: E402  # Project-root bootstrap above enables direct module execution.
    DEFAULT_CONTEXT,
    DEFAULT_SERVER_URL,
    _isolated_environment,
    _prepare_run,
    _read_jsonl,
    parse_server_prompt_eval_tokens,
    summarize_resources,
    summarize_usage,
)
from benchmark.provenance import git_provenance  # noqa: E402  # Project-root bootstrap above enables direct module execution.

EXPERIMENT = "model-quality-paired-20261012-r1d"
HARNESS = "opencode"
HARNESS_VERSION = "1.19.0"
RUNTIME_REVISION = "d81235049384534c167caea52b85a694f6103d14"
TASKS = ("calculator_division", "whitespace_normalization", "dotenv_line_parser")
MODELS: dict[str, dict[str, str]] = {
    "qwen3.5-4b": {
        "alias": "Qwen3.5-4B-Q4_K_M",
        "revision": "4168f45a16a1290d65a4ec0fa312ae917a4c15d6",
        "path": "models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf",
        "sha256": "13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983",
    },
    "qwen3.5-9b": {
        "alias": "Qwen3.5-9B-Q4_K_M",
        "revision": "3885219b6810b007914f3a7950a8d1b469d598a5",
        "path": "models/gguf/Qwen3.5-9B-Q4_K_M.gguf",
        "sha256": "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
    },
}
MEASURED_REPEATS = 3
TASK_LIMIT_SECONDS = 180
MAX_PRIMARY_STEPS = 20
ROUND_LIMIT_SECONDS = 75 * 60
MIN_FREE_EXT4_BYTES = 8 * 1024**3
MAX_SCRATCH_BYTES = 1 * 1024**3
SWAP_GROWTH_LIMIT_BYTES = 512 * 1024**2
SWAP_GROWTH_SAMPLES = 10
SERVER_URL = DEFAULT_SERVER_URL
SERVER_PORT = 8080
PROMPT_CACHE = "off"
KV_CACHE = "q4_0"
CONTEXT = DEFAULT_CONTEXT


def measured_schedule() -> list[dict[str, Any]]:
    """Return 18 rows in six alternating task/model blocks (three repeats each)."""
    result = []
    for task_index, task in enumerate(TASKS):
        first = tuple(MODELS)[task_index % len(MODELS)]
        second = next(model for model in MODELS if model != first)
        for model in (first, second):
            for repeat in range(1, MEASURED_REPEATS + 1):
                result.append({"model": model, "task": task, "repeat": repeat, "stage": "measurement"})
    return result


PILOT_EXPERIMENT = "model-quality-pilot-20261012"
PILOT_TASKS = ("config_precedence", "retry_policy")
PILOT_ROUND_LIMIT_SECONDS = 25 * 60

V2_EXPERIMENT = "model-quality-v2-20261012"
V2_TASKS = (
    "calculator_division",
    "whitespace_normalization",
    "dotenv_line_parser",
    "config_precedence",
    "retry_policy",
    "package_refactor",
)
V2_ROUND_LIMIT_SECONDS = 120 * 60
V2_REPEATS = 2


def build_pilot_schedule() -> list[dict[str, Any]]:
    """Return 4 rows: 2 new tasks x 2 models x 1 repeat."""
    rows = []
    for model in ("qwen3.5-4b", "qwen3.5-9b"):
        for task in PILOT_TASKS:
            rows.append({"model": model, "task": task, "repeat": 1, "stage": "measurement"})
    return rows


def build_v2_schedule() -> list[dict[str, Any]]:
    """Return 24 rows in 4 model blocks (AB/BA) across 6 tasks with 2 repeats."""
    blocks = [
        ("qwen3.5-4b", 1),
        ("qwen3.5-9b", 1),
        ("qwen3.5-9b", 2),
        ("qwen3.5-4b", 2),
    ]
    rows = []
    for model, repeat in blocks:
        for task in V2_TASKS:
            rows.append({"model": model, "task": task, "repeat": repeat, "stage": "measurement"})
    return rows


def frozen_pilot_protocol() -> dict[str, Any]:
    proto = frozen_protocol()
    proto["experiment"] = PILOT_EXPERIMENT
    proto["tasks"] = list(PILOT_TASKS)
    proto["measured_repeats_per_model_task"] = 1
    proto["schedule"] = build_pilot_schedule()
    proto["round_limit_seconds"] = PILOT_ROUND_LIMIT_SECONDS
    return proto


def frozen_v2_protocol() -> dict[str, Any]:
    proto = frozen_protocol()
    proto["experiment"] = V2_EXPERIMENT
    proto["tasks"] = list(V2_TASKS)
    proto["measured_repeats_per_model_task"] = V2_REPEATS
    proto["schedule"] = build_v2_schedule()
    proto["round_limit_seconds"] = V2_ROUND_LIMIT_SECONDS
    return proto


def frozen_protocol() -> dict[str, Any]:
    """Stable configuration payload written before any observations are collected."""
    return {
        "experiment": EXPERIMENT,
        "round0_prerequisite": {
            "status": "failed",
            "measurement_eligible": False,
            "reason": "previous controlled read-only smoke completed with zero child calls",
            "not_a_single_agent_prerequisite": True,
            "relationship": "historical failed multiagent gate; preserved and not relaxed by this independent single-agent series",
        },
        "single_agent_prerequisite": {
            "status": "pending",
            "measurement_eligible": False,
            "release_required": "parent must explicitly authorize with --single-agent-release after review",
            "requirements": ["model loaded at configured context", "exact effective single-agent profile",
                             "real successful bash call", "real successful edit call"],
        },
        "harness": HARNESS,
        "harness_version": HARNESS_VERSION,
        "models": MODELS,
        "tasks": list(TASKS),
        "task_limits_seconds": TASK_LIMIT_SECONDS,
        "max_primary_steps": MAX_PRIMARY_STEPS,
        "measured_repeats_per_model_task": MEASURED_REPEATS,
        "schedule": measured_schedule(),
        "calibration": "one calculator_division task per model; diagnostic only",
        "warmup": "one calculator_division task per model; excluded",
        "context_tokens": CONTEXT,
        "kv_cache_kv": [KV_CACHE, KV_CACHE],
        "flash_attention": "on",
        "gpu_layers": 99,
        "temperature": 0,
        "seed": 1234,
        "reasoning": "off",
        "prompt_cache": PROMPT_CACHE,
        "parallel_slots": 1,
        "endpoint": SERVER_URL,
        "autoupdate": False,
        "agent_mode": "single primary agent; task denied; bash/edit explicitly allowed",
        "external_directory": "deny",
        "task_limit_seconds": TASK_LIMIT_SECONDS,
        "round_limit_seconds": ROUND_LIMIT_SECONDS,
        "scratch_limit_bytes": MAX_SCRATCH_BYTES,
        "minimum_free_ext4_bytes": MIN_FREE_EXT4_BYTES,
        "swap_growth_stop": {
            "bytes_over_baseline": SWAP_GROWTH_LIMIT_BYTES,
            "consecutive_one_second_samples": SWAP_GROWTH_SAMPLES,
        },
        "runtime_revision": RUNTIME_REVISION,
        "server_flags": ["--ctx-size 16384", "--n-gpu-layers 99", "--flash-attn on",
                         "--cache-type-k q4_0", "--cache-type-v q4_0", "--reasoning off",
                         "--no-cache-prompt", "--parallel 1"],
        "profile_sha256_by_model": {
            model: hashlib.sha256(json.dumps(build_profile(model), sort_keys=True).encode()).hexdigest()
            for model in MODELS
        },
        "quant": "Q4_K_M",
        "storage_profile": "ssd-wsl-ext4-c",
    }


def denominator_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep all measured outcomes, including failures; exclude calibration/warmup."""
    return [record for record in records if record.get("stage") == "measurement"]


def summarize_denominators(records: list[dict[str, Any]]) -> dict[str, Any]:
    measured = [record for record in denominator_rows(records) if record.get("attempted", True)]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in measured:
        groups.setdefault((str(record.get("model")), str(record.get("task"))), []).append(record)
    summary = {}
    for (model, task), rows in sorted(groups.items()):
        walls = [float(row["task_wall_seconds"]) for row in rows if row.get("task_wall_seconds") is not None]
        summary[f"{model}/{task}"] = {
            "passes": sum(bool(row.get("strict_pass")) for row in rows),
            "attempts": len(rows),
            "pass_fraction": sum(bool(row.get("strict_pass")) for row in rows) / len(rows),
            "task_wall_median_seconds": statistics.median(walls) if walls else None,
            "task_wall_min_seconds": min(walls) if walls else None,
            "task_wall_max_seconds": max(walls) if walls else None,
        }
    return {"measured_rows": len(measured), "by_model_task": summary}


def compatibility_gate(*, server_loaded: bool, effective_profile_ok: bool,
                       bash_tool_round_trip: bool, edit_tool_round_trip: bool) -> bool:
    """Only setup/load/tool compatibility decides whether the matrix may start."""
    return server_loaded and effective_profile_ok and bash_tool_round_trip and edit_tool_round_trip


FAILURE_CLASSES: set[str] = {
    "none",
    "runner",
    "transport",
    "capability",
    "tool_env",
    "model_contract",
    "functional",
    "scope",
    "resource",
    "timeout",
}


def classify_failure(
    *,
    runner_error: bool = False,
    transport_error: bool = False,
    resource_error: bool = False,
    tool_env_error: bool = False,
    timeout_error: bool = False,
    scope_error: bool = False,
    contract_error: bool = False,
    functional_error: bool = False,
) -> str:
    """Classify the primary failure class into the standardized laboratory taxonomy."""
    if runner_error:
        return "runner"
    if transport_error:
        return "transport"
    if resource_error:
        return "resource"
    if tool_env_error:
        return "tool_env"
    if timeout_error:
        return "timeout"
    if scope_error:
        return "scope"
    if contract_error:
        return "model_contract"
    if functional_error:
        return "functional"
    return "none"


def mechanical_preflight(
    *,
    python_executable: str | Path | None = None,
    fixture_dir: Path | None = None,
    endpoint_url: str | None = None,
) -> dict[str, Any]:
    """Verify system prerequisites (python3, fixture readable, endpoint) without running model inference."""
    py_target = str(python_executable or "python3")
    py_path = shutil.which(py_target)
    python_ok = py_path is not None
    fixture_ok = True
    if fixture_dir is not None:
        p = Path(fixture_dir)
        fixture_ok = p.is_dir() and any(p.iterdir())
    endpoint_ok = True
    if endpoint_url is not None:
        try:
            req = urllib.request.Request(endpoint_url.rstrip("/") + "/v1/models", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                endpoint_ok = resp.status == 200
        except Exception:
            endpoint_ok = False
    passed = python_ok and fixture_ok and endpoint_ok
    fc = "none"
    if not python_ok or not fixture_ok:
        fc = "tool_env"
    elif not endpoint_ok:
        fc = "transport"
    return {
        "passed": passed,
        "python_executable": py_path,
        "python_ok": python_ok,
        "fixture_ok": fixture_ok,
        "endpoint_ok": endpoint_ok,
        "failure_class": fc,
    }


def swap_growth_breach(samples: list[dict[str, Any]], baseline_bytes: int) -> bool:
    """Detect the declared swap stop rule from one-second sampler rows."""
    consecutive = 0
    for row in samples:
        used = row.get("swap_used_bytes")
        if used is None and row.get("swap_used_mb") is not None:
            used = float(row["swap_used_mb"]) * 1024**2
        if used is not None and float(used) - baseline_bytes > SWAP_GROWTH_LIMIT_BYTES:
            consecutive += 1
            if consecutive >= SWAP_GROWTH_SAMPLES:
                return True
        else:
            consecutive = 0
    return False


def strict_quality_pass(grade: dict[str, Any], *, modes_preserved: bool, workflow_complete: bool,
                        tool_round_trip: bool, command_ok: bool) -> bool:
    """Combine independent code grader with filesystem and harness completion gates."""
    return all((bool(grade.get("success")), modes_preserved, workflow_complete, tool_round_trip, command_ok))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _file_modes(root: Path) -> dict[str, int]:
    return {
        path.relative_to(root).as_posix(): path.stat().st_mode & 0o777
        for path in root.rglob("*") if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts
    }


def pregrade_workspace_gate(workspace: Path, baseline_modes: dict[str, int]) -> dict[str, Any]:
    """Reject links/non-regular entries and mode changes before grader reads code."""
    try:
        root_mode = workspace.lstat().st_mode
    except OSError as error:
        return {"passed": False, "root_error": f"{type(error).__name__}: {error}",
                "symlinks": [], "unusual_entries": [], "mode_changes": []}
    if stat.S_ISLNK(root_mode):
        return {"passed": False, "root_symlink": True,
                "symlinks": ["."], "unusual_entries": [], "mode_changes": []}
    if not stat.S_ISDIR(root_mode):
        return {"passed": False, "root_error": "workspace root is not a directory",
                "symlinks": [], "unusual_entries": ["."], "mode_changes": []}
    links: list[str] = []
    unusual: list[str] = []
    current_modes: dict[str, int] = {}
    for current, dirs, files in os.walk(workspace, followlinks=False):
        for name in dirs + files:
            path = Path(current) / name
            mode = path.lstat().st_mode
            relative = path.relative_to(workspace).as_posix()
            if stat.S_ISLNK(mode):
                links.append(relative)
            elif not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                unusual.append(relative)
            elif stat.S_ISREG(mode) and ".git" not in path.parts and "__pycache__" not in path.parts:
                current_modes[relative] = stat.S_IMODE(mode)
    mode_changes = sorted(path for path in baseline_modes.keys() | current_modes.keys()
                          if baseline_modes.get(path) != current_modes.get(path))
    return {"passed": not links and not unusual and not mode_changes,
            "symlinks": sorted(links), "unusual_entries": sorted(unusual),
            "mode_changes": mode_changes}


def _protected_files_preserved(workspace: Path, baseline: Path, task: str) -> dict[str, Any]:
    allowed = {
        "calculator_division": {"src/calculator.py", "tests/test_calculator.py"},
        "whitespace_normalization": {"src/text_utils.py", "tests/test_text_utils.py"},
        "dotenv_line_parser": {"src/config_parser.py", "tests/test_config_parser.py"},
        "config_precedence": {"src/config.py", "tests/test_config.py"},
        "retry_policy": {"src/retry.py", "tests/test_retry.py"},
        "package_refactor": {"src/service.py", "src/metrics.py", "tests/test_service.py"},
    }[task]
    # Caller must first pass pregrade_workspace_gate, which uses lstat and does not
    # follow links. Recheck before reading in case the workspace changed meanwhile.
    safety = pregrade_workspace_gate(workspace, _file_modes(baseline))
    if not safety["passed"]:
        return {**safety, "protected_content_changes": [], "protected_mode_changes": [],
                "unscoped_added_files": [], "added_allowed_files": []}
    base_modes = _file_modes(baseline)
    current_modes = _file_modes(workspace)
    base_files = {path.relative_to(baseline).as_posix(): path.read_bytes()
                  for path in baseline.rglob("*") if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts}
    current_files = {path.relative_to(workspace).as_posix(): path.read_bytes()
                     for path in workspace.rglob("*") if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts}
    paths = (base_files.keys() | current_files.keys()) - allowed
    content_changes = sorted(path for path in paths if base_files.get(path) != current_files.get(path))
    mode_changes = sorted(path for path in paths if base_modes.get(path) != current_modes.get(path))
    added_allowed = sorted(path for path in current_files.keys() - base_files.keys() if path in allowed)
    unscoped_added = sorted(current_files.keys() - base_files.keys() - allowed)
    return {"passed": not content_changes and not mode_changes and not unscoped_added,
            "symlinks": safety["symlinks"], "protected_content_changes": content_changes,
            "protected_mode_changes": mode_changes, "unscoped_added_files": unscoped_added,
            "added_allowed_files": added_allowed}


def _independent_grade(workspace: Path, baseline: Path, task: str, run_dir: Path) -> dict[str, Any]:
    """Run independent graders under a bounded, stripped environment and process group."""
    grade_home = run_dir / "grader-home"
    grade_tmp = run_dir / "grader-tmp"
    grade_home.mkdir(exist_ok=False)
    grade_tmp.mkdir(exist_ok=False)
    env = {"PATH": os.pathsep.join(["/usr/local/bin", "/usr/bin", "/bin"]),
           "PYTHONPATH": str(REPO_ROOT), "PYTHONIOENCODING": "utf-8", "LANG": "C.UTF-8",
           "HOME": str(grade_home), "TMPDIR": str(grade_tmp)}
    code = ("import json,sys; from benchmark.harness_eval import grade_workspace; "
            "print(json.dumps(grade_workspace(__import__('pathlib').Path(sys.argv[1]), "
            "__import__('pathlib').Path(sys.argv[2]), task=sys.argv[3])))")
    proc = subprocess.Popen([sys.executable, "-c", code, str(workspace), str(baseline), task],
                            cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(timeout=75)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            stdout, stderr = proc.communicate()
        return {"success": False, "grader_error": "independent grader exceeded 75 seconds",
                "grader_timed_out": True, "grader_stderr": stderr[-4000:]}
    if proc.returncode != 0:
        return {"success": False, "grader_error": f"independent grader exited {proc.returncode}",
                "grader_stderr": stderr[-4000:]}
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return {"success": False, "grader_error": "independent grader returned invalid JSON",
                "grader_stdout": stdout[-2000:], "grader_stderr": stderr[-4000:]}
    return result


def _grade_workspace_when_safe(workspace: Path, baseline: Path, task: str, run_dir: Path,
                               baseline_modes: dict[str, int]) -> tuple[dict[str, Any], dict[str, Any]]:
    gate = pregrade_workspace_gate(workspace, baseline_modes)
    if not gate["passed"]:
        return ({"success": False, "grader_skipped": True,
                 "grader_error": "workspace integrity gate failed before grader access"}, gate)
    protected = _protected_files_preserved(workspace, baseline, task)
    gate["protected_files"] = protected
    if not protected["passed"]:
        gate["passed"] = False
        return ({"success": False, "grader_skipped": True,
                 "grader_error": "protected-content gate failed before grader access"}, gate)
    return _independent_grade(workspace, baseline, task, run_dir), gate


def build_profile(model: str) -> dict[str, Any]:
    """Create an explicit one-agent OpenCode profile with the frozen permissions."""
    if model not in MODELS:
        raise ValueError(f"Unsupported model: {model}")
    alias = MODELS[model]["alias"]
    base = json.loads((REPO_ROOT / "benchmark/configs/harnesses/opencode-subagents.json").read_text(encoding="utf-8"))
    base["autoupdate"] = False
    base["model"] = f"local/{alias}"
    base["subagent_depth"] = 0
    base["agent"] = {
        "build": {
            "mode": "primary",
            "steps": MAX_PRIMARY_STEPS,
            "permission": {
                "task": {"*": "deny"},
                "bash": {"*": "allow"},
                "edit": {"*": "allow"},
                "external_directory": {"*": "deny"},
            },
        }
    }
    base["provider"]["local"]["options"]["baseURL"] = SERVER_URL + "/v1"
    base["provider"]["local"]["models"] = {
        alias: {
            "name": alias,
            "limit": {"context": CONTEXT, "output": 1024},
            "options": {"temperature": 0, "seed": 1234},
        }
    }
    return base


def _permission_profile_checks(permissions: list[dict[str, Any]], home: str, tmpdir: str) -> dict[str, bool]:
    def rules_for(permission: str) -> list[dict[str, Any]]:
        return [item for item in permissions if item.get("permission") == permission]

    def final_action(permission: str) -> str | None:
        return next((item.get("action") for item in reversed(rules_for(permission))
                     if item.get("pattern") == "*"), None)

    task_specific_allow = any(item.get("action") == "allow" and item.get("pattern") != "*"
                              for item in rules_for("task"))
    safe_external_allowlist = {
        str(Path(home) / ".local/share/opencode/tool-output/*"),
        str(Path(tmpdir) / "opencode/*"),
    }
    external_allows = [item.get("pattern") for item in rules_for("external_directory")
                       if item.get("action") == "allow" and item.get("pattern") != "*"]
    return {
        "task_denied": final_action("task") == "deny",
        "task_specific_overrides_denied": not task_specific_allow,
        "bash_allowed": final_action("bash") == "allow",
        "edit_allowed": final_action("edit") == "allow",
        "external_directory_denied": final_action("external_directory") == "deny",
        "external_directory_overrides_scoped": set(external_allows) <= safe_external_allowlist,
    }


def _profile_checks(binary: Path, env: dict[str, str], model: str,
                    deadline: float | None = None) -> dict[str, Any]:
    def remaining() -> int:
        if deadline is None:
            return 20
        seconds = int(deadline - time.monotonic())
        if seconds <= 0:
            raise TimeoutError("75-minute round deadline reached during profile inspection")
        return min(20, seconds)
    config = subprocess.run([str(binary), "debug", "config", "--pure"], env=env, capture_output=True, text=True, timeout=remaining())
    agent = subprocess.run([str(binary), "debug", "agent", "build", "--pure"], env=env, capture_output=True, text=True, timeout=remaining())
    if config.returncode or agent.returncode:
        raise RuntimeError("OpenCode effective configuration inspection failed")
    config_json = json.loads(config.stdout)
    agent_json = json.loads(agent.stdout)
    pairs: list[tuple[str, Any]] = []
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                pairs.append((str(key).lower(), item))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(config_json)
    permissions = agent_json.get("permission", [])
    provider = config_json.get("provider", {}).get("local", {})
    effective_model = provider.get("models", {}).get(MODELS[model]["alias"], {})
    model_options = effective_model.get("options", {})
    checks = {
        "local_endpoint": any(key == "baseurl" and value == SERVER_URL + "/v1" for key, value in pairs),
        "autoupdate_disabled": any(key == "autoupdate" and value is False for key, value in pairs),
        "configured_model": any(key == "model" and value == f"local/{MODELS[model]['alias']}" for key, value in pairs),
        "model_context": effective_model.get("limit", {}).get("context") == CONTEXT,
        "model_output_cap": effective_model.get("limit", {}).get("output") == 1024,
        "model_temperature": model_options.get("temperature") == 0,
        "model_seed": model_options.get("seed") == 1234,
        "default_agent": config_json.get("default_agent") == "build",
        "single_agent_only": config_json.get("subagent_depth") == 0 and set(config_json.get("agent", {})) == {"build"},
        "primary_agent": agent_json.get("mode") == "primary",
        "step_limit": agent_json.get("steps") == MAX_PRIMARY_STEPS,
        **_permission_profile_checks(permissions, env["HOME"], env["TMPDIR"]),
    }
    return {"checks": checks, "passed": all(checks.values()), "effective_config": config_json, "effective_agent": agent_json}


def _is_ext4(path: Path) -> bool:
    result = subprocess.run(["findmnt", "-n", "-o", "FSTYPE", "-T", str(path)], capture_output=True, text=True, check=True)
    return result.stdout.strip() == "ext4"


def _memory_baseline_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("SwapTotal:"):
            total = int(line.split()[1]) * 1024
        elif line.startswith("SwapFree:"):
            free = int(line.split()[1]) * 1024
    return total - free


def _server_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/v1/models", timeout=1) as response:
            return response.status == 200
    except (OSError, TimeoutError):
        return False


def _server_segment_has_oom(server_log: Path, offset: int) -> bool:
    """Catch allocator OOMs even if the HTTP endpoint remains responsive."""
    if not server_log.exists():
        return False
    try:
        with server_log.open("rb") as source:
            source.seek(max(0, offset))
            segment = source.read().decode("utf-8", errors="replace").lower()
    except OSError:
        return False
    markers = ("out of memory", "failed to allocate", "allocation failed", "cuda malloc failed",
               "std::bad_alloc", "bad_alloc", "cannot allocate memory", "not enough memory",
               "oom-kill", "oom killer")
    return any(marker in segment for marker in markers)


def _post_child_server_failure(server_log: Path, offset: int, *, server_healthy: bool) -> str | None:
    """Run after child exit too: the OOM line may be written in its final burst."""
    if _server_segment_has_oom(server_log, offset) or not server_healthy:
        return "server_lost_or_oom"
    return None


def _post_child_stop_reason(server_log: Path, offset: int, *, server_healthy: bool,
                            existing_reason: str | None,
                            resource_samples: list[dict[str, Any]],
                            swap_baseline_bytes: int) -> str | None:
    """Apply final server and swap guards after child and sampler cleanup."""
    server_failure = _post_child_server_failure(server_log, offset, server_healthy=server_healthy)
    if server_failure:
        return server_failure
    if swap_growth_breach(resource_samples, swap_baseline_bytes):
        return "swap_growth_limit"
    return existing_reason


def _terminate_process_group(proc: subprocess.Popen[Any], *, grace_seconds: int) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_seconds
    while True:
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            break
        if proc.poll() is None:
            try:
                proc.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue
        else:
            time.sleep(min(0.05, remaining))
    if proc.poll() is None:
        proc.wait()


def fatal_diagnostic_stop(record: dict[str, Any]) -> bool:
    """System/runner stops abort calibration; ordinary quality failures do not."""
    reason = str(record.get("stop_reason") or "")
    return (reason in {"server_lost_or_oom", "swap_growth_limit", "round_deadline",
                       "effective_profile_failed"}
            or reason.startswith("runner_error:") or reason.startswith("grader_error:"))


def _model_loaded(url: str, alias: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/v1/models", timeout=2) as response:
            models = json.load(response).get("data", [])
        loaded = next((item for item in models if item.get("id") == alias), None)
        return loaded is not None and int(loaded.get("meta", {}).get("n_ctx", 0) or 0) >= CONTEXT
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return False


def _server_command(server: Path, model_path: Path, model: str) -> list[str]:
    return [str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(SERVER_PORT),
            "--alias", MODELS[model]["alias"], "--ctx-size", str(CONTEXT), "--n-gpu-layers", "99",
            "--batch-size", "512", "--ubatch-size", "256", "--flash-attn", "on",
            "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--reasoning", "off",
            "--no-cache-prompt", "--parallel", "1", "--no-webui"]


def _tool_round_trip(binary: Path, install_root: Path, model: str, server_log: Path,
                     output_root: Path, round_deadline: float,
                     swap_baseline_bytes: int) -> dict[str, Any]:
    """One real local OpenCode tool call gates compatibility; excluded from results."""
    run_dir = output_root / "compatibility" / model
    run_dir.mkdir(parents=True, exist_ok=False)
    prompt = ("Use bash to run python3 -c 'print(6 * 7)'. Then use the edit tool to replace all of "
              "TASK.md with exactly this content: edit probe ok. Do not use bash to change TASK.md. "
              "Return only the bash output.")
    fixture = REPO_ROOT / "benchmark/fixtures/harness_task"
    _prepare_run("opencode", run_dir, install_root, prompt, MODELS[model]["alias"], SERVER_URL, CONTEXT,
                 fixture=fixture)
    profile = build_profile(model)
    profile_path = run_dir / "home/.config/opencode/opencode.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    env = _isolated_environment("opencode", run_dir, install_root, run_dir / "workspace")
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    checks = _profile_checks(binary, env, model, round_deadline)
    output = run_dir / "events.jsonl"
    server_loaded_at_context = _model_loaded(SERVER_URL, MODELS[model]["alias"])
    if not checks.get("passed"):
        output.write_text("", encoding="utf-8")
        result = {"return_code": None, "wall_seconds": 0.0, "tool_calls": 0,
                  "completed_tool_calls": 0, "task_calls": 0, "completed_bash_tool_calls": 0,
                  "completed_edit_tool_calls": 0, "expected_output_seen": False,
                  "edit_file_verified": False, "server_loaded_at_context": server_loaded_at_context,
                  "profile_checks": checks, "passed": False,
                  "stop_reason": "effective_profile_failed", "events_sha256": _sha256(output),
                  "events_path": str(output), "run_dir": str(run_dir), "model": model,
                  "model_revision": MODELS[model]["revision"], "model_sha256": MODELS[model]["sha256"],
                  "server_log_path": str(server_log)}
        return result
    if not server_loaded_at_context:
        output.write_text("", encoding="utf-8")
        return {"return_code": None, "wall_seconds": 0.0, "tool_calls": 0,
                "completed_tool_calls": 0, "task_calls": 0, "completed_bash_tool_calls": 0,
                "completed_edit_tool_calls": 0, "edit_file_verified": False,
                "expected_output_seen": False, "profile_checks": checks,
                "server_loaded_at_context": False, "passed": False,
                "stop_reason": "model_not_loaded_at_context", "events_sha256": _sha256(output),
                "events_path": str(output), "run_dir": str(run_dir), "model": model,
                "model_revision": MODELS[model]["revision"], "model_sha256": MODELS[model]["sha256"],
                "server_log_path": str(server_log)}
    command = [str(binary), "run", "--format", "json", "--agent", "build", "--model",
               f"local/{MODELS[model]['alias']}", "--dir", str(run_dir / "workspace"), prompt]
    started = time.monotonic()
    event_log_offset = server_log.stat().st_size if server_log.exists() else 0
    resource_path = run_dir / "resources.jsonl"
    resource_path.write_text("", encoding="utf-8")
    (run_dir / "stderr.log").write_text("", encoding="utf-8")
    if started >= round_deadline:
        output.write_text("", encoding="utf-8")
        return {"return_code": None, "wall_seconds": 0.0, "tool_calls": 0,
                "completed_tool_calls": 0, "task_calls": 0, "completed_bash_tool_calls": 0,
                "completed_edit_tool_calls": 0, "edit_file_verified": False,
                "server_loaded_at_context": True, "profile_checks": checks,
                "passed": False, "timed_out": True, "stop_reason": "round_deadline",
                "events_sha256": _sha256(output), "events_path": str(output),
                "resource_summary": summarize_resources([]), "run_dir": str(run_dir),
                "server_log_path": str(server_log)}
    proc: subprocess.Popen[Any] | None = None
    sampler: subprocess.Popen[Any] | None = None
    return_code: int | None = None
    stop_reason: str | None = None
    with output.open("w", encoding="utf-8") as target, (run_dir / "stderr.log").open("w", encoding="utf-8") as errors:
        try:
            sampler = subprocess.Popen([sys.executable, str(REPO_ROOT / "benchmark/resource_sampler.py"),
                                        "--output", str(resource_path), "--interval", "1"],
                                       cwd=run_dir / "workspace", env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
            proc = subprocess.Popen(command, cwd=run_dir / "workspace", env=env,
                                    stdin=subprocess.DEVNULL, stdout=target,
                                    stderr=errors, start_new_session=True)
            task_deadline = min(round_deadline, started + 90)
            while proc.poll() is None:
                if time.monotonic() >= round_deadline:
                    stop_reason = "round_deadline"
                    break
                if time.monotonic() >= task_deadline:
                    stop_reason = "task_timeout"
                    break
                if _server_segment_has_oom(server_log, event_log_offset) or not _server_ready(SERVER_URL):
                    stop_reason = "server_lost_or_oom"
                    break
                if swap_growth_breach(_read_jsonl(resource_path), swap_baseline_bytes):
                    stop_reason = "swap_growth_limit"
                    break
                time.sleep(0.25)
            if _server_segment_has_oom(server_log, event_log_offset) or not _server_ready(SERVER_URL):
                stop_reason = "server_lost_or_oom"
            elif stop_reason is None and time.monotonic() >= round_deadline:
                stop_reason = "round_deadline"
            elif stop_reason is None and time.monotonic() >= task_deadline:
                stop_reason = "task_timeout"
            if stop_reason:
                _terminate_process_group(proc, grace_seconds=3)
            return_code = proc.wait()
        finally:
            if proc is not None:
                _terminate_process_group(proc, grace_seconds=3)
            if sampler is not None:
                _terminate_process_group(sampler, grace_seconds=3)
    stop_reason = _post_child_stop_reason(
        server_log, event_log_offset, server_healthy=_server_ready(SERVER_URL),
        existing_reason=stop_reason, resource_samples=_read_jsonl(resource_path),
        swap_baseline_bytes=swap_baseline_bytes)
    events = _read_jsonl(output)
    calls = [event for event in events if event.get("type") == "tool_use"]
    task_calls = [event for event in calls if str(event.get("part", {}).get("tool", "")).lower() == "task"]
    completed_bash = [event for event in calls
                      if str(event.get("part", {}).get("tool", "")).lower() in {"bash", "shell"}
                      and _successful_event(event)]
    output_text = "\n".join(str(event.get("part", {}).get("state", {}).get("output", "")) for event in completed_bash)
    probe_file = run_dir / "workspace/TASK.md"
    edit_file_verified = False
    edit_workspace_gate = pregrade_workspace_gate(run_dir / "workspace", _file_modes(fixture))
    if edit_workspace_gate["passed"] and hasattr(os, "O_NOFOLLOW"):
        descriptor: int | None = None
        try:
            descriptor = os.open(probe_file, os.O_RDONLY | os.O_NOFOLLOW)
            mode = os.fstat(descriptor)
            if stat.S_ISREG(mode.st_mode) and mode.st_size <= 256:
                edit_file_verified = os.read(descriptor, 257) in {b"edit probe ok", b"edit probe ok\n"}
        except OSError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
    edit_evidence = compatibility_edit_evidence(events, run_dir / "workspace",
                                                 file_verified=edit_file_verified)
    return {"return_code": return_code, "timed_out": stop_reason in {"task_timeout", "round_deadline"},
            "stop_reason": stop_reason,
            "wall_seconds": round(time.monotonic() - started, 3),
            "tool_calls": len(calls), "completed_tool_calls": sum(event.get("part", {}).get("state", {}).get("status") == "completed" for event in calls),
            "task_calls": len(task_calls),
            "completed_bash_tool_calls": len(completed_bash),
            **edit_evidence, "edit_workspace_gate": edit_workspace_gate,
            "server_loaded_at_context": server_loaded_at_context,
            "expected_output_seen": "42" in output_text, "profile_checks": checks,
            "passed": proc is not None and return_code == 0
                      and stop_reason is None and "42" in output_text and not task_calls
                      and compatibility_gate(server_loaded=server_loaded_at_context,
                                             effective_profile_ok=checks["passed"],
                                             bash_tool_round_trip=bool(completed_bash),
                                             edit_tool_round_trip=edit_evidence["edit_tool_round_trip"]),
            "events_sha256": _sha256(output), "events_path": str(output), "run_dir": str(run_dir),
            "resource_summary": summarize_resources(_read_jsonl(resource_path)),
            "server_log_segment_sha256": hashlib.sha256(
                (server_log.read_bytes()[event_log_offset:] if server_log.exists() else b"")).hexdigest(),
            "model": model, "model_revision": MODELS[model]["revision"],
            "model_sha256": MODELS[model]["sha256"], "server_log_path": str(server_log)}


def _run_task(binary: Path, install_root: Path, model: str, task: str, stage: str,
              repeat: int | None, output_root: Path, server_log: Path, round_deadline: float,
              swap_baseline_bytes: int, experiment_name: str = EXPERIMENT) -> dict[str, Any]:
    info = MODELS[model]
    label = stage if repeat is None else f"{stage}-{repeat}"
    run_dir = output_root / "runs" / model / task / label
    run_dir.mkdir(parents=True, exist_ok=False)
    fixture_rel, prompt_rel = __import__("benchmark.harness_runner", fromlist=["resolve_task"]).resolve_task(task)
    prompt = prompt_rel.read_text(encoding="utf-8").strip()
    prompt_file = _prepare_run("opencode", run_dir, install_root, prompt, info["alias"], SERVER_URL, CONTEXT, fixture=fixture_rel)
    profile = build_profile(model)
    profile_path = run_dir / "home/.config/opencode/opencode.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    env = _isolated_environment("opencode", run_dir, install_root, run_dir / "workspace")
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    profile_result = _profile_checks(binary, env, model, round_deadline)
    workspace = run_dir / "workspace"
    baseline_modes = _file_modes(fixture_rel)
    original_server_log = server_log.stat().st_size
    event_path, stderr_path = run_dir / "events.jsonl", run_dir / "stderr.log"
    prompt_bytes = len(prompt_file.read_bytes())
    if not profile_result.get("passed"):
        event_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        (run_dir / "resources.jsonl").write_text("", encoding="utf-8")
        server_segment = server_log.read_bytes()[original_server_log:].decode("utf-8", errors="replace") if server_log.exists() else ""
        return {
            "experiment": experiment_name, "stage": stage, "model": model, "model_alias": info["alias"],
            "model_revision": info["revision"], "model_sha256": info["sha256"], "task": task, "repeat": repeat,
            "attempted": True, "return_code": None, "timed_out": False,
            "stop_reason": "effective_profile_failed", "task_wall_seconds": 0.0,
            "model_load_seconds": None, "effective_profile_checks": profile_result,
            "workflow_complete": False, "tool_round_trip": False, "final_answer_separate": False,
            "modes_preserved": False, "protected_files": {"passed": False, "not_checked": True},
            "grade": {"success": False, "grader_skipped": True}, "strict_pass": False,
            "changed_files": [], "usage": {}, "server_prefill_tokens": parse_server_prompt_eval_tokens(server_segment),
            "completion_tokens_from_harness_usage": None, "completion_usage_source": "OpenCode step_finish token counters",
            "profile_sha256": _sha256(profile_path), "fixture_sha256": _tree_sha256(fixture_rel),
            "task_prompt_sha256": _sha256(prompt_file), "prompt_bytes": prompt_bytes,
            "source_git_sha": git_provenance(REPO_ROOT)[0], "source_tree_dirty": git_provenance(REPO_ROOT)[1],
            "events_sha256": _sha256(event_path), "stderr_sha256": _sha256(stderr_path),
            "server_log_segment_sha256": hashlib.sha256(server_segment.encode()).hexdigest(),
            "server_log_path": str(server_log), "events_path": str(event_path), "stderr_path": str(stderr_path),
            "resource_summary": summarize_resources([]), "run_dir": str(run_dir),
        }
    command = [str(binary), "run", "--format", "json", "--agent", "build", "--model",
               f"local/{info['alias']}", "--dir", str(workspace), prompt]
    start = time.monotonic()
    timed_out = False
    return_code: int | None = None
    process: subprocess.Popen[Any] | None = None
    sampler: subprocess.Popen[Any] | None = None
    stop_reason: str | None = None
    server_log_offset = server_log.stat().st_size if server_log.exists() else 0
    try:
        with event_path.open("w", encoding="utf-8") as events_out, stderr_path.open("w", encoding="utf-8") as errors_out:
            process = subprocess.Popen(command, cwd=workspace, env=env,
                                       stdin=subprocess.DEVNULL, stdout=events_out,
                                       stderr=errors_out, start_new_session=True)
        sampler = subprocess.Popen([sys.executable, str(REPO_ROOT / "benchmark/resource_sampler.py"), "--output",
                                    str(run_dir / "resources.jsonl"), "--interval", "1"], cwd=workspace, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        while process.poll() is None:
            if time.monotonic() >= round_deadline:
                stop_reason = "round_deadline"
                break
            if time.monotonic() - start >= TASK_LIMIT_SECONDS:
                timed_out = True
                stop_reason = "task_timeout"
                break
            if _server_segment_has_oom(server_log, server_log_offset) or not _server_ready(SERVER_URL):
                stop_reason = "server_lost_or_oom"
                break
            samples = _read_jsonl(run_dir / "resources.jsonl")
            if swap_growth_breach(samples, swap_baseline_bytes):
                stop_reason = "swap_growth_limit"
                break
            time.sleep(0.25)
        if stop_reason:
            _terminate_process_group(process, grace_seconds=4)
        return_code = process.wait()
    finally:
        if process is not None:
            _terminate_process_group(process, grace_seconds=4)
        if sampler is not None:
            _terminate_process_group(sampler, grace_seconds=3)
    final_resources = _read_jsonl(run_dir / "resources.jsonl")
    stop_reason = _post_child_stop_reason(
        server_log, server_log_offset, server_healthy=_server_ready(SERVER_URL),
        existing_reason=stop_reason, resource_samples=final_resources,
        swap_baseline_bytes=swap_baseline_bytes)
    wall = round(time.monotonic() - start, 3)
    events = _read_jsonl(event_path)
    try:
        grade, safe_to_grade = _grade_workspace_when_safe(workspace, fixture_rel, task, run_dir, baseline_modes)
    except Exception as error:
        safe_to_grade = pregrade_workspace_gate(workspace, baseline_modes)
        grade = {"success": False, "grader_error": f"{type(error).__name__}: {error}"}
    if safe_to_grade["passed"]:
        protected = _protected_files_preserved(workspace, fixture_rel, task)
        modes = _file_modes(workspace) == baseline_modes
    else:
        protected = {**safe_to_grade, "protected_content_changes": [], "protected_mode_changes": [],
                     "unscoped_added_files": [], "added_allowed_files": []}
        modes = False
    calls = [event for event in events if event.get("type") == "tool_use"]
    completed_calls = [event for event in calls if event.get("part", {}).get("state", {}).get("status") == "completed"]
    bash_calls = [event for event in completed_calls if str(event.get("part", {}).get("tool", "")).lower() in {"bash", "shell"}]
    edit_indices = [index for index, event in enumerate(events)
                    if event.get("type") == "tool_use"
                    and str(event.get("part", {}).get("tool", "")).lower() in {"edit", "write"}
                    and _successful_event(event)]
    test_indices = [index for index, event in enumerate(events)
                    if event.get("type") == "tool_use"
                    and str(event.get("part", {}).get("tool", "")).lower() in {"bash", "shell"}
                    and "unittest" in json.dumps(event.get("part", {}).get("state", {}).get("input", {})).lower()
                    and _successful_test_event(event)]
    tests_done = bool(test_indices)
    final_text = _primary_final_text(events)
    last_tool_index = max((index for index, event in enumerate(events) if event.get("type") == "tool_use"), default=-1)
    final_answer_separate = bool(final_text.strip()) and any(
        index > last_tool_index and event.get("type") == "text" and str(event.get("part", {}).get("text", "")).strip()
        for index, event in enumerate(events))
    workflow_complete = (bool(edit_indices) and bool(bash_calls) and tests_done
                         and max(edit_indices) < max(test_indices)
                         and final_answer_separate and return_code == 0 and not timed_out)
    tool_round_trip = bool(completed_calls)
    grade["protected_files"] = protected
    grade["success"] = bool(grade.get("success")) and protected["passed"]
    quality_ok = strict_quality_pass(grade, modes_preserved=modes, workflow_complete=workflow_complete,
                                     tool_round_trip=tool_round_trip, command_ok=return_code == 0 and not timed_out)
    server_segment = server_log.read_bytes()[original_server_log:].decode("utf-8", errors="replace") if server_log.exists() else ""
    usage = summarize_usage("opencode", events)
    return {
        "experiment": experiment_name, "stage": stage, "model": model, "model_alias": info["alias"],
        "model_revision": info["revision"], "model_sha256": info["sha256"], "task": task, "repeat": repeat,
        "harness": HARNESS, "harness_version": HARNESS_VERSION, "runtime_revision": RUNTIME_REVISION,
        "context_tokens": CONTEXT, "kv_cache_kv": [KV_CACHE, KV_CACHE], "flash_attention": True,
        "gpu_layers": 99, "reasoning": "off", "prompt_cache": PROMPT_CACHE, "seed": 1234,
        "profile_sha256": _sha256(profile_path), "fixture_sha256": _tree_sha256(fixture_rel),
        "task_prompt_sha256": _sha256(prompt_file), "prompt_bytes": prompt_bytes,
        "source_git_sha": git_provenance(REPO_ROOT)[0], "source_tree_dirty": git_provenance(REPO_ROOT)[1],
        "attempted": True,
        "return_code": return_code, "timed_out": timed_out, "stop_reason": stop_reason,
        "task_wall_seconds": wall, "model_load_seconds": None, "effective_profile_checks": profile_result,
        "workflow_complete": workflow_complete, "tool_round_trip": tool_round_trip,
        "final_answer_separate": final_answer_separate, "modes_preserved": modes,
        "protected_files": protected, "grade": grade, "strict_pass": quality_ok,
        "changed_files": grade.get("changed_files", []), "usage": usage,
        "server_prefill_tokens": parse_server_prompt_eval_tokens(server_segment),
        "completion_tokens_from_harness_usage": usage.get("completion_tokens"),
        "completion_usage_source": "OpenCode step_finish token counters",
        "events_sha256": _sha256(event_path), "stderr_sha256": _sha256(stderr_path),
        "server_log_segment_sha256": hashlib.sha256(server_segment.encode("utf-8")).hexdigest(),
        "server_log_path": str(server_log), "events_path": str(event_path), "stderr_path": str(stderr_path),
        "command": command,
        "resource_summary": summarize_resources(_read_jsonl(run_dir / "resources.jsonl")),
        "run_dir": str(run_dir),
    }


def _successful_event(event: dict[str, Any]) -> bool:
    state = event.get("part", {}).get("state", {})
    metadata = state.get("metadata", {})
    output = state.get("output", "")
    exit_code = metadata.get("exit", metadata.get("exitCode", metadata.get("exit_code")))
    tool = str(event.get("part", {}).get("tool", "")).lower()
    exit_ok = exit_code == 0 if tool in {"bash", "shell"} else exit_code in {None, 0}
    return (state.get("status") == "completed" and not state.get("error") and exit_ok
            and "exit code 1" not in str(output).lower())


def _edit_event_targets_task_md(event: dict[str, Any], workspace: Path) -> bool:
    """Match the completed edit's lexical input path without following links."""
    tool_input = event.get("part", {}).get("state", {}).get("input", {})
    path = tool_input.get("filePath") or tool_input.get("path")
    if not isinstance(path, str) or not path:
        return False
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    expected = (workspace.absolute() / "TASK.md").as_posix()
    return normalized in {"TASK.md", expected}


def compatibility_edit_evidence(events: list[dict[str, Any]], workspace: Path,
                                *, file_verified: bool) -> dict[str, Any]:
    """Require a completed edit or write explicitly targeting TASK.md plus its verified bytes."""
    completed_edits = [event for event in events
                       if event.get("type") == "tool_use"
                       and str(event.get("part", {}).get("tool", "")).lower() in {"edit", "write"}
                       and _successful_event(event)]
    task_md_edits = [event for event in completed_edits
                     if _edit_event_targets_task_md(event, workspace)]
    return {"completed_edit_tool_calls": len(completed_edits),
            "edit_task_md_tool_calls": len(task_md_edits),
            "edit_file_verified": file_verified,
            "edit_tool_round_trip": bool(task_md_edits) and file_verified}


def _successful_test_event(event: dict[str, Any]) -> bool:
    state = event.get("part", {}).get("state", {})
    metadata = state.get("metadata", {})
    output = metadata.get("output", state.get("output", "")) if isinstance(metadata, dict) else state.get("output", "")
    if isinstance(output, dict):
        output = output.get("text", output.get("content", ""))
    import re
    return (_successful_event(event) and isinstance(metadata, dict) and metadata.get("exit") == 0
            and re.search(r"Ran\s+[1-9]\d*\s+tests?\b", str(output)) is not None
            and re.search(r"\bOK\b", str(output)) is not None)


def _primary_final_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "text" and isinstance(event.get("part", {}).get("text"), str):
            return event["part"]["text"]
    return ""


def _append_record(root: Path, record: dict[str, Any]) -> None:
    with (root / "records.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


def _persist_records(root: Path, records: list[dict[str, Any]]) -> None:
    (root / "records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    (root / "summary.json").write_text(
        json.dumps(summarize_denominators(records), indent=2) + "\n", encoding="utf-8")


def _record_diagnostic(root: Path, records: list[dict[str, Any]], record: dict[str, Any]) -> bool:
    """Persist a calibration/warmup diagnostic and report whether it halts the series."""
    records.append(record)
    _append_record(root, record)
    if fatal_diagnostic_stop(record):
        _persist_records(root, records)
        return True
    return False


def _scratch_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _run_server(server: Path, install_root: Path, model: str, server_log: Path,
                round_deadline: float) -> tuple[subprocess.Popen[Any], float]:
    libdir = install_root / "tools/llama-bin"
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib", "LD_LIBRARY_PATH": str(libdir),
           "HOME": str(install_root), "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
    log = server_log.open("w", encoding="utf-8")
    started = time.monotonic()
    proc = subprocess.Popen(_server_command(server, install_root / MODELS[model]["path"], model), env=env,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    deadline = min(started + 180, round_deadline)
    try:
        while time.monotonic() < deadline:
            if _model_loaded(SERVER_URL, MODELS[model]["alias"]):
                return proc, round(time.monotonic() - started, 3)
            if proc.poll() is not None:
                raise RuntimeError(f"Owned llama-server failed during load: exit {proc.returncode}")
            time.sleep(1)
        raise RuntimeError("Owned llama-server did not become ready before its load or round deadline")
    except Exception:
        _stop_server(proc)
        raise


def _stop_server(proc: subprocess.Popen[Any]) -> None:
    _terminate_process_group(proc, grace_seconds=10)


def run_series(install_root: Path, output_root: Path, *, single_agent_released: bool = False,
               mode: str = "r1d") -> list[dict[str, Any]]:
    """Execute gated calibration, warmups, then the frozen schedule."""
    if not single_agent_released:
        raise RuntimeError("Single-agent prerequisite requires the explicit parent release flag before measurement")
    install_root, output_root = install_root.resolve(), output_root.resolve()
    if output_root.exists():
        raise RuntimeError(f"Refusing to overwrite existing output: {output_root}")
    if not _is_ext4(REPO_ROOT) or not _is_ext4(install_root) or not _is_ext4(output_root.parent):
        raise RuntimeError("Source, runtime, and output must be on WSL ext4 SSD")
    if shutil_disk_free(install_root) < MIN_FREE_EXT4_BYTES:
        raise RuntimeError("Refusing series: less than 8 GiB ext4 reserve remains")
    for model, info in MODELS.items():
        model_path = install_root / info["path"]
        if not model_path.is_file() or _sha256(model_path) != info["sha256"]:
            raise RuntimeError(f"Pinned model missing or SHA-256 mismatch: {model}")
    binary = install_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    server = install_root / "tools/llama-bin/llama-server"
    if not binary.is_file() or not server.is_file():
        raise RuntimeError("Pinned OpenCode or llama.cpp binary is missing")
    if subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=10).stdout.find(HARNESS_VERSION) < 0:
        raise RuntimeError("Unexpected OpenCode version")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", SERVER_PORT)) == 0:
            raise RuntimeError("Port 8080 is occupied; refusing to attach to an existing server")
    _assert_server_bundle(server, install_root / "tools/llama-bin")
    _assert_free_resources(install_root)
    server_env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
                  "LD_LIBRARY_PATH": str(install_root / "tools/llama-bin"),
                  "HOME": str(install_root), "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
    runtime_version = subprocess.run([str(server), "--version"], env=server_env, capture_output=True,
                                     text=True, timeout=10)
    if runtime_version.returncode != 0:
        raise RuntimeError("Pinned llama.cpp version command failed")
    version_text = require_runtime_revision(runtime_version.stdout, runtime_version.stderr, RUNTIME_REVISION[:9])
    output_root.mkdir(parents=True, exist_ok=False)
    if mode == "pilot":
        protocol = frozen_pilot_protocol()
        deadline = time.monotonic() + PILOT_ROUND_LIMIT_SECONDS
        schedule = build_pilot_schedule()
        experiment_name = PILOT_EXPERIMENT
    elif mode == "v2":
        protocol = frozen_v2_protocol()
        deadline = time.monotonic() + V2_ROUND_LIMIT_SECONDS
        schedule = build_v2_schedule()
        experiment_name = V2_EXPERIMENT
    else:
        protocol = frozen_protocol()
        deadline = time.monotonic() + ROUND_LIMIT_SECONDS
        schedule = measured_schedule()
        experiment_name = EXPERIMENT
    protocol["source_git_sha"], protocol["source_tree_dirty"] = git_provenance(REPO_ROOT)
    protocol["llama_cpp_version"] = version_text
    protocol["source_file_sha256"] = {
        str(path.relative_to(REPO_ROOT).as_posix()): _sha256(path)
        for path in (Path(__file__), REPO_ROOT / "benchmark/harness_runner.py",
                     REPO_ROOT / "benchmark/harness_eval.py", REPO_ROOT / "benchmark/opencode_controlled_probe.py")
    }
    protocol["started_at_utc"] = datetime.now(timezone.utc).isoformat()
    (output_root / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    records: list[dict[str, Any]] = []
    swap_baseline_bytes = _memory_baseline_bytes()
    for model in MODELS:
        server_log = output_root / f"llama-server-{model}.log"
        try:
            server_process, startup_seconds = _run_server(server, install_root, model, server_log, deadline)
        except Exception as error:
            record = {"experiment": experiment_name, "stage": "compatibility", "model": model,
                      "passed": False, "stop_reason": "model_load_failure",
                      "error": f"{type(error).__name__}: {error}",
                      "server_log_path": str(server_log), "runtime_version": version_text}
            records.append(record)
            _append_record(output_root, record)
            (output_root / "records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            return records
        try:
            try:
                compatibility = _tool_round_trip(binary, install_root, model, server_log, output_root,
                                                 deadline, swap_baseline_bytes)
            except Exception as error:
                compatibility = {"passed": False, "error": f"{type(error).__name__}: {error}",
                                 "profile_checks": {"passed": False}, "server_log_path": str(server_log)}
            (output_root / "compatibility" / model / "record.json").write_text(json.dumps(compatibility, indent=2) + "\n", encoding="utf-8")
            if not compatibility["passed"]:
                record = {"stage": "compatibility", "model": model, "passed": False, "compatibility": compatibility}
                records.append(record)
                _append_record(output_root, record)
                (output_root / "records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
                return records
            try:
                calibration = _run_task(binary, install_root, model, "calculator_division", "calibration", None,
                                        output_root, server_log, deadline, swap_baseline_bytes,
                                        experiment_name=experiment_name)
            except Exception as error:
                calibration = {"experiment": experiment_name, "stage": "calibration", "model": model,
                               "task": "calculator_division", "attempted": True, "strict_pass": False,
                               "stop_reason": f"runner_error:{type(error).__name__}", "error": str(error),
                               "task_wall_seconds": None}
            calibration["model_load_seconds"] = round(startup_seconds, 3)
            calibration["compatibility_passed"] = True
            if _record_diagnostic(output_root, records, calibration):
                return records
            try:
                warmup = _run_task(binary, install_root, model, "calculator_division", "warmup", None,
                                   output_root, server_log, deadline, swap_baseline_bytes,
                                   experiment_name=experiment_name)
            except Exception as error:
                warmup = {"experiment": experiment_name, "stage": "warmup", "model": model,
                          "task": "calculator_division", "attempted": True, "strict_pass": False,
                          "stop_reason": f"runner_error:{type(error).__name__}", "error": str(error),
                          "task_wall_seconds": None}
            warmup["model_load_seconds"] = round(startup_seconds, 3)
            if _record_diagnostic(output_root, records, warmup):
                return records
        finally:
            _stop_server(server_process)
        if _scratch_size(output_root) > MAX_SCRATCH_BYTES:
            record = {"experiment": experiment_name, "stage": "series_guard", "model": model,
                      "attempted": False, "strict_pass": False,
                      "stop_reason": "scratch_limit_after_calibration_warmup"}
            records.append(record)
            _append_record(output_root, record)
            (output_root / "records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
            (output_root / "summary.json").write_text(json.dumps(summarize_denominators(records), indent=2) + "\n", encoding="utf-8")
            return records
    try:
        measured_block = 0
        for item in schedule:
            if time.monotonic() >= deadline:
                record = {**item, "attempted": False, "strict_pass": False, "stop_reason": "round_deadline", "task_wall_seconds": None}
                records.append(record)
                _append_record(output_root, record)
                continue
            model = item["model"]
            active_model = getattr(run_series, "_active_model", None)
            process = getattr(run_series, "_active_server", None)
            if active_model != model or process is None or process.poll() is not None:
                if process is not None and process.poll() is None:
                    _stop_server(process)
                if active_model is not None and _is_ext4(install_root):
                    time.sleep(0.5)
                measured_block += 1
                server_log = output_root / f"llama-server-measured-block-{measured_block}-{model}.log"
                try:
                    process, startup_seconds = _run_server(server, install_root, model, server_log, deadline)
                except Exception as error:
                    record = {**item, "attempted": False, "strict_pass": False,
                              "stop_reason": "measured_model_load_failure",
                              "error": f"{type(error).__name__}: {error}",
                              "server_log_path": str(server_log), "task_wall_seconds": None}
                    records.append(record)
                    _append_record(output_root, record)
                    _persist_records(output_root, records)
                    break
                run_series._active_model, run_series._active_server = model, process
            try:
                row = _run_task(binary, install_root, model, item["task"], "measurement", item["repeat"],
                                output_root, server_log, deadline, swap_baseline_bytes,
                                experiment_name=experiment_name)
            except Exception as error:
                row = {**item, "attempted": True, "strict_pass": False,
                       "stop_reason": f"runner_error:{type(error).__name__}",
                       "error": str(error), "task_wall_seconds": None}
            row["model_load_seconds"] = startup_seconds
            records.append(row)
            _append_record(output_root, row)
            _persist_records(output_root, records)
            if fatal_diagnostic_stop(row):
                break
            if _scratch_size(output_root) > MAX_SCRATCH_BYTES:
                record = {"experiment": experiment_name, "stage": "series_guard", "model": model,
                          "task": item["task"], "repeat": item["repeat"], "attempted": False,
                          "strict_pass": False, "stop_reason": "scratch_limit"}
                records.append(record)
                _append_record(output_root, record)
                _persist_records(output_root, records)
                break
    finally:
        process = getattr(run_series, "_active_server", None)
        if process is not None:
            _stop_server(process)
            run_series._active_server = None
            run_series._active_model = None
    (output_root / "summary.json").write_text(json.dumps(summarize_denominators(records), indent=2) + "\n", encoding="utf-8")
    return records


def shutil_disk_free(path: Path) -> int:
    import shutil
    return shutil.disk_usage(path).free


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, default=Path(os.getenv("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark")))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--mode", choices=["r1d", "pilot", "v2"], default="r1d",
                        help="series mode: r1d (historical), pilot (4 calls), v2 (24 trials)")
    parser.add_argument("--pilot", action="store_true", help="shorthand for --mode pilot")
    parser.add_argument("--v2", "--matrix", action="store_true", dest="v2", help="shorthand for --mode v2")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="write the frozen protocol only (the default; inference never starts)")
    parser.add_argument("--execute", action="store_true", help="explicitly run the gated GPU series")
    parser.add_argument("--single-agent-release", action="store_true",
                        help="record the parent's prospective release for this independently gated single-agent series")
    args = parser.parse_args(argv)
    if args.pilot:
        mode = "pilot"
    elif args.v2:
        mode = "v2"
    else:
        mode = args.mode

    if mode == "pilot":
        default_dir = f"model-quality-pilot-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        protocol = frozen_pilot_protocol()
    elif mode == "v2":
        default_dir = f"model-quality-v2-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        protocol = frozen_v2_protocol()
    else:
        default_dir = "model-quality-paired-20261012-r1d"
        protocol = frozen_protocol()

    output = args.output_root or args.benchmark_root / "results/raw" / default_dir
    if not args.execute:
        print(json.dumps({"protocol": protocol, "benchmark_root": str(args.benchmark_root),
                          "output_root": str(output), "mode": mode, "inference_started": False}, indent=2))
        return 0
    if not args.single_agent_release:
        parser.error("--execute requires the independent single-agent release; Round 0 remains recorded as failed")
    run_series(args.benchmark_root, output, single_agent_released=args.single_agent_release, mode=mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
