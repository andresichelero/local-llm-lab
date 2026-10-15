"""Isolated prefix caching paired experiment (Roadmap Tarefa 6A).

Evaluates whether prefix caching (--cache-prompt) in llama-server improves
wall-clock latency and prompt prefill token reuse in OpenCode multi-turn runs
without degrading strict task pass quality or contract compliance.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
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

from benchmark.harness_eval import GRADER_PROTOCOL_VERSION, grade_workspace  # noqa: E402
from benchmark.harness_runner import (  # noqa: E402
    _isolated_environment,
    _prepare_run,
    _read_jsonl,
    parse_server_prompt_eval_tokens,
    summarize_resources,
    summarize_usage,
)
from benchmark.provenance import git_provenance  # noqa: E402
from benchmark.safe_execution_guard import block_legacy_execution  # noqa: E402

EXPERIMENT = "prefix-cache-paired-20261012-6a"
HARNESS = "opencode"
HARNESS_VERSION = "1.19.0"
RUNTIME_REVISION = "d81235049384534c167caea52b85a694f6103d14"
SERVER_PORT = 8080
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
CONTEXT = 16384
MAX_PRIMARY_STEPS = 20
TASK_LIMIT_SECONDS = 180
ROUND_LIMIT_SECONDS = 45 * 60  # 45-minute total round cap per roadmap

# 2 distinct verified tasks, 3 pairs off/on each = 12 measured trials
TASKS = ("calculator_division", "dotenv_line_parser")
PAIRS_PER_TASK = 3
MODEL_KEY = "qwen3.5-4b"

MODELS: dict[str, dict[str, str]] = {
    "qwen3.5-4b": {
        "alias": "Qwen3.5-4B-Q4_K_M",
        "revision": "4168f45a16a1290d65a4ec0fa312ae917a4c15d6",
        "path": "models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf",
        "sha256": "13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983",
    },
}


def build_schedule() -> list[dict[str, Any]]:
    """Build the 12-trial balanced paired schedule (2 tasks x 3 pairs off/on)."""
    schedule: list[dict[str, Any]] = []
    trial_num = 1
    for pair_idx in range(1, PAIRS_PER_TASK + 1):
        for task in TASKS:
            # Alternating order: off then on, or on then off for balance
            modes = [False, True] if pair_idx % 2 == 1 else [True, False]
            for cache_enabled in modes:
                schedule.append({
                    "trial": trial_num,
                    "task": task,
                    "pair": pair_idx,
                    "cache_prompt": cache_enabled,
                    "model": MODEL_KEY,
                })
                trial_num += 1
    return schedule


def server_command(server: Path, model_path: Path, model: str, *, cache_prompt: bool) -> list[str]:
    cache_flag = "--cache-prompt" if cache_prompt else "--no-cache-prompt"
    return [
        str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(SERVER_PORT),
        "--alias", MODELS[model]["alias"], "--ctx-size", str(CONTEXT), "--n-gpu-layers", "99",
        "--batch-size", "512", "--ubatch-size", "256", "--flash-attn", "on",
        "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--reasoning", "off",
        cache_flag, "--parallel", "1", "--no-webui"
    ]


def build_profile(model: str) -> dict[str, Any]:
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


def run_single_trial(
    binary: Path,
    install_root: Path,
    model: str,
    task: str,
    cache_prompt: bool,
    pair_num: int,
    output_root: Path,
    server_log: Path,
    round_deadline: float,
) -> dict[str, Any]:
    block_legacy_execution("benchmark.prefix_cache_paired.run_single_trial")
    info = MODELS[model]
    mode_label = "cache_on" if cache_prompt else "cache_off"
    run_dir = output_root / "runs" / task / f"pair_{pair_num}_{mode_label}"
    run_dir.mkdir(parents=True, exist_ok=False)
    
    fixture_rel, prompt_rel = __import__("benchmark.harness_runner", fromlist=["resolve_task"]).resolve_task(task)
    prompt = prompt_rel.read_text(encoding="utf-8").strip()
    _prepare_run("opencode", run_dir, install_root, prompt, info["alias"], SERVER_URL, CONTEXT, fixture=fixture_rel)
    
    profile = build_profile(model)
    profile_path = run_dir / "home/.config/opencode/opencode.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    
    env = _isolated_environment("opencode", run_dir, install_root, run_dir / "workspace")
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    
    workspace = run_dir / "workspace"
    event_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    resource_path = run_dir / "resources.jsonl"
    
    command = [
        str(binary), "run", "--format", "json", "--agent", "build", "--model",
        f"local/{info['alias']}", "--dir", str(workspace), prompt
    ]
    
    start = time.monotonic()
    timed_out = False
    return_code: int | None = None
    proc: subprocess.Popen[Any] | None = None
    sampler: subprocess.Popen[Any] | None = None
    stop_reason: str | None = None
    server_log_offset = server_log.stat().st_size if server_log.exists() else 0
    
    try:
        with event_path.open("w", encoding="utf-8") as events_out, stderr_path.open("w", encoding="utf-8") as errors_out:
            proc = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.DEVNULL, stdout=events_out, stderr=errors_out, start_new_session=True)
            sampler = subprocess.Popen([sys.executable, str(REPO_ROOT / "benchmark/resource_sampler.py"), "--output",
                                        str(resource_path), "--interval", "1"], cwd=workspace, env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            while proc.poll() is None:
                if time.monotonic() >= round_deadline:
                    stop_reason = "round_deadline"
                    break
                if time.monotonic() - start >= TASK_LIMIT_SECONDS:
                    timed_out = True
                    stop_reason = "task_timeout"
                    break
                time.sleep(0.25)
            if stop_reason:
                _kill_process_group(proc, grace_seconds=4)
            return_code = proc.wait()
    finally:
        if proc is not None:
            _kill_process_group(proc, grace_seconds=4)
        if sampler is not None:
            _kill_process_group(sampler, grace_seconds=3)
        # Clean up ephemeral node_modules to preserve disk space
        shutil.rmtree(run_dir / "home/.config/opencode/node_modules", ignore_errors=True)
        
    wall = round(time.monotonic() - start, 3)
    events = _read_jsonl(event_path)
    
    # Independent grade
    try:
        grade = grade_workspace(workspace, fixture_rel, task=task, artifact_dir=run_dir / "grader-artifacts")
        quality_ok = bool(grade.get("success", False))
    except Exception as err:
        grade = {"success": False, "grader_error": f"{type(err).__name__}: {err}"}
        quality_ok = False
        
    usage = summarize_usage("opencode", events)
    server_segment = server_log.read_bytes()[server_log_offset:].decode("utf-8", errors="replace") if server_log.exists() else ""
    prefill_tokens = parse_server_prompt_eval_tokens(server_segment)
    
    return {
        "experiment": EXPERIMENT,
        "model": model,
        "task": task,
        "pair": pair_num,
        "cache_prompt": cache_prompt,
        "return_code": return_code,
        "timed_out": timed_out,
        "stop_reason": stop_reason,
        "task_wall_seconds": wall,
        "strict_pass": quality_ok,
        "grade": grade,
        "usage": usage,
        "server_prefill_tokens": prefill_tokens,
        "resource_summary": summarize_resources(_read_jsonl(resource_path)),
        "run_dir": str(run_dir),
    }


def _kill_process_group(proc: subprocess.Popen[Any], *, grace_seconds: int = 4) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    deadline = time.monotonic() + grace_seconds
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


def summarize_prefix_cache_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate paired comparison between cache off and on."""
    summary: dict[str, Any] = {}
    for task in TASKS:
        off_rows = [r for r in records if r["task"] == task and not r["cache_prompt"]]
        on_rows = [r for r in records if r["task"] == task and r["cache_prompt"]]
        
        off_walls = [r["task_wall_seconds"] for r in off_rows if r.get("task_wall_seconds") is not None]
        on_walls = [r["task_wall_seconds"] for r in on_rows if r.get("task_wall_seconds") is not None]
        
        summary[task] = {
            "cache_off": {
                "attempts": len(off_rows),
                "passes": sum(bool(r.get("strict_pass")) for r in off_rows),
                "wall_median": statistics.median(off_walls) if off_walls else None,
                "wall_min": min(off_walls) if off_walls else None,
                "wall_max": max(off_walls) if off_walls else None,
            },
            "cache_on": {
                "attempts": len(on_rows),
                "passes": sum(bool(r.get("strict_pass")) for r in on_rows),
                "wall_median": statistics.median(on_walls) if on_walls else None,
                "wall_min": min(on_walls) if on_walls else None,
                "wall_max": max(on_walls) if on_walls else None,
            },
            "wall_speedup": (
                round(statistics.median(off_walls) / statistics.median(on_walls), 3)
                if off_walls and on_walls and statistics.median(on_walls) > 0 else None
            ),
        }
    return summary


def run_series(
    install_root: Path,
    output_root: Path,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    schedule = build_schedule()
    if dry_run:
        print(f"[dry-run] Planned {len(schedule)} prefix-cache trials:")
        for item in schedule:
            print(f"  Trial {item['trial']}: task={item['task']}, pair={item['pair']}, cache_prompt={item['cache_prompt']}")
        return schedule

    block_legacy_execution("benchmark.prefix_cache_paired.run_series")

    install_root = install_root.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    server = install_root / "tools/llama-bin/llama-server"
    binary = install_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    model_path = install_root / MODELS[MODEL_KEY]["path"]

    protocol = {
        "experiment": EXPERIMENT,
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
        "runtime_revision": RUNTIME_REVISION,
        "model": MODEL_KEY,
        "tasks": list(TASKS),
        "schedule": schedule,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    protocol["source_git_sha"], protocol["source_tree_dirty"] = git_provenance(REPO_ROOT)
    (output_root / "protocol.json").write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")

    round_deadline = time.monotonic() + ROUND_LIMIT_SECONDS
    records: list[dict[str, Any]] = []

    for item in schedule:
        if time.monotonic() >= round_deadline:
            record = {**item, "strict_pass": False, "stop_reason": "round_deadline"}
            records.append(record)
            continue

        cache_mode = item["cache_prompt"]
        trial_id = item["trial"]
        task = item["task"]
        pair_num = item["pair"]

        server_log = output_root / f"llama-server-trial-{trial_id}-{task}-cache-{cache_mode}.log"
        cmd = server_command(server, model_path, MODEL_KEY, cache_prompt=cache_mode)
        server_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
            "LD_LIBRARY_PATH": str(install_root / "tools/llama-bin"),
            "HOME": str(install_root),
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
        }

        # Start server
        print(f"[prefix-cache] Starting trial {trial_id}/{len(schedule)}: task={task}, pair={pair_num}, cache_prompt={cache_mode}")
        log_f = server_log.open("w", encoding="utf-8")
        server_proc = subprocess.Popen(cmd, env=server_env, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True)
        
        try:
            # Wait for ready
            for _ in range(60):
                if server_proc.poll() is not None:
                    raise RuntimeError(f"Server crashed during load: exit code {server_proc.returncode}")
                try:
                    with urllib.request.urlopen(f"{SERVER_URL}/v1/models", timeout=1) as res:
                        if res.status == 200:
                            break
                except Exception:
                    time.sleep(0.5)
            else:
                raise RuntimeError("Server failed to start within 30s timeout")

            # Execute trial
            record = run_single_trial(
                binary, install_root, MODEL_KEY, task, cache_mode,
                pair_num, output_root, server_log, round_deadline
            )
            record["trial"] = trial_id
            records.append(record)
            print(f"[prefix-cache] Trial {trial_id} completed: pass={record.get('strict_pass')}, wall={record.get('task_wall_seconds')}s, prefill_tokens={record.get('server_prefill_tokens')}")

            with (output_root / "records.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(record) + "\n")
            (output_root / "records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        finally:
            _kill_process_group(server_proc, grace_seconds=5)
            log_f.close()

    (output_root / "summary.json").write_text(
        json.dumps(summarize_prefix_cache_results(records), indent=2) + "\n", encoding="utf-8"
    )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Execute inference on local SSD")
    parser.add_argument("--dry-run", action="store_true", help="Print schedule and exit")
    parser.add_argument("--install-root", type=Path, default=Path("/home/foxtrot/local-llm-benchmark"))
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()

    if not args.execute and not args.dry_run:
        parser.print_help()
        sys.exit(1)

    if args.dry_run:
        run_series(args.install_root, Path("/tmp/dry-run"), dry_run=True)
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = args.output_root or (args.install_root / "results/raw" / f"{EXPERIMENT}-{stamp}")
    run_series(args.install_root, out_dir, dry_run=False)


if __name__ == "__main__":
    main()
