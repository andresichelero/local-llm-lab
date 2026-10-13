"""Controlled Candidate Admission Paired Runner (Milestone M5 Tarefa 7).

Evaluates newly admitted candidate model (Gemma-4-E4B-it-qat UD-Q4_K_XL) against
control (Qwen3.5-4B-Q4_K_M) across 2 non-saturated tasks (calculator_division, dotenv_line_parser)
with 3 paired repetitions (12 measured trials).
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

from benchmark.harness_eval import grade_workspace  # noqa: E402
from benchmark.harness_runner import (  # noqa: E402
    _isolated_environment,
    _prepare_run,
    _read_jsonl,
    parse_server_prompt_eval_tokens,
    summarize_resources,
    summarize_usage,
)
from benchmark.provenance import git_provenance  # noqa: E402

DEFAULT_EXPERIMENT = "candidate-admission-granite-8b-20261012"
HARNESS = "opencode"
HARNESS_VERSION = "1.19.0"
RUNTIME_REVISION = "d81235049384534c167caea52b85a694f6103d14"
SERVER_PORT = 8080
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
CONTEXT = 16384
MAX_PRIMARY_STEPS = 20
TASK_LIMIT_SECONDS = 180
ROUND_LIMIT_SECONDS = 45 * 60

DEFAULT_TASKS = ("retry_policy", "dotenv_line_parser")
REPEATS_PER_TASK = 3

MODELS: dict[str, dict[str, str]] = {
    "qwen3.5-4b": {
        "alias": "Qwen3.5-4B-Q4_K_M",
        "revision": "4168f45a16a1290d65a4ec0fa312ae917a4c15d6",
        "path": "models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf",
        "sha256": "13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983",
    },
    "granite-4.1-8b": {
        "alias": "granite-4.1-8b-Q4_K_M",
        "revision": "865b82c2e7970d82e3731278c88c57ae7138359c",
        "path": "models/gguf/granite-4.1-8b/granite-4.1-8b-Q4_K_M.gguf",
        "sha256": "ed902ac9eb6adce5a90c6a08c8ea201b50e23fdc5976d1cd0362006afac5309e",
    },
    "gemma-4-e4b": {
        "alias": "gemma-4-E4B-it-qat-UD-Q4_K_XL",
        "revision": "8c5a9e4fd5482e2be20fe0bf013b4c262a8f4265",
        "path": "models/gguf/gemma-4-e4b/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf",
        "sha256": "df0fd4ee07072c607c29a0a1cb4f98918426cca12f45a2776bdd6ee6d09a4de3",
    },
}


def build_schedule(
    control: str = "qwen3.5-4b",
    candidate: str = "gemma-4-e4b",
    tasks: tuple[str, ...] = ("calculator_division", "dotenv_line_parser"),
    repeats: int = REPEATS_PER_TASK,
) -> list[dict[str, Any]]:
    """Build the balanced schedule (tasks x 2 models x repeats)."""
    schedule: list[dict[str, Any]] = []
    trial_num = 1
    blocks = []
    for r in range(repeats):
        if r % 2 == 0:
            blocks.append((control, candidate))
        else:
            blocks.append((candidate, control))

    for repeat_idx, (first_model, second_model) in enumerate(blocks, start=1):
        for task in tasks:
            for model_key in (first_model, second_model):
                schedule.append({
                    "trial": trial_num,
                    "task": task,
                    "model": model_key,
                    "repeat": repeat_idx,
                })
                trial_num += 1
    return schedule


def server_command(server: Path, model_path: Path, model: str) -> list[str]:
    return [
        str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(SERVER_PORT),
        "--alias", MODELS[model]["alias"], "--ctx-size", str(CONTEXT), "--n-gpu-layers", "99",
        "--batch-size", "512", "--ubatch-size", "256", "--flash-attn", "on",
        "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--reasoning", "off",
        "--cache-prompt", "--parallel", "1", "--no-webui", "--metrics",
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
    repeat: int,
    output_root: Path,
    server_log: Path,
    round_deadline: float,
    experiment: str = DEFAULT_EXPERIMENT,
) -> dict[str, Any]:
    info = MODELS[model]
    run_dir = output_root / "runs" / task / f"{model}_repeat_{repeat}"
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
        shutil.rmtree(run_dir / "home/.config/opencode/node_modules", ignore_errors=True)

    wall = round(time.monotonic() - start, 3)
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

    return {
        "experiment": experiment,
        "model": model,
        "task": task,
        "repeat": repeat,
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


def summarize_admission_results(
    records: list[dict[str, Any]],
    tasks: tuple[str, ...] | None = None,
    models: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate comparative summary between control and candidate."""
    if tasks is None:
        tasks = tuple(dict.fromkeys(r["task"] for r in records))
    if models is None:
        models = list(dict.fromkeys(r["model"] for r in records))
    summary: dict[str, Any] = {}
    for task in tasks:
        task_summary: dict[str, Any] = {}
        for model_key in models:
            rows = [r for r in records if r["task"] == task and r["model"] == model_key]
            walls = [r["task_wall_seconds"] for r in rows if r.get("task_wall_seconds") is not None]
            vram_peaks = [
                (r.get("resource_summary") or {}).get("vram_used_mb_peak")
                for r in rows
                if (r.get("resource_summary") or {}).get("vram_used_mb_peak") is not None
            ]
            task_summary[model_key] = {
                "attempts": len(rows),
                "passes": sum(bool(r.get("strict_pass")) for r in rows),
                "pass_rate": round(sum(bool(r.get("strict_pass")) for r in rows) / len(rows), 3) if rows else 0.0,
                "wall_median": statistics.median(walls) if walls else None,
                "wall_min": min(walls) if walls else None,
                "wall_max": max(walls) if walls else None,
                "vram_peak_max": max(vram_peaks) if vram_peaks else None,
            }
        summary[task] = task_summary
    return summary


def run_series(
    install_root: Path,
    output_root: Path,
    *,
    control: str = "qwen3.5-4b",
    candidate: str = "granite-4.1-8b",
    tasks: tuple[str, ...] = DEFAULT_TASKS,
    repeats: int = REPEATS_PER_TASK,
    experiment: str = DEFAULT_EXPERIMENT,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    schedule = build_schedule(control=control, candidate=candidate, tasks=tasks, repeats=repeats)
    if dry_run:
        print(f"[dry-run] Planned {len(schedule)} admission trials:")
        for item in schedule:
            print(f"  Trial {item['trial']}: task={item['task']}, model={item['model']}, repeat={item['repeat']}")
        return schedule

    install_root = install_root.resolve()
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)

    server = install_root / "tools/llama-bin/llama-server"
    binary = install_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"

    protocol = {
        "experiment": experiment,
        "runtime_revision": RUNTIME_REVISION,
        "control": control,
        "candidate": candidate,
        "models": [control, candidate],
        "tasks": list(tasks),
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

        model_key = item["model"]
        trial_id = item["trial"]
        task = item["task"]
        repeat = item["repeat"]

        model_path = install_root / MODELS[model_key]["path"]
        server_log = output_root / f"llama-server-trial-{trial_id}-{task}-{model_key}.log"
        cmd = server_command(server, model_path, model_key)
        server_env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/lib/wsl/lib",
            "LD_LIBRARY_PATH": str(install_root / "tools/llama-bin"),
            "HOME": str(install_root),
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
        }

        print(f"[admission] Starting trial {trial_id}/{len(schedule)}: task={task}, model={model_key}, repeat={repeat}")
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
                binary, install_root, model_key, task,
                repeat, output_root, server_log, round_deadline,
                experiment=experiment,
            )
            record["trial"] = trial_id
            records.append(record)
            print(f"[admission] Trial {trial_id} completed: model={model_key}, pass={record.get('strict_pass')}, wall={record.get('task_wall_seconds')}s")

            with (output_root / "records.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(record) + "\n")
            (output_root / "records.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        finally:
            _kill_process_group(server_proc, grace_seconds=5)
            log_f.close()

    (output_root / "summary.json").write_text(
        json.dumps(summarize_admission_results(records, tasks, [control, candidate]), indent=2) + "\n", encoding="utf-8"
    )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Execute inference on local SSD")
    parser.add_argument("--dry-run", action="store_true", help="Print schedule and exit")
    parser.add_argument("--control", default="qwen3.5-4b", choices=list(MODELS.keys()))
    parser.add_argument("--candidate", default="granite-4.1-8b", choices=list(MODELS.keys()))
    parser.add_argument("--tasks", nargs="+", default=list(DEFAULT_TASKS))
    parser.add_argument("--repeats", type=int, default=REPEATS_PER_TASK)
    parser.add_argument("--experiment", default=DEFAULT_EXPERIMENT)
    parser.add_argument("--install-root", type=Path, default=Path("/home/foxtrot/local-llm-benchmark"))
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()

    if not args.execute and not args.dry_run:
        parser.print_help()
        sys.exit(1)

    tasks_tuple = tuple(args.tasks)
    if args.dry_run:
        run_series(
            args.install_root, Path("/tmp/dry-run"),
            control=args.control, candidate=args.candidate,
            tasks=tasks_tuple, repeats=args.repeats,
            experiment=args.experiment, dry_run=True,
        )
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = args.output_root or (args.install_root / "results/raw" / f"{args.experiment}-{stamp}")
    run_series(
        args.install_root, out_dir,
        control=args.control, candidate=args.candidate,
        tasks=tasks_tuple, repeats=args.repeats,
        experiment=args.experiment, dry_run=False,
    )


if __name__ == "__main__":
    main()
