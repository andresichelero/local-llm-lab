"""Model switch latency benchmark (Milestone M6 Tarefa 8).

Measures five alternating switch cycles between Qwen3.5-4B and Qwen3.5-9B,
recording exact individual unload, load, and readiness times.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
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

SERVER_PORT = 8080
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
CONTEXT = 16384

MODELS: dict[str, dict[str, str]] = {
    "qwen3.5-4b": {
        "alias": "Qwen3.5-4B-Q4_K_M",
        "path": "models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf",
    },
    "qwen3.5-9b": {
        "alias": "Qwen3.5-9B-Q4_K_M",
        "path": "models/gguf/Qwen3.5-9B-Q4_K_M.gguf",
    },
}


def server_command(server: Path, model_path: Path, alias: str) -> list[str]:
    return [
        str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(SERVER_PORT),
        "--alias", alias, "--ctx-size", str(CONTEXT), "--n-gpu-layers", "99",
        "--batch-size", "512", "--ubatch-size", "256", "--flash-attn", "on",
        "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--reasoning", "off",
        "--cache-prompt", "--parallel", "1", "--no-webui",
    ]


def _kill_process_group(proc: subprocess.Popen[Any], *, grace_seconds: int = 5) -> float:
    start = time.monotonic()
    if proc.poll() is not None:
        return 0.0
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    deadline = start + grace_seconds
    while proc.poll() is None:
        if time.monotonic() >= deadline:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            break
        time.sleep(0.05)
    if proc.poll() is None:
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
    return round(time.monotonic() - start, 3)


def check_readiness(url: str = SERVER_URL) -> float:
    payload = {
        "model": "default",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0,
        "max_tokens": 1,
    }
    start = time.monotonic()
    req = urllib.request.Request(
        f"{url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        _ = resp.read()
    return round(time.monotonic() - start, 3)


def run_switch_benchmark(install_root: Path, output_dir: Path, num_cycles: int = 5) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    server = install_root / "tools/llama-bin/llama-server"
    server_env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
        "LD_LIBRARY_PATH": str(install_root / "tools/llama-bin"),
        "HOME": str(install_root),
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
    }

    # Initial start of model A (4B)
    current_model = "qwen3.5-4b"
    log_file = output_dir / f"server-initial-{current_model}.log"
    log_f = log_file.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        server_command(server, install_root / MODELS[current_model]["path"], MODELS[current_model]["alias"]),
        env=server_env, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True
    )
    # Wait ready
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{SERVER_URL}/v1/models", timeout=1) as res:
                if res.status == 200:
                    break
        except Exception:
            time.sleep(0.25)

    switches: list[dict[str, Any]] = []

    try:
        for cycle in range(1, num_cycles + 1):
            target_model = "qwen3.5-9b" if current_model == "qwen3.5-4b" else "qwen3.5-4b"
            print(f"[switch] Cycle {cycle}/{num_cycles}: Switching from {current_model} to {target_model}...")

            # 1. Unload
            unload_time = _kill_process_group(proc)
            log_f.close()

            # 2. Load
            target_log = output_dir / f"server-cycle-{cycle}-{target_model}.log"
            log_f = target_log.open("w", encoding="utf-8")
            start_load = time.monotonic()
            proc = subprocess.Popen(
                server_command(server, install_root / MODELS[target_model]["path"], MODELS[target_model]["alias"]),
                env=server_env, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True
            )

            load_time: float | None = None
            for _ in range(120):
                if proc.poll() is not None:
                    raise RuntimeError(f"Server crashed during switch: exit code {proc.returncode}")
                try:
                    with urllib.request.urlopen(f"{SERVER_URL}/v1/models", timeout=1) as res:
                        if res.status == 200:
                            load_time = round(time.monotonic() - start_load, 3)
                            break
                except Exception:
                    time.sleep(0.1)

            if load_time is None:
                raise TimeoutError("Server failed to load target model within 30s")

            # 3. Readiness ping
            readiness_time = check_readiness()

            record = {
                "cycle": cycle,
                "from_model": current_model,
                "to_model": target_model,
                "unload_seconds": unload_time,
                "load_seconds": load_time,
                "readiness_seconds": readiness_time,
                "total_switch_seconds": round(unload_time + load_time + readiness_time, 3),
            }
            switches.append(record)
            print(f"  Cycle {cycle} complete: unload={unload_time}s, load={load_time}s, readiness={readiness_time}s, total={record['total_switch_seconds']}s")
            current_model = target_model
    finally:
        _kill_process_group(proc)
        try:
            log_f.close()
        except Exception:
            pass

    (output_dir / "records.json").write_text(json.dumps(switches, indent=2) + "\n", encoding="utf-8")
    return switches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Execute switch benchmark")
    parser.add_argument("--cycles", type=int, default=5, help="Number of alternating switch cycles")
    parser.add_argument("--install-root", type=Path, default=Path("/home/foxtrot/local-llm-benchmark"))
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    if not args.execute:
        parser.print_help()
        sys.exit(1)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = args.output_dir or (args.install_root / "results/raw" / f"model-switch-{stamp}")
    run_switch_benchmark(args.install_root, out, num_cycles=args.cycles)


if __name__ == "__main__":
    main()
