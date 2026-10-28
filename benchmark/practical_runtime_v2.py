"""Isolated execution and grading for the practical-agent v2 campaign.

The candidate gets only its seeded workspace, the pinned OpenCode/Node/Python
runtimes, a small driver, and the public MCP service. Task references and
acceptance checks remain host-side and are mounted only into fresh graders.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from benchmark import campaign_readiness, model_quality_paired, practical_tasks_v2, practical_test_quality as test_quality, safe_campaign
from benchmark.linux_sandbox import (
    McpPolicy,
    ResourceLimits,
    RuntimeBind,
    SandboxSpec,
    SandboxSupervisor,
)
from benchmark.model_broker import BrokerPolicy
from benchmark.practical_mcp_bridge import McpBridge
from benchmark.practical_policy import BudgetPolicy, classify_request, usage_from_bytes, validate_history
from benchmark.practical_manual import manual_evidence


ROOT = Path(__file__).resolve().parents[1]
LAB = Path("/home/foxtrot/local-llm-benchmark")
PROTOCOL = "practical-agent-limits-skills-v2"
DEFAULT_GPU_FREE_FLOOR_MIB = 7168
MIN_GPU_FREE_FLOOR_MIB = 7000
GPU_FREE_FLOOR_MIB = DEFAULT_GPU_FREE_FLOOR_MIB
NODE_ROOT = LAB / "runtimes/node-v22.23.3-linux-x64"
NODE = NODE_ROOT / "bin/node"
OPENCODE = LAB / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
SEEDS = {1: 101, 2: 202, 3: 303}
_CONTEXTS = {"baseline": (16384, False), "cache_on": (16384, True)}
_MCP_TASKS = {"C2", "M2", "D2", "H2"}
_ARTIFACTS = {"C2": "report.json", "M2": "receipt.json",
              "D2": "reconciliation.json", "H2": "asset-report.json"}
_VERIFIED_MODEL_HASHES: dict[tuple[Any, ...], str] = {}
_VERIFIED_SERVER_BUNDLE: set[tuple[str, int, int, int, int]] = set()
_ACTIVE_RUNTIME_CONTRACT: dict[str, str] | None = None


def configure_runtime_contract(contract: Mapping[str, str] | None) -> None:
    """Select a measured daily runtime for a new practical campaign only."""
    if contract is not None and (
            not isinstance(contract, Mapping) or set(contract) != {'opencode', 'llama_revision'}
            or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', str(contract.get('opencode', '')))
            or not re.fullmatch(r'[0-9a-f]{40}', str(contract.get('llama_revision', '')))):
        raise ValueError('invalid runtime contract')
    global _ACTIVE_RUNTIME_CONTRACT
    _ACTIVE_RUNTIME_CONTRACT = dict(contract) if contract is not None else None


def current_runtime_contract(lab: Path) -> dict[str, str]:
    if _ACTIVE_RUNTIME_CONTRACT is not None:
        return dict(_ACTIVE_RUNTIME_CONTRACT)
    day = datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
    marker = Path(lab) / 'state/runtime-updates' / f'daily-{day}.json'
    if marker.is_file():
        value = json.loads(marker.read_text())
        if value.get('date') != day or value.get('status') != 'complete':
            raise ValueError('invalid daily runtime evidence')
        result = {'opencode': value['applications']['opencode'],
                  'llama_revision': value['llama_cpp']['commit']}
        if (not re.fullmatch(r'[0-9a-f]{40}', str(result['llama_revision']))
                or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', str(result['opencode']))):
            raise ValueError('invalid daily runtime contract')
        return result
    return {'opencode': model_quality_paired.HARNESS_VERSION,
            'llama_revision': model_quality_paired.RUNTIME_REVISION}


def build_generation_policy(repetition: int) -> dict[str, Any]:
    if type(repetition) is not int or repetition not in SEEDS:
        raise ValueError("repetition must be one of 1, 2, or 3")
    return {"temperature": 0.2, "top_p": 0.95, "seed": SEEDS[repetition], "max_tokens": 4096}


def validate_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, Mapping):
        raise ValueError("profile must be a mapping")
    profile_id = profile.get("id")
    if profile_id == "context_32k":
        expected_context = 32768
        cache = profile.get("cache_prompt")
        if type(cache) is not bool:
            raise ValueError("context_32k profile must freeze cache_prompt")
    elif profile_id in _CONTEXTS:
        expected_context, expected_cache = _CONTEXTS[profile_id]
        cache = profile.get("cache_prompt")
        if type(cache) is not bool or cache is not expected_cache:
            raise ValueError(f"{profile_id} profile has a non-canonical prompt-cache setting")
    else:
        raise ValueError("profile id must be baseline, cache_on, or context_32k")
    if type(profile.get("context_tokens")) is not int or profile["context_tokens"] != expected_context:
        raise ValueError("profile context does not match its canonical id")
    if set(profile) != {"id", "context_tokens", "cache_prompt"}:
        raise ValueError("profile contains unfrozen settings")
    return {"id": profile_id, "context_tokens": expected_context, "cache_prompt": cache}


def configure_gpu_free_floor_mib(value: int) -> None:
    """Apply an explicit, bounded per-load GPU capacity floor."""
    if type(value) is not int or not MIN_GPU_FREE_FLOOR_MIB <= value <= DEFAULT_GPU_FREE_FLOOR_MIB:
        raise ValueError(
            f"GPU free floor must be between {MIN_GPU_FREE_FLOOR_MIB} and "
            f"{DEFAULT_GPU_FREE_FLOOR_MIB} MiB"
        )
    global GPU_FREE_FLOOR_MIB
    GPU_FREE_FLOOR_MIB = value


def make_opencode_profile(alias: str, contract: Mapping[str, Any], profile: Mapping[str, Any],
                          repetition: int = 1, *, mcp_command: list[str] | None = None,
                          steps: int = 30) -> dict[str, Any]:
    selected = validate_profile(profile)
    generation = build_generation_policy(repetition)
    alias = str(contract.get("alias", alias))
    limit = selected["context_tokens"]
    if type(steps) is not int or not 1 <= steps <= 240:
        raise ValueError("OpenCode step limit must be between 1 and 240")
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "model": f"local/{alias}",
        "default_agent": "build",
        "subagent_depth": 0,
        "provider": {"local": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Pinned local llama.cpp server",
            "options": {"baseURL": "http://127.0.0.1:18888/v1", "apiKey": "local"},
            "models": {alias: {
                "name": alias,
                "limit": {"context": limit, "input": limit, "output": 4096},
                "options": {key: generation[key] for key in ("temperature", "top_p", "seed")},
            }},
        }},
        "agent": {"build": {
            "mode": "primary",
            "steps": steps,
            "permission": {
                "*": "allow", "task": {"*": "deny"}, "doom_loop": "deny", "skill": "deny",
                "external_directory": {"*": "deny"},
                "webfetch": "deny", "websearch": "deny", "question": "deny",
            },
        }},
        "permission": {"*": "allow", "task": "deny", "doom_loop": "deny", "skill": "deny", "external_directory": "deny",
                       "webfetch": "deny", "websearch": "deny", "question": "deny"},
        "compaction": {"auto": True, "prune": True, "reserved": 6144},
        "tool_output": {"max_bytes": 6000, "max_lines": 200},
    }
    permissions = {
        '*': 'deny', 'read': 'allow', 'glob': 'allow', 'grep': 'allow', 'list': 'allow',
        'bash': 'allow', 'edit': {'*': 'allow', '/workspace/TASK.md': 'deny',
                                 '/workspace/tests/test_existing*': 'deny', '/workspace/.opencode/*': 'deny'},
        'doom_loop': 'deny', 'external_directory': 'deny', 'task': 'deny', 'skill': 'deny',
        'question': 'deny', 'webfetch': 'deny', 'websearch': 'deny',
    }
    if mcp_command:
        permissions['lab_*'] = 'allow'
    config['permission'] = permissions
    config['agent']['build']['permission'] = dict(permissions)
    if mcp_command:
        config["mcp"] = {"lab": {"type": "local", "command": mcp_command,
                                   "enabled": True, "timeout": 10000}}
    return config


def resolve_server(contract: Mapping[str, Any], lab: Path) -> tuple[Path, str]:
    """Resolve an explicit model runtime, retaining the historical default."""
    custom = contract.get("runtime")
    if custom is None:
        revision = current_runtime_contract(Path(lab))['llama_revision'][:7]
        return Path(lab) / "tools/llama-bin/llama-server", revision
    if (not isinstance(custom, Mapping) or set(custom) != {"server", "version_prefix", "sha256"}
            or not isinstance(custom["server"], str)
            or not Path(custom["server"]).is_absolute()
            or not re.fullmatch(r"[0-9a-f]{7,40}", str(custom["version_prefix"]))
            or not re.fullmatch(r"[0-9a-f]{64}", str(custom["sha256"]))):
        raise ValueError("invalid explicit model runtime contract")
    return Path(custom["server"]), str(custom["version_prefix"])


def make_server_command(model_path: str | Path, alias: str, profile: Mapping[str, Any], port: int,
                        *, server: str | Path = "llama-server") -> list[str]:
    selected = validate_profile(profile)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("server port is invalid")
    command = [str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(port),
               "--alias", alias, "--ctx-size", str(selected["context_tokens"]),
               "--n-gpu-layers", "99", "--batch-size", "512", "--ubatch-size", "256",
               "--flash-attn", "on", "--cache-type-k", "q4_0", "--cache-type-v", "q4_0",
               "--reasoning", "off", "--parallel", "1", "--no-webui"]
    command.append("--cache-prompt" if selected["cache_prompt"] else "--no-cache-prompt")
    return command


def classify_http_error(status: int, detail: str) -> str | None:
    if type(status) is not int or status < 400:
        return None
    text = str(detail).lower()
    if any(term in text for term in (
        "context length", "context window", "prompt exceeds", "too many tokens",
        "prompt is too long", "exceeds model context", "n_ctx", "kv cache is full", "context is full",
    )):
        return "context_exhausted"
    if status in {408, 425, 429, 500, 502, 503, 504}:
        return "infrastructure"
    if status == 400:
        return "configuration"
    return "infrastructure" if status >= 500 else "configuration"


CAPACITY_WAIT_SECONDS = 120.0
CAPACITY_POLL_SECONDS = 2.0
CAPACITY_STABLE_SAMPLES = 3


def capacity_guard(probe: Any, *, clock: Any = time.monotonic, sleep: Any = time.sleep,
                   max_wait_seconds: float = CAPACITY_WAIT_SECONDS,
                   poll_seconds: float = CAPACITY_POLL_SECONDS,
                   stable_samples: int = CAPACITY_STABLE_SAMPLES) -> bool:
    """Preparation gate: wait only until the capacity probe resolves ready.

    The guard belongs to episode preparation and must never be mistaken for
    model budget: the probe makes zero inference calls and never starts,
    stops or retunes a server. Readiness counts only after ``stable_samples``
    consecutive ready probes; when the wait expires first, the episode is
    not started and the caller must report the probe's infrastructure reason.
    """
    deadline = clock() + max_wait_seconds
    stable = 0
    while True:
        if probe():
            stable += 1
            if stable >= stable_samples:
                return True
        else:
            stable = 0
        if clock() >= deadline:
            return False
        sleep(poll_seconds)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _version(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        raise RuntimeError(f"version query failed: {Path(command[0]).name}")
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0][:240] if value else "unknown"


def validate_environment(*, lab: Path = LAB) -> dict[str, Any]:
    """Check pinned local tools without model inference, GPU queries, or downloads."""
    lab = Path(lab)
    try:
        expected = current_runtime_contract(lab)
        if not sys.platform.startswith("linux"):
            raise RuntimeError("WSL/Linux is required for the namespace sandbox")
        required = (lab / "tools/llama-bin/llama-server", OPENCODE, NODE,
                    lab / "cache/opencode-node-modules", lab / "cache/package.json",
                    lab / "cache/package-lock.json")
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise RuntimeError("missing pinned runtime: " + ", ".join(missing))
        from benchmark.practical_worker_guard import worker_capabilities
        guard_capabilities=worker_capabilities()
        if not guard_capabilities['supported']:
            raise RuntimeError('required candidate worker isolation is unavailable')
        runtime_versions = {
            "python": _version(["/usr/bin/python3", "--version"]),
            'worker_landlock_abi':str(guard_capabilities['landlock_abi']),
            'kernel':guard_capabilities['kernel'],
            "node": _version([str(NODE), "--version"]),
            "opencode": _version([str(OPENCODE), "--version"]),
            "llama_server": _version([str(lab / "tools/llama-bin/llama-server"), "--version"]),
            "llama_runtime_revision": expected['llama_revision'],
            "opencode_expected_version": expected['opencode'],
            "python_sha256": _sha256(Path("/usr/bin/python3")),
            "node_sha256": _sha256(NODE),
            "opencode_sha256": _sha256(OPENCODE),
            "llama_server_sha256": _sha256(lab / "tools/llama-bin/llama-server"),
            "mcp_server_sha256": _sha256(ROOT / "benchmark/practical_mcp_v2.py"),
            "mcp_grader_sha256": _sha256(ROOT / "benchmark/practical_mcp_grading_v2.py"),
            "driver_sha256": _sha256(ROOT / "benchmark/practical_driver_v2.py"),
            "runtime_sha256": _sha256(ROOT / "benchmark/practical_runtime_v2.py"),
            "tasks_sha256": _sha256(ROOT / "benchmark/practical_tasks_v2.py"),
        }
        if runtime_versions["node"] != "v22.23.3":
            raise RuntimeError(f"unexpected Node runtime: {runtime_versions['node']}")
        if runtime_versions["opencode"] != expected['opencode']:
            raise RuntimeError(f"unexpected OpenCode runtime: {runtime_versions['opencode']}")
        from benchmark.opencode_controlled_probe import _assert_server_bundle, require_runtime_revision

        server = lab / "tools/llama-bin/llama-server"
        _assert_server_bundle(server, server.parent)
        require_runtime_revision(runtime_versions["llama_server"], "", expected['llama_revision'][:7])
        campaign_readiness._runtime_binds(benchmark_root=lab, opencode_binary=OPENCODE,
                                          include_provider=True)
        return {"passed": True, "status": "passed", "runtime_versions": runtime_versions,
                "reason": "pinned runtimes available; no inference performed"}
    except Exception as exc:
        return {"passed": False, "status": "infrastructure", "failure": "infrastructure",
                "reason": f"{type(exc).__name__}: {str(exc)[:300]}", "runtime_versions": {}}


def _runtime_binds(lab: Path, runtime: Path, *, opencode: bool = True,
                   node: bool = True) -> tuple[RuntimeBind, ...]:
    binds = list(campaign_readiness._runtime_binds(
        benchmark_root=lab, opencode_binary=OPENCODE if opencode else None,
        include_provider=opencode,
    ))
    if node:
        binds.append(RuntimeBind(NODE_ROOT.resolve(strict=True), "/opt/node"))
    binds.append(RuntimeBind(runtime.resolve(strict=True), "/opt/practical"))
    return tuple(binds)


def _new_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_model_server(model: str, contract: Mapping[str, Any], profile: Mapping[str, Any],
                        run_dir: Path, *, lab: Path) -> tuple[subprocess.Popen[bytes], Path, int, float]:
    from benchmark.opencode_controlled_probe import _assert_server_bundle, require_runtime_revision

    selected = validate_profile(profile)
    _model_start_preflight(lab)
    model_path = lab / str(contract["path"])
    server, expected_revision = resolve_server(contract, lab)
    if not model_path.is_file() or model_path.is_symlink():
        raise RuntimeError(f"pinned model asset is missing or has a hash mismatch: {model}")
    stat = model_path.stat()
    identity = (str(model_path.resolve(strict=True)), stat.st_dev, stat.st_ino,
                stat.st_size, stat.st_mtime_ns)
    actual_hash = _VERIFIED_MODEL_HASHES.get(identity)
    if actual_hash is None:
        actual_hash = _sha256(model_path)
        _VERIFIED_MODEL_HASHES[identity] = actual_hash
    if actual_hash != contract.get("sha256"):
        raise RuntimeError(f"pinned model asset is missing or has a hash mismatch: {model}")
    server_stat = server.stat()
    if contract.get("runtime") and _sha256(server) != contract["runtime"]["sha256"]:
        raise RuntimeError("explicit model runtime hash mismatch")
    server_identity = (str(server.resolve(strict=True)), server_stat.st_dev, server_stat.st_ino,
                       server_stat.st_size, server_stat.st_mtime_ns)
    if server_identity not in _VERIFIED_SERVER_BUNDLE:
        _assert_server_bundle(server, server.parent)
        version = subprocess.run([str(server), "--version"], capture_output=True, text=True,
                                 timeout=15, check=False)
        if version.returncode:
            raise RuntimeError("pinned llama-server version query failed")
        require_runtime_revision(version.stdout, version.stderr, expected_revision)
        _VERIFIED_SERVER_BUNDLE.add(server_identity)
    port = _new_port()
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
           "LD_LIBRARY_PATH": str(server.parent), "HOME": str(lab), "TMPDIR": "/tmp", "LANG": "C.UTF-8"}
    log_path = run_dir / "llama-server.log"
    started = time.monotonic()
    with log_path.open("xb") as log:
        process = subprocess.Popen(
            make_server_command(model_path, str(contract["alias"]), selected, port, server=server),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
            close_fds=True, start_new_session=True,
        )
    deadline = started + 180
    import urllib.request
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"owned llama-server exited during model load ({process.returncode})")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1) as response:
                    payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
                item = next((entry for entry in payload.get("data", [])
                             if entry.get("id") == contract["alias"]), None)
                if response.status == 200 and item is not None:
                    meta = item.get("meta", {}) if isinstance(item, dict) else {}
                    context = meta.get("n_ctx")
                    if isinstance(context, int) and context < selected["context_tokens"]:
                        raise ValueError("model context metadata is below the requested profile")
                    return process, log_path, port, time.monotonic() - started
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(1)
        raise TimeoutError("pinned model did not load before the 180-second deadline")
    except BaseException:
        _stop_model_server(process)
        raise


def _model_start_preflight(lab: Path) -> None:
    """Apply the existing storage/RAM/GPU gate immediately before each load."""
    from benchmark.opencode_controlled_probe import _assert_free_resources

    _assert_free_resources(lab)
    command = ["/usr/lib/wsl/lib/nvidia-smi", "--query-gpu=memory.free,memory.total",
               "--format=csv,noheader,nounits"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("GPU capacity query failed; refusing model load")
    try:
        free, total = (int(item.strip()) for item in result.stdout.splitlines()[0].split(",", 1))
    except (ValueError, IndexError) as exc:
        raise RuntimeError("GPU capacity query was malformed; refusing model load") from exc
    if free < GPU_FREE_FLOOR_MIB or total < 8192:
        raise RuntimeError(
            f"GPU capacity gate failed ({free} MiB free of {total} MiB; "
            f"need {GPU_FREE_FLOOR_MIB} MiB)"
        )


def _stop_model_server(process: subprocess.Popen[bytes] | None) -> bool:
    if process is None:
        return True
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    return False
    return process.poll() is not None


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _safe_extract_snapshot(raw: bytes, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(__import__("io").BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 512 or sum(item.file_size for item in members) > 8 * 1024**2:
            raise ValueError("workspace snapshot exceeds its bound")
        seen: set[str] = set()
        for item in members:
            name = item.filename
            path = PurePosixPath(name)
            mode = item.external_attr >> 16
            if (path.is_absolute() or ".." in path.parts or "\\" in name or name in seen
                    or (mode & 0o170000) == 0o120000):
                raise ValueError("workspace snapshot contains an unsafe path")
            seen.add(name)
        for item in members:
            target = destination.joinpath(*PurePosixPath(item.filename).parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))


def _json_events(raw: bytes):
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        yield event


def _events(raw: bytes) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    native: list[dict[str, Any]] = []
    driver: list[dict[str, Any]] = []
    for event in _json_events(raw):
        if event.get("_practical_driver") in {"phase", "environment", "tool_review", 'policy_tool_start', 'policy_tool_end', 'recovery', 'budget_halt'}:
            driver.append(event)
        else:
            native.append(event)
    return native, driver


def _tool_guard_from_output(task: str, raw: bytes, policy_mode: str):
    """Rebuild tool review in event order so recovery only clears its own phase."""
    from benchmark.practical_tool_guard import ToolErrorGuard

    guard = ToolErrorGuard(task)
    recoveries: list[dict[str, Any]] = []
    current_phase = 1
    no_progress_phase: int | None = None
    for event in _json_events(raw):
        kind = event.get('_practical_driver')
        if kind == 'phase':
            phase = event.get('phase')
            if type(phase) is int:
                current_phase = max(current_phase, phase + 1)
            continue
        if kind == 'recovery':
            recoveries.append(event)
            phase = event.get('phase')
            successful = (policy_mode == 'operational' and type(phase) is int
                          and event.get('exit_code') == 0 and event.get('stop_reason') is None)
            if (successful and phase == no_progress_phase and guard.reason == 'model_no_progress'):
                guard.reason = None
                no_progress_phase = None
            continue
        if kind == 'tool_review':
            if event.get('reason') == 'tool_timeout':
                guard.reason = 'tool_timeout'
            continue
        if kind is not None:
            continue

        previous_count = len(guard.evidence)
        guard.observe(event)
        if (len(guard.evidence) > previous_count
                and 'LAB_POLICY_STOP:model_no_progress' in guard.evidence[-1].get('message', '')):
            no_progress_phase = current_phase
    return guard, recoveries


def _mcp_events(native: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from benchmark.practical_mcp_v2 import TOOLS

    names = {item["name"] for item in TOOLS}
    result = []
    for event in native:
        if event.get("type") != "tool_use" or not isinstance(event.get("part"), dict):
            continue
        part = event["part"]
        raw_name = str(part.get("tool", ""))
        name = next((candidate for candidate in names
                     if raw_name == candidate or raw_name.endswith("_" + candidate)
                     or raw_name.endswith("." + candidate)), None)
        if not name:
            continue
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        is_error = state.get("status") == "error" or bool(state.get("error"))
        output = state.get("output")
        if output is None and is_error:
            output = state.get("error")
        if isinstance(output, str):
            try:
                output = json.loads(output)
            except json.JSONDecodeError:
                pass
        input_value = state.get("input", {})
        result.append({"name": name, "arguments": input_value if isinstance(input_value, dict) else {},
                       "result": output,
                       "isError": is_error})
    return result



def _mcp_journal(run_dir: Path) -> dict[str, Any] | None:
    """The trusted, host-side journal of the episode's dedicated MCP channel."""
    try:
        journal = json.loads((run_dir / "mcp-journal.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return journal if isinstance(journal, dict) and journal.get(
        "schema") == "practical-mcp-journal-v1" else None


def _mcp_journal_status(result: Any, journal_path: Path) -> Any:
    """Upgrade a finished sandbox result when its MCP journal is untrustworthy.

    A successful sandbox run whose dedicated channel never closed cleanly —
    missing, unreadable, unrecognized, or faulty journal — is infrastructure,
    never a candidate verdict.
    """
    if not journal_path.is_file():
        return replace(result, infrastructure_error="mcp_journal_missing")
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return replace(result, infrastructure_error="mcp_journal_unreadable")
    if not isinstance(journal, dict) or journal.get("schema") != "practical-mcp-journal-v1":
        return replace(result, infrastructure_error="mcp_journal_unrecognized")
    if journal.get("fault"):
        return replace(result, infrastructure_error=f"mcp_channel_fault:{journal.get('fault')}")
    from benchmark.practical_mcp_bridge import validate_journal
    problem = validate_journal(journal)
    if problem:
        return replace(result,infrastructure_error='mcp_journal_invalid:'+problem)
    return result


def tool_error_counts(task: str, native: list[dict[str, Any]]) -> dict[str, int]:
    """Keep legacy raw/remainder counts; the remainder does not establish blame.

    Causal categories are recorded separately by ToolErrorGuard.
    """
    from benchmark.practical_mcp_grading_v2 import expected_tool_errors

    total = sum(
        event.get("type") == "tool_use" and isinstance(event.get("part"), dict)
        and isinstance(event["part"].get("state"), dict)
        and event["part"]["state"].get("status") == "error" for event in native)
    expected = min(total, expected_tool_errors(task, _mcp_events(native)))
    return {"tool_errors": total, "expected_tool_errors": expected,
            "avoidable_tool_errors": total - expected}


def _artifact_values(task: str, workspace: Path) -> dict[str, Any]:
    name = _ARTIFACTS.get(task)
    if not name:
        return {}
    path = workspace / name
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return {name: value}


def _grader_result(task: str, phase: int, workspace: Path, *, lab: Path,
                   mcp_events: list[dict[str, Any]] | None = None,
                   task_contract_id: str | None = None,
                   mcp_journal: dict[str, Any] | None = None) -> dict[str, Any]:
    language = practical_tasks_v2.TASK_SPECS[task]["language"]
    if language == "mcp":
        from benchmark.practical_mcp_grading_v2 import grade_mcp_evidence

        result = grade_mcp_evidence(task, mcp_events or [], None,
                                    _artifact_values(task, workspace),
                                    task_contract_id=task_contract_id,
                                    journal=mcp_journal)
        return {"passed": bool(result.get("passed")), "reason": result.get("reason"),
                "failures": result.get("failures", [])}

    with tempfile.TemporaryDirectory(prefix="practical-v2-checks-") as temporary:
        runtime = Path(temporary)
        source_text = practical_tasks_v2.checks_source(
            task, phase=phase, task_contract_id=task_contract_id)
        from benchmark.practical_grade_contract import (
            SEED_FILE_NAME, node_check_case_ids, python_check_case_ids,
            report_export_paths, validate_grade_report)

        check = runtime / ('checks.py' if language == 'python' else 'checks.test.js')
        launcher = runtime / 'checks_launcher.py'
        contract = runtime / 'grade_contract.py'
        guard = runtime / 'worker_guard.py'
        node_rpc = runtime / 'node_rpc.mjs'
        shutil.copyfile(ROOT/'benchmark/practical_python_checks.py',launcher)
        shutil.copyfile(ROOT/'benchmark/practical_grade_contract.py',contract)
        shutil.copyfile(ROOT/'benchmark/practical_worker_guard.py',guard)
        shutil.copyfile(ROOT/'benchmark/practical_node_rpc.mjs',node_rpc)
        check.write_text(source_text, encoding="utf-8")
        binds = list(campaign_readiness._runtime_binds())
        if language == "javascript":
            binds.append(RuntimeBind(NODE_ROOT.resolve(strict=True), "/opt/node"))
        argv = ("/usr/bin/python3", "-B", "-I", "/opt/checks_launcher.py",
                "--parent", "--language",language,"--checks", "/opt/"+check.name,
                "--seed-file", SEED_FILE_NAME)
        if language == 'javascript':
            argv += ('--node-root','/opt/node','--node-reporter','/opt/practical_node_rpc.mjs')
        binds.append(RuntimeBind(check.resolve(strict=True), "/opt/" + check.name))
        binds.append(RuntimeBind(launcher.resolve(strict=True),
                                 "/opt/" + launcher.name))
        if contract is not None:
            binds.append(RuntimeBind(contract.resolve(strict=True),
                                     "/opt/practical_grade_contract.py"))
        binds.append(RuntimeBind(guard.resolve(strict=True),'/opt/practical_worker_guard.py'))
        binds.append(RuntimeBind(node_rpc.resolve(strict=True),'/opt/practical_node_rpc.mjs'))
        limits = ResourceLimits(memory_bytes=768 * 1024**2, swap_bytes=256 * 1024**2,
                                cpu_quota_percent=100, cpu_seconds=75, pids=48,
                                wall_seconds=75, output_bytes=64 * 1024,
                                workspace_bytes=256 * 1024**2,
                                workspace_files=5000, workspace_file_bytes=64 * 1024**2,
                                scratch_bytes=128 * 1024**2, file_bytes=64 * 1024**2,
                                open_files=256, export_file_bytes=2 * 1024**2,
                                export_total_bytes=2 * 1024**2, rootfs_bytes=32 * 1024**2,
                                startup_seconds=10, stop_grace_seconds=2)
        nonce = secrets.token_hex(16)
        slots = report_export_paths(nonce)
        (workspace / SEED_FILE_NAME).write_text(
            json.dumps({"schema": "practical-grade-seed-v1", "nonce": nonce}),
            encoding="utf-8")
        run = SandboxSupervisor().run(SandboxSpec(
            argv=argv, workspace=workspace, runtime_ro=tuple(binds),
            env={"PYTHONDONTWRITEBYTECODE": "1"}, limits=limits,
            workspace_exports=slots,
        ))
        if run.infrastructure_error or not run.cleanup_verified:
            return {"passed": False, "infrastructure": True,
                    "reason": run.infrastructure_error or "grader sandbox cleanup failed"}
        from benchmark.practical_grade_contract import REPORT_PREFIX
        packets = [line[len(REPORT_PREFIX):] for line in run.output.decode(errors='replace').splitlines()
                   if line.startswith(REPORT_PREFIX)]
        report = None
        if len(packets) == 1:
            try:
                report = json.loads(packets[0])
            except ValueError:
                pass
        expected = set(node_check_case_ids(source_text) if language == "javascript"
                       else python_check_case_ids(source_text))
        verdict = validate_grade_report(
            report, expected, returncode=run.returncode,
            cleanup_verified=run.cleanup_verified, expected_nonce=nonce)
        return {**verdict, "returncode": run.returncode, "timed_out": run.timed_out,
                "cleanup_verified": run.cleanup_verified,
                "output": run.output.decode("utf-8", errors="replace")[-12000:]}


def _authored_test_result(task: str, workspace: Path, *, lab: Path) -> dict[str, Any]:
    language = practical_tasks_v2.TASK_SPECS[task]["language"]
    if language == "mcp":
        return {"passed": None, "count": 0, "baseline_count": 0}
    if language == "javascript":
        argv = ("/opt/node/bin/node", "--test", "--test-reporter=tap")
        runtime = (RuntimeBind(NODE_ROOT.resolve(strict=True), "/opt/node"),)
        count_pattern = r"(?:^|\n)#\s+tests\s+(\d+)(?:\n|$)|\u2139\s+tests\s+(\d+)"
        baseline = 1 if task in {"B2", "M1", "D2"} else 0
    else:
        argv = ("/usr/bin/python3", "-B", "-m", "unittest", "discover", "-s", "tests")
        runtime = ()
        count_pattern = r"Ran\s+(\d+)\s+tests?"
        baseline = 1 if task in {"B1", "C1", "D1", "H1"} else 0
    limits = ResourceLimits(memory_bytes=768 * 1024**2, swap_bytes=256 * 1024**2,
                            cpu_quota_percent=100, cpu_seconds=25, pids=48, wall_seconds=30,
                            output_bytes=64 * 1024, workspace_bytes=256 * 1024**2,
                            workspace_files=5000, workspace_file_bytes=64 * 1024**2,
                            scratch_bytes=128 * 1024**2, file_bytes=64 * 1024**2,
                            open_files=256, export_file_bytes=2 * 1024**2,
                            export_total_bytes=2 * 1024**2, rootfs_bytes=32 * 1024**2,
                            startup_seconds=10, stop_grace_seconds=2)
    result = SandboxSupervisor().run(SandboxSpec(argv=argv, workspace=workspace,
                                                  runtime_ro=tuple(campaign_readiness._runtime_binds()) + runtime,
                                                  env={"PYTHONDONTWRITEBYTECODE": "1"}, limits=limits))
    text = result.output.decode("utf-8", errors="replace")
    matches = re.search(count_pattern, text)
    count = int(next((group for group in matches.groups() if group), "0")) if matches else 0
    return {"passed": (result.returncode == 0 and not result.timed_out and count > baseline),
            "suite_passed": bool(result.returncode == 0 and not result.timed_out and count > 0),
            "count": count, "baseline_count": baseline, "additional_count": max(0, count - baseline),
            "returncode": result.returncode, "timed_out": result.timed_out,
            "cleanup_verified": result.cleanup_verified,
            "infrastructure": bool(result.infrastructure_error or not result.cleanup_verified),
            "reason": result.infrastructure_error,
            "output": text[-8000:]}


def _phase_observed(entry: Mapping[str, Any], language: str) -> bool:
    """True only when this phase's trusted grader concluded its own report."""
    hidden = entry.get("hidden") or {}
    if not isinstance(hidden, Mapping) or hidden.get("infrastructure"):
        return False
    if language == "mcp":
        return hidden.get("passed") in (True, False)
    return (hidden.get("contract_invalid") is False
            and hidden.get("infrastructure") is False
            and (hidden.get("checks_completed", 0) > 0
                 or hidden.get("candidate_failure_observed") is True))


def _phase_grade(task: str, phase: int, snapshot: Path, *, lab: Path,
                 mcp_events: list[dict[str, Any]],
                 task_contract_id: str | None = None,
                 mcp_journal: dict[str, Any] | None = None) -> dict[str, Any]:
    workspace = snapshot.parent / f"grade-input-{phase}"
    _safe_extract_snapshot(snapshot.read_bytes(), workspace)
    try:
        hidden = _grader_result(task, phase, workspace, lab=lab, mcp_events=mcp_events,
                                task_contract_id=task_contract_id,
                                mcp_journal=mcp_journal)
        authored = _authored_test_result(task, workspace, lab=lab)
        mcp = None
        if task in _MCP_TASKS and practical_tasks_v2.TASK_SPECS[task]["language"] != "mcp":
            from benchmark.practical_mcp_grading_v2 import grade_mcp_evidence

            mcp = grade_mcp_evidence(task, mcp_events, None,
                                     _artifact_values(task, workspace),
                                     task_contract_id=task_contract_id,
                                     journal=mcp_journal)
        return {"phase": phase, "hidden": hidden, "mcp": mcp, "authored_tests": authored,
                "snapshot_sha256": _sha256(snapshot)}
    finally:
        shutil.rmtree(workspace)


def _finalize_outcome(row: dict[str, Any], *, phase_results: list[dict[str, Any]],
                      phase_native: list[dict[str, Any]], native: list[dict[str, Any]],
                      driver: list[dict[str, Any]], prompt_count: int, language: str,
                      result: Any, model_stop: bool) -> None:
    """Apply the documented causal order once every phase observation is in."""
    grade_infra = any(
        entry.get("hidden", {}).get("infrastructure")
        or entry.get("authored_tests", {}).get("infrastructure")
        for entry in phase_results
    )
    grade_contract_invalid = any(
        entry.get("hidden", {}).get("contract_invalid")
        for entry in phase_results
    )
    functional_observed = (len(phase_results) == prompt_count
                           and not grade_infra and not grade_contract_invalid
                           and all(_phase_observed(item, language)
                                   for item in phase_results))
    # The functional verdict lives in its own field: preserved when the
    # trusted graders concluded, unknown (None) when they never did.
    row["functional_correct"] = row["correct"] if functional_observed else None
    halted = any(item.get("_practical_driver") == "budget_halt" for item in driver)
    if (not result.cleanup_verified or result.infrastructure_error or grade_infra
            or row["environment_passed"] is False):
        row["failure"] = "infrastructure"
    elif grade_contract_invalid:
        row.update(failure='contract_error', review_required=True,
                   scoring_eligible=False, autonomous=False, correct=False)
    elif row["review_required"]:
        if row['failure'] not in {'contract_error', 'tool_timeout'}:
            row["failure"] = "task_review"
        row["autonomous"] = False
    elif model_stop:
        row['autonomous'] = False
    elif result.timed_out or any(item.get("exit_code") == 124 for item in phase_native) or halted:
        row["deadline_exceeded"] = True
        if row.get("failure") not in {"call_limit", "context_exhausted", "configuration",
                                      "infrastructure", 'budget_exhausted', 'contract_error'}:
            row["failure"] = "budget_exhausted"
    elif row.get('failure') in {'unknown','configuration'}:
        row.update(review_required=True,scoring_eligible=False,correct=False,autonomous=False)
    elif row["correct"] and row["autonomous"]:
        row["failure"] = "passed"
    elif row.get("failure") in {"context_exhausted", "configuration", "call_limit",
                                "budget_exhausted", 'contract_error', 'unknown'}:
        # A delimited outcome (budget, context, or unattributed cause)
        # keeps its own kind; it is never inferred as a functional fault.
        pass
    elif not functional_observed:
        # Missing snapshots or graders that never concluded: the functional
        # observation does not exist, so no wrong_result is fabricated.
        row["failure"] = "invalid_execution"
    elif not row["correct"]:
        row["failure"] = "wrong_result"
    else:
        row["failure"] = "workflow"
    if row["failure"] == "infrastructure":
        # Infrastructure precedence must not leave stale success flags
        # behind: the documented audit leak between ranking and failure.
        row.update(correct=False, autonomous=False)
    _normalize_outcome(row)


def _normalize_outcome(row: dict[str,Any]) -> None:
    from benchmark.practical_evidence import VALID_EXECUTION_FAILURES, verified_success
    if row.get('failure') == 'passed' and row.get('functional_correct') is not True:
        row['failure'] = 'invalid_execution'
    invalid = (row.get('failure') not in VALID_EXECUTION_FAILURES
               or row.get('scoring_eligible') is False or row.get('review_required') is True)
    row['execution_valid'] = not invalid
    row['scoring_eligible'] = not invalid
    row['workflow_complete'] = bool(row.get('autonomous')) if not invalid else False
    if invalid:
        row.update(correct=False,autonomous=False)
        if row.get('failure') in {'unknown','configuration','contract_error','invalid_execution'}:
            row['review_required']=True
        if row.get('failure') == 'infrastructure':
            row['review_required']=False
    row['verified_success'] = verified_success(row)


def _run_agent(task: str, model: str, contract: Mapping[str, Any], profile: Mapping[str, Any],
               repetition: int, workspace: Path, run_dir: Path, *, lab: Path,
               upstream_port: int, seconds: int, max_requests: int,
               prompts: list[str] | None = None, policy_mode: str = 'benchmark',
               base_max_requests=None, task_contract_id: str | None = None) -> Any:
    language = practical_tasks_v2.TASK_SPECS[task]["language"]
    with tempfile.TemporaryDirectory(prefix="practical-v2-runtime-") as temporary:
        runtime = Path(temporary)
        shutil.copyfile(ROOT / "benchmark/practical_driver_v2.py", runtime / "driver.py")
        shutil.copyfile(ROOT / "benchmark/practical_tool_guard.py", runtime / "practical_tool_guard.py")
        shutil.copyfile(ROOT / "benchmark/practical_policy_plugin.mjs", runtime / "policy-plugin.mjs")
        policy = BudgetPolicy.for_task({'max_requests': max_requests, 'seconds': seconds,
                                       'base_max_requests': base_max_requests or max_requests}, mode=policy_mode)
        _write_json(runtime / 'policy.json', policy.as_dict())
        mcp_port: int | None = None
        mcp_bridge: McpBridge | None = None
        if task in _MCP_TASKS:
            # Task 7: the trusted server and fixtures stay host-side, one
            # instance per episode.  Only the source-free stdio proxy enters
            # the candidate namespace through the dedicated channel.
            shutil.copyfile(ROOT / "benchmark/practical_mcp_bridge.py",
                            runtime / "practical_mcp_bridge.py")
            mcp_port = _new_port()
            while mcp_port == 18888:  # the in-namespace broker adapter port
                mcp_port = _new_port()
            mcp_bridge = McpBridge(
                task, journal_path=run_dir / "mcp-journal.json",
                contract_id=str(task_contract_id) if task_contract_id else None)
        mcp_command = (
            ["/usr/bin/python3", "-I", "-u", "/opt/practical/practical_mcp_bridge.py",
             "--proxy", "127.0.0.1", str(mcp_port)]
            if mcp_bridge is not None else None)
        config = make_opencode_profile(str(contract["alias"]), contract, profile, repetition,
                                       mcp_command=mcp_command,
                                       steps=max_requests * policy.multiplier)
        config['plugin'] = ['file:///opt/practical/policy-plugin.mjs']
        _write_json(runtime / "opencode.json", config)
        if prompts is None:
            prompts = [practical_tasks_v2.seed_task(task, workspace)]
            if practical_tasks_v2.TASK_SPECS[task]["phases"] == 2:
                prompts.append(practical_tasks_v2.followup_prompt(task))
        _write_json(runtime / "driver.json", {
            "model": f"local/{contract['alias']}", "prompts": prompts,
            "seconds": seconds, "language": language, "task": task, 'policy': policy.as_dict(),
        })
        (run_dir / "broker").mkdir(mode=0o700)
        base_limits = safe_campaign._agent_limits()
        limits = replace(base_limits, wall_seconds=seconds * policy.multiplier, cpu_seconds=seconds * policy.multiplier + 30,
                         output_bytes=1024**2, export_file_bytes=9 * 1024**2,
                         export_total_bytes=24 * 1024**2, memory_bytes=3 * 1024**3,
                         swap_bytes=512 * 1024**2, scratch_bytes=512 * 1024**2)
        binds = list(_runtime_binds(lab, runtime, opencode=True, node=True))
        protected = runtime / 'protected'
        protected.mkdir()
        for relative in ('TASK.md', 'tests/test_existing.py', 'tests/test_existing.test.js'):
            source = workspace / relative
            if source.is_file():
                copy = protected / source.name
                shutil.copyfile(source, copy)
                binds.append(RuntimeBind(copy, '/workspace/' + relative))
        locked_config = runtime / 'locked-config'
        locked_config.mkdir()
        (locked_config / '.gitignore').write_text('*\n', encoding='utf-8')
        binds.append(RuntimeBind(locked_config, '/workspace/.opencode'))
        exports = [".practical.json"]
        phase_count = len(prompts)
        exports.extend(f".snapshot{phase}.zip" for phase in range(1, phase_count + 1))
        spec = SandboxSpec(
            argv=("/usr/bin/python3", "-B", "/opt/practical/driver.py"),
            workspace=workspace, workspace_exports=tuple(exports),
            runtime_ro=tuple(binds),
            env={"OPENCODE_CONFIG": "/opt/practical/opencode.json",
                 "OPENCODE_DISABLE_AUTOUPDATE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
            limits=limits,
            broker=BrokerPolicy(
                upstream_port=upstream_port, model_allowlist=(str(contract["alias"]),),
                output_token_cap=4096, frozen_generation=build_generation_policy(repetition),
                max_requests=policy.max_model_requests, deadline_seconds=float(seconds * policy.multiplier),
                request_limits=policy.as_dict(),
            ),
            broker_transcript_dir=run_dir / "broker",
            mcp=None if mcp_bridge is None else McpPolicy(port=mcp_port),
            mcp_bridge=mcp_bridge,
        )
        result = SandboxSupervisor().run(spec)
        if mcp_bridge is not None and result.infrastructure_error is None:
            # A successful sandbox run whose dedicated channel did not close
            # cleanly is infrastructure, never a candidate verdict.
            result = _mcp_journal_status(result, run_dir / "mcp-journal.json")
        return result


def _resource_peaks(run_dir: Path) -> dict[str, float | None]:
    peaks: dict[str, float | None] = {"vram_mib": None, "ram_mib": None}
    for path in (run_dir / "resources").rglob("*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            metrics = row.get("metrics", row)
            for target, name in (("vram_mib", "vram_used_mb"), ("ram_mib", "wsl_ram_used_mib")):
                value = metrics.get(name) if isinstance(metrics, dict) else None
                if isinstance(value, dict):
                    value = value.get("value")
                if isinstance(value, (int, float)):
                    peaks[target] = max(float(peaks[target] or 0), float(value))
    return peaks


def model_call_evidence(run_dir: Path) -> dict[str, Any]:
    request_counts = dict(main=0, title=0, compaction=0, unknown=0)
    call_counts = dict(main=0, title=0, compaction=0, unknown=0)
    path = run_dir / 'broker/transcript.jsonl'
    if path.is_file():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            event = {}
            try:
                parsed = json.loads(line)
                if not isinstance(parsed, dict) or parsed.get('method') != 'POST':
                    continue
                event = parsed
                name = event.get('files', {}).get('client_request', {}).get('name', '')
                if not name or Path(name).name != name:
                    raise ValueError('request file unavailable')
                request = json.loads((path.parent / name).read_text())
                category = classify_request(request)
            except (OSError, ValueError, TypeError, AttributeError):
                category = 'unknown'
            request_counts[category] += 1
            if event.get('upstream_started_utc'):
                call_counts[category] += 1
    return {
        'model_calls': sum(call_counts.values()),
        'model_call_breakdown': call_counts,
        'model_call_requests': sum(request_counts.values()),
        'model_call_request_breakdown': request_counts,
    }


def model_call_breakdown(run_dir: Path) -> dict[str, int]:
    return model_call_evidence(run_dir)['model_call_breakdown']


def history_delivery_verified(run_dir: Path) -> bool:
    seen = False
    for path in (run_dir / 'broker').glob('*client_request.bin'):
        try:
            request = json.loads(path.read_text())
            if not isinstance(request, dict) or not request.get('messages'):
                continue
            seen = True
            if validate_history(request['messages']):
                return False
        except (OSError, ValueError, TypeError):
            return False
    return seen


def usage_evidence(run_dir: Path):
    values = []
    for path in sorted((run_dir / 'broker').glob('*upstream_response.bin')):
        usage = usage_from_bytes(path.read_bytes())
        values.append({'request': path.name, 'usage': usage, 'source': 'server' if usage else 'unavailable'})
    return values


_TRANSPORT_TERMS = ('connectionreseterror', 'econnreset', 'connection reset', 'brokenpipeerror',
                    'eoferror', 'connection closed', 'server disconnected', 'remote end closed',
                    'connection dropped', 'stream interrupted')


def _error_text(event: Mapping[str, Any]) -> str:
    for candidate in (event.get('part'), event):
        if isinstance(candidate, Mapping):
            for key in ('message', 'text', 'error'):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value[:2000]
        elif isinstance(candidate, str) and candidate.strip():
            return candidate[:2000]
    return ""


def _transport_evidence(text: str) -> bool:
    lowered = str(text).lower()
    return any(term in lowered for term in _TRANSPORT_TERMS)


def _budget_evidence(text: str) -> bool:
    lowered = str(text).lower()
    return 'timeout' in lowered or 'deadline' in lowered or 'budget_exhausted' in lowered


def _broker_failure(run: Any, run_dir: Path) -> str | None:
    manifest = run_dir / "broker/transcript.jsonl"
    summaries = []
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("method") == "POST":
                summaries.append(item)
    post_events = [event for event in run.broker_events if event.method == "POST"]
    transport_faults = False
    deadline_canceled = False
    for index, event in enumerate(post_events):
        summary = summaries[index] if index < len(summaries) else {}
        stream_error = str(summary.get("error") or "")
        if stream_error:
            deadline_canceled = deadline_canceled or _budget_evidence(stream_error)
            transport_faults = transport_faults or _transport_evidence(stream_error)
        if event.outcome.startswith('budget_exhausted:'):
            return 'budget_exhausted'
        if event.outcome.startswith('contract_error:'):
            return 'contract_error'
        if "request_budget" in event.outcome:
            return "call_limit"
        if event.status < 400:
            continue
        detail = str(event.outcome)
        if _transport_evidence(detail):
            transport_faults = True
        elif _budget_evidence(detail):
            deadline_canceled = True
        if index < len(summaries):
            files = summaries[index].get("files", {})
            name = files.get("upstream_response", {}).get("name")
            if name:
                response = run_dir / "broker" / name
                try:
                    detail += " " + response.read_bytes()[:12000].decode("utf-8", errors="replace")
                except OSError:
                    pass
            if summaries[index].get("upstream_status") is None:
                # These are local broker rejections, such as the frozen request policy.
                detail += " " + str(summaries[index].get("error") or "")
        if _transport_evidence(detail):
            # Transport evidence forbids a configuration verdict: an unproven
            # cause stays unattributed rather than blaming the model.
            transport_faults = True
            continue
        kind = classify_http_error(event.status, detail)
        if kind:
            return kind
    if deadline_canceled and not transport_faults:
        return 'budget_exhausted'
    return None


def _failure_for(run: Any, native: list[dict[str, Any]], *, fallback: str | None = None,
                 run_dir: Path | None = None) -> str:
    if run is not None and run.infrastructure_error:
        return "infrastructure"
    if run is not None and run.timed_out:
        return "budget_exhausted"
    if run is not None:
        if run_dir is not None:
            kind = _broker_failure(run, run_dir)
            if kind:
                return kind
    if fallback:
        return fallback
    functional_errors = [event for event in native if event.get("type") == "error"]
    if functional_errors:
        # A generic/mixed SDK error is not proof of model configuration fault.
        # Explicit broker configuration rejection was handled above.
        return "unknown"
    return "workflow"


def _execute_episode(task: str, model: str, profile: Mapping[str, Any], repetition: int,
                     output: Path, models: Mapping[str, Mapping[str, Any]], *, lab: Path,
                     server_process: subprocess.Popen[bytes] | None,
                     upstream_port: int, model_load_seconds: float = 0.0,
                     episode_dir: Path | None = None, policy_mode: str = 'benchmark',
                     with_skills=True, budget_multiplier=1,
                     task_contract_id: str | None = None) -> dict[str, Any]:
    selected = validate_profile(profile)
    if task not in practical_tasks_v2.ALL_TASKS:
        raise ValueError(f"unknown practical task {task!r}")
    contract_id = practical_tasks_v2.resolve_task_contract(task, task_contract_id)
    if budget_multiplier not in (1, 2, 4) or (policy_mode == 'operational' and budget_multiplier != 1):
        raise ValueError('unsupported calibration budget')
    spec = dict(practical_tasks_v2.TASK_SPECS[task])
    spec['base_max_requests'] = spec['max_requests']
    spec['seconds'] *= budget_multiplier
    spec['max_requests'] *= budget_multiplier
    contract = models[model]
    run_id = f"{model}-{selected['id']}-{task}-r{repetition}-{time.time_ns()}"
    run_dir = episode_dir or output / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=episode_dir is not None)
    workspace = run_dir / "input"
    workspace.mkdir()
    prompt = practical_tasks_v2.seed_task(task, workspace, with_skills=with_skills,
                                         task_contract_id=contract_id)
    prompts = [prompt]
    if spec["phases"] == 2:
        prompts.append(practical_tasks_v2.followup_prompt(task))
    started = time.monotonic()
    row: dict[str, Any] = {
        "protocol": PROTOCOL, "model": model, "profile": selected["id"], "task": task,
        "repetition": repetition, "generation_seed": SEEDS[repetition], "profile_config": selected,
        "task_contract_id": contract_id,
        "correct": False, "functional_correct": None, "autonomous": False,
        "authored_tests_passed": None, "authored_tests_added": None,
        "authored_test_quality": None,
        "agent_finished": False, "environment_passed": None,
        "expected_tool_errors": 0, "avoidable_tool_errors": 0, "failure": "infrastructure",
        "seconds": 0.0, "tool_errors": 0, "model_calls": 0, "model_load_seconds": model_load_seconds,
        "run_dir": str(run_dir), "model_contract": dict(contract),
        'budget_policy': BudgetPolicy.for_task(spec, mode=policy_mode).as_dict(),
        'manual_hashes': manual_evidence(task, with_skills=with_skills),
    }
    monitor, monitor_status = safe_campaign._resource_monitor_start(
        run_dir / "resources", run_id=run_id, phase_id="agent", agent_id="opencode")
    result = None
    native: list[dict[str, Any]] = []
    driver: list[dict[str, Any]] = []
    phase_results: list[dict[str, Any]] = []
    server_cleanup = False
    try:
        result = _run_agent(task, model, contract, selected, repetition, workspace, run_dir,
                            lab=lab, upstream_port=upstream_port, seconds=spec["seconds"],
                            max_requests=spec["max_requests"], prompts=prompts, policy_mode=policy_mode,
                            base_max_requests=spec['base_max_requests'],
                            task_contract_id=contract_id)
        native, driver = _events(result.output)
        (run_dir / "native.jsonl").write_bytes(result.output)
        call_evidence = model_call_evidence(run_dir)
        row.update(call_evidence)
        row.update(tool_error_counts(task, native))
        tool_guard, recoveries = _tool_guard_from_output(task, result.output, policy_mode)
        row['recoveries'] = recoveries
        row["tool_review"] = tool_guard.as_dict()
        row["model_tool_errors"] = tool_guard.model_errors
        row['infrastructure_tool_errors'] = tool_guard.infrastructure_errors
        row['unattributed_tool_errors'] = tool_guard.unattributed_errors
        model_stop = tool_guard.reason in {'model_tool_error_threshold', 'model_no_progress'}
        row["review_required"] = bool(tool_guard.reason) and not model_stop and tool_guard.reason != 'budget_exhausted'
        row["scoring_eligible"] = not row["review_required"]
        environment_checks = [item for item in driver if item.get("_practical_driver") == "environment"]
        if environment_checks:
            row["environment_passed"] = all(item.get("passed") is True for item in environment_checks)
        row["failure"] = _failure_for(result, native, run_dir=run_dir)
        row['budget_ledger'] = result.resource_evidence.get('budget_ledger')
        row['history_delivery_verified'] = history_delivery_verified(run_dir)
        row['usage'] = usage_evidence(run_dir)
        if row['failure'] == 'contract_error':
            row.update(review_required=True, scoring_eligible=False)
            row['tool_review'] = {**row['tool_review'], 'reason':'contract_error'}
        if tool_guard.reason == 'budget_exhausted':
            row['failure'] = 'budget_exhausted'
        elif tool_guard.reason == 'tool_timeout':
            row['failure'] = 'tool_timeout'
        if model_stop:
            if row['history_delivery_verified']:
                row['failure'] = 'model_no_progress' if tool_guard.reason == 'model_no_progress' else 'model_tool_error'
            else:
                row.update(failure='contract_error', review_required=True, scoring_eligible=False)
        row["broker_events"] = [vars(event) for event in result.broker_events]
        row["sandbox"] = {
            "returncode": result.returncode, "timed_out": result.timed_out,
            "cleanup_verified": result.cleanup_verified, "output_limited": result.output_limited,
            "infrastructure_error": result.infrastructure_error,
            "namespace_evidence": dict(result.namespace_evidence),
            "network_evidence": dict(result.network_evidence),
            "resource_evidence": dict(result.resource_evidence),
            "workspace_audit": dict(result.workspace_audit),
            "broker_transcript_evidence": dict(result.broker_transcript_evidence),
        }
        _write_json(run_dir / 'execution.json', {key: row[key] for key in (
            'protocol', 'model', 'task', 'profile', 'repetition', 'run_dir',
            'task_contract_id',
            'model_calls', 'model_call_breakdown', 'model_call_requests',
            'model_call_request_breakdown', 'usage', 'budget_policy', 'budget_ledger',
            'history_delivery_verified', 'manual_hashes', 'sandbox')})
        for name, raw in result.workspace_outputs.items():
            (run_dir / name).write_bytes(raw)
        is_mcp_only = spec["language"] == "mcp"
        authored_qualities: list[str] = []
        mcp_journal = _mcp_journal(run_dir) if task in _MCP_TASKS else None
        for phase in range(1, len(prompts) + 1):
            snapshot = run_dir / f".snapshot{phase}.zip"
            if not snapshot.is_file():
                break
            phase_results.append(_phase_grade(task, phase, snapshot, lab=lab,
                                              mcp_events=_mcp_events(native),
                                              task_contract_id=contract_id,
                                              mcp_journal=mcp_journal))
            if is_mcp_only:
                continue
            try:
                authored_test_quality = test_quality.assess_authored_regression(
                    task, snapshot, lab=lab,
                    candidate=phase_results[-1].get("authored_tests"))
            except Exception as exc:
                # A broken assessment never fabricates a quality and never
                # changes the episode's own infrastructure status.
                authored_test_quality = test_quality.make_assessment(
                    task, test_quality.UNVERIFIED,
                    f"authored-test quality assessment failed: {type(exc).__name__}")
            phase_results[-1]["authored_test_quality"] = authored_test_quality
            authored_qualities.append(authored_test_quality["quality"])
        row["authored_test_quality"] = (
            test_quality.NOT_APPLICABLE if is_mcp_only else
            test_quality.aggregate_qualities(authored_qualities) if phase_results
            else test_quality.UNVERIFIED)
        mcp_grade = phase_results[0].get("mcp") if task in _MCP_TASKS and phase_results else None
        if task in _MCP_TASKS and spec["language"] == "mcp" and phase_results:
            mcp_grade = phase_results[0]["hidden"]
        if task in _MCP_TASKS:
            _write_json(run_dir / "mcp-grade.json", mcp_grade or {"passed": False, "reason": "snapshot unavailable"})
        phase_ok = len(phase_results) == len(prompts)
        hidden_ok = phase_ok and all(item.get("hidden", {}).get("passed") for item in phase_results)
        authored_ok = (is_mcp_only or
                       (phase_ok and all(item.get("authored_tests", {}).get("passed") for item in phase_results)))
        row["correct"] = bool(hidden_ok and (mcp_grade is None or mcp_grade.get("passed")))
        phase_native = [item for item in driver if item.get("_practical_driver") == "phase"]
        all_driver_phases = len(phase_native) == len(prompts)
        driver_complete = all(type(item.get("exit_code")) is int and item["exit_code"] == 0
                              and bool(item.get("session_id")) for item in phase_native)
        tool_workflow = (task not in _MCP_TASKS or bool(mcp_grade and mcp_grade.get("passed")))
        no_agent_error = not any(item.get("type") == "error" for item in native)
        if not row['model_calls'] and not driver_complete:
            row.update(failure='contract_error', review_required=True, scoring_eligible=False)
            row['tool_review'] = {**row['tool_review'], 'reason':'agent_startup_contract'}
        additional_tests = (is_mcp_only or
                            all(item.get("authored_tests", {}).get("additional_count", 0) > 0
                                for item in phase_results))
        row["autonomous"] = bool(all_driver_phases and driver_complete and authored_ok
                                 and additional_tests and tool_workflow and no_agent_error
                                 and not result.timed_out and not result.output_limited)
        row["agent_finished"] = bool(all_driver_phases and driver_complete and no_agent_error
                                     and not result.timed_out and not result.output_limited)
        row["authored_tests_passed"] = (
            None if is_mcp_only or not additional_tests else
            bool(phase_ok and all(item.get("authored_tests", {}).get("suite_passed",
                                 item.get("authored_tests", {}).get("passed"))
                                  for item in phase_results)))
        row["authored_tests_added"] = None if is_mcp_only else bool(additional_tests)
        row["phases"] = phase_results
        row["driver_phases"] = phase_native
        row["mcp_grade"] = mcp_grade
        _finalize_outcome(row, phase_results=phase_results, phase_native=phase_native,
                          native=native, driver=driver, prompt_count=len(prompts),
                          language=spec["language"], result=result, model_stop=model_stop)
    except Exception as exc:
        row["failure"] = "infrastructure"
        row["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        (run_dir / "error.txt").write_text(row["error"] + "\n", encoding="utf-8")
    finally:
        row["seconds"] = round(time.monotonic() - started, 3)
        try:
            stopped = safe_campaign._resource_monitor_stop(monitor, monitor_status)
            _write_json(run_dir / "resource-sampling.json", stopped)
            row.update(_resource_peaks(run_dir))
        except Exception as exc:
            row.setdefault("resource_sampling_error", f"{type(exc).__name__}: {str(exc)[:200]}")
        server_cleanup = _stop_model_server(server_process)
        row["server_cleanup_verified"] = server_cleanup
        if not server_cleanup:
            row["failure"] = "infrastructure"
        row["artifact_identity"] = {
            "model_sha256": contract.get("sha256"),
            "profile_sha256": hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
            "snapshot_sha256": {path.name: _sha256(path) for path in run_dir.glob(".snapshot*.zip")},
            "runtime_sha256": {
                "driver": _sha256(ROOT / "benchmark/practical_driver_v2.py"),
                "mcp_server": _sha256(ROOT / "benchmark/practical_mcp_v2.py"),
            },
        }
        _normalize_outcome(row)
        from benchmark.practical_evidence import append_verdict
        row['evaluation_path'] = str(append_verdict(run_dir, {key: row.get(key) for key in (
            'correct', 'functional_correct', 'autonomous', 'failure', 'review_required',
            'scoring_eligible', 'tool_review', 'mcp_grade', 'phases', 'task_contract_id',
            'authored_test_quality', 'execution_valid', 'workflow_complete',
            'verified_success')}))
        _write_json(run_dir / "record.json", row)
    return row


def run_episode(model: str, task: str, profile: Mapping[str, Any], repetition: int,
                output: Path, models: Mapping[str, Mapping[str, Any]], *, lab: Path = LAB,
                policy_mode: str = 'benchmark', with_skills=True, budget_multiplier=1,
                task_contract_id: str | None = None) -> dict[str, Any]:
    """Run one fresh task with an owned model server, sandbox and independent grader."""
    selected = validate_profile(profile)
    generation = build_generation_policy(repetition)
    if model not in models:
        raise ValueError(f"unknown model contract {model!r}")
    if task not in practical_tasks_v2.ALL_TASKS:
        raise ValueError(f"unknown practical task {task!r}")
    if task not in practical_tasks_v2.ALL_TASKS:
        raise ValueError(f"unknown practical task {task!r}")
    task_contract = practical_tasks_v2.resolve_task_contract(task, task_contract_id)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # A fresh process and port are owned by this call and always stopped in _execute_episode.
    model_contract = models[model]
    run_hint = output / "runs"
    run_hint.mkdir(parents=True, exist_ok=True)
    preflight_dir = run_hint / f"{model}-{selected['id']}-{task}-r{repetition}-{time.time_ns()}"
    preflight_dir.mkdir()
    server_process: subprocess.Popen[bytes] | None = None
    try:
        server_process, log_path, upstream_port, load_seconds = _start_model_server(
            model, model_contract, selected, preflight_dir, lab=Path(lab))
        (preflight_dir / "llama-server-startup.json").write_text(json.dumps({
            "log": str(log_path), "port": upstream_port, "load_seconds": round(load_seconds, 3),
            "command": make_server_command(Path(lab) / model_contract["path"],
                                            str(model_contract["alias"]), selected, upstream_port,
                                            server=resolve_server(model_contract, Path(lab))[0]),
        }, indent=2) + "\n", encoding="utf-8")
        return _execute_episode(task, model, selected, repetition, output, models, lab=Path(lab),
                                server_process=server_process, upstream_port=upstream_port,
                                model_load_seconds=load_seconds, episode_dir=preflight_dir, policy_mode=policy_mode,
                                with_skills=with_skills, budget_multiplier=budget_multiplier,
                                task_contract_id=task_contract)
    except Exception as exc:
        message = f"{type(exc).__name__}: {str(exc)[:400]}"
        lowered = message.lower()
        failure = ("context_exhausted" if "context" in lowered and
                   any(word in lowered for word in ("exceed", "below", "full", "window")) else
                   "configuration" if any(word in lowered for word in ("unsupported", "profile", "configuration")) else
                   "infrastructure")
        record = {
            "protocol": PROTOCOL, "model": model, "profile": selected["id"], "task": task,
            "repetition": repetition, "generation_seed": generation["seed"],
            "task_contract_id": task_contract,
            "correct": False, "autonomous": False, "failure": failure,
            "seconds": 0.0, "tool_errors": 0, "model_calls": 0,
            "error": message,
            "run_dir": str(preflight_dir), "server_cleanup_verified": _stop_model_server(server_process),
            "artifact_identity": {"model_sha256": model_contract.get("sha256")},
        }
        if not record["server_cleanup_verified"]:
            record["failure"] = "infrastructure"
        _normalize_outcome(record)
        _write_json(preflight_dir / "record.json", record)
        return record


def probe_profile(model: str, profile: Mapping[str, Any], *, lab: Path = LAB,
                  output: Path | None = None,
                  models: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Load one pinned profile and require an actual OpenCode-to-MCP round trip."""
    selected = validate_profile(profile)
    try:
        from benchmark.practical_selection import contracts

        if models is None:
            models = contracts()
        if model not in models:
            raise ValueError(f"unknown model contract {model!r}")
        root = Path(output or Path(tempfile.mkdtemp(prefix="practical-v2-probe-")))
        root.mkdir(parents=True, exist_ok=True)
        run_dir = root / f"{model}-{selected['id']}-{time.time_ns()}"
        run_dir.mkdir()
        process = None
        try:
            process, log_path, port, load_seconds = _start_model_server(
                model, models[model], selected, run_dir, lab=Path(lab))
            server_command = make_server_command(
                Path(lab) / models[model]["path"], str(models[model]["alias"]),
                selected, port, server=resolve_server(models[model], Path(lab))[0])
            _write_json(run_dir / "llama-server-startup.json", {
                "log": str(log_path), "port": port,
                "load_seconds": round(load_seconds, 3), "command": server_command,
            })
            workspace = run_dir / "input"
            workspace.mkdir()
            contract = models[model]
            # The prompt deliberately requires one live MCP result and no task-bank content.
            result = _run_agent(
                "C2", model, contract, selected, 1, workspace, run_dir, lab=Path(lab),
                upstream_port=port, seconds=75, max_requests=5,
                prompts=["Call the local MCP tool named lab_list_issues exactly once, inspect its returned data, then reply READY."],
            )
            native, driver = _events(result.output)
            (run_dir / "native.jsonl").write_bytes(result.output)
            events = _mcp_events(native)
            successful = any(event["name"] == "list_issues" and not event["isError"] for event in events)
            compatible = successful and result.cleanup_verified and not result.infrastructure_error
            call_evidence = model_call_evidence(run_dir)
            evidence = {
                "model_server_log": str(log_path), "model_load_seconds": round(load_seconds, 3),
                **call_evidence,
                "tool_events": events, "server_cleanup_verified": _stop_model_server(process),
                "sandbox_cleanup_verified": result.cleanup_verified,
                "sandbox_infrastructure_error": result.infrastructure_error,
                "native_events_sha256": hashlib.sha256(result.output).hexdigest(),
            }
            environment_checks = [item for item in driver if item.get("_practical_driver") == "environment"]
            environment_failed = any(item.get("passed") is False for item in environment_checks)
            evidence["environment_passed"] = (all(item.get("passed") is True for item in environment_checks)
                                               if environment_checks else None)
            infrastructure = (result.infrastructure_error or not result.cleanup_verified
                              or not evidence["server_cleanup_verified"] or environment_failed)
            status = ("infrastructure" if infrastructure else
                      "passed" if compatible else "capability_diagnostic")
            return {"passed": status == "passed", "status": status,
                    "failure": (None if status == "passed" else
                                "infrastructure" if status == "infrastructure" else
                                "tool_call_not_observed"),
                    "model": model, "profile": selected, "model_calls": evidence["model_calls"],
                    "model_call_requests": evidence["model_call_requests"],
                    "run_dir": str(run_dir), "evidence": evidence}
        finally:
            if process is not None:
                _stop_model_server(process)
    except Exception as exc:
        message = f"{type(exc).__name__}: {str(exc)[:300]}"
        incompatible = isinstance(exc, ValueError) and any(
            token in str(exc).lower() for token in ("context", "profile", "unsupported", "configuration"))
        return {"passed": False, "status": "incompatible" if incompatible else "infrastructure",
                "failure": "configuration" if incompatible else "infrastructure",
                "model": model, "profile": selected, "reason": message, "model_calls": 0}


def _regrade_record(run_dir: Path, row: Mapping[str, Any], *,
                    task_contract_id: str,
                    verdict_profile: str, evaluation_producer: dict | None = None) -> dict[str, Any]:
    task = str(row["task"])
    native_path = run_dir / "native.jsonl"
    native, _ = _events(native_path.read_bytes()) if native_path.is_file() else ([], [])
    mcp_events = _mcp_events(native)
    mcp_journal = _mcp_journal(run_dir) if task in _MCP_TASKS else None
    phases = []
    for phase in range(1, practical_tasks_v2.TASK_SPECS[task]["phases"] + 1):
        snapshot = run_dir / f".snapshot{phase}.zip"
        if not snapshot.is_file():
            break
        phases.append(_phase_grade(task, phase, snapshot, lab=LAB, mcp_events=mcp_events,
                                   task_contract_id=task_contract_id,
                                   mcp_journal=mcp_journal))
    mcp_grade = None
    if task in _MCP_TASKS:
        from benchmark.practical_mcp_grading_v2 import grade_mcp_evidence

        workspace = run_dir / "regrade-mcp-input"
        if (run_dir / ".snapshot1.zip").is_file():
            _safe_extract_snapshot((run_dir / ".snapshot1.zip").read_bytes(), workspace)
            try:
                mcp_grade = grade_mcp_evidence(task, mcp_events, None,
                                               _artifact_values(task, workspace),
                                               task_contract_id=task_contract_id,
                                               journal=mcp_journal)
            finally:
                shutil.rmtree(workspace)
    observed = (len(phases) == practical_tasks_v2.TASK_SPECS[task]['phases']
                and all(not p.get('hidden',{}).get('infrastructure')
                        and not p.get('hidden',{}).get('contract_invalid') for p in phases))
    correct = (len(phases) == practical_tasks_v2.TASK_SPECS[task]["phases"]
               and all(item["hidden"].get("passed") for item in phases)
               and (mcp_grade is None or mcp_grade.get("passed")))
    value = {
        "task": task, "model": row.get("model"), "phases": phases,
        "task_contract_id": task_contract_id, "verdict_profile": verdict_profile,
        "record_task_contract_id": (
            str(row["task_contract_id"])
            if row.get("task_contract_id") is not None
            else practical_tasks_v2.HISTORICAL_CONTRACT),
        "mcp_grade": mcp_grade,
        # A sensitivity-only evaluation states its own contrast; it never
        # claims a main functional verdict. The appended record keeps both.
        "correct": bool(correct) if verdict_profile == "main" and observed else None,
        'review_required':not observed,
        'functional_correct':bool(correct) if observed else None,
        'evaluation_valid':observed,
        'scoring_eligible':observed and verdict_profile == 'main',
        'execution_valid':False if not observed else row.get('execution_valid'),
        'workflow_complete':False if not observed else row.get('workflow_complete'),
        "original_score_preserved": True,
        'evaluation_producer':evaluation_producer,
    }
    from benchmark.practical_evidence import append_verdict
    value['evaluation_path'] = str(append_verdict(run_dir, value))
    return value


# Legacy runs recorded a protocol instead of a task contract. The verified
# provenance rule: this runtime's own historical protocol id (and its recorded
# variant suffixes like -recovery). Any other protocol, or unknown explicit
# contract ids, require review instead of contract guessing.
_VERIFIED_HISTORICAL_PROTOCOL = PROTOCOL
_HISTORICAL_CENSUS = ROOT/'results/reports/full-result-audit-20261023/inventory.json'


def _is_verified_historical_protocol(protocol: str) -> bool:
    return (protocol == _VERIFIED_HISTORICAL_PROTOCOL
            or protocol.startswith(_VERIFIED_HISTORICAL_PROTOCOL + "-"))


def _verified_historical_record(row: Mapping[str,Any], run_dir: Path | None = None) -> bool:
    """Resolve legacy semantics from an audited fingerprint map, never a prefix."""
    try:
        directory=Path(run_dir) if run_dir is not None else Path(str(row.get('run_dir','')))
        if row.get('run_dir') is not None and row['run_dir'] != str(directory):
            return False
        census=json.loads(_HISTORICAL_CENSUS.read_text())
        entry=next(item for item in census['runs'] if item['run_dir']==str(directory))
        if entry.get('record',{}).get('task') not in (None,row.get('task')):
            return False
        fingerprints=entry.get('evidence') or {}
        if 'record.json' not in fingerprints:
            return False
        for name,info in fingerprints.items():
            if Path(name).name!=name or '\\' in name or not info.get('sha256'):
                return False
            if _sha256(directory/name)!=info['sha256']:
                return False
        stored=json.loads((directory/'record.json').read_text())
        if stored!=dict(row):
            return False
        owner=next(out for out in census['outputs'] if str(directory).startswith(out['output']+'/'))
        path=Path(owner['output'])/'manifest.json'
        if _sha256(path)!=owner.get('manifest_sha256'):
            return False
        manifest=json.loads(path.read_text())
        return (row.get('protocol')==manifest.get('protocol_id')==owner.get('protocol')
                and owner.get('immutable_hash_valid') is True
                and manifest.get('immutable_sha256')==hashlib.sha256(
                    json.dumps(manifest.get('immutable',{}),sort_keys=True,separators=(',',':'),
                               ensure_ascii=False).encode()).hexdigest())
    except (OSError,ValueError,KeyError,TypeError,StopIteration):
        return False


def _resolve_regrade_contract(row: Mapping[str, Any],
                              evaluation_profile: str | None, *, run_dir: Path | None = None) -> tuple[str, str]:
    """Resolve the grading contract for a stored episode.

    Default resolution picks the record's explicit task contract. A known
    legacy record without one falls back to the historical profile through the
    verified protocol map. An incompatible override may still grade, but only
    as a sensitivity evaluation: it can never produce the main verdict.
    """
    task = str(row["task"])
    allowed = practical_tasks_v2.task_contracts(task)
    explicit = row.get("task_contract_id")
    if evaluation_profile is not None:
        if evaluation_profile not in allowed:
            raise ValueError(
                f"unsupported task contract {evaluation_profile!r} for {task!r}: review required"
            )
        if explicit is None:
            if not _verified_historical_record(row,run_dir):
                raise ValueError(
                    f"legacy record {row.get('run_dir')!r} without a verified "
                    "historical provenance requires review"
                )
            profile = ("main" if evaluation_profile == practical_tasks_v2.HISTORICAL_CONTRACT
                       else "sensitivity")
            return evaluation_profile, profile
        if evaluation_profile == explicit:
            return evaluation_profile, "main"
        return evaluation_profile, "sensitivity"
    if explicit is None:
        if not _verified_historical_record(row,run_dir):
            raise ValueError(
                f"record {row.get('run_dir')!r} has no task contract and an "
                "no verified historical provenance: review required"
            )
        return practical_tasks_v2.HISTORICAL_CONTRACT, "main"
    resolved = practical_tasks_v2.resolve_task_contract(task, str(explicit))
    return resolved, "main"


def regrade_episode(run_dir: Path, *, evaluation_profile: str | None = None) -> dict[str, Any]:
    """Re-run saved hidden graders from immutable snapshots without inference.

    The grading contract comes from the record's explicit ``task_contract_id``;
    a verified legacy record (known historical protocol, no explicit id) is
    graded with the historical profile. An ``evaluation_profile`` override is
    allowed only for known contracts of the task: a compatible id keeps the
    main verdict slot, while an incompatible one produces a sensitivity-only
    evaluation that never replaces the main verdict.
    """
    directory = Path(run_dir)
    row = json.loads((directory / "record.json").read_text(encoding="utf-8"))
    contract, profile = _resolve_regrade_contract(row, evaluation_profile,run_dir=directory)
    return _regrade_record(directory, row, task_contract_id=contract,
                           verdict_profile=profile)


def regrade_run(output_dir: Path) -> list[dict[str, Any]]:
    """Regrade every saved episode in an output tree; no server is started."""
    output = Path(output_dir)
    return [regrade_episode(record.parent) for record in sorted((output / "runs").glob("*/record.json"))]


__all__ = ["LAB", "PROTOCOL", "build_generation_policy", "validate_profile",
           "make_opencode_profile", "make_server_command", "classify_http_error",
           "validate_environment", "probe_profile", "run_episode", "regrade_episode", "regrade_run"]
