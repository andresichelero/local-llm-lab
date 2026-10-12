#!/usr/bin/env python3
"""Frozen, paired MTP off/on probe for the pinned local Qwen3.5-4B GGUF.

Dry-run is the default. Inference requires an explicit ``--execute`` and a
WSL ext4 SSD installation of the pinned model and llama.cpp runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import itertools
import json
import math
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.opencode_controlled_probe import (  # noqa: E402 - local CLI import after path setup
    _assert_free_resources,
    _assert_server_bundle,
    _is_ext4,
    require_runtime_revision,
)

EXPERIMENT = "mtp-paired-probe-r2-20261012"
MODEL_RELATIVE_PATH = Path("models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf")
MODEL_ID = "local"
MODEL_SHA256 = "13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983"
RUNTIME_REVISION = "d81235049384534c167caea52b85a694f6103d14"
RUNTIME_VERSION_PREFIX = "d81235049"
RUNTIME_SERVER_SHA256 = "83005935917f6e3ec98319e277bd4c4c7e3da3e4dc1876bcc451c32d8d4d37d1"
CONTEXT_TOKENS = 16_384
MAX_NEW_TOKENS = 512
TEMPERATURE = 0
SEED = 1234
PORT = 18_763
ROUND_LIMIT_SECONDS = 30 * 60
SWAP_GROWTH_LIMIT_BYTES = 512 * 1024**2
SWAP_GROWTH_SAMPLES = 10

# These user-message strings are UTF-8 frozen payload bytes; changing either
# text deliberately changes the prompt digest in protocol.json.
PROMPTS = {
    "division_repair": (
        "Repair the Python function so it divides a by b and raises ValueError "
        "with the exact message 'division by zero' when b is zero. Return only "
        "the corrected function.\n\n"
        "```python\n"
        "def divide(a, b):\n"
        "    return a + b\n"
        "```"
    ),
    "text_summary": (
        "Summarize the passage below in three concise sentences. Each sentence "
        "must add a distinct point; do not repeat an idea.\n\n"
        "Passage: A neighborhood library extended its evening hours after a "
        "survey showed that many residents could not visit before work ended. "
        "During the first month, evening visits increased, and the library "
        "hosted two volunteer-led reading groups. Staff also noted that the "
        "later schedule required a second closing shift, so the library will "
        "review attendance and staffing costs before making the change permanent."
    ),
}

COUNTER_NAMES = {
    "drafted_tokens": "llamacpp:spec_decode_num_draft_tokens_total",
    "accepted_tokens": "llamacpp:spec_decode_num_accepted_tokens_total",
    "verification_steps": "llamacpp:spec_decode_num_drafts_total",
}
OOM_MARKERS = (
    "out of memory", "failed to allocate", "allocation failed", "cuda malloc failed",
    "std::bad_alloc", "bad_alloc", "cannot allocate memory", "not enough memory",
    "oom-kill", "oom killer",
)


class RoundDeadline(Exception):
    """Raised by the one run-wide alarm so all owned children can be reaped."""


class RunStop(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def measured_schedule() -> list[dict[str, Any]]:
    """Return six fresh-server arm blocks, four warmups, and twelve rows."""
    rows: list[dict[str, Any]] = []
    warmed: set[tuple[str, str]] = set()
    for pair, arm_order in ((1, ("off", "on")), (2, ("on", "off")), (3, ("off", "on"))):
        for arm in arm_order:
            session_id = f"pair-{pair}-{arm}"
            for prompt_id in PROMPTS:
                if (arm, prompt_id) not in warmed:
                    rows.append({"stage": "warmup", "prompt_id": prompt_id, "arm": arm,
                                 "pair": pair, "repeat": None, "session_id": session_id})
                    warmed.add((arm, prompt_id))
                rows.append({"stage": "measurement", "prompt_id": prompt_id,
                             "arm": arm, "pair": pair, "repeat": pair,
                             "session_id": session_id})
    return rows


def request_payload(prompt: str, model: str = MODEL_ID) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "seed": SEED,
        "max_tokens": MAX_NEW_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def parse_sse_events(lines: Iterable[str | bytes]) -> dict[str, Any]:
    """Parse the pinned server's OpenAI-compatible data-line stream."""
    content: list[str] = []
    timings: dict[str, Any] = {}
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    saw_done = False
    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            saw_done = True
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError as error:
            raise ValueError(f"Malformed SSE JSON event: {data[:240]}") from error
        usage = event.get("usage")
        if isinstance(usage, dict):
            value = usage.get("prompt_tokens")
            if isinstance(value, int):
                prompt_tokens = value
            value = usage.get("completion_tokens")
            if isinstance(value, int):
                completion_tokens = value
        if isinstance(event.get("timings"), dict):
            timings.update(event["timings"])
        for choice in event.get("choices") or []:
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if isinstance(text, str):
                content.append(text)
            if isinstance(choice.get("finish_reason"), str):
                finish_reason = choice["finish_reason"]
    return {"content": "".join(content), "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "timings": timings,
            "finish_reason": finish_reason, "saw_done": saw_done}


_PROMETHEUS_ROW = re.compile(
    r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{[^}]*\})?\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$"
)


def parse_prometheus_counters(text: str) -> dict[str, float]:
    counters: dict[str, float] = {}
    for line in text.splitlines():
        match = _PROMETHEUS_ROW.match(line.strip())
        if not match:
            continue
        value = float(match.group(2))
        if math.isfinite(value):
            counters[match.group(1)] = value
    return counters


def counter_delta(before: dict[str, float], after: dict[str, float], name: str) -> dict[str, Any]:
    start, end = before.get(name), after.get(name)
    available = start is not None and end is not None and end >= start
    return {"available": available, "before": start, "after": end,
            "delta": end - start if available else None}


def classify_cap_condition(finish_reason: str | None,
                           completion_tokens: int | None) -> str:
    if finish_reason == "length" or completion_tokens == MAX_NEW_TOKENS:
        return "cap"
    if finish_reason == "stop":
        return "stop"
    return finish_reason or "unknown"


def swap_growth_breach(samples: list[dict[str, Any]], baseline_bytes: int) -> bool:
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


def stop_reason(*, now: float, deadline: float, server_healthy: bool,
                server_log: str, swap_samples: list[dict[str, Any]],
                swap_baseline_bytes: int) -> str | None:
    if now >= deadline:
        return "round_deadline"
    if any(marker in server_log.lower() for marker in OOM_MARKERS) or not server_healthy:
        return "server_lost_or_oom"
    if swap_growth_breach(swap_samples, swap_baseline_bytes):
        return "swap_growth_limit"
    return None


def summarize_denominators(records: list[dict[str, Any]]) -> dict[str, Any]:
    measurements = [row for row in records if row.get("stage") == "measurement"]
    attempted = [row for row in measurements if row.get("attempted")]
    completed = [row for row in attempted if row.get("completed")]
    groups: dict[str, dict[str, int]] = {}
    for row in attempted:
        key = f"{row.get('arm')}/{row.get('prompt_id')}"
        group = groups.setdefault(key, {"attempted": 0, "completed": 0})
        group["attempted"] += 1
        group["completed"] += int(bool(row.get("completed")))
    return {"planned_measurements": len(measurements),
            "attempted_measurements": len(attempted),
            "completed_measurements": len(completed),
            "by_arm_prompt": dict(sorted(groups.items()))}


def summarize_speculative_activity(records: list[dict[str, Any]]) -> dict[str, Any]:
    measured_on = [row for row in records if row.get("stage") == "measurement"
                   and row.get("arm") == "on" and row.get("attempted")]
    totals: dict[str, int] = {}
    available_rows: dict[str, int] = {}
    for name in ("drafted_tokens", "accepted_tokens"):
        values = []
        for row in measured_on:
            delta = ((row.get("speculative_counters") or {}).get(name) or {})
            if delta.get("available") and isinstance(delta.get("delta"), (int, float)):
                values.append(int(delta["delta"]))
        totals[name] = sum(values)
        available_rows[name] = len(values)
    active = totals["drafted_tokens"] > 0 and totals["accepted_tokens"] > 0
    return {
        "status": "active_counters_observed" if active else "inactive_or_incomplete",
        "on_measurements_attempted": len(measured_on),
        "counter_rows_available": available_rows,
        "counter_totals": totals,
        "activation_confirmed": active,
        "speedup_claim_allowed": False,
        "coding_behavior_gate": "pending",
    }


def evaluate_quality_gates(records: list[dict[str, Any]]) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    for mode in ("structured_json", "tool_round_trip"):
        matches = [row for row in records if row.get("mode") == mode]
        if not matches:
            checks[mode] = {"passed": False, "reason": "missing_record", "record": None}
        elif len(matches) != 1:
            checks[mode] = {"passed": False, "reason": "duplicate_records", "record": matches}
        elif matches[0].get("success") is not True:
            checks[mode] = {"passed": False, "reason": "reported_failure", "record": matches[0]}
        else:
            checks[mode] = {"passed": True, "reason": None, "record": matches[0]}
    return {"passed": all(check["passed"] for check in checks.values()), "checks": checks}


def server_command(server: str | Path, model: str | Path, port: int, arm: str) -> list[str]:
    if arm not in {"off", "on"}:
        raise ValueError(f"Unknown MTP arm: {arm}")
    command = [
        str(server), "--offline", "--model", str(model), "--host", "127.0.0.1",
        "--port", str(port), "--ctx-size", str(CONTEXT_TOKENS),
        "--n-predict", str(MAX_NEW_TOKENS), "--gpu-layers", "99",
        "--flash-attn", "on", "--cache-type-k", "q4_0", "--cache-type-v", "q4_0",
        "--no-cache-prompt", "--parallel", "1", "--spec-type",
        "draft-mtp" if arm == "on" else "none",
        "--spec-draft-n-max", "3", "--spec-draft-type-k", "f16",
        "--spec-draft-type-v", "f16", "--reasoning", "off", "--temp", "0",
        "--metrics", "--slots", "--log-timestamps", "--verbosity", "4",
    ]
    return command


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_record(root: Path, records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    records.append(record)
    with (root / "records.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")
        output.flush()
    _write_json(root / "summary.json", summarize_denominators(records))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _swap_baseline_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("SwapTotal:"):
            total = int(line.split()[1]) * 1024
        elif line.startswith("SwapFree:"):
            free = int(line.split()[1]) * 1024
    return total - free


def _gpu_compute_apps() -> str:
    command = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
    result = subprocess.run([command, "--query-compute-apps=pid,used_memory",
                             "--format=csv,noheader,nounits"], capture_output=True,
                            text=True, timeout=5, check=True)
    return "\n".join(line.strip() for line in result.stdout.splitlines() if line.strip())


def _assert_gpu_free() -> None:
    apps = _gpu_compute_apps()
    if apps:
        raise RuntimeError(f"GPU compute application already present; refusing shared-GPU run: {apps}")


def _runtime_environment(root: Path, runtime: Path) -> dict[str, str]:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
            "LD_LIBRARY_PATH": str(runtime), "HOME": str(root), "TMPDIR": "/tmp",
            "LANG": "C.UTF-8", "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
            "GIT_TERMINAL_PROMPT": "0"}


def _fetch(url: str, *, timeout: float) -> tuple[int, bytes]:
    if not url.startswith("http://127.0.0.1:"):
        raise ValueError("Probe HTTP requests must stay on the loopback interface")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return response.status, response.read()


def _get_metrics(url: str, timeout: float = 5) -> dict[str, float]:
    try:
        status, body = _fetch(url.rstrip("/") + "/metrics", timeout=timeout)
        if status != 200:
            return {}
        return parse_prometheus_counters(body.decode("utf-8", errors="replace"))
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return {}


def _server_healthy(url: str) -> bool:
    try:
        status, _ = _fetch(url.rstrip("/") + "/health", timeout=2)
        return status == 200
    except (OSError, TimeoutError, urllib.error.URLError, ValueError):
        return False


def _sse_first_text(raw: bytes) -> bool:
    line = raw.decode("utf-8", errors="replace").strip()
    if not line.startswith("data:") or line[5:].strip() == "[DONE]":
        return False
    try:
        event = json.loads(line[5:].strip())
    except json.JSONDecodeError:
        return False
    return any(isinstance((choice.get("delta") or {}).get("content"), str)
               and bool((choice.get("delta") or {}).get("content"))
               for choice in event.get("choices") or [])


def request_completion(url: str, payload: dict[str, Any], *, timeout: float,
                       on_event: Any = None) -> dict[str, Any]:
    parsed_url = urllib.parse.urlsplit(url)
    if (parsed_url.scheme != "http" or parsed_url.hostname != "127.0.0.1"
            or parsed_url.port is None or parsed_url.query or parsed_url.fragment):
        raise ValueError("Chat completion requests must use an explicit 127.0.0.1 HTTP endpoint")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    started = time.monotonic()
    first_text_at: float | None = None
    lines: list[bytes] = []
    path = f"{parsed_url.path.rstrip('/')}/v1/chat/completions"
    connection = http.client.HTTPConnection(parsed_url.hostname, parsed_url.port, timeout=timeout)
    connection.request("POST", path, body=data,
                       headers={"Content-Type": "application/json"})
    messages: queue.Queue[tuple[str, Any]] = queue.Queue()

    def read_response() -> None:
        response: http.client.HTTPResponse | None = None
        try:
            response = connection.getresponse()
            messages.put(("opened", response.status))
            if response.status >= 400:
                messages.put(("http_error", (response.status, response.read(4096))))
                return
            for raw in response:
                messages.put(("line", raw))
        except Exception as error:
            messages.put(("error", error))
        finally:
            if response is not None:
                response.close()
            messages.put(("end", None))

    reader = threading.Thread(target=read_response, name="mtp-chat-stream-reader", daemon=True)
    reader.start()
    status: int | None = None
    ended = False
    try:
        while not ended:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("chat completion exceeded its request timeout")
            try:
                kind, value = messages.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if on_event is not None:
                    on_event()
                continue
            if kind == "opened":
                status = value
            elif kind == "line":
                raw = value
                lines.append(raw)
                if on_event is not None:
                    on_event()
                if first_text_at is None and _sse_first_text(raw):
                    first_text_at = time.monotonic()
            elif kind == "http_error":
                error_status, body = value
                raise RuntimeError(f"HTTP {error_status}: {body.decode('utf-8', errors='replace')}")
            elif kind == "error":
                raise value
            elif kind == "end":
                ended = True
        if status is None:
            raise RuntimeError("chat completion ended without an HTTP response")
    finally:
        if not ended:
            connection.close()
        reader.join(timeout=0.1)
    finished = time.monotonic()
    parsed = parse_sse_events(lines)
    return {"http_status": status, **parsed,
            "ttft_ms": round((first_text_at - started) * 1000, 2) if first_text_at else None,
            "wall_time_s": round(finished - started, 4)}


def _server_log_has_oom(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return any(marker in content for marker in OOM_MARKERS)


def _terminate_process_group(proc: subprocess.Popen[Any] | None, grace_seconds: int = 5) -> None:
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    end = time.monotonic() + grace_seconds
    while time.monotonic() < end:
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            break
        if proc.poll() is None:
            try:
                proc.wait(timeout=0.1)
            except subprocess.TimeoutExpired:
                continue
        else:
            time.sleep(0.05)
    try:
        os.killpg(proc.pid, 0)
    except ProcessLookupError:
        pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.wait()


def _session_dir(root: Path, sequence: int, row: dict[str, Any]) -> Path:
    return root / "sessions" / f"{sequence:02d}-{row['session_id']}"


def _session_record(row: dict[str, Any], sequence: int, prompt: str) -> dict[str, Any]:
    return {"experiment": EXPERIMENT, "sequence": sequence, **row,
            "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
            "prompt_bytes": len(prompt.encode("utf-8")), "model_id": MODEL_ID,
            "model_sha256": MODEL_SHA256, "runtime_revision": RUNTIME_REVISION,
            "context_tokens": CONTEXT_TOKENS, "max_new_tokens": MAX_NEW_TOKENS,
            "temperature": TEMPERATURE, "seed": SEED, "prompt_cache": "off",
            "target_kv_cache": {"k": "q4_0", "v": "q4_0"},
            "mtp_draft_context_kv": {"k": "f16", "v": "f16"} if row["arm"] == "on" else None,
            "coding_behavior_gate": "not_evaluated", "attempted": False,
            "quality_gate_status": "not_run", "quality_gate_summary_path": None,
            "completed": False, "stop_reason": None, "prompt_tokens": None,
            "completion_tokens": None, "output_chars": None, "finish_reason": None,
            "cap_condition": "not_available", "ttft_ms": None, "wall_time_s": None}


def _run_quality_gates(*, arm: str, install_root: Path, runtime: Path, session: Path,
                       url: str, server_log: Path, resources_path: Path,
                       deadline: float, swap_baseline: int) -> dict[str, Any]:
    gate_dir = session / "quality-gates"
    gate_dir.mkdir(parents=True, exist_ok=False)
    output_path = gate_dir / "records.jsonl"
    stdout_path = gate_dir / "stdout.log"
    stderr_path = gate_dir / "stderr.log"
    command = [sys.executable, str(REPO_ROOT / "benchmark/quality_smoke.py"),
               "--url", url, "--model", MODEL_ID, "--output", str(output_path)]
    env = _runtime_environment(install_root, runtime)
    env.update({"BENCH_STORAGE_ROOT": str(install_root), "LAB_SOURCE_DIRTY": "true",
                "LAB_RUNTIME_COMMIT": RUNTIME_REVISION, "LAB_REASONING": "off",
                "LAB_CONTEXT_TOKENS": str(CONTEXT_TOKENS), "LAB_KV_CACHE_K": "q4_0",
                "LAB_KV_CACHE_V": "q4_0", "LAB_GPU_LAYERS": "99"})
    started = time.monotonic()
    metrics_before = _get_metrics(url)
    process: subprocess.Popen[Any] | None = None
    stop: str | None = None
    error_text: str | None = None
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(command, cwd=REPO_ROOT, env=env, stdout=stdout,
                                       stderr=stderr, start_new_session=True)
            while True:
                now = time.monotonic()
                if now >= deadline:
                    stop = "round_deadline"
                    raise RoundDeadline("round deadline reached during quality gates")
                if _server_log_has_oom(server_log):
                    stop = "server_lost_or_oom"
                    raise RunStop(stop)
                if swap_growth_breach(_read_jsonl(resources_path), swap_baseline):
                    stop = "swap_growth_limit"
                    raise RunStop(stop)
                if process.poll() is not None:
                    break
                time.sleep(min(0.25, max(0.0, deadline - now)))
    except RoundDeadline as exc:
        stop = "round_deadline"
        error_text = str(exc)
    except RunStop as exc:
        stop = exc.reason
        error_text = str(exc)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        stop = "quality_gate_runner_error"
        error_text = f"{type(exc).__name__}: {exc}"
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_group(process, grace_seconds=2)
        elif process is not None:
            process.wait()
    metrics_after = _get_metrics(url)
    diagnostic_records = _read_jsonl(output_path)
    assessment = evaluate_quality_gates(diagnostic_records)
    passed = stop is None and process is not None and process.returncode == 0 and assessment["passed"]
    result = {
        "arm": arm,
        "passed": passed,
        "status": "passed" if passed else "failed_closed",
        "stop_reason": stop or (None if passed else "quality_gate_failed"),
        "error": error_text,
        "command": command,
        "child_exit_code": process.returncode if process is not None else None,
        "started_monotonic": started,
        "elapsed_seconds": round(time.monotonic() - started, 4),
        "runner_sha256": sha256_file(REPO_ROOT / "benchmark/quality_smoke.py"),
        "records_path": str(output_path),
        "records_sha256": sha256_file(output_path) if output_path.is_file() else None,
        "records": diagnostic_records,
        "assessment": assessment,
        "runtime_configuration": {
            "spec_type": "draft-mtp" if arm == "on" else "none",
            "context_tokens": CONTEXT_TOKENS,
            "reasoning": "off",
            "prompt_cache": "off",
            "target_kv_cache": {"k": "q4_0", "v": "q4_0"},
            "mtp_draft_context_kv": {"k": "f16", "v": "f16"} if arm == "on" else None,
            "runtime_revision": RUNTIME_REVISION,
            "runtime_server_sha256": RUNTIME_SERVER_SHA256,
            "model_sha256": MODEL_SHA256,
        },
        "stdout_path": str(stdout_path),
        "stdout_sha256": sha256_file(stdout_path) if stdout_path.is_file() else None,
        "stderr_path": str(stderr_path),
        "stderr_sha256": sha256_file(stderr_path) if stderr_path.is_file() else None,
        "resource_summary": _resource_summary(_read_jsonl(resources_path)),
        "speculative_counters_before": metrics_before,
        "speculative_counters_after": metrics_after,
        "speculative_counter_deltas": {
            key: counter_delta(metrics_before, metrics_after, metric)
            for key, metric in COUNTER_NAMES.items()
        },
        "record_environment": {key: env[key] for key in (
            "LAB_SOURCE_DIRTY", "LAB_RUNTIME_COMMIT", "LAB_REASONING",
            "LAB_CONTEXT_TOKENS", "LAB_KV_CACHE_K", "LAB_KV_CACHE_V", "LAB_GPU_LAYERS")},
    }
    result["summary_path"] = str(gate_dir / "gate-summary.json")
    _write_json(Path(result["summary_path"]), result)
    return result


def _run_session(*, install_root: Path, server: Path, runtime: Path,
                 output_root: Path, rows: list[dict[str, Any]], sequence: int,
                 deadline: float, swap_baseline: int,
                 records: list[dict[str, Any]]) -> tuple[str | None, int]:
    first_row = rows[0]
    session = _session_dir(output_root, sequence, first_row)
    session.mkdir(parents=True, exist_ok=False)
    server_log = session / "server.log"
    resources_path = session / "resources.jsonl"
    url = f"http://127.0.0.1:{PORT}"
    env = _runtime_environment(install_root, runtime)
    process: subprocess.Popen[Any] | None = None
    sampler: subprocess.Popen[Any] | None = None
    log_handle = None
    startup_started = time.monotonic()
    processed = 0
    fatal_reason: str | None = None
    server_error: str | None = None
    quality_gate: dict[str, Any] | None = None
    try:
        sampler = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "benchmark/resource_sampler.py"),
             "--output", str(resources_path), "--interval", "1"],
            cwd=REPO_ROOT, env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        log_handle = server_log.open("w", encoding="utf-8")
        process = subprocess.Popen(server_command(server, install_root / MODEL_RELATIVE_PATH,
                                                  PORT, first_row["arm"]), env=env,
                                    stdout=log_handle, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        while time.monotonic() < deadline:
            if _server_log_has_oom(server_log):
                raise RunStop("server_lost_or_oom")
            if swap_growth_breach(_read_jsonl(resources_path), swap_baseline):
                raise RunStop("swap_growth_limit")
            if _server_healthy(url):
                break
            if process.poll() is not None:
                raise RuntimeError(f"owned llama-server exited during startup ({process.returncode})")
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        else:
            raise RoundDeadline("round deadline reached during server startup")
        startup_seconds = round(time.monotonic() - startup_started, 3)
        if first_row["pair"] == 1 and any(row["stage"] == "warmup" for row in rows):
            quality_gate = _run_quality_gates(
                arm=first_row["arm"], install_root=install_root, runtime=runtime,
                session=session, url=url, server_log=server_log,
                resources_path=resources_path, deadline=deadline,
                swap_baseline=swap_baseline,
            )
            if not quality_gate["passed"]:
                fatal_reason = quality_gate["stop_reason"] or "quality_gate_failed"
                server_error = quality_gate.get("error") or fatal_reason
        run_rows = rows if fatal_reason is None else []
        for row in run_rows:
            prompt = PROMPTS[row["prompt_id"]]
            record = _session_record(row, sequence, prompt)
            record.update({"session_dir": str(session), "server_log_path": str(server_log),
                           "resources_path": str(resources_path), "server_pid": process.pid,
                           "server_startup_seconds": startup_seconds,
                           "quality_gate_status": (quality_gate["status"] if quality_gate
                                                    else "passed_in_prior_arm_setup"),
                           "quality_gate_summary_path": (quality_gate["summary_path"]
                                                          if quality_gate else None)})
            before: dict[str, float] = {}
            after: dict[str, float] = {}
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RoundDeadline("round deadline reached before request")
                before = _get_metrics(url)
                record["attempted"] = True

                last_health_check = 0.0

                def monitor_request() -> None:
                    nonlocal last_health_check
                    now = time.monotonic()
                    if now >= deadline:
                        raise RunStop("round_deadline")
                    if now - last_health_check < 1.0:
                        return
                    last_health_check = now
                    samples = _read_jsonl(resources_path)
                    try:
                        log_text = server_log.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        log_text = ""
                    healthy = process is not None and process.poll() is None and _server_healthy(url)
                    reason = stop_reason(now=time.monotonic(), deadline=deadline,
                                         server_healthy=healthy, server_log=log_text,
                                         swap_samples=samples, swap_baseline_bytes=swap_baseline)
                    if reason:
                        raise RunStop(reason)

                result = request_completion(url, request_payload(prompt), timeout=remaining,
                                            on_event=monitor_request)
                after = _get_metrics(url)
                output_tokens = result["completion_tokens"]
                elapsed_after_first = (result["wall_time_s"] - (result["ttft_ms"] or 0) / 1000)
                output_tps = (output_tokens / elapsed_after_first
                              if output_tokens is not None and elapsed_after_first > 0 else None)
                finish_reason = result["finish_reason"]
                cap_condition = classify_cap_condition(finish_reason, output_tokens)
                record.update({"completed": bool(result["http_status"] == 200 and result["saw_done"]),
                               "http_status": result["http_status"],
                               "prompt_tokens": result["prompt_tokens"],
                               "completion_tokens": output_tokens,
                               "output_chars": len(result["content"]),
                               "finish_reason": finish_reason,
                               "cap_condition": cap_condition,
                               "output_tokens_per_second": round(output_tps, 3) if output_tps is not None else None,
                               "ttft_ms": result["ttft_ms"], "wall_time_s": result["wall_time_s"],
                               "prompt_eval_ms": result["timings"].get("prompt_ms"),
                               "generation_eval_ms": result["timings"].get("predicted_ms"),
                               "generation_tps": result["timings"].get("predicted_per_second"),
                               "response": result["content"],
                               "timings": result["timings"], "sse_done": result["saw_done"]})
                if not record["completed"]:
                    record["stop_reason"] = "incomplete_stream"
            except RunStop as error:
                record["stop_reason"] = error.reason
                record["error"] = str(error)
                fatal_reason = error.reason
            except RoundDeadline as error:
                record["stop_reason"] = "round_deadline"
                record["error"] = str(error)
                fatal_reason = "round_deadline"
            except (OSError, RuntimeError, ValueError, urllib.error.URLError,
                    TimeoutError, json.JSONDecodeError) as error:
                record["error"] = f"{type(error).__name__}: {error}"
                record["stop_reason"] = "request_error"
                if _server_log_has_oom(server_log) or process.poll() is not None:
                    fatal_reason = "server_lost_or_oom" if _server_log_has_oom(server_log) else "server_start_error"
                    record["stop_reason"] = fatal_reason
            finally:
                if not after:
                    after = _get_metrics(url)
                _attach_counter_deltas(record, before, after)
            record["resource_summary"] = _resource_summary(_read_jsonl(resources_path))
            if _server_log_has_oom(server_log):
                fatal_reason = "server_lost_or_oom"
                record["stop_reason"] = fatal_reason
            elif fatal_reason is None:
                now = time.monotonic()
                if now >= deadline:
                    fatal_reason = "round_deadline"
                    record["stop_reason"] = fatal_reason
                elif swap_growth_breach(_read_jsonl(resources_path), swap_baseline):
                    fatal_reason = "swap_growth_limit"
                    record["stop_reason"] = fatal_reason
            _append_record(output_root, records, record)
            processed += 1
            if fatal_reason:
                break
    except RunStop as error:
        fatal_reason = error.reason
        server_error = str(error)
    except RoundDeadline as error:
        fatal_reason = "round_deadline"
        server_error = str(error)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        fatal_reason = "server_start_error"
        server_error = f"{type(error).__name__}: {error}"
    finally:
        _terminate_process_group(sampler, grace_seconds=3)
        _terminate_process_group(process, grace_seconds=5)
        if log_handle is not None:
            log_handle.close()
    log_text = server_log.read_text(encoding="utf-8", errors="replace") if server_log.is_file() else ""
    if fatal_reason is None:
        if any(marker in log_text.lower() for marker in OOM_MARKERS):
            fatal_reason = "server_lost_or_oom"
        elif swap_growth_breach(_read_jsonl(resources_path), swap_baseline):
            fatal_reason = "swap_growth_limit"
        elif time.monotonic() >= deadline:
            fatal_reason = "round_deadline"
        if fatal_reason and processed:
            records[-1]["stop_reason"] = fatal_reason
            with (output_root / "records.jsonl").open("w", encoding="utf-8") as output:
                for item in records:
                    output.write(json.dumps(item, ensure_ascii=False) + "\n")
            _write_json(output_root / "summary.json", summarize_denominators(records))
    session_summary = {"session_id": first_row["session_id"], "server_pid": process.pid if process else None,
                       "server_process_reaped": process is not None and process.poll() is not None,
                       "server_log_sha256": sha256_file(server_log) if server_log.is_file() else None,
                       "server_log_has_oom": any(marker in log_text.lower() for marker in OOM_MARKERS),
                       "resource_summary": _resource_summary(_read_jsonl(resources_path)),
                       "fatal_stop_reason": fatal_reason, "startup_error": server_error,
                       "quality_gate": quality_gate}
    _write_json(session / "session-summary.json", session_summary)
    while processed < len(rows):
        row = rows[processed]
        pending = _session_record(row, sequence, PROMPTS[row["prompt_id"]])
        pending.update({"attempted": False, "completed": False,
                        "stop_reason": fatal_reason or "series_aborted",
                        "error": server_error, "session_dir": str(session),
                        "server_log_path": str(server_log), "resources_path": str(resources_path),
                        "quality_gate_status": (quality_gate["status"] if quality_gate
                                                else "not_run_before_session"),
                        "quality_gate_summary_path": (quality_gate["summary_path"]
                                                       if quality_gate else None)})
        _append_record(output_root, records, pending)
        processed += 1
    return fatal_reason, processed


def _attach_counter_deltas(record: dict[str, Any], before: dict[str, float],
                           after: dict[str, float]) -> None:
    record["metrics_before_available"] = sorted(before)
    record["metrics_after_available"] = sorted(after)
    record["metrics_before_values"] = before
    record["metrics_after_values"] = after
    record["speculative_counters"] = {
        key: counter_delta(before, after, metric) for key, metric in COUNTER_NAMES.items()
    }


def _resource_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_paths = {
        "ram_used_mb": lambda row: row.get("ram_used_mb"),
        "swap_used_mb": lambda row: row.get("swap_used_mb"),
        "vram_used_mb": lambda row: (row.get("gpu") or {}).get("vram_used_mb"),
        "gpu_util_pct": lambda row: (row.get("gpu") or {}).get("gpu_util_pct"),
    }
    result: dict[str, Any] = {"sample_count": len(rows)}
    for key, select in numeric_paths.items():
        values = []
        for row in rows:
            try:
                value = float(select(row))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                values.append(value)
        result[key] = {"min": min(values), "max": max(values)} if values else None
    return result


def _round_preflight(root: Path, output_root: Path) -> tuple[Path, Path, dict[str, str], str]:
    root = root.resolve()
    output_root = output_root.resolve()
    model = root / MODEL_RELATIVE_PATH
    runtime = root / "tools/llama-bin"
    server = runtime / "llama-server"
    if output_root.exists():
        raise RuntimeError(f"Refusing to overwrite existing output: {output_root}")
    for path, label in ((REPO_ROOT, "source"), (root, "installation"),
                        (model, "model"), (server, "server"), (output_root.parent, "output")):
        if not _is_ext4(path):
            raise RuntimeError(f"{label} must be on WSL ext4 SSD: {path}")
    _assert_free_resources(root)
    if sha256_file(model) != MODEL_SHA256:
        raise RuntimeError("Pinned 4B model SHA-256 mismatch; refusing run")
    if sha256_file(server) != RUNTIME_SERVER_SHA256:
        raise RuntimeError("Pinned llama-server SHA-256 mismatch; refusing run")
    _assert_server_bundle(server, runtime)
    env = _runtime_environment(root, runtime)
    version = subprocess.run([str(server), "--version"], env=env, capture_output=True,
                             text=True, timeout=10, check=True)
    version_text = require_runtime_revision(version.stdout, version.stderr, RUNTIME_VERSION_PREFIX)
    _assert_gpu_free()
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", PORT)) == 0:
            raise RuntimeError(f"Probe port {PORT} is occupied; refusing to attach to any server")
    library_hashes = {
        path.name: sha256_file(path)
        for path in sorted(runtime.iterdir())
        if path.is_file() and (path.name.startswith("lib") or path.name == "llama-server")
    }
    return model, server, library_hashes, version_text


def frozen_protocol(model: Path | None = None, server: Path | None = None) -> dict[str, Any]:
    prompt_records = {
        prompt_id: {"text": text, "utf8_bytes": len(text.encode("utf-8")),
                    "sha256": sha256_bytes(text.encode("utf-8"))}
        for prompt_id, text in PROMPTS.items()
    }
    return {
        "experiment": EXPERIMENT,
        "model": {"id": MODEL_ID, "path": str(model or (Path("/home/foxtrot/local-llm-benchmark") / MODEL_RELATIVE_PATH)),
                  "sha256": MODEL_SHA256},
        "runtime": {"path": str(server or "/home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server"),
                    "revision": RUNTIME_REVISION, "sha256": RUNTIME_SERVER_SHA256},
        "prompts": prompt_records,
        "context_tokens": CONTEXT_TOKENS,
        "max_new_tokens_per_response": MAX_NEW_TOKENS,
        "temperature": TEMPERATURE,
        "seed": SEED,
        "target_kv_cache": {"k": "q4_0", "v": "q4_0"},
        "prompt_cache": "off",
        "reasoning": "off",
        "gpu_layers": 99,
        "flash_attention": "on",
        "parallel_slots": 1,
        "arms": {
            "off": {"spec_type": "none", "mtp_draft_context": "not loaded"},
            "on": {"spec_type": "draft-mtp", "draft_max_tokens": 3,
                   "mtp_draft_context_kv": {"k": "f16", "v": "f16"}},
        },
        "schedule": measured_schedule(),
        "warmups_excluded": 4,
        "planned_measured_rows": 12,
        "round_limit_seconds_including_load": ROUND_LIMIT_SECONDS,
        "swap_stop": {"bytes_over_baseline": SWAP_GROWTH_LIMIT_BYTES,
                      "consecutive_one_second_samples": SWAP_GROWTH_SAMPLES},
        "quality_gates": {
            "strict_json": "benchmark/quality_smoke.py; required for each arm before warmups",
            "tool_round_trip": "benchmark/quality_smoke.py; required for each arm before warmups",
            "coding_behavior": "pending separate promotion gate",
            "promotion_allowed_by_this_probe": False,
        },
        "quality_claim": "no useful-gain claim from this probe",
    }


def _alarm_handler(_signum: int, _frame: Any) -> None:
    raise RoundDeadline("30-minute round deadline reached")


def run_series(install_root: Path, output_root: Path) -> list[dict[str, Any]]:
    started = time.monotonic()
    deadline = started + ROUND_LIMIT_SECONDS
    install_root, output_root = install_root.resolve(), output_root.resolve()
    previous_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, ROUND_LIMIT_SECONDS)
    records: list[dict[str, Any]] = []
    schedule = measured_schedule()
    try:
        model, server, libraries, version_text = _round_preflight(install_root, output_root)
        output_root.mkdir(parents=True, exist_ok=False)
        (output_root / "prompts").mkdir()
        for prompt_id, prompt in PROMPTS.items():
            (output_root / "prompts" / f"{prompt_id}.txt").write_bytes(prompt.encode("utf-8"))
        protocol = frozen_protocol(model, server)
        protocol.update({
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "llama_cpp_version": version_text,
            "runtime_files_sha256": libraries,
            "server_argv_by_arm": {
                arm: server_command(server, model, PORT, arm) for arm in ("off", "on")
            },
            "source_files_sha256": {
                str(path.relative_to(REPO_ROOT).as_posix()): sha256_file(path)
                for path in (Path(__file__), REPO_ROOT / "benchmark/quality_smoke.py",
                             REPO_ROOT / "benchmark/llama_cpp_bench.py",
                             REPO_ROOT / "benchmark/resource_sampler.py",
                             REPO_ROOT / "benchmark/opencode_controlled_probe.py")
            },
        })
        _write_json(output_root / "protocol.json", protocol)
        swap_baseline = _swap_baseline_bytes()
        schedule_offset = 0
        try:
            for block_index, (_session_id, block_iter) in enumerate(
                    itertools.groupby(schedule, key=lambda row: row["session_id"]), start=1):
                block = list(block_iter)
                if time.monotonic() >= deadline:
                    break
                fatal, processed = _run_session(
                    install_root=install_root, server=server,
                    runtime=install_root / "tools/llama-bin", output_root=output_root,
                    rows=block, sequence=block_index, deadline=deadline,
                    swap_baseline=swap_baseline, records=records,
                )
                schedule_offset += processed
                if fatal:
                    break
        except RoundDeadline:
            pass
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sequence, row in enumerate(schedule[schedule_offset:], start=schedule_offset + 1):
            pending = _session_record(row, sequence, PROMPTS[row["prompt_id"]])
            pending.update({"attempted": False, "completed": False,
                            "stop_reason": "round_deadline" if time.monotonic() >= deadline else "series_aborted"})
            _append_record(output_root, records, pending)
        gate_summaries = []
        sessions_root = output_root / "sessions"
        if sessions_root.is_dir():
            for summary_path in sorted(sessions_root.glob("*/session-summary.json")):
                session_summary = json.loads(summary_path.read_text(encoding="utf-8"))
                quality_gate = session_summary.get("quality_gate")
                if quality_gate is not None:
                    gate_summaries.append(quality_gate)
        gates_by_arm = {arm: next((gate for gate in gate_summaries if gate.get("arm") == arm), None)
                        for arm in ("off", "on")}
        _write_json(output_root / "summary.json", {
            **summarize_denominators(records),
            "quality_gates_by_arm": gates_by_arm,
            "speculative_activity": summarize_speculative_activity(records),
            "coding_behavior_gate": "pending",
            "promotion_status": "blocked_pending_coding_behavior",
            "speedup_claim_allowed": False,
        })
        return records
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path,
                        default=Path(os.getenv("BENCHMARK_ROOT", "/home/foxtrot/local-llm-benchmark")))
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--execute", action="store_true",
                        help="explicitly execute the frozen 30-minute paired probe")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = args.output_root or args.benchmark_root / "results/raw" / f"mtp-paired-probe-r2-{stamp}"
    if not args.execute:
        print(json.dumps({"protocol": frozen_protocol(), "benchmark_root": str(args.benchmark_root),
                          "output_root": str(output_root), "inference_started": False},
                         ensure_ascii=False, indent=2))
        return 0
    run_series(args.benchmark_root, output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
