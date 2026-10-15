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
import shutil
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
from benchmark.process_control import ProcessGroupStopError, stop_process_group  # noqa: E402
from benchmark.run_observer import RunObserver, _is_secret  # noqa: E402
from benchmark.harness_runner import (  # noqa: E402
    _isolated_environment,
    _prepare_run,
    _read_jsonl,
    summarize_resources,
    summarize_usage,
)
from benchmark.provenance import git_provenance  # noqa: E402
from benchmark.safe_execution_guard import block_legacy_execution  # noqa: E402
from benchmark.visible_feedback import (  # noqa: E402
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
OBSERVABILITY_PROTOCOL_ID = "cascade-observer-v1-2026-10-13"

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
        block_legacy_execution("benchmark.cascade_routing_matrix.LlamaServerManager.ensure_model")
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


def _fixture_file_paths(root: Path) -> list[Path]:
    """Enumerate only ordinary files under the selected, fixed task fixture."""
    result: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            name for name in dirnames
            if not (Path(directory) / name).is_symlink()
            and name not in {".git", "node_modules", "__pycache__"}
            and not _is_secret(name)
        )
        for name in sorted(filenames):
            path = Path(directory) / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
            except OSError:
                continue
            if _is_secret(name):
                continue
            result.append(path)
    return sorted(result)


def _observer_manifest(
    *,
    task: str,
    fixture: Path,
    prompt_source: Path,
    prompt_copy: Path,
    run_dir: Path,
    profiles: dict[str, Path],
) -> dict[str, Any]:
    """Build provenance from a small explicit source/task/grader/scaffold list."""
    eval_suite = REPO_ROOT / "benchmark/eval_suites" / task
    source_paths = [
        REPO_ROOT / relative for relative in (
            "benchmark/cascade_routing_matrix.py",
            "benchmark/process_control.py",
            "benchmark/resource_sampler.py",
            "benchmark/run_observer.py",
            "benchmark/visible_feedback.py",
            "benchmark/harness_runner.py",
            "benchmark/guarded_edit.py",
            "benchmark/harness_eval.py",
            "benchmark/pristine_grading.py",
            "benchmark/restricted_python.py",
            "benchmark/configs/grading/fixture-fingerprints-v2.json",
        )
    ]
    config_template = REPO_ROOT / "benchmark/configs/harnesses/opencode-subagents.json"
    paths: list[tuple[str, Path]] = []
    paths.extend(("source", path) for path in source_paths)
    paths.extend(("task_fixture", path) for path in _fixture_file_paths(fixture))
    paths.append(("task", prompt_source))
    paths.append(("grader_suite", REPO_ROOT / "benchmark/eval_suites/__init__.py"))
    if eval_suite.is_dir():
        paths.extend(("grader_suite", path) for path in _fixture_file_paths(eval_suite))
    paths.extend(("scaffold", path) for path in [config_template, prompt_copy, *profiles.values()])

    hash_allowlist = []
    for category, path in paths:
        try:
            relative = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        except ValueError:
            relative = f"run-artifacts/{path.name}"
        if path.is_relative_to(run_dir):
            relative = "run-artifacts/" + path.relative_to(run_dir).as_posix()
        hash_allowlist.append({"category": category, "path": relative, "file": path})

    snapshot_hash_allowlist = [path.relative_to(fixture).as_posix() for path in _fixture_file_paths(fixture)]
    declared_models = {
        key: {
            "identity": {"value": MODELS[key]["alias"], "status": "declared_only"},
            "artifact_sha256": {
                "value": None, "status": "unavailable", "reason": "not_hashed_by_observer_v1",
            },
            "quantization": {"value": "Q4_K_M", "status": "declared_only"},
        }
        for key in ("qwen3.5-4b", "qwen3.5-9b")
    }
    try:
        git_sha, source_tree_dirty = git_provenance(REPO_ROOT)
        source_revision = {"value": git_sha, "status": "measured"}
        source_dirty = {"value": source_tree_dirty, "status": "measured"}
    except Exception:
        source_revision = {"value": None, "status": "unavailable", "reason": "git_provenance_failed"}
        source_dirty = {"value": None, "status": "unavailable", "reason": "git_provenance_failed"}

    return {
        "schema_version": "1",
        "protocol_id": OBSERVABILITY_PROTOCOL_ID,
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
        "experiment": EXPERIMENT,
        "task_id": task,
        "fixture_id": fixture.relative_to(REPO_ROOT).as_posix(),
        "grader_id": f"benchmark/pristine_grading.py:{GRADER_PROTOCOL_VERSION}:{task}",
        "scaffold_id": "opencode-build-agent-cascade",
        "generated_profiles": ["initial", "repair"],
        "harness": {"name": HARNESS, "version": HARNESS_VERSION, "status": "declared_only"},
        "source_revision": source_revision,
        "source_tree_dirty": source_dirty,
        "runtime": {
            "python_version": sys.version.split()[0], "status": "verified",
            "agent_runtime": {"value": None, "status": "unavailable"},
            "llama_runtime_revision": {"value": RUNTIME_REVISION, "status": "declared_only"},
        },
        "hardware": {"identity": None, "status": "unavailable"},
        "models": declared_models,
        "declared_configuration": {
            "context_tokens": {"value": CONTEXT, "status": "declared_only"},
            "temperature": {"value": 0, "status": "declared_only"},
            "seed": {"value": 1234, "status": "declared_only"},
            "max_primary_steps": {"value": MAX_PRIMARY_STEPS, "status": "declared_only"},
            "model_endpoint": {"value": "127.0.0.1:8080/v1", "status": "declared_only"},
            "network_policy": {"value": None, "status": "unavailable"},
        },
        "coverage": {
            "resource_scope": "system_wide",
            "resource_phases": ["initial_agent", "repair_agent"],
            "uncovered_phases": ["model_transition", "grading"],
            "process_tree": "not_collected",
            "network": "not_collected",
            "sandbox_boundary": "unavailable",
            "observer_file_isolation": "unavailable_same_user_process",
            "native_tool_call_coverage": "incomplete_raw_streams_only",
            "general_workspace_content_diff": "not_collected",
            "training_exposure": "unavailable",
            "observer_overhead": "not_measured",
        },
        "suite_role": "regression",
        "capability_evidence_eligible": False,
        "filesystem_enforced": False,
        "network_enforced": False,
        "pristine_regrade": True,
        "private_holdout": False,
        "hash_allowlist": hash_allowlist,
        "snapshot_hash_allowlist": snapshot_hash_allowlist,
    }


def run_single_trial(
    binary: Path,
    install_root: Path,
    server_mgr: LlamaServerManager,
    trial_info: dict[str, Any],
    output_root: Path,
    round_deadline: float,
) -> dict[str, Any]:
    block_legacy_execution("benchmark.cascade_routing_matrix.run_single_trial")
    policy = trial_info["policy"]
    task = trial_info["task"]
    repeat = trial_info["repeat"]
    trial_num = trial_info["trial"]
    total_start = time.monotonic()
    output_root = output_root.resolve()
    run_dir = (output_root / "runs" / f"trial_{trial_num:02d}_{policy}_{task}_r{repeat}").resolve()
    if run_dir.exists():
        raise FileExistsError(f"Run output directory already exists: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "tmp").mkdir()

    from benchmark.harness_runner import resolve_task

    fixture_rel, prompt_rel = resolve_task(task)
    prompt = prompt_rel.read_text(encoding="utf-8").strip()
    initial_model = "qwen3.5-4b" if policy in ("always-4b", "dynamic-cascade") else "qwen3.5-9b"
    final_model = initial_model
    workspace = (run_dir / "workspace").resolve()
    event_path = run_dir / "events.jsonl"
    stderr_path = run_dir / "stderr.log"
    resource_path = run_dir / "resources.jsonl"
    profiles_dir = run_dir / "observer-scaffold"
    profiles_dir.mkdir()
    profiles = {
        "initial": profiles_dir / "initial-profile.json",
        "repair": profiles_dir / "repair-profile.json",
    }
    for key, model in (("initial", initial_model), ("repair", "qwen3.5-9b")):
        profiles[key].write_text(json.dumps(build_profile(model), indent=2) + "\n", encoding="utf-8")

    _prepare_run(
        HARNESS, run_dir, install_root, prompt, MODELS[initial_model]["alias"], SERVER_URL,
        CONTEXT, fixture=fixture_rel,
    )
    prompt_copy = run_dir / "TASK_PROMPT.md"
    profile_path = run_dir / "home/.config/opencode/opencode.json"
    shutil.copyfile(profiles["initial"], profile_path)
    env = _isolated_environment(HARNESS, run_dir, install_root, workspace)
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"

    # Construction and manifest creation are fail-closed: nothing agent-controlled has started.
    observer = RunObserver(
        run_dir,
        _observer_manifest(
            task=task,
            fixture=fixture_rel,
            prompt_source=prompt_rel,
            prompt_copy=prompt_copy,
            run_dir=run_dir,
            profiles=profiles,
        ),
    )
    evidence_complete = [True]
    evidence_errors: list[dict[str, str]] = []
    phase_durations: dict[str, float] = {}

    def observe(method: str, *args: Any, component: str, phase_id: str | None = None,
                required: bool = False, **kwargs: Any) -> Any:
        try:
            return getattr(observer, method)(*args, **kwargs)
        except Exception as exc:
            evidence_complete[0] = False
            error_type = type(exc).__name__[:80]
            evidence_errors.append({"component": component, "error_type": error_type})
            try:
                observer.record(
                    "evidence_error", phase_id, source="observer",
                    details={"component": component, "error_type": error_type},
                )
            except Exception:
                pass
            if required:
                raise RuntimeError("pre-launch observer evidence could not be recorded") from exc
            return None

    setup_phase = observe(
        "start_phase", "setup", source="cascade", component="observer", required=True,
    )
    setup_start = time.monotonic()
    try:
        swap_duration = server_mgr.ensure_model(initial_model)
        shutil.copyfile(profiles["initial"], profile_path)
        observe(
            "end_phase", setup_phase, "completed", source="cascade", component="observer",
            required=True, details={"duration_ns": int((time.monotonic() - setup_start) * 1e9)},
        )
    except Exception as exc:
        observe(
            "end_phase", setup_phase, "failed", source="cascade", component="observer",
        )
        observe("finalize", "error", "incomplete", source="cascade", component="observer",
                error=type(exc).__name__)
        raise
    phase_durations["setup"] = time.monotonic() - setup_start

    def snapshot(label: str, agent_id: str, *, required: bool = False) -> bool:
        result = observe(
            "snapshot", label, workspace, agent_id=agent_id, parent_agent_id="cascade-runner",
            source="cascade",
            component="snapshot", phase_id="initial_agent" if "initial_agent" in label else "repair_agent",
            required=required,
        )
        complete = isinstance(result, dict) and result.get("status") == "complete"
        if not complete:
            evidence_complete[0] = False
            if required:
                raise RuntimeError("pre-launch workspace snapshot is incomplete")
        return complete

    def stop_owned(
        process: subprocess.Popen[Any], *, timed_out: bool, grace_seconds: float = 0.5,
    ) -> tuple[int | None, bool]:
        try:
            if hasattr(process, "pid"):
                code = stop_process_group(process, grace_seconds=grace_seconds)
            elif timed_out:
                process.kill()
                code = process.wait()
            else:
                code = process.wait()
            return code, True
        except ProcessGroupStopError as exc:
            evidence_complete[0] = False
            evidence_errors.append({"component": "process_group", "error_type": type(exc).__name__})
            return getattr(process, "returncode", None), False
        except Exception as exc:
            evidence_complete[0] = False
            evidence_errors.append({"component": "process_group", "error_type": type(exc).__name__[:80]})
            return getattr(process, "returncode", None), False

    def run_agent_stage(
        *, agent_id: str, model: str, command: list[str], stream_mode: str,
    ) -> dict[str, Any]:
        phase_id = "initial_agent" if agent_id == "initial-agent" else "repair_agent"
        started = time.monotonic()
        phase_id_value = observe(
            "start_phase", phase_id, agent_id=agent_id, source="cascade",
            component="observer", required=(agent_id == "initial-agent"),
        )
        if phase_id_value is None:
            evidence_complete[0] = False
        before_ok = snapshot(f"before_{phase_id}", agent_id, required=(agent_id == "initial-agent"))
        if not before_ok and agent_id == "initial-agent":
            raise RuntimeError("initial workspace snapshot is incomplete")

        sampler: subprocess.Popen[Any] | None = None
        sampler_stopped = True
        sampler_command = [
            sys.executable, str(REPO_ROOT / "benchmark/resource_sampler.py"),
            "--output", str(resource_path), "--interval", "0.5",
            "--run-id", observer.run_id, "--phase-id", phase_id, "--agent-id", agent_id,
            "--parent-agent-id", "cascade-runner",
        ]
        try:
            sampler = subprocess.Popen(
                sampler_command, cwd=workspace, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=(os.name == "posix"),
            )
            observe("record", "sampler_start", phase_id, agent_id=agent_id, source="sampler",
                    component="observer", details={"status": "started"})
        except OSError as exc:
            evidence_complete[0] = False
            evidence_errors.append({"component": "sampler_start", "error_type": type(exc).__name__[:80]})
            observe("record", "evidence_error", phase_id, agent_id=agent_id, source="sampler",
                    component="observer", details={"component": "sampler", "error_type": type(exc).__name__[:80]})

        agent: subprocess.Popen[Any] | None = None
        exit_code: int | None = None
        timed_out = False
        group_stopped = True
        spawn_error: str | None = None
        try:
            with event_path.open(stream_mode, encoding="utf-8") as stdout_file, stderr_path.open(
                stream_mode, encoding="utf-8"
            ) as stderr_file:
                observe(
                    "record", "agent_spawn", phase_id, agent_id=agent_id, source="agent_process",
                    component="observer", details={"status": "starting"},
                )
                try:
                    agent = subprocess.Popen(
                        command, cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                        stdout=stdout_file, stderr=stderr_file,
                        start_new_session=(os.name == "posix"),
                    )
                    try:
                        exit_code = agent.wait(timeout=TASK_LIMIT_SECONDS)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                except OSError as exc:
                    spawn_error = type(exc).__name__
                if agent is not None:
                    exit_code, group_stopped = stop_owned(agent, timed_out=timed_out)
                stdout_file.flush()
                stderr_file.flush()
        except OSError as exc:
            spawn_error = type(exc).__name__
        finally:
            if sampler is not None:
                sampler_exit_code, sampler_stopped = stop_owned(
                    sampler, timed_out=False, grace_seconds=2.0,
                )
                sampler_failed = not sampler_stopped or sampler_exit_code != 0
                sampler_reason = (
                    "cleanup_failed" if not sampler_stopped
                    else "nonzero_exit" if sampler_exit_code != 0
                    else None
                )
                sampler_details: dict[str, Any] = {
                    "status": "failed" if sampler_failed else "completed",
                    "exit_code": sampler_exit_code,
                }
                if sampler_reason is not None:
                    sampler_details["reason"] = sampler_reason
                observe(
                    "record", "sampler_end", phase_id, agent_id=agent_id, source="sampler",
                    component="observer", details=sampler_details,
                )
                if sampler_failed:
                    evidence_complete[0] = False
                    evidence_errors.append({
                        "component": "sampler_stop" if not sampler_stopped else "sampler_exit",
                        "error_type": sampler_reason or "unexpected_exit",
                    })

        if spawn_error:
            evidence_complete[0] = False
            evidence_errors.append({"component": "agent_spawn", "error_type": spawn_error})
        status = "timed_out" if timed_out else "failed" if spawn_error or exit_code not in (0, None) else "completed"
        stage_wall = time.monotonic() - started
        phase_durations[phase_id] = phase_durations.get(phase_id, 0.0) + stage_wall
        observe(
            "record", "agent_exit", phase_id, agent_id=agent_id, source="agent_process",
            component="observer", details={
                "status": status, "exit_code": exit_code, "timed_out": timed_out,
                "duration_ns": int(stage_wall * 1e9),
            },
        )
        if group_stopped:
            snapshot(f"after_{phase_id}", agent_id)
        else:
            evidence_complete[0] = False
        if phase_id_value is not None:
            observe(
                "end_phase", phase_id_value, status, agent_id=agent_id, source="cascade",
                component="observer", details={"duration_ns": int(stage_wall * 1e9)},
            )
        return {
            "model": model, "exit_code": exit_code, "timed_out": timed_out,
            "process_group_stopped": group_stopped,
            "sampler_stopped": sampler_stopped,
            "spawned": agent is not None,
        }

    initial_alias = MODELS[initial_model]["alias"]
    initial_command = [
        str(binary), "run", "--format", "json", "--agent", "build", "--model",
        f"local/{initial_alias}", "--dir", str(workspace), prompt,
    ]
    initial_attempt = run_agent_stage(
        agent_id="initial-agent", model=initial_model, command=initial_command, stream_mode="w",
    )
    agent_attempts: list[dict[str, Any]] = [
        {key: initial_attempt[key] for key in ("model", "exit_code", "timed_out")}
    ]

    def visible_results() -> Any:
        start = time.monotonic()
        phase = observe(
            "start_phase", "visible_feedback", agent_id="visible-tests", source="cascade",
            component="observer",
        )
        result = collect_visible_feedback(workspace, env=env)
        wall = time.monotonic() - start
        phase_durations["visible_feedback"] = phase_durations.get("visible_feedback", 0.0) + wall
        if phase is not None:
            observe(
                "end_phase", phase,
                "timed_out" if result["timed_out"] else "completed" if result["passed"] else "failed",
                agent_id="visible-tests", source="cascade", component="observer",
                details={
                    "exit_code": result["exit_code"], "timed_out": result["timed_out"],
                    "passed": result["passed"], "duration_ns": int(wall * 1e9),
                },
            )
        return result

    cleanup_ok = bool(initial_attempt["process_group_stopped"])
    visible_feedback = None
    if cleanup_ok:
        visible_feedback = visible_results()
        cleanup_ok = bool(visible_feedback.get("process_group_stopped", True)) and not bool(
            visible_feedback.get("execution_error", False)
        )
    if not cleanup_ok:
        evidence_complete[0] = False
    if visible_feedback is None:
        visible_feedback = {
            "phase": "visible_development", "passed": False, "output": "",
            "exit_code": None, "timed_out": False, "process_group_stopped": False,
        }
    initial_pass = (
        visible_feedback["passed"] and not visible_feedback["timed_out"]
        and visible_feedback["exit_code"] == 0
        and not initial_attempt["timed_out"] and initial_attempt["exit_code"] == 0
    )

    escalation_requested = decide_escalation(policy=policy, initial_pass=initial_pass)
    escalated = False
    escalation_swap = 0.0
    if escalation_requested and cleanup_ok:
        transition = observe("start_phase", "model_transition", source="cascade", component="observer")
        transition_start = time.monotonic()
        try:
            escalation_swap = server_mgr.ensure_model("qwen3.5-9b")
            shutil.copyfile(profiles["repair"], profile_path)
            final_model = "qwen3.5-9b"
            transition_status = "completed"
        except Exception as exc:
            evidence_complete[0] = False
            evidence_errors.append({"component": "model_transition", "error_type": type(exc).__name__[:80]})
            transition_status = "failed"
        transition_wall = time.monotonic() - transition_start
        phase_durations["model_transition"] = transition_wall
        if transition is not None:
            observe(
                "end_phase", transition, transition_status, source="cascade", component="observer",
                details={"duration_ns": int(transition_wall * 1e9)},
            )
        if transition_status == "completed":
            escalated = True
            repair_prompt = build_repair_prompt(visible_feedback)
            repair_command = [
                str(binary), "run", "--format", "json", "--agent", "build", "--model",
                f"local/{MODELS[final_model]['alias']}", "--dir", str(workspace), repair_prompt,
            ]
            repair_attempt = run_agent_stage(
                agent_id="repair-agent", model=final_model, command=repair_command, stream_mode="a",
            )
            agent_attempts.append({
                key: repair_attempt[key] for key in ("model", "exit_code", "timed_out")
            })
            cleanup_ok = cleanup_ok and bool(repair_attempt["process_group_stopped"])
            if not cleanup_ok:
                evidence_complete[0] = False
            if cleanup_ok:
                visible_feedback = visible_results()
                cleanup_ok = bool(visible_feedback.get("process_group_stopped", True)) and not bool(
                    visible_feedback.get("execution_error", False)
                )
    else:
        skipped = observe(
            "start_phase", "repair_agent", agent_id="repair-agent", source="cascade",
            component="observer",
        )
        if skipped is not None:
            observe(
                "end_phase", skipped, "skipped", agent_id="repair-agent", source="cascade",
                component="observer", details={
                    "reason": "routing_did_not_escalate" if not escalation_requested
                    else "previous_process_group_unstopped",
                },
            )
    if escalation_requested and cleanup_ok and not escalated:
        skipped = observe(
            "start_phase", "repair_agent", agent_id="repair-agent", source="cascade",
            component="observer",
        )
        if skipped is not None:
            observe(
                "end_phase", skipped, "skipped", agent_id="repair-agent", source="cascade",
                component="observer", details={"reason": "model_transition_failed"},
            )

    events = _read_jsonl(event_path)
    res_rows = _read_jsonl(resource_path)
    res_summary = summarize_resources(res_rows)
    usage = summarize_usage(HARNESS, events)
    final_attempt = agent_attempts[-1]
    grade_success = False
    grade: dict[str, Any]
    if cleanup_ok:
        grade_phase = observe(
            "start_phase", "grading", agent_id="final-grader", source="cascade", component="observer",
        )
        grade_start = time.monotonic()
        try:
            # Exactly one private grade, after all agent and visible-test groups stop.
            grade = grade_workspace(workspace, fixture_rel, task=task, artifact_dir=run_dir / "grader-artifacts")
            grade_success = bool(grade.get("success", False))
            grade_status = "passed" if grade_success else "failed"
        except Exception as exc:
            grade = {"success": False, "status": "grader_error", "error_type": type(exc).__name__[:80]}
            grade_status = "failed"
        grade_wall = time.monotonic() - grade_start
        phase_durations["grading"] = grade_wall
        observe(
            "record", "grader_result", "grading", agent_id="final-grader", source="final_grader",
            component="observer", details={"status": grade_status},
        )
        if grade_phase is not None:
            observe(
                "end_phase", grade_phase, "completed", agent_id="final-grader", source="final_grader",
                component="observer", details={"duration_ns": int(grade_wall * 1e9)},
            )
    else:
        grade = {"success": False, "status": "skipped_unstopped_process_group"}
    benchmark_valid = bool(
        cleanup_ok and all(attempt["exit_code"] is not None for attempt in agent_attempts)
    )
    strict_pass = bool(
        benchmark_valid and grade_success and visible_feedback["passed"] and visible_feedback["exit_code"] == 0
        and not visible_feedback["timed_out"] and final_attempt["exit_code"] == 0
        and not final_attempt["timed_out"]
    )
    evidence_status = "complete" if evidence_complete[0] else "incomplete"
    observe(
        "finalize", "pass" if strict_pass else "fail" if cleanup_ok else "incomplete", evidence_status,
        source="cascade", component="observer",
    )
    task_wall = (
        phase_durations.get("initial_agent", 0.0)
        + phase_durations.get("repair_agent", 0.0)
        + escalation_swap
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
        "grader_pass": grade_success if cleanup_ok else None,
        "benchmark_valid": benchmark_valid,
        "evidence_status": evidence_status,
        "suite_role": "regression",
        "capability_evidence_eligible": False,
        "filesystem_enforced": False,
        "network_enforced": False,
        "pristine_regrade": bool(cleanup_ok),
        "private_holdout": False,
        "evidence_errors": evidence_errors,
        "task_wall_seconds": round(task_wall, 3),
        "observer_total_seconds": round(time.monotonic() - total_start, 3),
        "phase_durations_seconds": {key: round(value, 3) for key, value in phase_durations.items()},
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
        "grader_protocol_version": GRADER_PROTOCOL_VERSION,
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
