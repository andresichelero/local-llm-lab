"""Fresh, input-bound no-model readiness controls for the canonical campaign."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
FINGERPRINTS = REPO_ROOT / "benchmark/configs/grading/fixture-fingerprints-v2.json"
CAMPAIGN_CONFIG = REPO_ROOT / "benchmark/configs/safe-model-campaign-v1.json"
REQUIRED_GATES = (
    "input_hashes", "trusted_grader_scope", "six_references", "six_noops", "six_mutants",
    "mutation_identity_controls", "runner_forgery", "unsupported_side_effects", "sandbox_sentinel",
    "host_file_oracle_observer_denial", "network_denial", "fake_broker",
    "detached_descendant_cleanup", "output_resource_scratch_caps", "fake_opencode_roundtrip",
    "workspace_export_modes", "observer_sampling", "canonical_trial_end_to_end",
    "model_bundle_audit", "workspace_checks",
)
_CONTROL_PATHS = (
    "docs/restricted-python-v2.md",
    "benchmark/configs/safe-model-campaign-v1.json",
    "benchmark/configs/grading/fixture-fingerprints-v2.json",
    "benchmark/configs/harnesses/opencode-subagents.json",
    "benchmark/safe_campaign.py", "benchmark/safe_execution_guard.py",
    "benchmark/campaign_readiness.py", "benchmark/trusted_grade_worker.py",
    "benchmark/campaign_e2e_control.py",
    "benchmark/campaign_observer.py", "benchmark/resource_sampler.py", "benchmark/provenance.py",
    "benchmark/summarize_vibe_context_stress.py",
    "benchmark/visible_feedback.py",
    "benchmark/pristine_grading.py", "benchmark/harness_eval.py", "benchmark/restricted_python.py",
    "benchmark/linux_sandbox.py", "benchmark/sandbox_bootstrap.py", "benchmark/model_broker.py",
    "benchmark/run_observer.py", "benchmark/harness_runner.py", "benchmark/model_quality_paired.py",
    "benchmark/opencode_controlled_probe.py", "benchmark/cascade_routing_matrix.py",
    "benchmark/candidate_admission_paired.py", "benchmark/mtp_agentic_paired.py",
    "benchmark/prefix_cache_paired.py", "tests/test_trusted_task_tests.py", "tests/test_pristine_grading.py",
    "tests/test_harness_eval.py", "tests/test_restricted_python.py", "tests/test_linux_sandbox.py",
    "tests/test_model_broker.py", "tests/test_safe_campaign.py", "tests/test_campaign_readiness.py",
    "tests/test_campaign_observer.py", "tests/test_visible_feedback.py",
    "tests/test_vibe_context_stress_summary.py",
    "tests/test_safe_execution_guard.py",
    "tests/test_campaign_e2e_control.py",
)
_OUTPUT_LIMIT = 64 * 1024


def _sha256_file(path: Path, *, limit: int | None = None) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if limit is not None and total > limit:
                raise ValueError("input_file_too_large")
            digest.update(chunk)
    return digest.hexdigest()


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    """Normalize immutable mappings/tuples and reject non-JSON evidence values."""
    if depth > 64:
        raise ValueError("readiness evidence exceeds JSON nesting limit")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("readiness evidence contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("readiness evidence mapping keys must be strings")
            result[key] = _json_safe(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    raise TypeError(f"readiness evidence contains unsupported JSON value: {type(value).__name__}")


def _manifest_files() -> set[str]:
    from benchmark.harness_runner import TASK_PATHS

    payload = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    if payload.get("grader_protocol_version") != "restricted-python-workspace-v2":
        raise ValueError("unexpected_grader_protocol")
    files: set[str] = set()
    for task in payload.get("tasks", {}).values():
        fixture = task["fixture"]
        files.update(f"{fixture}/{relative}" for relative in task["files"])
        files.add(task["probe"]["file"])
    files.update(prompt.as_posix() for _fixture, prompt in TASK_PATHS.values())
    return files


def _runtime_input_records(benchmark_root: Path | None) -> list[dict[str, Any]]:
    """Hash concrete executable assets and stable runtime identities, not model weights."""
    root = Path(benchmark_root) if benchmark_root is not None else Path(
        os.environ.get("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark"))
    records: list[dict[str, Any]] = []
    binaries = {
        "runtime/lab-python": Path(sys.executable),
        "runtime/sandbox-python": Path("/usr/bin/python3"),
        "runtime/opencode": root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode",
        "runtime/llama-server": root / "tools/llama-bin/llama-server",
    }
    for label, path in binaries.items():
        records.append(_runtime_file_record(label, path))
    for tool in ("systemd-run", "systemctl", "unshare", "python3", "findmnt", "nvidia-smi", "ruff"):
        executable = shutil.which(tool)
        records.append(_runtime_file_record(f"runtime/tool/{tool}",
                                            Path(executable) if executable else Path(f"/missing/{tool}")))
    library_dir = root / "tools/llama-bin"
    try:
        if not library_dir.is_dir() or library_dir.is_symlink():
            raise OSError("bundle_library_directory_unavailable")
        for current, directories, filenames in os.walk(library_dir, followlinks=False):
            directories.sort()
            filenames.sort()
            for name in list(directories):
                path = Path(current) / name
                if path.is_symlink():
                    directories.remove(name)
                    target = os.readlink(path)
                    resolved = path.resolve(strict=True)
                    if library_dir.resolve(strict=True) not in resolved.parents:
                        raise OSError("library_symlink_escapes_bundle")
                    info = resolved.stat()
                    records.append({"path": f"runtime/llama-library/{path.relative_to(library_dir).as_posix()}",
                                    "size_bytes": info.st_size, "sha256": _sha256_file(resolved),
                                    "symlink_target_sha256": hashlib.sha256(target.encode()).hexdigest(),
                                    "status": "measured"})
            for name in filenames:
                path = Path(current) / name
                if path.is_symlink():
                    target = os.readlink(path)
                    resolved = path.resolve(strict=True)
                    if library_dir.resolve(strict=True) not in resolved.parents:
                        raise OSError("library_symlink_escapes_bundle")
                    info = resolved.stat()
                    records.append({"path": f"runtime/llama-library/{path.relative_to(library_dir).as_posix()}",
                                    "size_bytes": info.st_size, "sha256": _sha256_file(resolved),
                                    "symlink_target_sha256": hashlib.sha256(target.encode()).hexdigest(),
                                    "status": "measured"})
                elif path.is_file():
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode):
                        raise OSError("non_regular_library_asset")
                    records.append({"path": f"runtime/llama-library/{path.relative_to(library_dir).as_posix()}",
                                    "size_bytes": info.st_size, "sha256": _sha256_file(path),
                                    "status": "measured"})
        if not any(record["path"].startswith("runtime/llama-library/") for record in records):
            raise OSError("bundle_library_assets_unavailable")
    except OSError as exc:
        records.append({"path": "runtime/llama-library", "size_bytes": None,
                        "sha256": None, "status": "unavailable", "reason": type(exc).__name__})
    provider_root = root / "cache/opencode-node-modules"
    try:
        provider_root = provider_root.resolve(strict=True)
        if not provider_root.is_dir():
            raise OSError("provider_cache_not_directory")
        entry_count = 0
        for current, directories, filenames in os.walk(provider_root, followlinks=False):
            directories.sort()
            filenames.sort()
            for name in list(directories):
                path = Path(current) / name
                relative = path.relative_to(provider_root).as_posix()
                info = path.lstat()
                entry_count += 1
                if entry_count > 50_000:
                    raise OSError("provider_cache_entry_limit")
                if stat.S_ISLNK(info.st_mode):
                    target = os.readlink(path)
                    resolved = path.resolve(strict=True)
                    if (Path("..") in Path(target).parts or provider_root not in resolved.parents
                            or not (resolved.is_file() or resolved.is_dir())):
                        raise OSError("provider_cache_symlink_escapes_root")
                    record_path = f"runtime/opencode-provider/{relative}"
                    records.append({"path": record_path, "type": "symlink", "size_bytes": None,
                                    "sha256": hashlib.sha256(target.encode()).hexdigest(),
                                    "status": "measured"})
                    directories.remove(name)
                else:
                    records.append({"path": f"runtime/opencode-provider/{relative}", "type": "directory",
                                    "size_bytes": None, "sha256": None, "status": "measured"})
            for name in filenames:
                path = Path(current) / name
                relative = path.relative_to(provider_root).as_posix()
                info = path.lstat()
                entry_count += 1
                if entry_count > 50_000:
                    raise OSError("provider_cache_entry_limit")
                if stat.S_ISLNK(info.st_mode):
                    target = os.readlink(path)
                    resolved = path.resolve(strict=True)
                    if (Path("..") in Path(target).parts or provider_root not in resolved.parents
                            or not resolved.is_file()):
                        raise OSError("provider_cache_symlink_escapes_root")
                    records.append({"path": f"runtime/opencode-provider/{relative}", "type": "symlink",
                                    "size_bytes": resolved.stat().st_size,
                                    "sha256": _sha256_file(resolved),
                                    "link_target_sha256": hashlib.sha256(target.encode()).hexdigest(),
                                    "status": "measured"})
                elif stat.S_ISREG(info.st_mode):
                    records.append({"path": f"runtime/opencode-provider/{relative}", "type": "file",
                                    "size_bytes": info.st_size, "sha256": _sha256_file(path),
                                    "status": "measured"})
                else:
                    raise OSError("provider_cache_contains_non_regular_file")
        for name in ("package.json", "package-lock.json"):
            path = root / "cache" / name
            records.append(_runtime_file_record(f"runtime/opencode-provider-{name}", path))
        if not any(record["path"].startswith("runtime/opencode-provider/")
                   and record.get("type") == "file" for record in records):
            raise OSError("provider_cache_has_no_package_files")
    except OSError as exc:
        records.append({"path": "runtime/opencode-provider", "size_bytes": None,
                        "sha256": None, "status": "unavailable", "reason": type(exc).__name__})
    stable = {
        "runtime/python-version": sys.version.encode("utf-8"),
        "runtime/platform": platform.platform().encode("utf-8"),
        "runtime/kernel-release": Path("/proc/sys/kernel/osrelease").read_bytes()
        if Path("/proc/sys/kernel/osrelease").is_file() else b"",
    }
    for label, value in stable.items():
        records.append({"path": label, "size_bytes": len(value),
                        "sha256": hashlib.sha256(value).hexdigest(),
                        "status": "measured" if value else "unavailable"})
    return records


def _runtime_file_record(label: str, path: Path) -> dict[str, Any]:
    """Hash a regular executable or the verified target and identity of its symlink."""
    try:
        info = path.lstat()
        link_target = None
        resolved = path
        if stat.S_ISLNK(info.st_mode):
            link_target = os.readlink(path)
            resolved = path.resolve(strict=True)
            info = resolved.stat()
        if not stat.S_ISREG(info.st_mode):
            raise OSError("not_regular_file")
        record: dict[str, Any] = {"path": label, "size_bytes": info.st_size,
                                  "sha256": _sha256_file(resolved), "status": "measured",
                                  "resolved_path": str(resolved)}
        if link_target is not None:
            record.update(type="symlink", link_target=link_target,
                          link_target_sha256=hashlib.sha256(link_target.encode()).hexdigest())
        else:
            record["type"] = "file"
        return record
    except OSError as exc:
        return {"path": label, "size_bytes": None, "sha256": None,
                "status": "unavailable", "reason": type(exc).__name__}


def input_hash_manifest(*, benchmark_root: Path | None = None) -> dict[str, Any]:
    """Hash all source and fixture inputs plus the exact external runtime assets."""
    try:
        paths = set(_CONTROL_PATHS) | _manifest_files()
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        paths = set(_CONTROL_PATHS)
    records: list[dict[str, Any]] = []
    for relative in sorted(paths):
        path = REPO_ROOT / relative
        try:
            info = path.lstat()
            if path.is_symlink() or not path.is_file():
                raise OSError("not_a_regular_file")
            records.append({"path": relative, "size_bytes": info.st_size,
                            "sha256": _sha256_file(path, limit=8 * 1024 * 1024), "status": "measured"})
        except (OSError, ValueError) as exc:
            records.append({"path": relative, "size_bytes": None, "sha256": None,
                            "status": "unavailable", "reason": type(exc).__name__})
    records.extend(_runtime_input_records(benchmark_root))
    records.sort(key=lambda row: row["path"])
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"records": records, "digest": hashlib.sha256(encoded).hexdigest(),
            "complete": bool(records) and all(row["status"] == "measured" for row in records)}


def validate_readiness_report(report: dict[str, Any], *, current_input_digest: str) -> dict[str, Any]:
    """Reject stale or incomplete readiness evidence, including forged READY labels."""
    gates = report.get("gates")
    missing = [name for name in REQUIRED_GATES if not isinstance(gates, dict) or name not in gates]
    failed = [name for name in REQUIRED_GATES if isinstance(gates, dict) and name in gates
              and (not isinstance(gates[name], dict) or gates[name].get("status") != "passed")]
    if missing or failed:
        return {"ready": False, "reason": "required_gate_missing_or_unavailable",
                "failed_gates": sorted(set(missing + failed))}
    if report.get("input_digest") != current_input_digest:
        return {"ready": False, "reason": "input_digest_mismatch", "failed_gates": []}
    if report.get("verdict") != "READY":
        return {"ready": False, "reason": "source_verdict_not_ready", "failed_gates": []}
    return {"ready": True, "reason": "all_required_gates_passed_for_current_inputs", "failed_gates": []}


def _load_control_tests() -> Any:
    path = REPO_ROOT / "tests/test_trusted_task_tests.py"
    spec = importlib.util.spec_from_file_location("_safe_campaign_trusted_controls", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("trusted_control_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_grade_case(task: str, implementation: dict[str, str], destination: Path) -> None:
    controls = _load_control_tests()
    controls._prepare_grade_workspace(task, implementation, destination)


def _bounded_drain(stream: Any, limit: int, state: dict[str, Any], key: str,
                   exceeded: threading.Event) -> None:
    retained = bytearray()
    total = 0
    while True:
        chunk = stream.read(8192)
        if not chunk:
            break
        total += len(chunk)
        if len(retained) < limit:
            retained.extend(chunk[:limit - len(retained)])
        if total > limit:
            exceeded.set()
    state[key] = bytes(retained)
    state[f"{key}_total"] = total


def run_scoped_grade(workspace: Path, task: str, *, artifact_dir: Path | None = None,
                     wall_seconds: int = 20) -> dict[str, Any]:
    """Run the trusted JSON worker in its own verified transient systemd scope."""
    from benchmark.linux_sandbox import (ResourceLimits, SandboxError, new_scope_unit,
                                         read_scope_resource_evidence, stop_owned_scope,
                                         systemd_scope_command)

    limits = ResourceLimits(memory_bytes=768 * 1024**2, swap_bytes=256 * 1024**2,
                            cpu_quota_percent=100, cpu_seconds=25, pids=32,
                            wall_seconds=wall_seconds, output_bytes=_OUTPUT_LIMIT,
                            workspace_bytes=16 * 1024**2, workspace_files=500,
                            workspace_file_bytes=4 * 1024**2, scratch_bytes=16 * 1024**2,
                            file_bytes=16 * 1024**2, open_files=128,
                            export_file_bytes=2 * 1024**2, export_total_bytes=8 * 1024**2,
                            rootfs_bytes=32 * 1024**2, startup_seconds=5, stop_grace_seconds=2)
    unit = new_scope_unit("trusted-grader")
    worker_code = ("import sys; sys.path.insert(0, " + repr(str(REPO_ROOT)) + "); "
                   "from benchmark.trusted_grade_worker import main; raise SystemExit(main())")
    command = systemd_scope_command([sys.executable, "-I", "-c", worker_code], limits, unit=unit)
    env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
    for name in ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        if name in os.environ:
            env[name] = os.environ[name]
    process: subprocess.Popen[bytes] | None = None
    threads: list[threading.Thread] = []
    output_state: dict[str, Any] = {}
    exceeded = threading.Event()
    evidence: dict[str, Any] | None = None
    started = time.monotonic()
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, close_fds=True, env=env)
        assert process.stdout is not None and process.stderr is not None
        for key, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            reader = threading.Thread(target=_bounded_drain,
                                      args=(stream, _OUTPUT_LIMIT, output_state, key, exceeded), daemon=True)
            reader.start()
            threads.append(reader)
        startup_deadline = time.monotonic() + min(8, wall_seconds / 2)
        while time.monotonic() < startup_deadline and process.poll() is None:
            try:
                evidence = read_scope_resource_evidence(unit, limits)
                break
            except (SandboxError, OSError, subprocess.SubprocessError):
                time.sleep(0.05)
        if evidence is None:
            stop_owned_scope(unit)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            return {"status": "infrastructure_failure", "reason": "trusted_grader_scope_evidence_unavailable",
                    "returncode": process.returncode, "resource_evidence": None,
                    "stderr": output_state.get("stderr", b"").decode("utf-8", errors="replace")}
        request = {"workspace": str(workspace.resolve(strict=True)), "task": task,
                   "artifact_dir": str(artifact_dir.resolve(strict=False)) if artifact_dir else None}
        assert process.stdin is not None
        process.stdin.write(json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n")
        process.stdin.close()
        deadline = time.monotonic() + wall_seconds
        while process.poll() is None and time.monotonic() < deadline:
            if exceeded.is_set():
                stop_owned_scope(unit)
                break
            time.sleep(0.02)
        timed_out = process.poll() is None
        if timed_out:
            stop_owned_scope(unit)
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        for reader in threads:
            reader.join(timeout=2)
        stdout = output_state.get("stdout", b"")
        result: dict[str, Any] = {
            "returncode": process.returncode, "timed_out": timed_out,
            "output_limited": exceeded.is_set(), "resource_evidence": evidence,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": output_state.get("stderr", b"").decode("utf-8", errors="replace"),
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        if timed_out or exceeded.is_set() or process.returncode != 0:
            resource = timed_out or exceeded.is_set() or process.returncode in {-9, 137}
            result.update(status="resource_limit" if resource else "infrastructure_failure",
                          reason="trusted_grader_timeout_or_output_limit" if resource else "trusted_grader_abnormal_exit")
            return result
        lines = [line for line in stdout.decode("utf-8", errors="replace").splitlines() if line]
        if len(lines) != 1 or len(lines[0].encode("utf-8")) > _OUTPUT_LIMIT:
            result.update(status="infrastructure_failure", reason="trusted_grader_output_invalid")
            return result
        envelope = json.loads(lines[0])
        if not isinstance(envelope, dict) or envelope.get("status") != "ok" or not isinstance(envelope.get("result"), dict):
            result.update(status="infrastructure_failure", reason="trusted_grader_worker_error",
                          worker_error=envelope if isinstance(envelope, dict) else None)
            return result
        result.update(status="completed", grade=envelope["result"])
        return result
    except (OSError, ValueError, SandboxError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        if process is not None and process.poll() is None:
            stop_owned_scope(unit)
        return {"status": "infrastructure_failure", "reason": f"trusted_grader_launch:{type(exc).__name__}",
                "resource_evidence": evidence}
    finally:
        for reader in threads:
            reader.join(timeout=0.2)


def _compact_grade(item: dict[str, Any]) -> dict[str, Any]:
    grade = item.get("grade")
    if not isinstance(grade, dict):
        return {key: item.get(key) for key in ("status", "reason", "returncode")}
    return {key: grade.get(key) for key in ("evaluation_status", "success", "functional_pass",
                                             "regression_pass", "runtime_result_authenticated")} | {
        "scope_status": item.get("status"), "returncode": item.get("returncode")}


class _FakeModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/v1/models":
            self.send_error(404)
            return
        state = self.server.readiness_state  # type: ignore[attr-defined]
        state["models_requests"] += 1
        self._send({"data": [{"id": self.server.readiness_model}]})  # type: ignore[attr-defined]

    def do_POST(self) -> None:  # noqa: N802
        size = int(self.headers.get("Content-Length", "0"))
        if self.path != "/v1/chat/completions" or not 0 < size <= 2 * 1024 * 1024:
            self.send_error(400)
            return
        try:
            payload = json.loads(self.rfile.read(size))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400)
            return
        state = self.server.readiness_state  # type: ignore[attr-defined]
        state["chat_requests"] += 1
        calls = _calls_from_tools(payload.get("tools"))
        if calls and not state["tool_response_sent"]:
            state["tool_calls"] = [call["function"]["name"] for call in calls]
            state["tool_response_sent"] = True
            body = {"id": "fake-readiness-tools", "object": "chat.completion", "created": 0,
                    "model": self.server.readiness_model, "choices": [{"index": 0,
                    "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                    "tool_calls": calls}}]}  # type: ignore[attr-defined]
        else:
            body = {"id": "fake-readiness-final", "object": "chat.completion", "created": 0,
                    "model": self.server.readiness_model, "choices": [{"index": 0,
                    "finish_reason": "stop", "message": {"role": "assistant",
                    "content": "fake endpoint roundtrip complete"}}]}  # type: ignore[attr-defined]
        if payload.get("stream") is True:
            self._send_stream(body)
        else:
            self._send(body)

    def _send(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_stream(self, payload: dict[str, Any]) -> None:
        choice = payload["choices"][0]
        message = choice["message"]
        if message.get("tool_calls"):
            delta = {"role": "assistant", "tool_calls": [
                {"index": index, **call} for index, call in enumerate(message["tool_calls"])
            ]}
        else:
            delta = {"role": "assistant", "content": message.get("content", "")}
        chunk = {"id": payload["id"], "object": "chat.completion.chunk", "created": 0,
                 "model": payload["model"], "choices": [{"index": 0, "delta": delta,
                 "finish_reason": choice["finish_reason"]}]}
        data = ("data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n"
                + "data: [DONE]\n\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def _calls_from_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, list):
        return []
    selected: list[tuple[str, dict[str, Any]]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            continue
        if function["name"].lower() in {"bash", "edit"}:
            selected.append((function["name"], function))
    if {name.lower() for name, _ in selected} != {"bash", "edit"}:
        return []
    result = []
    for index, (name, schema) in enumerate(selected):
        args = _schema_arguments(schema.get("parameters", {}), name)
        result.append({"id": f"fake-call-{index + 1}", "type": "function",
                       "function": {"name": name, "arguments": json.dumps(args, separators=(",", ":"))}})
    return result


def _schema_arguments(schema: Any, tool_name: str) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        return {}
    result: dict[str, Any] = {}
    for raw_key in required:
        if not isinstance(raw_key, str) or raw_key not in properties:
            continue
        key = raw_key.lower().replace("_", "")
        spec = properties[raw_key]
        if tool_name.lower() == "bash" and key in {"command", "cmd", "script"}:
            value: Any = "printf fake-bash-ok > src/bash-probe.txt"
        elif key in {"filepath", "path", "file"}:
            value = "/workspace/src/probe.txt" if key == "filepath" else "src/probe.txt"
        elif key in {"oldstring", "oldtext", "search"}:
            value = "replace-target"
        elif key in {"newstring", "newtext", "content", "text"}:
            value = "fake-edit-ok"
        else:
            value = _schema_default(spec)
        result[raw_key] = value
    return result


def _schema_default(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return ""
    choices = schema.get("enum")
    if isinstance(choices, list) and choices:
        return choices[0]
    kind = schema.get("type")
    if kind == "boolean":
        return False
    if kind == "integer":
        return schema.get("minimum", 1)
    if kind == "number":
        return schema.get("minimum", 0.5)
    if kind == "array":
        return []
    if kind == "object":
        return _schema_arguments(schema, "")
    return "readiness probe"


def _fake_endpoint(model_id: str) -> tuple[ThreadingHTTPServer, threading.Thread, dict[str, Any]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeModelHandler)
    server.daemon_threads = True
    state: dict[str, Any] = {"models_requests": 0, "chat_requests": 0,
                             "tool_response_sent": False, "tool_calls": [], "last_request": None}
    server.readiness_state = state  # type: ignore[attr-defined]
    server.readiness_model = model_id  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread, state


def _set_gate(gates: dict[str, dict[str, Any]], name: str, passed: bool, reason: str,
              details: dict[str, Any] | None = None) -> None:
    gates[name] = _json_safe(details) if details else {}
    if "status" in gates[name]:
        gates[name]["evidence_status"] = gates[name]["status"]
    gates[name].update({"status": "passed" if passed else "unavailable", "reason": reason})


def _prepare_evidence_root(path: Path | None, *, benchmark_root: Path | None = None) -> Path:
    if path is None:
        root = Path(benchmark_root) if benchmark_root is not None else Path(
            os.environ.get("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark"))
        if not root.is_dir():
            raise FileNotFoundError("benchmark root is unavailable for durable readiness evidence")
        parent = root / "results"
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = parent / f"readiness-{time.time_ns()}"
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.mkdir(mode=0o700, exist_ok=False)
    path.chmod(0o700)
    path = path.resolve(strict=True)
    repo = REPO_ROOT.resolve(strict=True)
    if path == repo or repo in path.parents:
        raise ValueError("readiness evidence must be stored outside the source repository")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise OSError("readiness evidence directory must be private")
    findmnt = shutil.which("findmnt")
    if findmnt is None:
        raise OSError("findmnt is required to verify durable evidence filesystem")
    filesystem = subprocess.run([findmnt, "-n", "-o", "FSTYPE", "-T", str(path)],
                                capture_output=True, text=True, timeout=5, check=False)
    if filesystem.returncode != 0 or filesystem.stdout.strip() != "ext4":
        raise OSError("readiness evidence must be stored on ext4")
    return path


def _start_resource_monitor(evidence_root: Path, *, name: str, run_id: str,
                            phase_id: str, agent_id: str) -> tuple[Any, dict[str, Any]]:
    try:
        from benchmark.campaign_observer import ResourceMonitor

        directory = evidence_root / f"{name}-{time.time_ns()}"
        monitor = ResourceMonitor.start(directory, run_id=run_id, phase_id=phase_id,
                                        agent_id=agent_id, interval=1.0)
        return monitor, {"status": "running", "scope": "system_wide"}
    except Exception as exc:
        return None, {"status": "unavailable", "scope": "system_wide",
                      "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _stop_resource_monitor(monitor: Any, startup: dict[str, Any]) -> dict[str, Any]:
    if monitor is None:
        return startup
    try:
        return monitor.stop()
    except Exception as exc:
        return {"status": "unavailable", "scope": "system_wide",
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _loopback_port_is_free(port: int) -> bool:
    """Check server-compatible bind/listen availability, including TIME_WAIT reuse."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
            # A bind alone can coexist with an existing SO_REUSEADDR listener on
            # Linux. listen must also succeed; never enable SO_REUSEPORT here.
            probe.listen(1)
            return True
        except OSError:
            return False


def _model_bundle_audit(benchmark_root: Path | None = None) -> dict[str, Any]:
    """Read-only check of pinned model/server bundle and current resource headroom."""
    from benchmark.model_quality_paired import MODELS, RUNTIME_REVISION, SERVER_PORT
    from benchmark.opencode_controlled_probe import _assert_server_bundle, require_runtime_revision

    root = Path(benchmark_root) if benchmark_root is not None else Path(
        os.environ.get("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark"))
    requirements = json.loads(CAMPAIGN_CONFIG.read_text(encoding="utf-8"))["resource_requirements"]
    evidence: dict[str, Any] = {"benchmark_root": str(root), "models": {}, "server": {}, "resources": {}}
    if not root.is_dir():
        return {"passed": False, "reason": "benchmark_root_unavailable", "evidence": evidence}
    for name, model in MODELS.items():
        path = root / model["path"]
        try:
            metadata = path.lstat()
        except OSError:
            metadata = None
        if metadata is None or path.is_symlink() or not path.is_file():
            evidence["models"][name] = {"status": "unavailable", "reason": "pinned_model_missing"}
            continue
        digest = _sha256_file(path)
        evidence["models"][name] = {"status": "passed" if digest == model["sha256"] else "failed",
                                    "sha256": digest, "expected_sha256": model["sha256"],
                                    "size_bytes": path.stat().st_size}
    binary = root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    server = root / "tools/llama-bin/llama-server"
    libdir = root / "tools/llama-bin"
    try:
        _assert_server_bundle(server, libdir)
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp",
               "LANG": "C.UTF-8", "LD_LIBRARY_PATH": str(libdir)}
        version = subprocess.run([str(server), "--version"], env=env, capture_output=True, timeout=15, check=False)
        if version.returncode != 0:
            raise RuntimeError(f"llama_server_version_failed:{version.returncode}")
        version_text = require_runtime_revision(version.stdout.decode("utf-8", errors="replace"),
                                               version.stderr.decode("utf-8", errors="replace"), RUNTIME_REVISION[:9])
        evidence["server"]["bundle"] = "passed"
        evidence["server"]["runtime_revision"] = version_text
        opencode = subprocess.run([str(binary), "--version"], env=env, capture_output=True, timeout=15, check=False)
        version_text = opencode.stdout.decode("utf-8", errors="replace").strip()[:200]
        evidence["server"]["opencode_version"] = version_text
        evidence["server"]["opencode_binary"] = "passed" if binary.is_file() and opencode.returncode == 0 and "1.19.0" in version_text else "failed"
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        evidence["server"]["status"] = f"unavailable:{type(exc).__name__}"
        evidence["server"]["reason"] = str(exc)[:1000]
    try:
        for port in (SERVER_PORT, 18888):
            evidence["resources"][f"port_{port}_free"] = _loopback_port_is_free(port)
        try:
            meminfo = {}
            for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
                key, _, tail = line.partition(":")
                if key in {"MemAvailable", "SwapFree"}:
                    meminfo[key] = int(tail.split()[0]) * 1024
            evidence["resources"]["mem_available_bytes"] = meminfo.get("MemAvailable")
            evidence["resources"]["swap_free_bytes"] = meminfo.get("SwapFree")
            evidence["resources"]["memory_reserve_passed"] = (
                meminfo.get("MemAvailable", 0) >= requirements["minimum_available_memory_bytes"]
                and meminfo.get("SwapFree", 0) >= requirements["minimum_free_swap_bytes"]
            )
        except (OSError, ValueError):
            evidence["resources"]["memory_reserve_passed"] = False
        if shutil.which("nvidia-smi"):
            gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.free,memory.total,utilization.gpu",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5, check=False)
            evidence["resources"]["gpu_status"] = "passed" if gpu.returncode == 0 and gpu.stdout.strip() else "unavailable"
            evidence["resources"]["gpu_summary"] = gpu.stdout[:1000]
            try:
                evidence["resources"]["gpu_devices"] = [
                    {"name": fields[0].strip(), "memory_free_mib": int(fields[1]),
                     "memory_total_mib": int(fields[2]), "utilization_percent": int(fields[3])}
                    for line in gpu.stdout.splitlines()
                    if len(fields := line.split(",")) == 4
                ]
            except ValueError:
                evidence["resources"]["gpu_devices"] = []
            evidence["resources"]["gpu_headroom_passed"] = any(
                device["memory_free_mib"] >= requirements["minimum_free_vram_mib"]
                and device["memory_total_mib"] >= requirements["minimum_total_vram_mib"]
                and device["utilization_percent"] <= requirements["maximum_initial_gpu_utilization_percent"]
                for device in evidence["resources"]["gpu_devices"]
            )
        else:
            evidence["resources"]["gpu_status"] = "unavailable"
            evidence["resources"]["gpu_devices"] = []
            evidence["resources"]["gpu_headroom_passed"] = False
        findmnt = shutil.which("findmnt")
        if findmnt:
            fs = subprocess.run([findmnt, "-n", "-o", "FSTYPE", "-T", str(root)],
                                capture_output=True, text=True, timeout=5, check=False)
            evidence["resources"]["benchmark_filesystem"] = fs.stdout.strip() if fs.returncode == 0 else "unavailable"
            source_fs = subprocess.run([findmnt, "-n", "-o", "FSTYPE", "-T", str(REPO_ROOT)],
                                       capture_output=True, text=True, timeout=5, check=False)
            evidence["resources"]["source_filesystem"] = (
                source_fs.stdout.strip() if source_fs.returncode == 0 else "unavailable")
        else:
            evidence["resources"]["benchmark_filesystem"] = "unavailable"
            evidence["resources"]["source_filesystem"] = "unavailable"
        evidence["resources"]["benchmark_free_bytes"] = shutil.disk_usage(root).free
        evidence["resources"]["benchmark_disk_reserve_passed"] = (
            shutil.disk_usage(root).free >= requirements["minimum_benchmark_disk_bytes"])
        source_parent = REPO_ROOT if REPO_ROOT.exists() else REPO_ROOT.parent
        evidence["resources"]["source_free_bytes"] = shutil.disk_usage(source_parent).free
    except (OSError, subprocess.SubprocessError) as exc:
        evidence["resources"]["audit_error"] = type(exc).__name__
    passed = (all(row.get("status") == "passed" for row in evidence["models"].values())
              and evidence["server"].get("bundle") == "passed"
              and evidence["server"].get("opencode_binary") == "passed"
              and evidence["resources"].get("port_8080_free") is True
              and evidence["resources"].get("port_18888_free") is True
              and evidence["resources"].get("memory_reserve_passed") is True
              and evidence["resources"].get("benchmark_disk_reserve_passed") is True
              and evidence["resources"].get("gpu_status") == "passed"
              and evidence["resources"].get("gpu_headroom_passed") is True
              and evidence["resources"].get("benchmark_filesystem") == "ext4"
              and evidence["resources"].get("source_filesystem") == "ext4")
    return {"passed": passed, "reason": "read_only_bundle_resource_and_port_audit", "evidence": evidence}


def _workspace_checks() -> dict[str, Any]:
    patterns = ("test_restricted_python.py", "test_pristine_grading.py", "test_harness_eval.py",
                "test_trusted_task_tests.py", "test_linux_sandbox.py", "test_model_broker.py",
                "test_safe_campaign.py", "test_campaign_readiness.py", "test_safe_execution_guard.py",
                "test_campaign_e2e_control.py")
    checks: dict[str, Any] = {}
    for pattern in patterns:
        test_path = REPO_ROOT / "tests" / pattern
        if not test_path.is_file():
            checks[pattern] = {"status": "unavailable", "reason": "focused_test_file_missing"}
            continue
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   str(test_path)]
        env = os.environ.copy()
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        try:
            result = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True,
                                    timeout=120, check=False)
            output = (result.stdout + result.stderr)[-_OUTPUT_LIMIT:]
            combined = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            outcomes = _pytest_summary_counts(combined)
            test_count = sum(outcomes.values())
            valid = (result.returncode == 0 and outcomes["passed"] > 0
                     and all(outcomes[key] == 0 for key in ("failed", "errors", "skipped", "xfailed", "xpassed")))
            checks[pattern] = {"status": "passed" if valid else "failed",
                               "returncode": result.returncode,
                               "test_count": test_count,
                               "test_outcomes": outcomes,
                               "output_tail": output.decode("utf-8", errors="replace")}
        except (OSError, subprocess.SubprocessError) as exc:
            checks[pattern] = {"status": "unavailable", "reason": type(exc).__name__}
    ruff = shutil.which("ruff")
    if ruff is None:
        user_ruff = Path.home() / ".local/bin/ruff"
        ruff = str(user_ruff) if user_ruff.is_file() else None
    if ruff:
        paths = [str(REPO_ROOT / path) for path in _CONTROL_PATHS if path.endswith(".py") and (REPO_ROOT / path).exists()]
        try:
            result = subprocess.run([ruff, "check", *paths], cwd=REPO_ROOT, capture_output=True, timeout=60, check=False)
            output = (result.stdout + result.stderr)[-_OUTPUT_LIMIT:]
            checks["ruff"] = {"status": "passed" if result.returncode == 0 else "failed",
                              "returncode": result.returncode,
                              "output_tail": output.decode("utf-8", errors="replace")}
        except (OSError, subprocess.SubprocessError) as exc:
            checks["ruff"] = {"status": "unavailable", "reason": type(exc).__name__}
    else:
        checks["ruff"] = {"status": "unavailable", "reason": "ruff_not_installed"}
    return {"passed": all(item.get("status") == "passed" for item in checks.values()), "checks": checks}


def _pytest_summary_counts(output: str) -> dict[str, int]:
    """Parse actual pytest summary outcomes; skips and xfails cannot satisfy a gate."""
    labels = ("passed", "failed", "errors", "skipped", "xfailed", "xpassed")
    return {label: sum(int(value) for value in re.findall(rf"\b(\d+)\s+{label}\b", output))
            for label in labels}


def _grade_controls(evidence_dir: Path | None) -> dict[str, dict[str, Any]]:
    from benchmark.pristine_grading import TASK_POLICIES

    gate_names = ("trusted_grader_scope", "six_references", "six_noops", "six_mutants",
                  "mutation_identity_controls", "runner_forgery", "unsupported_side_effects")
    try:
        controls = _load_control_tests()
    except BaseException as exc:
        return {name: {"status": "unavailable", "reason": f"control_data:{type(exc).__name__}"}
                for name in gate_names}
    retained = evidence_dir / "grade-controls" if evidence_dir is not None else None
    if retained is not None:
        retained.mkdir(parents=True, exist_ok=True)

    def run_case(label: str, task: str, implementation: dict[str, str]) -> dict[str, Any]:
        temporary = tempfile.TemporaryDirectory(prefix=f"safe-grade-{label}-")
        root = Path(temporary.name)
        workspace = root / "workspace"
        try:
            _write_grade_case(task, implementation, workspace)
            artifacts = root / "trusted-artifacts"
            artifacts.mkdir()
            result = run_scoped_grade(workspace, task, artifact_dir=artifacts)
            grade = result.get("grade")
            result["authenticated"] = isinstance(grade, dict) and grade.get("runtime_result_authenticated") is True
            if retained is not None:
                target = retained / f"{label}-{task}"
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(root, target)
                result["evidence_path"] = str(target)
            return result
        except BaseException as exc:
            return {"status": "infrastructure_failure", "reason": f"case_setup:{type(exc).__name__}"}
        finally:
            temporary.cleanup()

    references = [run_case("reference", task, controls.IMPLEMENTATIONS[task]) for task in TASK_POLICIES]
    noops = [run_case("noop", task, controls.NOOPS[task]) for task in TASK_POLICIES]
    mutants = [run_case("mutant", task, controls.MUTANTS[task]) for task in TASK_POLICIES]
    scopes_pass = all(item.get("status") == "completed" and isinstance(item.get("resource_evidence"), dict)
                      for item in references + noops + mutants)
    gates: dict[str, dict[str, Any]] = {}
    _set_gate(gates, "trusted_grader_scope", scopes_pass,
              "all_controls_ran_in_verified_trusted_grader_systemd_scopes",
              {"scope_count": len(references + noops + mutants)})
    refs_pass = all(item.get("status") == "completed" and item.get("authenticated")
                    and item.get("grade", {}).get("success") is True for item in references)
    noops_fail = all(item.get("status") == "completed" and item.get("authenticated")
                     and item.get("grade", {}).get("success") is False
                     and item.get("grade", {}).get("functional_pass") is False for item in noops)
    mutants_fail = all(item.get("status") == "completed" and item.get("authenticated")
                       and item.get("grade", {}).get("success") is False
                       and item.get("grade", {}).get("functional_pass") is False for item in mutants)
    _set_gate(gates, "six_references", refs_pass, "all_six_reference_sources_pass",
              {"results": [_compact_grade(item) for item in references]})
    _set_gate(gates, "six_noops", noops_fail, "all_six_noops_fail_functionally",
              {"results": [_compact_grade(item) for item in noops]})
    _set_gate(gates, "six_mutants", mutants_fail, "all_six_behavioral_mutants_fail",
              {"results": [_compact_grade(item) for item in mutants]})

    mutation_source = {"src/config.py": (
        "def resolve_config(defaults, file_config=None, cli_args=None):\n"
        "    if file_config is not None: defaults.update(file_config)\n"
        "    if cli_args is not None: defaults.update(cli_args)\n"
        "    return defaults\n")}
    metric_source = controls.IMPLEMENTATIONS["package_refactor"]["src/metrics.py"]
    distinct_service = (
        "from src.metrics import summarize_metrics\n"
        "def summarize_metrics(data):\n"
        "    if not data: return {'count': 0.0, 'mean': 0.0, 'min': 0.0, 'max': 0.0}\n"
        "    return {'count': float(len(data)), 'mean': float(sum(data) / len(data)), 'min': float(min(data)), 'max': float(max(data))}\n"
        "def generate_service_summary(records):\n"
        "    latencies = []\n"
        "    for record in records:\n"
        "        if 'latency' in record and record['latency'] is not None: latencies.append(record['latency'])\n"
        "    return summarize_metrics(latencies)\n")
    mutation = run_case("mutation", "config_precedence", mutation_source)
    identity = run_case("identity", "package_refactor",
                        {"src/metrics.py": metric_source, "src/service.py": distinct_service})
    mutation_fails = (mutation.get("status") == "completed" and mutation.get("authenticated")
                      and mutation.get("grade", {}).get("regression_pass") is False
                      and "test_does_not_mutate_inputs" in mutation.get("grade", {}).get("test_output", ""))
    identity_fails = (identity.get("status") == "completed" and identity.get("authenticated")
                      and identity.get("grade", {}).get("success") is False
                      and identity.get("grade", {}).get("regression_pass") is False)
    _set_gate(gates, "mutation_identity_controls", mutation_fails and identity_fails,
              "real_mutation_and_distinct_callable_identity_fail_original_controls",
              {"mutation": _compact_grade(mutation), "identity": _compact_grade(identity)})

    forged = {
        "src/calculator.py": (
            "import unittest\n"
            "unittest.TestResult.wasSuccessful = lambda self: True\n"
            "def add(a, b): return a + b\n"
            "def multiply(a, b): return a * b\n"
            "def divide(a, b): return 0.0\n")}
    attack = run_case("runner-forgery", "calculator_division", forged)
    rejected = (attack.get("status") == "completed" and attack.get("grade", {}).get("success") is False
                and attack.get("grade", {}).get("runtime_result_authenticated") is False
                and attack.get("grade", {}).get("evaluation_status") == "unsupported_syntax")
    _set_gate(gates, "runner_forgery", rejected,
              "original_runner_forgery_rejected_before_trusted_test_execution",
              {"result": _compact_grade(attack)})

    side_effect = {
        "src/calculator.py": (
            "from pathlib import Path\n"
            "Path('/tmp/safe-candidate-import-side-effect').write_text('executed')\n"
            "def add(a, b): return a + b\n"
            "def multiply(a, b): return a * b\n"
            "def divide(a, b): return a / b\n")}
    alternative = run_case("side-effect", "calculator_division", side_effect)
    side_effect_rejected = (alternative.get("status") == "completed"
                            and alternative.get("grade", {}).get("evaluation_status") == "unsupported_syntax"
                            and alternative.get("grade", {}).get("runtime_result_authenticated") is False)
    _set_gate(gates, "unsupported_side_effects", side_effect_rejected,
              "native_candidate_import_side_effect_rejected",
              {"result": _compact_grade(alternative)})
    return gates


def _runtime_binds(*, benchmark_root: Path | None = None,
                   opencode_binary: Path | None = None,
                   include_provider: bool = False) -> tuple[Any, ...]:
    from benchmark.linux_sandbox import RuntimeBind

    binds = []
    for source, targets in (
        (Path("/usr/bin"), ("/usr/bin", "/bin")),
        (Path("/usr/lib/python3.12"), ("/usr/lib/python3.12",)),
        (Path("/usr/lib/x86_64-linux-gnu"),
         ("/usr/lib/x86_64-linux-gnu", "/lib/x86_64-linux-gnu")),
    ):
        if not source.is_dir() or source.is_symlink():
            raise RuntimeError(f"required_runtime_directory_unavailable:{source}")
        resolved = source.resolve(strict=True)
        for target in targets:
            binds.append(RuntimeBind(resolved, target))
    loader_dir = Path("/lib64").resolve(strict=False)
    if loader_dir.is_dir():
        binds.extend((RuntimeBind(loader_dir.resolve(strict=True), "/lib64"),
                      RuntimeBind(loader_dir.resolve(strict=True), "/usr/lib64")))
    if include_provider:
        root = Path(benchmark_root) if benchmark_root is not None else Path(
            os.environ.get("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark"))
        provider_root = root / "cache/opencode-node-modules"
        package_json = root / "cache/package.json"
        package_lock = root / "cache/package-lock.json"
        if (not provider_root.is_dir() or provider_root.is_symlink()
                or not package_json.is_file() or package_json.is_symlink()
                or not package_lock.is_file() or package_lock.is_symlink()):
            raise RuntimeError("pinned_opencode_provider_cache_unavailable")
        binds.extend((
            RuntimeBind(provider_root.resolve(strict=True),
                        "/scratch/home/agent/.config/opencode/node_modules",
                        symlinks_within_source=True),
            RuntimeBind(package_json.resolve(strict=True),
                        "/scratch/home/agent/.config/opencode/package.json"),
            RuntimeBind(package_lock.resolve(strict=True),
                        "/scratch/home/agent/.config/opencode/package-lock.json"),
        ))
    if opencode_binary is not None:
        if not opencode_binary.is_file() or opencode_binary.is_symlink():
            raise RuntimeError("pinned_opencode_binary_unavailable")
        binds.append(RuntimeBind(opencode_binary.resolve(strict=True), "/opt/opencode"))
    return tuple(binds)


def _probe_limits(*, output_bytes: int = 32 * 1024, scratch_bytes: int = 8 * 1024**2) -> Any:
    from benchmark.linux_sandbox import ResourceLimits

    return ResourceLimits(memory_bytes=768 * 1024**2, swap_bytes=256 * 1024**2,
                          cpu_quota_percent=100, cpu_seconds=20, pids=32, wall_seconds=15,
                          output_bytes=output_bytes, workspace_bytes=16 * 1024**2,
                          workspace_files=500, workspace_file_bytes=4 * 1024**2,
                          scratch_bytes=scratch_bytes, file_bytes=16 * 1024**2,
                          open_files=128, export_file_bytes=2 * 1024**2,
                          export_total_bytes=8 * 1024**2, rootfs_bytes=32 * 1024**2,
                          startup_seconds=8, stop_grace_seconds=2)


def _run_sandbox_probe(workspace: Path, limits: Any, *, broker: Any = None,
                       exports: tuple[str, ...] = ("src/result.json",),
                       broker_transcript_dir: Path | None = None) -> Any:
    from benchmark.linux_sandbox import SandboxSpec, SandboxSupervisor

    spec = SandboxSpec(
        argv=("/usr/bin/python3", "-I", "/workspace/src/main.py"),
        workspace=workspace,
        workspace_exports=exports,
        runtime_ro=_runtime_binds(),
        env={},
        limits=limits,
        broker=broker,
        broker_transcript_dir=broker_transcript_dir,
    )
    return SandboxSupervisor().run(spec)


def _workspace_export_mode_probe() -> dict[str, Any]:
    if not sys.platform.startswith("linux"):
        return {"passed": False, "reason": "linux_namespace_controls_require_linux"}
    try:
        with tempfile.TemporaryDirectory(prefix="safe-readiness-export-mode-") as temporary:
            workspace = Path(temporary) / "workspace"
            (workspace / "src").mkdir(parents=True)
            (workspace / "src/keep.txt").write_text("before", encoding="utf-8")
            (workspace / "src/deleted.txt").write_text("remove", encoding="utf-8")
            (workspace / "src/main.py").write_text(
                "import os\nfrom pathlib import Path\n"
                "target=Path('src/keep.txt'); target.write_text('after')\n"
                "os.chmod(target, 0o640)\nPath('src/deleted.txt').unlink()\n",
                encoding="utf-8")
            result = _run_sandbox_probe(workspace, _probe_limits(),
                                       exports=("src/keep.txt", "src/deleted.txt"))
        outputs = dict(result.workspace_outputs)
        modes = dict(result.workspace_output_modes)
        audit = getattr(result, "workspace_audit", None)
        passed = (
            result.returncode == 0 and result.cleanup_verified and not result.infrastructure_error
            and outputs == {"src/keep.txt": b"after"}
            and modes == {"src/keep.txt": 0o640}
            and isinstance(audit, Mapping) and audit.get("complete") is True
            and audit.get("missing_exports") == ["src/deleted.txt"]
            and audit.get("unsafe_paths") == []
        )
        return {"passed": passed, "reason": "exact_export_bytes_mode_and_deletion_audited",
                "workspace_output_modes": modes, "workspace_outputs": sorted(outputs),
                "workspace_audit": audit, "infrastructure_error": result.infrastructure_error}
    except Exception as exc:
        return {"passed": False, "reason": f"workspace_export_mode_probe:{type(exc).__name__}"}


def _sandbox_control_gates(evidence_dir: Path) -> dict[str, dict[str, Any]]:
    from benchmark.linux_sandbox import BrokerPolicy

    gates: dict[str, dict[str, Any]] = {}
    gate_names = ("sandbox_sentinel", "host_file_oracle_observer_denial", "network_denial",
                  "fake_broker", "detached_descendant_cleanup", "output_resource_scratch_caps",
                  "workspace_export_modes", "observer_sampling")
    if not sys.platform.startswith("linux"):
        return {name: {"status": "unavailable", "reason": "linux_namespace_controls_require_linux"}
                for name in gate_names}
    monitor, monitor_start = _start_resource_monitor(
        evidence_dir, name="sandbox-controls-resources", run_id=f"readiness-{time.time_ns()}",
        phase_id="sandbox_controls", agent_id="readiness-sandbox")
    try:
        with tempfile.TemporaryDirectory(prefix="safe-readiness-sentinel-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            (workspace / "src").mkdir(parents=True)
            host_marker, observer_marker = root / "host-marker", root / "observer-events.jsonl"
            host_marker.write_text("host-only", encoding="ascii")
            observer_marker.write_text("observer-only", encoding="ascii")
            oracle_marker = REPO_ROOT / "benchmark/eval_suites/retry_policy/test_probe.py"
            paths = json.dumps({"host": str(host_marker), "oracle": str(oracle_marker),
                                "observer": str(observer_marker)})
            script = (
                "import json, socket\nfrom pathlib import Path\n"
                f"paths = json.loads({paths!r})\n"
                "result = {}\n"
                "for label, path in paths.items():\n"
                "    try: Path(path).read_bytes(); result[label + '_visible'] = True\n"
                "    except OSError: result[label + '_visible'] = False\n"
                "try: Path('/usr/share/safe-readiness-write-probe').write_text('bad'); result['runtime_read_only'] = False\n"
                "except OSError: result['runtime_read_only'] = True\n"
                "sock = socket.socket(); sock.settimeout(0.2)\n"
                "try: result['external_blocked'] = sock.connect_ex(('192.0.2.1', 443)) != 0\n"
                "except OSError: result['external_blocked'] = True\n"
                "finally: sock.close()\n"
                "Path('src/result.json').write_text(json.dumps(result))\n"
            )
            (workspace / "src/main.py").write_text(script, encoding="utf-8")
            result = _run_sandbox_probe(workspace, _probe_limits())
        observed = json.loads(result.workspace_outputs.get("src/result.json", b"{}").decode("utf-8"))
        namespace = result.namespace_evidence
        namespace_pass = (all(namespace.get("isolated", {}).values())
                          and namespace.get("uid_map_valid") is True)
        sentinel_pass = (result.returncode == 0 and result.cleanup_verified and not result.infrastructure_error
                         and namespace_pass and result.file_evidence.get("runtime_read_only") is True
                         and observed.get("runtime_read_only") is True)
        _set_gate(gates, "sandbox_sentinel", sentinel_pass, "namespace_mount_and_write_sentinel",
                  {"namespace_evidence": dict(namespace), "file_evidence": dict(result.file_evidence),
                   "infrastructure_error": result.infrastructure_error})
        denied = (observed.get("host_visible") is False and observed.get("oracle_visible") is False
                  and observed.get("observer_visible") is False)
        _set_gate(gates, "host_file_oracle_observer_denial", sentinel_pass and denied,
                  "host_marker_oracle_and_observer_paths_unavailable", {"observed": observed})
        net_ok = (result.network_evidence.get("external_egress_unavailable") is True
                  and observed.get("external_blocked") is True)
        _set_gate(gates, "network_denial", sentinel_pass and net_ok,
                  "private_network_namespace_blocks_external_egress",
                  {"network_evidence": dict(result.network_evidence), "observed": observed})
    except BaseException as exc:
        for name in ("sandbox_sentinel", "host_file_oracle_observer_denial", "network_denial"):
            _set_gate(gates, name, False, f"sandbox_sentinel:{type(exc).__name__}")

    try:
        server, thread, state = _fake_endpoint("readiness-model")
        try:
            limits = _probe_limits()
            with tempfile.TemporaryDirectory(prefix="safe-readiness-broker-") as temporary:
                workspace = Path(temporary) / "workspace"
                (workspace / "src").mkdir(parents=True)
                script = (
                    "import json, urllib.request\n"
                    "models = json.load(urllib.request.urlopen('http://127.0.0.1:18888/v1/models', timeout=2))\n"
                    "body = json.dumps({'model':'readiness-model','messages':[{'role':'user','content':'ping'}], 'max_tokens':16, 'temperature':0}).encode()\n"
                    "request = urllib.request.Request('http://127.0.0.1:18888/v1/chat/completions', data=body, headers={'Content-Type':'application/json'})\n"
                    "reply = json.load(urllib.request.urlopen(request, timeout=2))\n"
                    "open('src/result.json','w').write(json.dumps({'model':models['data'][0]['id'],'reply':reply['choices'][0]['message']['content']}))\n"
                )
                (workspace / "src/main.py").write_text(script, encoding="utf-8")
                broker = BrokerPolicy(upstream_port=server.server_address[1],
                                      model_allowlist=("readiness-model",), output_token_cap=16,
                                      frozen_generation={"temperature": 0, "seed": 1234, "max_tokens": 16})
                result = _run_sandbox_probe(workspace, limits, broker=broker)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        body = json.loads(result.workspace_outputs.get("src/result.json", b"{}").decode("utf-8"))
        allowed = body.get("model") == "readiness-model" and body.get("reply") == "fake endpoint roundtrip complete"
        denied = result.network_evidence.get("external_egress_unavailable") is True
        _set_gate(gates, "fake_broker", result.returncode == 0 and not result.infrastructure_error
                  and allowed and denied and state["models_requests"] == 1
                  and any(event.outcome == "allowed" for event in result.broker_events),
                  "fake_endpoint_reached_only_through_fixed_broker",
                  {"broker_events": [event.outcome for event in result.broker_events],
                   "network_evidence": dict(result.network_evidence)})
    except BaseException as exc:
        _set_gate(gates, "fake_broker", False, f"fake_broker_probe:{type(exc).__name__}")

    try:
        limits = _probe_limits(output_bytes=1024, scratch_bytes=2 * 1024**2)
        with tempfile.TemporaryDirectory(prefix="safe-readiness-caps-") as temporary:
            workspace = Path(temporary) / "workspace"
            (workspace / "src").mkdir(parents=True)
            script = (
                "import json, subprocess, sys\nfrom pathlib import Path\n"
                "try: Path('/scratch/fill').write_bytes(b'x' * (4 * 1024 * 1024)); scratch_full = False\n"
                "except OSError: scratch_full = True\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)\n"
                "Path('src/result.json').write_text(json.dumps({'scratch_full':scratch_full,'child_pid':child.pid}))\n"
                "print('x' * (128 * 1024))\n"
            )
            (workspace / "src/main.py").write_text(script, encoding="utf-8")
            result = _run_sandbox_probe(workspace, limits)
        resources = dict(result.resource_evidence)
        output_ok = result.output_limited and len(result.output) <= limits.output_bytes
        scratch_ok = result.file_evidence.get("scratch_size_bytes") == limits.scratch_bytes
        memory_ok = resources.get("memory.max") == str(limits.memory_bytes)
        pids_ok = resources.get("pids.max") == str(limits.pids)
        cleanup_ok = result.cleanup_verified and resources.get("descendants_clean") is True
        _set_gate(gates, "detached_descendant_cleanup", cleanup_ok,
                  "namespace_supervisor_removed_detached_child",
                  {"cleanup_verified": result.cleanup_verified, "resource_evidence": resources})
        _set_gate(gates, "output_resource_scratch_caps", output_ok and scratch_ok and memory_ok and pids_ok,
                  "output_scratch_and_actual_cgroup_caps_verified",
                  {"output_limited": result.output_limited, "output_bytes": len(result.output),
                   "scratch_cap": scratch_ok, "memory_cap": memory_ok, "pids_cap": pids_ok,
                   "resource_evidence": resources})
    except BaseException as exc:
        _set_gate(gates, "detached_descendant_cleanup", False, f"resource_probe:{type(exc).__name__}")
        _set_gate(gates, "output_resource_scratch_caps", False, f"resource_probe:{type(exc).__name__}")
    export_modes = _workspace_export_mode_probe()
    _set_gate(gates, "workspace_export_modes", export_modes.get("passed") is True,
              str(export_modes.get("reason", "workspace_export_mode_probe")), export_modes)
    monitor_evidence = _stop_resource_monitor(monitor, monitor_start)
    _set_gate(gates, "observer_sampling",
              monitor_evidence.get("status") == "measured"
              and monitor_evidence.get("sample_count", 0) >= 1
              and monitor_evidence.get("cleanup_verified") is True,
              "host_resource_monitor_sampled_and_stopped", monitor_evidence)
    _set_gate(gates, "fake_opencode_roundtrip", False, "native_opencode_probe_not_run")
    return gates


def _fake_opencode_probe(evidence_dir: Path,
                         benchmark_root: Path | None = None) -> dict[str, Any]:
    """Run pinned OpenCode with real bash/edit tools against a local fake broker."""
    from benchmark.linux_sandbox import BrokerPolicy, RuntimeBind, SandboxSpec, SandboxSupervisor

    if not sys.platform.startswith("linux"):
        return {"passed": False, "reason": "linux_namespace_controls_require_linux"}
    from benchmark.model_quality_paired import MODELS, build_profile
    from benchmark.run_observer import RunObserver

    install_root = Path(benchmark_root) if benchmark_root is not None else Path(
        os.environ.get("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark"))
    binary = install_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    if binary.is_symlink() or not binary.is_file():
        return {"passed": False, "reason": "pinned_opencode_binary_unavailable"}
    model_key = "qwen3.5-4b"
    model = MODELS[model_key]
    server, thread, state = _fake_endpoint(model["alias"])
    run_dir = evidence_dir / f"fake-opencode-{time.time_ns()}"
    run_dir.mkdir(mode=0o700)
    transcript_dir = run_dir / "broker-transcript"
    transcript_dir.mkdir(mode=0o700)
    observer = None
    monitor = None
    monitor_start: dict[str, Any] = {"status": "unavailable", "reason": "monitor_not_started"}
    monitor_evidence = monitor_start
    try:
        with tempfile.TemporaryDirectory(prefix="safe-opencode-fake-") as temporary:
            workspace = Path(temporary) / "workspace"
            (workspace / "src").mkdir(parents=True)
            (workspace / "src/probe.txt").write_text("replace-target", encoding="utf-8")
            config = build_profile(model_key)
            config["provider"]["local"]["options"]["baseURL"] = "http://127.0.0.1:18888/v1"
            config_path = run_dir / "opencode.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            prompt = (
                "For this no-model readiness control, use both available tools. First create src/bash-probe.txt "
                "containing fake-bash-ok with the bash tool. Then edit src/probe.txt, replacing replace-target "
                "with fake-edit-ok using the edit tool. Report when both operations are complete."
            )
            prompt_path = run_dir / "prompt.txt"
            prompt_path.write_text(prompt + "\n", encoding="utf-8")
            observer = RunObserver(run_dir, {
                "experiment": "readiness-fake-opencode",
                "hash_allowlist": [
                    {"category": "profile", "path": "opencode.json", "file": config_path},
                    {"category": "prompt", "path": "prompt.txt", "file": prompt_path},
                ],
                "snapshot_hash_allowlist": ["src/probe.txt", "src/bash-probe.txt"],
            })
            phase = observer.start_phase("initial_agent", agent_id="opencode", source="agent_process")
            observer.snapshot("before_initial_agent", workspace, agent_id="opencode", source="observer")
            monitor, monitor_start = _start_resource_monitor(
                run_dir, name="resource-samples", run_id=observer.run_id,
                phase_id="initial_agent", agent_id="opencode")
            monitor_evidence = monitor_start
            # Exercise the exact sandbox resource policy used by campaign agents.
            # Only the upstream model response is fake in this compatibility gate.
            from benchmark.safe_campaign import _agent_limits, _temporary_profile_copy

            limits = _agent_limits()
            runtime = list(_runtime_binds(benchmark_root=install_root, opencode_binary=binary,
                                          include_provider=True))
            broker = BrokerPolicy(
                upstream_port=server.server_address[1], model_allowlist=(model["alias"],),
                output_token_cap=1024,
                frozen_generation={"temperature": 0, "seed": 1234, "max_tokens": 1024},
                max_requests=8,
            )
            with _temporary_profile_copy(config_path) as profile_copy:
                # Durable evidence may live under /home, which is not an approved
                # runtime bind source. Use the canonical private temporary copy.
                spec = SandboxSpec(
                    argv=("/opt/opencode", "run", "--format", "json", "--pure", "--agent", "build",
                          "--model", f"local/{model['alias']}", "--dir", "/workspace", prompt),
                    workspace=workspace,
                    workspace_exports=("src/probe.txt", "src/bash-probe.txt"),
                    runtime_ro=tuple(runtime) + (
                        RuntimeBind(profile_copy, "/opt/opencode.json"),
                    ),
                    env={"OPENCODE_CONFIG": "/opt/opencode.json", "OPENCODE_DISABLE_AUTOUPDATE": "1"},
                    limits=limits, broker=broker, broker_transcript_dir=transcript_dir,
                )
                result = SandboxSupervisor().run(spec)
            # Persist supervisor evidence before inspecting optional side artifacts,
            # so a missing transcript cannot hide the actual sandbox failure.
            (run_dir / "stdout.jsonl").write_bytes(result.output)
            _json_write(run_dir / "sandbox-result.json", {
                "returncode": result.returncode, "timed_out": result.timed_out,
                "cleanup_verified": result.cleanup_verified, "output_limited": result.output_limited,
                "infrastructure_error": result.infrastructure_error,
                "namespace_evidence": dict(result.namespace_evidence),
                "file_evidence": dict(result.file_evidence),
                "network_evidence": dict(result.network_evidence),
                "resource_evidence": dict(result.resource_evidence),
                "broker_transcript_evidence": dict(result.broker_transcript_evidence),
                "workspace_audit": dict(result.workspace_audit),
                "workspace_output_modes": dict(result.workspace_output_modes),
            })
            monitor_evidence = _stop_resource_monitor(monitor, monitor_start)
            monitor = None
            lines = [line for line in result.output.decode("utf-8", errors="replace").splitlines()
                     if line.strip()]
            events: list[dict[str, Any]] = []
            correlated: list[dict[str, Any]] = []
            for index, line in enumerate(lines, start=1):
                try:
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        item = {"type": "unparsed_output", "value": str(item)[:4000]}
                except json.JSONDecodeError:
                    item = {"type": "unparsed_output", "text": line[:4000]}
                events.append(item)
                part = item.get("part") if isinstance(item.get("part"), dict) else {}
                event_id = observer.record(
                    "native_event", phase, agent_id="opencode", source="agent_process",
                    details={"event_name": str(item.get("type", "unknown"))[:80],
                             "tool_name": str(part.get("tool", ""))[:80] or None,
                             "event_index": index,
                             "payload_sha256": hashlib.sha256(line.encode("utf-8")).hexdigest()},
                )
                correlated.append({"observer_event_id": event_id, "event_index": index, "event": item})
            _jsonl_path = run_dir / "native-events-correlated.jsonl"
            _jsonl_path.write_text("".join(json.dumps(item, sort_keys=True, ensure_ascii=False) + "\n"
                                               for item in correlated), encoding="utf-8")
            transcript_path = run_dir / "broker-transcript" / "transcript.jsonl"
            transcript_missing = not transcript_path.is_file()
            transcript_data = (transcript_path.read_bytes()[:32 * 1024 * 1024 + 1]
                               if not transcript_missing else b"")
            transcript_bounded = len(transcript_data) <= 32 * 1024 * 1024
            transcript_records = [json.loads(line) for line in transcript_data.splitlines() if line]
            transcript_digest = hashlib.sha256(transcript_data).hexdigest()
            observer.snapshot("after_initial_agent", workspace, agent_id="opencode", source="observer")
            workspace_audit = dict(result.workspace_audit)
            output_modes = dict(result.workspace_output_modes)
            output_view = {path: bytes(content) for path, content in result.workspace_outputs.items()}
            output_view = {path: content.decode("utf-8", errors="replace").strip()
                           for path, content in output_view.items()}
            tool_events = [event for event in events if event.get("type") == "tool_use"]
            completed = [event for event in tool_events
                         if event.get("part", {}).get("state", {}).get("status") == "completed"]
            completed_names = {str(event.get("part", {}).get("tool", "")).lower() for event in completed}
            request_count = state["chat_requests"]
            transcript_status = (
                "measured" if result.broker_transcript_evidence.get("complete") is True else "unavailable"
            )
            transcript_ok = (
                transcript_bounded and transcript_status == "measured"
                and len(transcript_records) >= request_count
                and not transcript_missing
                and all(isinstance(item, dict) and item.get("path") in {
                    "/v1/models", "/v1/chat/completions"} for item in transcript_records)
            )
            workspace_ok = (
                isinstance(workspace_audit, dict) and workspace_audit.get("complete") is True
                and not workspace_audit.get("protected_changed")
                and not workspace_audit.get("protected_missing")
                and not workspace_audit.get("unauthorized_extra_paths")
                and not workspace_audit.get("missing_exports")
                and not workspace_audit.get("unsafe_paths")
            )
            usage_evidence = _opencode_usage_evidence(events)
            passed = (
                result.returncode == 0 and result.cleanup_verified and not result.infrastructure_error
                and not result.timed_out and not result.output_limited
                and request_count >= 2 and {name.lower() for name in state["tool_calls"]} == {"bash", "edit"}
                and {"bash", "edit"} <= completed_names
                and output_view.get("src/bash-probe.txt") == "fake-bash-ok"
                and output_view.get("src/probe.txt") == "fake-edit-ok"
                and set(output_modes) == set(output_view) and workspace_ok and transcript_ok
                and monitor_evidence.get("status") == "measured"
                and monitor_evidence.get("cleanup_verified") is True
            )
            observer.end_phase(phase, "completed" if result.returncode == 0 else "failed",
                               agent_id="opencode", source="agent_process",
                               details={"exit_code": result.returncode, "timed_out": result.timed_out,
                                        "evidence_status": "measured" if result.cleanup_verified else "unavailable"})
            observer.record("sampler_end", agent_id="opencode", source="sampler",
                            details={"status": monitor_evidence.get("status", "unavailable"),
                                     "sample_count": monitor_evidence.get("sample_count", 0)})
            observer.finalize("pass" if passed else "fail",
                              "complete" if result.cleanup_verified else "incomplete")
            return {
                "passed": passed, "reason": "native_opencode_fake_endpoint_tool_call_and_edit_roundtrip",
                "returncode": result.returncode, "infrastructure_error": result.infrastructure_error,
                "cleanup_verified": result.cleanup_verified, "timed_out": result.timed_out,
                "output_limited": result.output_limited, "endpoint_chat_requests": request_count,
                "observed_tool_schemas": state["tool_calls"], "completed_tool_events": sorted(completed_names),
                "workspace_outputs": output_view, "workspace_output_modes": output_modes,
                "workspace_audit": workspace_audit, "broker_outcomes": [event.outcome for event in result.broker_events],
                "broker_transcript_status": transcript_status,
                "broker_transcript_missing": transcript_missing,
                "broker_transcript_evidence": dict(result.broker_transcript_evidence),
                "broker_transcript_sha256": transcript_digest,
                "broker_transcript_records": len(transcript_records),
                "native_event_authority": "untrusted_process_stream",
                "workflow_evidence_not_execution_attestation": True,
                "resource_sampling": monitor_evidence, "usage_evidence": usage_evidence,
                "native_stdout_path": str(run_dir / "stdout.jsonl"),
                "native_stdout_sha256": hashlib.sha256(result.output).hexdigest(),
                "correlated_events_path": str(_jsonl_path),
                "observer_events_path": str(run_dir / "observer-events.jsonl"),
                "run_id": observer.run_id,
            }
    except Exception as exc:
        monitor_evidence = (_stop_resource_monitor(monitor, monitor_start)
                            if monitor is not None else monitor_evidence)
        if observer is not None:
            try:
                observer.finalize("error", "incomplete", error=type(exc).__name__)
            except Exception:
                pass
        return {"passed": False, "reason": f"fake_opencode:{type(exc).__name__}",
                "error": str(exc)[:500], "traceback": traceback.format_exc()[-4000:],
                "resource_sampling": monitor_evidence, "run_dir": str(run_dir)}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def run_current_readiness(*, evidence_dir: Path | None = None,
                          benchmark_root: Path | None = None) -> dict[str, Any]:
    """Re-run every no-model control and bind the verdict to current exact inputs."""
    started = time.monotonic()
    evidence_dir = _prepare_evidence_root(evidence_dir, benchmark_root=benchmark_root)
    snapshot = input_hash_manifest(benchmark_root=benchmark_root)
    gates: dict[str, dict[str, Any]] = {}
    _set_gate(gates, "input_hashes", snapshot["complete"], "all_current_inputs_hashed",
              {"input_digest": snapshot["digest"], "input_count": len(snapshot["records"]),
               "unavailable": [item["path"] for item in snapshot["records"] if item["status"] != "measured"]})
    gates.update(_grade_controls(evidence_dir))
    gates.update(_sandbox_control_gates(evidence_dir))
    fake = _fake_opencode_probe(evidence_dir, benchmark_root)
    _set_gate(gates, "fake_opencode_roundtrip", fake.get("passed") is True,
              str(fake.get("reason", "native_opencode_fake_endpoint_roundtrip")), fake)
    trial = _canonical_trial_control(evidence_dir, benchmark_root)
    _set_gate(gates, "canonical_trial_end_to_end", trial.get("passed") is True,
              str(trial.get("reason", "canonical_fake_provider_task_roundtrip")), trial)
    model = _model_bundle_audit(benchmark_root)
    _set_gate(gates, "model_bundle_audit", model.get("passed") is True,
              str(model.get("reason", "read_only_bundle_audit")), {"evidence": model.get("evidence")})
    checks = _workspace_checks()
    _set_gate(gates, "workspace_checks", checks.get("passed") is True,
              "focused_unit_tests_and_ruff", {"checks": checks.get("checks")})
    for name in REQUIRED_GATES:
        gates.setdefault(name, {"status": "unavailable", "reason": "gate_not_run"})
    ready = snapshot["complete"] and all(gates[name]["status"] == "passed" for name in REQUIRED_GATES)
    report = {
        "schema_version": 1,
        "verdict": "READY" if ready else "BLOCKED",
        "ready": ready,
        "input_digest": snapshot["digest"],
        "inputs": snapshot["records"],
        "grader_protocol_version": "restricted-python-workspace-v2",
        "candidate_language_contract": "restricted-python-workspace-v2",
        "native_event_authority": "untrusted_process_stream",
        "workflow_evidence_not_execution_attestation": True,
        "evidence_dir": str(evidence_dir),
        "models_loaded": False,
        "inference_performed": False,
        "gates": gates,
        "failed_gates": [name for name in REQUIRED_GATES if gates[name]["status"] != "passed"],
        "duration_seconds": round(time.monotonic() - started, 3),
        "limitations": [
            "The six regression tasks do not establish CPython generality, unseen training data, private holdout status, OS isolation, or security proof.",
            "Trusted grading inspects candidate-authored test files as workflow data; they may run only inside the native agent sandbox.",
            "Native OpenCode JSONL is an untrusted process stream and workflow evidence, not an attestation that a specific process executed each action.",
            "Broker transcripts attest to the bytes and timings captured at the trusted adapter boundary, not to an individual same-UID writer identity.",
        ],
    }
    report = _json_safe(report)
    fresh = input_hash_manifest(benchmark_root=benchmark_root)
    report["self_validation"] = validate_readiness_report(report, current_input_digest=fresh["digest"])
    report["ready"] = report["self_validation"]["ready"]
    if not report["ready"]:
        report["verdict"] = "BLOCKED"
    _json_write(evidence_dir / "readiness-report.json", report)
    return report


def _canonical_trial_control(evidence_dir: Path, benchmark_root: Path | None) -> dict[str, Any]:
    """Run the real canonical task path against a local fake model endpoint."""
    try:
        from benchmark.campaign_e2e_control import run_control

        return run_control(evidence_dir, benchmark_root=benchmark_root)
    except Exception as exc:
        return {"passed": False, "reason": f"canonical_trial:{type(exc).__name__}",
                "error": str(exc)[:500], "traceback": traceback.format_exc()[-4000:]}


def _opencode_usage_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate counters printed by OpenCode from token usage returned by the backend."""
    model_calls = tool_calls = tool_failures = compactions = 0
    token_values: dict[str, list[int]] = {
        "input_tokens": [], "output_tokens": [], "reasoning_tokens": [],
        "cache_read_tokens": [], "cache_write_tokens": [],
    }
    for event in events:
        kind = event.get("type")
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        if kind == "step_finish":
            model_calls += 1
            tokens = part.get("tokens") if isinstance(part.get("tokens"), dict) else {}
            for label, source in (("input_tokens", "input"), ("output_tokens", "output"),
                                  ("reasoning_tokens", "reasoning")):
                value = tokens.get(source)
                if type(value) is int and value >= 0:
                    token_values[label].append(value)
            cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
            for label, source in (("cache_read_tokens", "read"), ("cache_write_tokens", "write")):
                value = cache.get(source)
                if type(value) is int and value >= 0:
                    token_values[label].append(value)
        elif kind == "tool_use":
            tool_calls += 1
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            if part.get("tool") == "invalid" or state.get("status") in {"error", "failed"}:
                tool_failures += 1
        elif kind in {"compaction", "compacted"}:
            compactions += 1
    has_token_fields = any(token_values.values())
    reported_tokens = {
        label: sum(values) if values else None for label, values in token_values.items()
    }
    return {
        "harness_reported_counts": {
            "source": "native_opencode_jsonl", "model_calls": model_calls,
            "tool_calls": tool_calls, "tool_failures": tool_failures,
            "compactions": compactions,
            "token_counts_status": "reported" if has_token_fields else "unavailable",
            "token_counts": reported_tokens,
        },
        "backend_token_usage": {
            "status": "unavailable", "source": "no verified backend usage parser",
            "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
        },
    }
