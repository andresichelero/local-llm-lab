"""Dynamic Cascade Routing Matrix Runner (Roadmap Trilha A / Marco M6-M8).

Evaluates live agentic performance across 3 routing policies:
  1. always-4b: Tier 1 Qwen3.5-4B (with --cache-prompt and draft-mtp n=3)
  2. always-9b: Tier 2 Qwen3.5-9B (with --cache-prompt)
  3. dynamic-cascade: Starts on Tier 1 (4B cache+MTP); if turn 1 fails validation/contract,
     escalates to Tier 2 (9B cache) with live model swap timing.

Matrix: 6 discriminant tasks x 2 repeats x 3 policies = 36 measured trials.
Strict GPU leases, MiB resource sampling, and deterministic grading.
"""
from __future__ import annotations

import argparse
import json
import os
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
    summarize_resources,
    summarize_usage,
)
from benchmark.provenance import git_provenance  # noqa: E402
from benchmark.visible_feedback import (  # noqa: E402
    VisibleDevelopmentFeedback,
    collect_visible_feedback,
    is_visible_development_feedback,
)

EXPERIMENT = "cascade-routing-matrix-20261012-trilha-a"
HARNESS = "opencode"
HARNESS_VERSION = "1.19.0"
RUNTIME_REVISION = "d81235049384534c167caea52b85a694f6103d14"
SERVER_PORT = 8080
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
CONTEXT = 16384
MAX_PRIMARY_STEPS = 20
TASK_LIMIT_SECONDS = 180
ROUND_LIMIT_SECONDS = 120 * 60

POLICIES = ("always-4b", "always-9b", "dynamic-cascade")

TASKS = [
    "calculator_division",
    "whitespace_normalization",
    "dotenv_line_parser",
    "config_precedence",
    "retry_policy",
    "package_refactor",
]

MODELS: dict[str, dict[str, Any]] = {
    "qwen3.5-4b": {
        "alias": "Qwen3.5-4B-Q4_K_M",
        "path": "models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf",
        "cache_prompt": True,
        "mtp": True,
    },
    "qwen3.5-9b": {
        "alias": "Qwen3.5-9B-Q4_K_M",
        "path": "models/gguf/Qwen3.5-9B-Q4_K_M.gguf",
        "cache_prompt": True,
        "mtp": False,
    },
}


def build_schedule() -> list[dict[str, Any]]:
    """Builds the 36-trial matrix schedule in balanced blocks."""
    schedule: list[dict[str, Any]] = []
    trial_idx = 1
    # 2 repeats of each task across 3 policies
    for repeat in (1, 2):
        # Order policies differently per repeat to distribute any ordering effects
        policy_order = POLICIES if repeat == 1 else ("dynamic-cascade", "always-9b", "always-4b")
        for policy in policy_order:
            for task in TASKS:
                schedule.append({
                    "trial": trial_idx,
                    "repeat": repeat,
                    "policy": policy,
                    "task": task,
                })
                trial_idx += 1
    return schedule


def server_command(server: Path, model_path: Path, model_info: dict[str, Any]) -> list[str]:
    """Generates the llama-server invocation flags."""
    spec_args = [
        "--spec-type", "draft-mtp",
        "--spec-draft-n-max", "3",
        "--spec-draft-type-k", "f16",
        "--spec-draft-type-v", "f16",
    ] if model_info.get("mtp") else [
        "--spec-type", "none",
    ]
    cache_flag = "--cache-prompt" if model_info.get("cache_prompt") else "--no-cache-prompt"
    return [
        str(server), "--model", str(model_path), "--host", "127.0.0.1", "--port", str(SERVER_PORT),
        "--alias", model_info["alias"], "--ctx-size", str(CONTEXT), "--n-gpu-layers", "99",
        "--batch-size", "512", "--ubatch-size", "256", "--flash-attn", "on",
        "--cache-type-k", "q4_0", "--cache-type-v", "q4_0", "--reasoning", "off",
        cache_flag, "--parallel", "1", "--no-webui", "--metrics",
        *spec_args,
    ]


def decide_escalation(*, policy: str, initial_pass: bool) -> bool:
    """Decides if execution should escalate to Tier 2."""
    if policy == "dynamic-cascade":
        return not initial_pass
    return False


def build_profile(model_key: str) -> dict[str, Any]:
    alias = MODELS[model_key]["alias"]
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


class LlamaServerManager:
    """Manages serial execution and live swapping of llama-server on GPU."""

    def __init__(self, server_bin: Path, repo_root: Path, log_dir: Path) -> None:
        self.server_bin = server_bin
        self.repo_root = repo_root
        self.log_dir = log_dir
        self.current_model: str | None = None
        self.proc: subprocess.Popen[Any] | None = None

    def ensure_model(self, model_key: str) -> float:
        """Ensures the specified model is active. Returns swap duration in seconds if swapped."""
        if self.current_model == model_key and self.proc is not None and self.proc.poll() is None:
            return 0.0

        swap_start = time.monotonic()
        # Unload existing server
        if self.proc is not None:
            self.stop()

        info = MODELS[model_key]
        model_path = self.repo_root / info["path"]
        if not model_path.is_file():
            raise FileNotFoundError(f"Model file missing: {model_path}")

        cmd = server_command(self.server_bin, model_path, info)
        log_file = self.log_dir / f"server_{model_key}_{int(time.time())}.log"
        log_f = log_file.open("w", encoding="utf-8")
        server_env = os.environ.copy()
        server_env["CUDA_VISIBLE_DEVICES"] = "0"

        self.proc = subprocess.Popen(cmd, env=server_env, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True)

        # Wait for readiness
        ready = False
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                log_f.close()
                log_content = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else "No log"
                raise RuntimeError(f"Server exited unexpectedly with code {self.proc.returncode}. Log tail:\n{log_content[-1500:]}\nCommand: {' '.join(cmd)}")
            try:
                with urllib.request.urlopen(f"{SERVER_URL}/v1/models", timeout=1.0) as res:
                    if res.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.2)

        if not ready:
            self.stop()
            raise TimeoutError(f"Server failed to become ready for {model_key} within 45s")

        self.current_model = model_key
        return time.monotonic() - swap_start

    def stop(self) -> float:
        """Stops the running server cleanly and measures unload duration."""
        if self.proc is None:
            return 0.0
        unload_start = time.monotonic()
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        deadline = time.monotonic() + 4.0
        while self.proc.poll() is None:
            if time.monotonic() >= deadline:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
                break
            time.sleep(0.05)
        if self.proc.poll() is None:
            try:
                self.proc.wait(timeout=2.0)
            except Exception:
                pass
        self.proc = None
        self.current_model = None
        return time.monotonic() - unload_start


def build_repair_prompt(feedback: object) -> str:
    """Build repair feedback only from a validated visible-development result."""
    if not is_visible_development_feedback(feedback):
        diagnostic = "Visible development feedback is unavailable. Review the task and workspace tests."
    else:
        diagnostics = []
        if feedback["timed_out"]:
            diagnostics.append("Visible workspace tests timed out.")
        elif not feedback["passed"]:
            diagnostics.append("Visible workspace tests did not pass.")
        diagnostic = "\n".join(diagnostics)
        if feedback["output"]:
            diagnostic = f"{diagnostic}\n{feedback['output'][-4000:]}".strip()
        if not diagnostic:
            diagnostic = "Review the task requirements and workspace tests."
    return f"The previous attempt needs repair. Review these visible development results:\n{diagnostic}"


def run_single_trial(
    binary: Path,
    install_root: Path,
    server_mgr: LlamaServerManager,
    trial_info: dict[str, Any],
    output_root: Path,
    round_deadline: float,
) -> dict[str, Any]:
    policy = trial_info["policy"]
    task = trial_info["task"]
    repeat = trial_info["repeat"]
    trial_num = trial_info["trial"]

    output_root = output_root.resolve()
    run_dir = (output_root / "runs" / f"trial_{trial_num:02d}_{policy}_{task}_r{repeat}").resolve()
    if run_dir.exists():
        raise FileExistsError(f"Run output directory already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "tmp").mkdir()

    fixture_rel, prompt_rel = __import__("benchmark.harness_runner", fromlist=["resolve_task"]).resolve_task(task)
    prompt = prompt_rel.read_text(encoding="utf-8").strip()

    initial_model = "qwen3.5-4b" if policy in ("always-4b", "dynamic-cascade") else "qwen3.5-9b"
    swap_duration = server_mgr.ensure_model(initial_model)

    model_alias = MODELS[initial_model]["alias"]
    _prepare_run("opencode", run_dir, install_root, prompt, model_alias, SERVER_URL, CONTEXT, fixture=fixture_rel)

    profile = build_profile(initial_model)
    profile_path = run_dir / "home/.config/opencode/opencode.json"
    profile_path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")

    workspace = (run_dir / "workspace").resolve()
    env = _isolated_environment("opencode", run_dir, install_root, workspace)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"

    event_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    resource_path = run_dir / "resources.jsonl"

    command = [
        str(binary), "run", "--format", "json", "--agent", "build", "--model",
        f"local/{model_alias}", "--dir", str(workspace), prompt
    ]

    task_start = time.monotonic()
    sampler_cmd = [
        sys.executable,
        str(REPO_ROOT / "benchmark/resource_sampler.py"),
        "--output", str(resource_path),
        "--interval", "0.5",
    ]
    sampler = subprocess.Popen(sampler_cmd, cwd=workspace, start_new_session=True)

    agent_proc = subprocess.Popen(
        command,
        cwd=workspace,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=event_path.open("w", encoding="utf-8"),
        stderr=stderr_path.open("w", encoding="utf-8"),
        start_new_session=True,
    )

    agent_timed_out = False
    try:
        agent_exit_code = agent_proc.wait(timeout=TASK_LIMIT_SECONDS)
    except subprocess.TimeoutExpired:
        agent_timed_out = True
        agent_proc.kill()
        agent_exit_code = agent_proc.wait()

    try:
        sampler.terminate()
        sampler.wait(timeout=2.0)
    except Exception:
        sampler.kill()

    task_wall = time.monotonic() - task_start
    events = _read_jsonl(event_path)
    res_rows = _read_jsonl(resource_path)
    res_summary = summarize_resources(res_rows)
    usage = summarize_usage("opencode", events)
    agent_attempts: list[dict[str, Any]] = [{
        "model": initial_model,
        "exit_code": agent_exit_code,
        "timed_out": agent_timed_out,
    }]
    visible_feedback: VisibleDevelopmentFeedback = collect_visible_feedback(
        workspace,
        env=env,
    )
    initial_pass = (
        visible_feedback["passed"]
        and not visible_feedback["timed_out"]
        and visible_feedback["exit_code"] == 0
        and not agent_timed_out
        and agent_exit_code == 0
    )

    escalated = False
    escalation_swap = 0.0
    final_model = initial_model

    # Dynamic cascade escalation logic
    if decide_escalation(policy=policy, initial_pass=initial_pass):
        escalated = True
        final_model = "qwen3.5-9b"
        escalation_swap = server_mgr.ensure_model(final_model)
        m9_alias = MODELS[final_model]["alias"]

        # Update profile for 9B
        profile_9b = build_profile(final_model)
        profile_path.write_text(json.dumps(profile_9b, indent=2) + "\n", encoding="utf-8")

        # Run repair turn on 9B
        repair_prompt = build_repair_prompt(visible_feedback)
        repair_command = [
            str(binary), "run", "--format", "json", "--agent", "build", "--model",
            f"local/{m9_alias}", "--dir", str(workspace), repair_prompt
        ]
        repair_start = time.monotonic()
        repair_proc = subprocess.Popen(
            repair_command,
            cwd=workspace,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=event_path.open("a", encoding="utf-8"),
            stderr=stderr_path.open("a", encoding="utf-8"),
            start_new_session=True,
        )
        repair_timed_out = False
        try:
            repair_exit_code = repair_proc.wait(timeout=TASK_LIMIT_SECONDS)
        except subprocess.TimeoutExpired:
            repair_timed_out = True
            repair_proc.kill()
            repair_exit_code = repair_proc.wait()

        agent_attempts.append({
            "model": final_model,
            "exit_code": repair_exit_code,
            "timed_out": repair_timed_out,
        })

        repair_wall = time.monotonic() - repair_start
        task_wall += repair_wall + escalation_swap

        visible_feedback = collect_visible_feedback(
            workspace,
            env=env,
        )

    # The private evaluator runs once, after the final agent action and all routing decisions.
    grade = grade_workspace(workspace, fixture_rel, task=task)
    final_attempt = agent_attempts[-1]
    strict_pass = bool(
        grade.get("success", False)
        and visible_feedback["passed"]
        and visible_feedback["exit_code"] == 0
        and not visible_feedback["timed_out"]
        and final_attempt["exit_code"] == 0
        and not final_attempt["timed_out"]
    )

    return {
        "trial": trial_num,
        "policy": policy,
        "task": task,
        "repeat": repeat,
        "initial_model": initial_model,
        "final_model": final_model,
        "escalated": escalated,
        "agent_attempts": agent_attempts,
        "swap_duration_seconds": round(escalation_swap if escalated else swap_duration, 3),
        "strict_pass": strict_pass,
        "task_wall_seconds": round(task_wall, 3),
        "steps": usage.get("turns", 0),
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "peak_vram_mib": int(res_summary.get("vram_used_mb_peak") or res_summary.get("peak_gpu_memory_used_mib") or 0),
        "grade_details": grade,
    }


def summarize_cascade_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarizes metrics across policies and tasks."""
    policies_summary: dict[str, Any] = {}

    for policy in POLICIES:
        p_records = [r for r in records if r.get("policy") == policy]
        if not p_records:
            continue
        passes = [r for r in p_records if r.get("strict_pass")]
        escalations = [r for r in p_records if r.get("escalated")]
        walls = [r["task_wall_seconds"] for r in p_records if "task_wall_seconds" in r]
        vrams = [r["peak_vram_mib"] for r in p_records if "peak_vram_mib" in r and r["peak_vram_mib"] > 0]

        policies_summary[policy] = {
            "trials": len(p_records),
            "strict_pass_count": len(passes),
            "strict_pass_pct": round(len(passes) / len(p_records) * 100, 1),
            "median_wall_seconds": round(statistics.median(walls), 2) if walls else 0.0,
            "mean_wall_seconds": round(statistics.mean(walls), 2) if walls else 0.0,
            "escalation_count": len(escalations),
            "escalation_rate_pct": round(len(escalations) / len(p_records) * 100, 1),
            "peak_vram_mib": max(vrams) if vrams else 0,
        }

    git_sha, dirty = git_provenance(REPO_ROOT)
    return {
        "experiment": EXPERIMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha,
        "source_dirty": dirty,
        "total_trials": len(records),
        "policies": policies_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dynamic Cascade Routing Matrix Runner")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Print plan without running")
    parser.add_argument("--execute", action="store_true", help="Execute trials")
    parser.add_argument("--single-agent-release", action="store_true", help="Required confirmation")
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "results/raw/cascade-routing-evaluation-20261012")
    args = parser.parse_args()

    schedule = build_schedule()
    print(f"[{EXPERIMENT}] Scheduled {len(schedule)} trials across {len(POLICIES)} policies and {len(TASKS)} tasks.")

    if not args.execute:
        print("[cascade] Dry-run completed. Specify --execute and --single-agent-release to run.")
        return 0

    if not args.single_agent_release:
        print("[cascade] Error: --execute requires --single-agent-release.")
        return 1

    args.output_root = args.output_root.resolve()
    args.output_root.mkdir(parents=True, exist_ok=True)
    install_root = Path.home() / "local-llm-benchmark"
    server_bin = install_root / "tools/llama-bin/llama-server"
    binary = install_root / "envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"

    server_mgr = LlamaServerManager(server_bin, install_root, args.output_root)
    records: list[dict[str, Any]] = []

    try:
        for trial_info in schedule:
            print(f"[cascade] Trial {trial_info['trial']}/36: policy={trial_info['policy']} task={trial_info['task']} repeat={trial_info['repeat']}")
            rec = run_single_trial(binary, install_root, server_mgr, trial_info, args.output_root, time.monotonic() + ROUND_LIMIT_SECONDS)
            records.append(rec)
            print(f"  Result: pass={rec.get('strict_pass')}, wall={rec.get('task_wall_seconds')}s, escalated={rec.get('escalated')}")
            with (args.output_root / "records.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(rec) + "\n")
    finally:
        server_mgr.stop()

    summary = summarize_cascade_results(records)
    with (args.output_root / "summary.json").open("w", encoding="utf-8") as out:
        out.write(json.dumps(summary, indent=2) + "\n")
    print(f"[cascade] Complete. Summary written to {args.output_root / 'summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
