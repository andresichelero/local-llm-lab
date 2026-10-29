"""Serial, evidence-preserving D1/D2 F1 diagnostic."""

import argparse
import fcntl
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from benchmark.qwen_engines import (
    ApiClient,
    ModelBudgetExceeded,
    ModelProtocolError,
    ModelServer,
    ResourceUnavailable,
)
from benchmark.qwen_optimization import write_json
from benchmark.qwen_quant_runner import Telemetry
from benchmark.qwen_workloads import ModelBehaviorFailure, run_development

CONFIG = Path(__file__).parent / "configs/qwen-4b-f1-diagnostic.json"
OUTPUT = Path("/home/foxtrot/local-llm-benchmark/results/qwen-4b-f1-diagnostic")
GENERATION = ("temperature", "top_p", "top_k", "min_p", "presence_penalty", "repeat_penalty")


def schedule(config):
    return [
        {"task": task, "seed": seed, "arm": arm}
        for task in config["tasks"]
        for seed in config["seeds"]
        for arm in config["seed_arm_order"][str(seed)]
    ]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_preflight(config):
    if digest(config["model"]) != config["model_sha256"]:
        raise RuntimeError("model SHA-256 mismatch")
    if shutil.disk_usage(OUTPUT.parent).free < 8 * 1024**3:
        raise RuntimeError("WSL free disk below 8 GiB")
    servers = subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True, text=True, check=False)
    if servers.returncode == 0:
        raise RuntimeError("another llama-server is running: " + servers.stdout.strip())
    if servers.returncode != 1:
        raise RuntimeError("cannot inspect existing llama-server processes")


def unit_name(unit):
    return f"{unit['task']}-seed{unit['seed']}-{unit['arm']}"


def run_attempt(config, unit, output):
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "unit.json", unit)
    profile = config["arms"][unit["arm"]]
    started = time.monotonic()
    client = None
    server = None
    result = None
    telemetry = Telemetry(output)
    try:
        check_preflight(config)
        with telemetry, ModelServer(
            config["model"], "llama.cpp", output / "server", config["context"],
            thinking=profile["thinking"], cache=config["kv_k"],
            cache_reuse=profile["cache_reuse"], gpu_free_floor_mib=0, gpu_reserve_mib=0,
        ) as server:
            warmup = ApiClient(server.port, output / "warmup", model=server.alias,
                               generation={k: profile[k] for k in GENERATION},
                               max_calls=1, max_tokens=64, seed=unit["seed"])
            warmup.chat([{"role": "user", "content": "Reply OK."}])
            client = ApiClient(
                server.port, output / "client", model=server.alias,
                generation={k: profile[k] for k in GENERATION}, seed=unit["seed"],
                context_tokens=config["context"], max_tokens=profile["max_tokens"],
                max_calls=config["limits"]["main"], wall_seconds=config["wall_seconds"],
                cache_prompt=profile["cache_prompt"],
            )
            result = run_development(client, unit["task"], output)
            if result.get("status") == "model_failure":
                result["failure"] = "grader_or_completion_failed"
    except (ModelBudgetExceeded, ModelBehaviorFailure) as exc:
        result = {"status": "model_failure", "full_completion": False,
                  "failure": "budget_exhausted" if isinstance(exc, ModelBudgetExceeded) else "model_no_progress",
                  "error": str(exc), "grader_available": False}
    except (ResourceUnavailable, OSError, RuntimeError) as exc:
        result = {"status": "infrastructure", "failure": "infrastructure", "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(exc, ModelProtocolError):
            result.update(status="runner_error", failure="model_protocol_error")
        if server is not None and server.process is not None and server.process.poll() not in (None, 0, -15):
            result.update(status="infrastructure", failure="server_exited")
    finally:
        if result is None:
            result = {"status": "runner_error", "failure": "unexpected_exception"}
        progress_path = output / "episode-progress.json"
        progress = json.loads(progress_path.read_text()) if progress_path.exists() else {}
        samples = [r["device_free_mib"] for r in telemetry.rows if "device_free_mib" in r]
        result.update(
            unit=unit, total_seconds=time.monotonic() - started,
            task_seconds=progress.get("seconds"), model_calls=progress.get("calls"),
            tool_calls=progress.get("tools"),
            compactions=len(list(output.glob("compaction-*.json"))),
            peak_device_vram_mib=(8192 - min(samples)) if samples else None,
            telemetry_complete=len(samples) >= 2 and all("error" not in r for r in telemetry.rows),
        )
        write_json(output / "attempt-result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    units = schedule(config)
    if args.dry_run:
        for index, unit in enumerate(units, 1):
            print(f"{index:02d} {unit_name(unit)}")
        return
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / "supervisor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = {"config": config, "config_sha256": digest(CONFIG),
                    "source_sha256": {str(Path(__file__).resolve()): digest(__file__),
                        str(Path(__file__).parent / "qwen_engines.py"): digest(Path(__file__).parent / "qwen_engines.py"),
                        **{str(Path(__file__).parent / name): digest(Path(__file__).parent / name) for name in (
                            "qwen_workloads.py", "practical_runtime_v2.py", "practical_tasks_v2.py",
                            "practical_test_quality.py", "practical_grade_contract.py", "practical_mcp_grading_v2.py")}},
                    "server_sha256": digest(config["engine"]), "schedule": units}
        manifest_path = OUTPUT / "manifest.json"
        if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
            raise RuntimeError("manifest changed; refusing to mix protocols")
        if not manifest_path.exists():
            write_json(manifest_path, manifest)
        selected = [{"task": "python_fix", "seed": 101, "arm": "D2"}] if args.smoke else units
        base = OUTPUT / ("smoke" if args.smoke else "units")
        for index, unit in enumerate(selected, 1):
            root = base / unit_name(unit)
            root.mkdir(parents=True, exist_ok=True)
            existing = sorted(root.glob("attempt-*/attempt-result.json"))
            if existing and json.loads(existing[-1].read_text()).get("status") != "infrastructure":
                continue
            attempts = sorted(root.glob("attempt-*"))
            if len(attempts) >= 2:
                raise RuntimeError(f"infrastructure retry exhausted: {unit_name(unit)}")
            print(f"[{index}/{len(selected)}] {unit_name(unit)} attempt {len(attempts) + 1}", flush=True)
            result = run_attempt(config, unit, root / f"attempt-{len(attempts) + 1:02d}")
            print(json.dumps({"unit": unit, "status": result["status"], "failure": result.get("failure")}), flush=True)
            if result["status"] == "infrastructure":
                if len(attempts) == 0:
                    result = run_attempt(config, unit, root / "attempt-02")
                if result["status"] == "infrastructure":
                    raise RuntimeError(f"infrastructure retry exhausted: {unit_name(unit)}: {result.get('error')}")
            if result["status"] == "runner_error":
                raise RuntimeError(f"runner error: {unit_name(unit)}: {result.get('error')}")


if __name__ == "__main__":
    main()
