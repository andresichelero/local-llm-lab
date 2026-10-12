"""Paired agentic evaluation of MTP (Multi-Token Prediction) vs standard decoding.

Milestone M4 Task 6B (Roadmap 2026-10-12):
Evaluates speculative decoding via draft-mtp (n-draft=3) against standard autoregressive
decoding in real multi-turn OpenCode agent runs across 2 discriminant tasks
(calculator_division and retry_policy).
Measures TTFT, token acceptance, speedup, memory, and functional pass quality.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
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

from benchmark.harness_eval import grade_workspace
from benchmark.harness_runner import (
    DEFAULT_CONTEXT,
    DEFAULT_SERVER_URL,
    _isolated_environment,
    _prepare_run,
    _read_jsonl,
    parse_server_prompt_eval_tokens,
    summarize_resources,
    summarize_usage,
)
from benchmark.provenance import git_provenance

EXPERIMENT = "mtp-agentic-paired-20261012-6b"
HARNESS = "opencode"
HARNESS_VERSION = "1.19.0"
RUNTIME_REVISION = "d81235049384534c167caea52b85a694f6103d14"
SERVER_PORT = 8080
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
CONTEXT = 16384
MAX_PRIMARY_STEPS = 20
TASK_LIMIT_SECONDS = 180
ROUND_LIMIT_SECONDS = 45 * 60

TASKS = ("calculator_division", "retry_policy")
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

_PROMETHEUS_ROW = re.compile(
    r"^([A-Za-z_:][A-Za-z0-9_:]*)(?:\{[^}]*\})?\s+"
    r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$"
)


def parse_prometheus_counters(text: str) -> dict[str, float]:
    """Parse Prometheus metric lines into name -> float value mapping."""
    counters: dict[str, float] = {}
    for line in text.splitlines():
        match = _PROMETHEUS_ROW.match(line.strip())
        if not match:
            continue
        value = float(match.group(2))
        if math.isfinite(value):
            counters[match.group(1)] = value
    return counters


def fetch_prometheus_counters(server_url: str = SERVER_URL) -> dict[str, float]:
    """Query /metrics from the llama-server instance."""
    try:
        req = urllib.request.Request(f"{server_url}/metrics")
        with urllib.request.urlopen(req, timeout=3) as res:
            text = res.read().decode("utf-8", errors="replace")
            return parse_prometheus_counters(text)
    except Exception:
        return {}


def build_schedule() -> list[dict[str, Any]]:
    """Build the 12-trial balanced paired schedule (2 tasks x 3 pairs off/on)."""
    schedule: list[dict[str, Any]] = []
    trial_num = 1
    for pair_idx in range(1, PAIRS_PER_TASK + 1):
        for task in TASKS:
            modes = [False, True] if pair_idx % 2 == 1 else [True, False]
            for mtp_enabled in modes:
                schedule.append({
                    "trial": trial_num,
                    "task": task,
                    "pair": pair_idx,
                    "mtp": mtp_enabled,
                    "model": MODEL_KEY,
                })
                trial_num += 1
    return schedule


def server_command(server: Path, model_path: Path, model: str, *, mtp: bool) -> list[str]:
    """Construct llama-server command line with or without draft-mtp."""
    spec_args = [
        "--spec-type", "draft-mtp",
        "--spec-draft-n-max", "3",
        "--spec-draft-type-k", "f16",
        "--spec-draft-type-v", "f16",
    ] if mtp else [
        "--spec-type", "none",
    ]
    return [
        str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(SERVER_PORT),
        "--alias", MODELS[model]["alias"], "--ctx-size", str(CONTEXT), "--n-gpu-layers", "99",
        "--batch-size", "512", "--ubatch-size", "256", "--flash-attn", "on",
        "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--reasoning", "off",
        "--cache-prompt", "--parallel", "1", "--no-webui", "--metrics",
        *spec_args,
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
    mtp: bool,
    pair_num: int,
    output_root: Path,
    server_log: Path,
    round_deadline: float,
) -> dict[str, Any]:
    info = MODELS[model]
    mode_label = "mtp_on" if mtp else "mtp_off"
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

    counters_before = fetch_prometheus_counters(SERVER_URL)
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
        shutil.rmtree(run_dir / "home/.config/opencode/node_modules", ignore_errors=True)

    wall = round(time.monotonic() - start, 3)
    counters_after = fetch_prometheus_counters(SERVER_URL)
    events = _read_jsonl(event_path)

    try:
        grade = grade_workspace(workspace, fixture_rel, task=task)
        quality_ok = bool(grade.get("success", False))
    except Exception as err:
        grade = {"success": False, "grader_error": f"{type(err).__name__}: {err}"}
        quality_ok = False

    usage = summarize_usage("opencode", events)
    server_segment = server_log.read_bytes()[server_log_offset:].decode("utf-8", errors="replace") if server_log.exists() else ""
    prefill_tokens = parse_server_prompt_eval_tokens(server_segment)

    drafted = int(counters_after.get("llamacpp:spec_decode_num_draft_tokens_total", 0.0) -
                  counters_before.get("llamacpp:spec_decode_num_draft_tokens_total", 0.0))
    accepted = int(counters_after.get("llamacpp:spec_decode_num_accepted_tokens_total", 0.0) -
                   counters_before.get("llamacpp:spec_decode_num_accepted_tokens_total", 0.0))
    drafts = int(counters_after.get("llamacpp:spec_decode_num_drafts_total", 0.0) -
                 counters_before.get("llamacpp:spec_decode_num_drafts_total", 0.0))
    acceptance_rate = round(accepted / drafted, 4) if drafted > 0 else None

    return {
        "experiment": EXPERIMENT,
        "model": model,
        "task": task,
        "pair": pair_num,
        "mtp": mtp,
        "return_code": return_code,
        "timed_out": timed_out,
        "stop_reason": stop_reason,
        "task_wall_seconds": wall,
        "strict_pass": quality_ok,
        "grade": grade,
        "usage": usage,
        "speculative_counters": {
            "drafted_tokens": drafted,
            "accepted_tokens": accepted,
            "verification_steps": drafts,
            "acceptance_rate": acceptance_rate,
        },
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


def summarize_mtp_agentic_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate paired comparison between mtp off and on."""
    summary: dict[str, Any] = {}
    for task in TASKS:
        off_rows = [r for r in records if r["task"] == task and not r.get("mtp")]
        on_rows = [r for r in records if r["task"] == task and r.get("mtp")]

        off_walls = [r["task_wall_seconds"] for r in off_rows if r.get("task_wall_seconds") is not None]
        on_walls = [r["task_wall_seconds"] for r in on_rows if r.get("task_wall_seconds") is not None]

        on_drafted = sum((r.get("speculative_counters") or {}).get("drafted_tokens", 0) for r in on_rows)
        on_accepted = sum((r.get("speculative_counters") or {}).get("accepted_tokens", 0) for r in on_rows)
        on_rate = round(on_accepted / on_drafted, 4) if on_drafted > 0 else None

        summary[task] = {
            "mtp_off": {
                "attempts": len(off_rows),
                "passes": sum(bool(r.get("strict_pass")) for r in off_rows),
                "wall_median": statistics.median(off_walls) if off_walls else None,
                "wall_min": min(off_walls) if off_walls else None,
                "wall_max": max(off_walls) if off_walls else None,
            },
            "mtp_on": {
                "attempts": len(on_rows),
                "passes": sum(bool(r.get("strict_pass")) for r in on_rows),
                "wall_median": statistics.median(on_walls) if on_walls else None,
                "wall_min": min(on_walls) if on_walls else None,
                "wall_max": max(on_walls) if on_walls else None,
                "total_drafted_tokens": on_drafted,
                "total_accepted_tokens": on_accepted,
                "overall_acceptance_rate": on_rate,
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
        print(f"[dry-run] Planned {len(schedule)} mtp-agentic trials:")
        for item in schedule:
            print(f"  Trial {item['trial']}: task={item['task']}, pair={item['pair']}, mtp={item['mtp']}")
        return schedule

    install_root = install_root.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    server = install_root / "tools/llama-bin/llama-server"
    binary = install_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
    model_path = install_root / MODELS[MODEL_KEY]["path"]

    protocol = {
        "experiment": EXPERIMENT,
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

        mtp_mode = item["mtp"]
        trial_id = item["trial"]
        task = item["task"]
        pair_num = item["pair"]

        server_log = output_root / f"llama-server-trial-{trial_id}-{task}-mtp-{mtp_mode}.log"
        cmd = server_command(server, model_path, MODEL_KEY, mtp=mtp_mode)
        server_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
            "LD_LIBRARY_PATH": str(install_root / "tools/llama-bin"),
            "HOME": str(install_root),
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
        }

        print(f"[mtp-agentic] Starting trial {trial_id}/{len(schedule)}: task={task}, pair={pair_num}, mtp={mtp_mode}")
        log_f = server_log.open("w", encoding="utf-8")
        server_proc = subprocess.Popen(cmd, env=server_env, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True)

        try:
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

            record = run_single_trial(
                binary, install_root, MODEL_KEY, task, mtp_mode,
                pair_num, output_root, server_log, round_deadline
            )
            record["trial"] = trial_id
            records.append(record)
            print(f"[mtp-agentic] Trial {trial_id} completed: pass={record.get('strict_pass')}, wall={record.get('task_wall_seconds')}s, "
                  f"drafted={record.get('speculative_counters', {}).get('drafted_tokens')}, accepted={record.get('speculative_counters', {}).get('accepted_tokens')}")

            with (output_root / "records.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(record) + "\n")
            (output_root / "records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        finally:
            _kill_process_group(server_proc, grace_seconds=5)
            log_f.close()

    (output_root / "summary.json").write_text(
        json.dumps(summarize_mtp_agentic_results(records), indent=2) + "\n", encoding="utf-8"
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
