#!/usr/bin/env python3
"""Mechanical Preflight and Diagnostic Fit for IBM Granite 4.1 8B (Milestone M5 / Tarefa 7).

Verifies:
1. GGUF checksum and size integrity.
2. 4K context server boot, VRAM footprint, structured JSON, and tool calling round trip.
3. 16K context server boot, VRAM fit on RTX 3070 (8192 MiB), and code synthesis generation.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_ROOT = Path(os.environ.get("BENCH_STORAGE_ROOT", "/home/foxtrot/local-llm-benchmark"))

MODEL_PATH = INSTALL_ROOT / "models/gguf/granite-4.1-8b/granite-4.1-8b-Q4_K_M.gguf"
EXPECTED_SIZE = 5347914400
EXPECTED_SHA256 = "ed902ac9eb6adce5a90c6a08c8ea201b50e23fdc5976d1cd0362006afac5309e"
SERVER_BIN = INSTALL_ROOT / "tools/llama-bin/llama-server"
SERVER_URL = "http://127.0.0.1:8080"


def get_vram_mb() -> float:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True,
        )
        return float(out.strip().splitlines()[0])
    except Exception:
        return 0.0


def kill_proc(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    deadline = time.monotonic() + 4.0
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def wait_for_server(url: str, proc: subprocess.Popen[Any], timeout: float = 30.0) -> bool:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if proc.poll() is not None:
            return False
        try:
            req = urllib.request.Request(f"{url}/v1/models")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def post_json(url: str, payload: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_4k(log_path: Path) -> dict[str, Any]:
    print("\n--- Phase 1: 4K Context Fit & Diagnostic Smoke ---")
    vram_before = get_vram_mb()
    print(f"VRAM baseline (before 4K boot): {vram_before:.1f} MiB")

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
        "LD_LIBRARY_PATH": str(INSTALL_ROOT / "tools/llama-bin"),
        "HOME": str(INSTALL_ROOT),
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
    }
    cmd = [
        str(SERVER_BIN),
        "--model", str(MODEL_PATH),
        "--host", "127.0.0.1",
        "--port", "8080",
        "--alias", "granite-4.1-8b-Q4_K_M",
        "--ctx-size", "4096",
        "--n-gpu-layers", "99",
        "--batch-size", "512",
        "--ubatch-size", "256",
        "--flash-attn", "on",
        "--cache-type-k", "q4_0",
        "--cache-type-v", "q4_0",
        "--reasoning", "off",
        "--cache-prompt",
        "--parallel", "1",
        "--no-webui",
        "--metrics",
    ]

    log_f = log_path.open("w", encoding="utf-8")
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, env=env, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True)

    result: dict[str, Any] = {"ctx": 4096, "pass": False}
    try:
        ready = wait_for_server(SERVER_URL, proc, timeout=30.0)
        boot_time = round(time.monotonic() - t0, 3)
        result["boot_time_s"] = boot_time
        print(f"Server ready in {boot_time}s (ready={ready})")
        if not ready:
            result["error"] = "Server failed to respond within 30s"
            return result

        vram_loaded = get_vram_mb()
        result["vram_loaded_mb"] = vram_loaded
        print(f"VRAM after 4K load: {vram_loaded:.1f} MiB (delta: {vram_loaded - vram_before:.1f} MiB)")

        # 1. Structured JSON Probe
        print("Running Structured JSON probe...")
        json_payload = {
            "model": "granite-4.1-8b-Q4_K_M",
            "messages": [
                {"role": "user", "content": 'Return a JSON object with exactly the keys "ok" and "count"; use true and 3.'}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 64,
        }
        t_json = time.monotonic()
        resp_json = post_json(SERVER_URL, json_payload)
        json_wall = round(time.monotonic() - t_json, 3)
        content = resp_json["choices"][0]["message"].get("content", "")
        print(f"JSON response ({json_wall}s): {content}")
        parsed = json.loads(content)
        json_ok = (parsed.get("ok") is True and parsed.get("count") == 3)
        result["json_probe"] = {"pass": json_ok, "wall_s": json_wall, "content": content}

        # 2. Tool Call Round Trip Probe
        print("Running Function Tool Call probe...")
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add two numbers",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                    },
                },
            }
        ]
        tool_payload = {
            "model": "granite-4.1-8b-Q4_K_M",
            "messages": [
                {"role": "user", "content": "Calculate 19 + 23 using the add tool."}
            ],
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
            "max_tokens": 128,
        }
        t_tool = time.monotonic()
        resp_tool = post_json(SERVER_URL, tool_payload)
        msg_tool = resp_tool["choices"][0]["message"]
        tool_calls = msg_tool.get("tool_calls", [])
        tool_wall = round(time.monotonic() - t_tool, 3)
        print(f"Tool call response ({tool_wall}s): {json.dumps(tool_calls)}")

        tool_ok = False
        if tool_calls and len(tool_calls) == 1:
            call = tool_calls[0]
            fn_name = call.get("function", {}).get("name")
            fn_args = json.loads(call.get("function", {}).get("arguments", "{}"))
            if fn_name == "add" and fn_args.get("a") == 19 and fn_args.get("b") == 23:
                tool_ok = True

        result["tool_probe"] = {
            "pass": tool_ok,
            "wall_s": tool_wall,
            "tool_calls": tool_calls,
        }

        vram_peak = get_vram_mb()
        result["vram_peak_mb"] = vram_peak
        result["pass"] = bool(json_ok and tool_ok)
        print(f"4K Phase Result: PASS={result['pass']}, VRAM peak={vram_peak:.1f} MiB")
        return result
    finally:
        kill_proc(proc)
        log_f.close()


def test_16k(log_path: Path) -> dict[str, Any]:
    print("\n--- Phase 2: 16K Context Fit & Code Synthesis ---")
    vram_before = get_vram_mb()
    print(f"VRAM baseline (before 16K boot): {vram_before:.1f} MiB")

    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
        "LD_LIBRARY_PATH": str(INSTALL_ROOT / "tools/llama-bin"),
        "HOME": str(INSTALL_ROOT),
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
    }
    cmd = [
        str(SERVER_BIN),
        "--model", str(MODEL_PATH),
        "--host", "127.0.0.1",
        "--port", "8080",
        "--alias", "granite-4.1-8b-Q4_K_M",
        "--ctx-size", "16384",
        "--n-gpu-layers", "99",
        "--batch-size", "512",
        "--ubatch-size", "256",
        "--flash-attn", "on",
        "--cache-type-k", "q4_0",
        "--cache-type-v", "q4_0",
        "--reasoning", "off",
        "--cache-prompt",
        "--parallel", "1",
        "--no-webui",
        "--metrics",
    ]

    log_f = log_path.open("w", encoding="utf-8")
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, env=env, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True)

    result: dict[str, Any] = {"ctx": 16384, "pass": False}
    try:
        ready = wait_for_server(SERVER_URL, proc, timeout=40.0)
        boot_time = round(time.monotonic() - t0, 3)
        result["boot_time_s"] = boot_time
        print(f"16K Server ready in {boot_time}s (ready={ready})")
        if not ready:
            result["error"] = "Server failed to respond within 40s"
            return result

        vram_loaded = get_vram_mb()
        result["vram_loaded_mb"] = vram_loaded
        print(f"VRAM after 16K load: {vram_loaded:.1f} MiB (delta: {vram_loaded - vram_before:.1f} MiB)")

        # Code synthesis prompt
        print("Running 16K Code Synthesis probe...")
        code_payload = {
            "model": "granite-4.1-8b-Q4_K_M",
            "messages": [
                {
                    "role": "user",
                    "content": "Write a Python function `safe_divide(a: float, b: float) -> float | None` that returns a / b or None if b == 0. Include docstring and type hints.",
                }
            ],
            "temperature": 0,
            "max_tokens": 128,
        }
        t_code = time.monotonic()
        resp_code = post_json(SERVER_URL, code_payload)
        code_wall = round(time.monotonic() - t_code, 3)
        content = resp_code["choices"][0]["message"].get("content", "")
        usage = resp_code.get("usage", {})
        print(f"Code response ({code_wall}s, tokens={usage}):\n{content}")

        code_ok = "def safe_divide" in content and "None" in content
        vram_peak = get_vram_mb()
        result["code_probe"] = {
            "pass": code_ok,
            "wall_s": code_wall,
            "usage": usage,
            "content": content,
        }
        result["vram_peak_mb"] = vram_peak
        result["vram_headroom_mb"] = 8192.0 - vram_peak
        result["pass"] = bool(code_ok and vram_peak <= 8192.0)
        print(f"16K Phase Result: PASS={result['pass']}, VRAM peak={vram_peak:.1f} MiB, Headroom={result['vram_headroom_mb']:.1f} MiB")
        return result
    finally:
        kill_proc(proc)
        log_f.close()


def main() -> int:
    out_dir = INSTALL_ROOT / "results/raw/granite8b-diagnostic"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=== Granite 4.1 8B Diagnostic Preflight ===")
    print(f"Target: {MODEL_PATH}")
    assert MODEL_PATH.exists(), f"Model file missing: {MODEL_PATH}"

    # Size check
    actual_size = MODEL_PATH.stat().st_size
    print(f"File size: {actual_size} bytes (expected {EXPECTED_SIZE})")
    assert actual_size == EXPECTED_SIZE, "Size mismatch"

    # SHA256 check
    print("Computing SHA256...")
    h = hashlib.sha256()
    with MODEL_PATH.open("rb") as f:
        while chunk := f.read(64 * 1024 * 1024):
            h.update(chunk)
    actual_sha = h.hexdigest()
    print(f"SHA-256: {actual_sha} (expected {EXPECTED_SHA256})")
    assert actual_sha == EXPECTED_SHA256, "SHA256 mismatch"

    # Run 4K test
    log_4k = out_dir / "llama-server-4k.log"
    res_4k = test_4k(log_4k)

    # Cooldown 2s
    time.sleep(2.0)

    # Run 16K test
    log_16k = out_dir / "llama-server-16k.log"
    res_16k = test_16k(log_16k)

    summary = {
        "model": "granite-4.1-8b-Q4_K_M",
        "file_size": actual_size,
        "sha256": actual_sha,
        "phase1_4k": res_4k,
        "phase2_16k": res_16k,
        "timestamp": time.time(),
    }
    summary_path = out_dir / "diagnostic_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nDiagnostic summary written to {summary_path}")

    overall_pass = res_4k.get("pass") and res_16k.get("pass")
    print(f"\nOVERALL MECHANICAL PREFLIGHT: {'PASS' if overall_pass else 'FAIL'}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
