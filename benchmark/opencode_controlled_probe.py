"""Gated, isolated OpenCode read-only and matched delegation probe."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.harness_eval import GRADER_PROTOCOL_VERSION, grade_workspace  # noqa: E402
from benchmark.provenance import git_provenance  # noqa: E402
from benchmark.harness_runner import (  # noqa: E402
    DEFAULT_CONTEXT,
    DEFAULT_MODEL,
    DEFAULT_MODEL_PATH,
    _isolated_environment,
    _preflight,
    _read_jsonl,
    _prepare_run,
    summarize_resources,
    summarize_usage,
)

CHILDREN = ("repo-explorer", "independent-reviewer")
PROFILE_PATH = REPO_ROOT / "benchmark/configs/harnesses/opencode-subagents.json"
MODEL_SHA256 = "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"
EXPECTED_SMOKE_NAMES = (
    "test_ignores_blank_and_comment_lines",
    "test_splits_on_first_equals_and_trims",
    "test_strips_matching_quotes",
)


def derive_profile(base: dict[str, Any], arm: str) -> dict[str, Any]:
    """Return a hardened 10-step smoke profile or a 20-step comparison arm."""
    if arm not in {"smoke", "control", "treatment"}:
        raise ValueError(f"Unsupported profile arm: {arm}")
    result = copy.deepcopy(base)
    agents = result["agent"]
    build = agents["build"]
    build_permissions = build.setdefault("permission", {})
    for name, agent in agents.items():
        agent.setdefault("permission", {})["external_directory"] = {"*": "deny"}
    if arm != "smoke":
        build["steps"] = 20
        permissions = {"*": "deny"}
        if arm == "treatment":
            permissions.update({name: "allow" for name in CHILDREN})
        build_permissions["task"] = permissions
    coding_action = "deny" if arm == "smoke" else "allow"
    for tool in ("bash", "edit"):
        build_permissions[tool] = {"*": coding_action}
    for child_name in CHILDREN:
        child_permissions = agents[child_name].setdefault("permission", {})
        child_permissions["bash"] = {"*": "deny"}
        child_permissions["edit"] = {"*": "deny"}
    return result


def _last_wildcard_action(permissions: list[dict[str, Any]], permission: str) -> str | None:
    """Return the last global action for a permission, including the global tool rule."""
    return next(
        (
            item.get("action")
            for item in reversed(permissions)
            if item.get("permission") in {permission, "*"} and item.get("pattern") == "*"
        ),
        None,
    )


def _terminal_deny_rule(
    permissions: list[dict[str, Any]], permission: str, allowed_later_rules: set[tuple[str, str, str]] | None = None
) -> bool:
    """Require the final broad deny to remain effective despite later matching rules."""
    allowed_later_rules = allowed_later_rules or set()
    deny_index = next(
        (
            index
            for index in range(len(permissions) - 1, -1, -1)
            if permissions[index].get("permission") == permission
            and permissions[index].get("pattern") == "*"
            and permissions[index].get("action") == "deny"
        ),
        None,
    )
    if deny_index is None:
        return False
    for item in permissions[deny_index + 1 :]:
        if item.get("permission") not in {permission, "*"} or item.get("action") not in {"allow", "ask"}:
            continue
        later_rule = (item.get("permission"), item.get("pattern"), item.get("action"))
        if later_rule not in allowed_later_rules:
            return False
    return True


def child_task_calls(events: list[dict[str, Any]]) -> list[str]:
    calls: list[str] = []
    for event in events:
        part = event.get("part", {})
        state = part.get("state", {})
        if event.get("type") != "tool_use" or part.get("tool") != "task":
            continue
        if state.get("status") != "completed":
            continue
        child = state.get("input", {}).get("subagent_type")
        if isinstance(child, str):
            calls.append(child)
    return calls


def _task_events(events: list[dict[str, Any]]) -> list[tuple[int, str, dict[str, Any]]]:
    result = []
    for index, event in enumerate(events):
        part = event.get("part", {})
        state = part.get("state", {})
        if event.get("type") == "tool_use" and part.get("tool") == "task":
            child = state.get("input", {}).get("subagent_type")
            if state.get("status") == "completed" and isinstance(child, str):
                result.append((index, child, state))
    return result


def read_only_smoke_gate(
    events: list[dict[str, Any]], output_text: str, changed_files: list[str]
) -> bool:
    names = re.findall(r"test_[A-Za-z0-9_]+", output_text)
    residue = output_text
    for name in EXPECTED_SMOKE_NAMES:
        residue = residue.replace(name, "")
    residue = re.sub(r"[\s,;:.*_`'\"-]", "", residue)
    return (
        child_task_calls(events) == ["repo-explorer"]
        and tuple(names) == EXPECTED_SMOKE_NAMES
        and not residue
        and not changed_files
    )


def calibration_gate(arm: str, task_success: bool, children: list[str]) -> bool:
    if arm == "control":
        return task_success and not children
    if arm == "treatment":
        return task_success and children == list(CHILDREN)
    raise ValueError(f"Unsupported calibration arm: {arm}")


def workflow_gate(arm: str, task_success: bool, events: list[dict[str, Any]]) -> bool:
    calls = _task_events(events)
    children = [name for _, name, _ in calls]
    if arm == "control":
        return task_success and not children
    if arm != "treatment":
        raise ValueError(f"Unsupported calibration arm: {arm}")
    indexed = {name: (index, state) for index, name, state in calls}
    if not calibration_gate(arm, task_success, children):
        return False
    explorer_index, _ = indexed[CHILDREN[0]]
    reviewer_index, reviewer_state = indexed[CHILDREN[1]]
    completed_tool_indices = [
        index for index, event in enumerate(events)
        if event.get("type") == "tool_use" and event.get("part", {}).get("state", {}).get("status") == "completed"
    ]
    if not completed_tool_indices or max(completed_tool_indices) != reviewer_index:
        return False
    edit_indices = [
        index for index, event in enumerate(events[explorer_index + 1:reviewer_index], explorer_index + 1)
        if str(event.get("part", {}).get("tool", "")).lower() in {"edit", "write"}
        and _successful_tool_event(event)
    ]
    if not edit_indices:
        return False
    test_indices = []
    for index, event in enumerate(events[explorer_index + 1:reviewer_index], explorer_index + 1):
        part = event.get("part", {})
        tool = str(part.get("tool", "")).lower()
        state = part.get("state", {})
        input_text = json.dumps(state.get("input", {}), ensure_ascii=False).lower()
        if tool in {"bash", "shell"} and re.search(r"python(?:3(?:\.\d+)?)?\s+-m\s+unittest\b", input_text) and _successful_test_event(event):
            test_indices.append(index)
    if not test_indices or max(edit_indices) >= max(test_indices) or max(test_indices) >= reviewer_index:
        return False
    for event in events[reviewer_index + 1:]:
        part = event.get("part", {})
        state = part.get("state", {})
        tool = str(part.get("tool", "")).lower()
        input_text = json.dumps(state.get("input", {}), ensure_ascii=False).lower()
        if (tool in {"edit", "write"} and _successful_tool_event(event)) or (
            tool in {"bash", "shell"}
            and re.search(r"python(?:3(?:\.\d+)?)?\s+-m\s+unittest\b", input_text)
            and _successful_test_event(event)
        ):
            return False
    output = reviewer_state.get("output", reviewer_state.get("result", ""))
    if isinstance(output, dict):
        output = output.get("text", output.get("content", output.get("message", "")))
    return isinstance(output, str) and len(output.strip()) >= 20


def _successful_tool_event(event: dict[str, Any]) -> bool:
    state = event.get("part", {}).get("state", {})
    if state.get("status") != "completed" or state.get("error"):
        return False
    metadata = state.get("metadata", {})
    exit_code = metadata.get("exit", metadata.get("exitCode", metadata.get("exit_code"))) if isinstance(metadata, dict) else None
    if exit_code is not None and exit_code != 0:
        return False
    output = state.get("output", "")
    if isinstance(output, dict):
        exit_code = output.get("exitCode", output.get("exit_code"))
        if exit_code is not None and exit_code != 0:
            return False
        output = output.get("text", output.get("content", ""))
    return not re.search(r"\bexit\s+code\s*[:=]\s*[1-9]\d*\b", str(output), re.IGNORECASE)


def _successful_test_event(event: dict[str, Any]) -> bool:
    state = event.get("part", {}).get("state", {})
    metadata = state.get("metadata", {})
    return _successful_tool_event(event) and isinstance(metadata, dict) and metadata.get("exit") == 0


def require_runtime_revision(stdout: str, stderr: str, expected: str) -> str:
    combined = (stdout + stderr).strip()
    if expected not in combined:
        raise RuntimeError(f"Unexpected llama.cpp build: {combined}")
    return combined


def primary_final_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "text" and isinstance(event.get("part", {}).get("text"), str):
            return event["part"]["text"]
    return ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts)
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _append_record(root: Path, records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    records.append(record)
    with (root / "records.jsonl").open("a", encoding="utf-8") as target:
        target.write(json.dumps(record, ensure_ascii=False) + "\n")
    _write_json(root / "series.json", {"records": records})


def _is_ext4(path: Path) -> bool:
    probe = path if path.exists() else path.parent
    result = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", str(probe)], capture_output=True, text=True, check=True
    )
    return result.stdout.strip() == "ext4"


def _assert_server_bundle(server: Path, libdir: Path) -> None:
    checker = REPO_ROOT / "scripts/lib/ssd_preflight.sh"
    command = (
        f"source {json.dumps(str(checker))}; "
        f"require_llama_cpp_ssd_bundle {json.dumps(str(server))} {json.dumps(str(libdir))}"
    )
    subprocess.run(["bash", "-lc", command], check=True, capture_output=True, text=True)


def _assert_free_resources(root: Path) -> None:
    free_gib = shutil.disk_usage(root).free / 1024**3
    if free_gib < 8:
        raise RuntimeError(f"Refusing probe: only {free_gib:.2f} GiB free on ext4; 8 GiB is reserved")
    memory = {}
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        key, _, tail = line.partition(":")
        if key in {"MemAvailable", "SwapFree"}:
            memory[key] = int(tail.split()[0]) * 1024
    if memory.get("MemAvailable", 0) < 5 * 1024**3:
        raise RuntimeError("Refusing probe: less than 5 GiB WSL memory is available")
    if memory.get("SwapFree", 0) < 3 * 1024**3:
        raise RuntimeError("Refusing probe: less than 3 GiB WSL swap is free")


def _run_checked(command: list[str], env: dict[str, str], timeout: int, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout, **kwargs)


def _config_gate(binary: Path, home: Path, env: dict[str, str], arm: str) -> dict[str, bool]:
    config = _run_checked([str(binary), "debug", "config", "--pure"], env, 20)
    build = _run_checked([str(binary), "debug", "agent", "build", "--pure"], env, 20)
    explorer = _run_checked([str(binary), "debug", "agent", CHILDREN[0], "--pure"], env, 20)
    reviewer = _run_checked([str(binary), "debug", "agent", CHILDREN[1], "--pure"], env, 20)
    for name, result in (("config", config), ("build", build), ("explorer", explorer), ("reviewer", reviewer)):
        if result.returncode != 0:
            raise RuntimeError(f"OpenCode effective {name} inspection failed (exit {result.returncode})")
    try:
        config_data = json.loads(config.stdout)
        agent_data = {"build": json.loads(build.stdout), CHILDREN[0]: json.loads(explorer.stdout), CHILDREN[1]: json.loads(reviewer.stdout)}
    except json.JSONDecodeError as error:
        raise RuntimeError("OpenCode effective profile output was not valid JSON") from error

    def pairs(value: Any):
        if isinstance(value, dict):
            yield from value.items()
            for nested in value.values():
                yield from pairs(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from pairs(nested)

    config_values = list(pairs(config_data))
    base_url = next((str(value) for key, value in config_values if str(key).lower() == "baseurl"), "")
    autoupdate = next((value for key, value in config_values if str(key).lower() == "autoupdate"), None)
    build_data = agent_data["build"]
    tool_output_rule = (
        "external_directory",
        str(Path(env["XDG_DATA_HOME"]) / "opencode/tool-output/*"),
        "allow",
    )
    task_rules = [
        (item.get("pattern"), item.get("action"))
        for item in build_data.get("permission", [])
        if item.get("permission") == "task"
    ]
    expected_rules = [("*", "deny")]
    if arm in {"smoke", "treatment"}:
        expected_rules.extend((name, "allow") for name in CHILDREN)
    checks = {
        "local_endpoint": base_url == "http://127.0.0.1:8080/v1",
        "autoupdate_disabled": autoupdate is False,
        "configured_model": any(str(key).lower() == "model" and value == f"local/{DEFAULT_MODEL}" for key, value in config_values),
        "build_primary": build_data.get("mode") == "primary",
        "build_steps": build_data.get("steps") == (10 if arm == "smoke" else 20),
        "task_permissions_exact": sorted(task_rules) == sorted(expected_rules),
    }
    expected_coding_action = "deny" if arm == "smoke" else "allow"
    checks["build_tool_permissions_explicit"] = all(
        _last_wildcard_action(build_data.get("permission", []), permission) == action
        for permission, action in (
            ("bash", expected_coding_action),
            ("edit", expected_coding_action),
            ("external_directory", "deny"),
        )
    )
    checks["build_external_directory_terminal_deny"] = _terminal_deny_rule(
        build_data.get("permission", []), "external_directory", {tool_output_rule}
    )
    checks["build_smoke_tool_denies_terminal"] = arm != "smoke" or all(
        _terminal_deny_rule(build_data.get("permission", []), permission)
        for permission in ("bash", "edit")
    )
    selected_agents: dict[str, Any] = {}
    for name, data in agent_data.items():
        permissions = [
            {"permission": item.get("permission"), "pattern": item.get("pattern"), "action": item.get("action")}
            for item in data.get("permission", [])
            if item.get("permission") in {"*", "task", "edit", "bash", "external_directory"}
        ]
        selected_agents[name] = {"name": data.get("name"), "mode": data.get("mode"), "steps": data.get("steps"), "permissions": permissions}
        checks[f"{name}_external_directory_denied"] = (
            _last_wildcard_action(data.get("permission", []), "external_directory") == "deny"
            and _terminal_deny_rule(data.get("permission", []), "external_directory", {tool_output_rule})
        )
    for child in CHILDREN:
        child_data = agent_data[child]
        checks[f"{child}_readonly"] = (
            child_data.get("mode") == "subagent"
            and _last_wildcard_action(child_data.get("permission", []), "bash") == "deny"
            and _last_wildcard_action(child_data.get("permission", []), "edit") == "deny"
            and _terminal_deny_rule(child_data.get("permission", []), "bash")
            and _terminal_deny_rule(child_data.get("permission", []), "edit")
            and _terminal_deny_rule(child_data.get("permission", []), "external_directory", {tool_output_rule})
        )
    _write_json(home.parent / f"effective-{arm}.json", {
        "model": next((str(value) for key, value in config_values if str(key).lower() == "model"), None),
        "base_url": base_url,
        "autoupdate": autoupdate,
        "agents": selected_agents,
        "checks": checks,
    })
    if not all(checks.values()):
        raise RuntimeError(f"Effective profile gate failed: {checks}")
    return checks


def _server_url_ready(url: str) -> bool:
    try:
        with urllib_request.urlopen(url.rstrip("/") + "/v1/models", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def _workspace_changes(workspace: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line[3:] for line in result.stdout.splitlines()]


def _run_arm(
    arm: str,
    run_dir: Path,
    install_root: Path,
    binary: Path,
    server_url: str,
    seconds: int,
    task: str,
    label: str | None = None,
) -> dict[str, Any]:
    fixture = REPO_ROOT / "benchmark/fixtures/harness_env_parser" if task == "readonly" else REPO_ROOT / "benchmark/fixtures/harness_task"
    if task == "readonly":
        prompt = (
            "Use repo-explorer to inspect tests/test_config_parser.py. Return only the exact three test function names. "
            "Do not edit, run commands, create files, or call any other tool."
        )
    else:
        prompt_path = REPO_ROOT / "benchmark/configs/harnesses/task_prompt.md"
        prompt = prompt_path.read_text(encoding="utf-8").strip()
        if arm == "treatment":
            prompt += (
                "\n\nOrchestration: first call repo-explorer to identify the calculator behavior and relevant tests. "
                "Then implement the requested change and run the existing tests. Finally call independent-reviewer "
                "to inspect the diff and test evidence. Do not broaden scope."
            )
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "tmp").mkdir()
    prompt_file = _prepare_run("opencode", run_dir, install_root, prompt, fixture=fixture)
    workspace = run_dir / "workspace"
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    profile = derive_profile(profile, arm)
    config_path = run_dir / "home/.config/opencode/opencode.json"
    config_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    env = _isolated_environment("opencode", run_dir, install_root, workspace)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    gate = _config_gate(binary, run_dir / "home", env, arm)
    output_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    resource_path = run_dir / "resources.jsonl"
    sampler = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "benchmark/resource_sampler.py"), "--output", str(resource_path), "--interval", "1"],
        cwd=workspace,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    command = [
        str(binary), "run", "--format", "json", "--agent", "build",
        "--model", f"local/{DEFAULT_MODEL}", "--dir", str(workspace), prompt,
    ]
    started = time.perf_counter()
    timed_out = False
    try:
        with output_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(command, cwd=workspace, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                return_code = process.wait(timeout=seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    return_code = process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    return_code = process.wait()
    finally:
        os.killpg(sampler.pid, signal.SIGTERM)
        try:
            sampler.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(sampler.pid, signal.SIGKILL)
            sampler.wait()
    wall_seconds = round(time.perf_counter() - started, 3)
    events = _read_jsonl(output_path)
    text_output = primary_final_text(events)
    changed = _workspace_changes(workspace)
    success = False
    quality: dict[str, Any] | None = None
    if task == "readonly":
        gate_passed = read_only_smoke_gate(events, text_output, changed)
        success = return_code == 0 and not timed_out and gate_passed
    else:
        quality = grade_workspace(workspace, fixture, artifact_dir=run_dir / "grader-artifacts")
        gate_passed = workflow_gate(arm, bool(quality.get("success")), events)
        success = return_code == 0 and not timed_out and gate_passed
    children = child_task_calls(events)
    source_revision, source_tree_dirty = git_provenance(REPO_ROOT)
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
        "arm": arm,
        "run_label": label or arm,
        "task": task,
        "command": command,
        "profile_sha256": _sha256(config_path),
        "tracked_profile_sha256": _sha256(PROFILE_PATH),
        "source_git_sha": source_revision,
        "source_tree_dirty": source_tree_dirty,
        "fixture_sha256": _tree_sha256(fixture),
        "task_prompt_sha256": _sha256(prompt_file),
        "effective_profile_checks": gate,
        "return_code": return_code,
        "timed_out": timed_out,
        "wall_seconds": wall_seconds,
        "child_task_calls_completed": children,
        "workflow_gate": gate_passed,
        "primary_text": text_output,
        "changed_files": changed,
        "success": success,
        "quality": quality,
        "usage": summarize_usage("opencode", events),
        "resources": summarize_resources(_read_jsonl(resource_path)),
        "prompt_file": str(prompt_file),
    }
    _write_json(run_dir / "record.json", record)
    return record


def _scratch_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-root", type=Path, default=Path(os.getenv("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark")))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--phase", choices=("smoke", "all"), default="all")
    args = parser.parse_args()
    root = args.install_root.resolve()
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = (args.output_root or root / "results/raw" / f"opencode-controlled-20261011-{run_stamp}").resolve()
    if output_root.exists():
        raise RuntimeError(f"Refusing to overwrite existing probe output: {output_root}")
    if not _is_ext4(REPO_ROOT) or not _is_ext4(root) or not _is_ext4(output_root.parent):
        raise RuntimeError("Source, runtime and results must be on WSL ext4 SSD")
    _assert_free_resources(root)
    model_path = root / DEFAULT_MODEL_PATH
    if _sha256(model_path) != MODEL_SHA256:
        raise RuntimeError("Pinned model SHA-256 mismatch; refusing probe")
    binary = root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    server = root / "tools/llama-bin/llama-server"
    libdir = root / "tools/llama-bin"
    _assert_server_bundle(server, libdir)
    version_env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp/opencode-version-home",
        "XDG_CONFIG_HOME": "/tmp/opencode-version-config",
        "XDG_DATA_HOME": "/tmp/opencode-version-data",
        "XDG_CACHE_HOME": "/tmp/opencode-version-cache",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
    }
    version = _run_checked([str(binary), "--version"], version_env, 10)
    if "1.19.0" not in version.stdout:
        raise RuntimeError(f"Unexpected OpenCode version: {version.stdout.strip()}")
    with socket.socket() as probe_socket:
        if probe_socket.connect_ex(("127.0.0.1", 8080)) == 0:
            raise RuntimeError("Port 8080 is already occupied; will not attach or stop an existing server")
    output_root.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + 35 * 60
    log_dir = output_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=False)
    server_log = log_dir / "llama-server.log"
    server_env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
        "LD_LIBRARY_PATH": str(libdir),
        "HOME": str(root),
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
    }
    runtime_version = _run_checked([str(server), "--version"], server_env, 10)
    runtime_version_text = require_runtime_revision(runtime_version.stdout, runtime_version.stderr, "d81235049")
    _write_json(output_root / "preflight.json", {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_git_sha": git_provenance(REPO_ROOT)[0],
        "opencode_version": version.stdout.strip(),
        "llama_cpp_version": runtime_version_text,
        "model_sha256": MODEL_SHA256,
        "server_bundle_ldd_preflight": "passed",
    })
    server_command = [
        str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", "8080",
        "--alias", DEFAULT_MODEL, "--ctx-size", str(DEFAULT_CONTEXT), "--n-gpu-layers", "99", "--batch-size", "512",
        "--ubatch-size", "256", "--flash-attn", "on", "--cache-type-k", "q4_0",
        "--cache-type-v", "q4_0", "--reasoning", "off", "--no-cache-prompt", "--parallel", "1", "--no-webui",
    ]
    with server_log.open("w", encoding="utf-8") as log:
        server_process = subprocess.Popen(server_command, env=server_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    records: list[dict[str, Any]] = []
    try:
        for _ in range(180):
            if _server_url_ready("http://127.0.0.1:8080"):
                break
            if server_process.poll() is not None:
                raise RuntimeError(f"Owned llama-server exited during startup ({server_process.returncode})")
            time.sleep(1)
        else:
            raise RuntimeError("Owned llama-server did not become ready within 180 seconds")
        preflight = _preflight(
            root,
            DEFAULT_MODEL,
            model_path,
            DEFAULT_CONTEXT,
            "http://127.0.0.1:8080",
            server_log,
            output_root / "series.json",
        )
        phases = ("smoke",) if args.phase == "smoke" else ("smoke", "calibration")
        smoke_ok = False
        if "smoke" in phases:
            record = _run_arm("smoke", output_root / "smoke", root, binary, "http://127.0.0.1:8080", 90, "readonly")
            _append_record(output_root, records, record)
            if _scratch_bytes(output_root) > 1024**3:
                raise RuntimeError("Probe scratch exceeded the 1 GiB total cap")
            smoke_ok = record["success"]
            if not smoke_ok:
                return 0 if smoke_ok else 2
        if args.phase == "smoke":
            return 0 if smoke_ok else 2
        if "calibration" in phases and smoke_ok:
            for arm in ("control", "treatment"):
                if time.monotonic() + 190 > deadline:
                    raise RuntimeError("35-minute probe budget exhausted before calibration")
                record = _run_arm(arm, output_root / f"calibration-{arm}", root, binary, "http://127.0.0.1:8080", 180, "calculator")
                record["calibration_gate"] = calibration_gate(arm, record["success"], record["child_task_calls_completed"])
                _append_record(output_root, records, record)
                if _scratch_bytes(output_root) > 1024**3:
                    raise RuntimeError("Probe scratch exceeded the 1 GiB total cap")
                if not record["calibration_gate"]:
                    return 2
            for arm in ("control", "treatment"):
                if time.monotonic() + 190 > deadline:
                    raise RuntimeError("35-minute probe budget exhausted before warm-up")
                record = _run_arm(arm, output_root / f"warmup-{arm}", root, binary, "http://127.0.0.1:8080", 180, "calculator", label="warmup")
                _append_record(output_root, records, record)
                if _scratch_bytes(output_root) > 1024**3:
                    raise RuntimeError("Probe scratch exceeded the 1 GiB total cap")
            pair_orders = (("control", "treatment"), ("treatment", "control"), ("control", "treatment"))
            for pair_number, order in enumerate(pair_orders, start=1):
                for arm in order:
                    if time.monotonic() + 190 > deadline:
                        raise RuntimeError("35-minute probe budget exhausted during measured pairs")
                    label = f"measurement-pair-{pair_number}"
                    record = _run_arm(arm, output_root / f"{label}-{arm}", root, binary, "http://127.0.0.1:8080", 180, "calculator", label=label)
                    record["pair_number"] = pair_number
                    _append_record(output_root, records, record)
                    if _scratch_bytes(output_root) > 1024**3:
                        raise RuntimeError("Probe scratch exceeded the 1 GiB total cap")
    finally:
        os.killpg(server_process.pid, signal.SIGTERM)
        try:
            server_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(server_process.pid, signal.SIGKILL)
            server_process.wait()
    print(json.dumps({"opencode_version": version.stdout.strip(), "llama_cpp_version": runtime_version_text, "model_sha256": MODEL_SHA256, "model_preflight": preflight, "records": records}, indent=2))
    return 0


try:
    from urllib import request as urllib_request
except ImportError:  # pragma: no cover
    urllib_request = None  # type: ignore[assignment]


if __name__ == "__main__":
    raise SystemExit(main())
