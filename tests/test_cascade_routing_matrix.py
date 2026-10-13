"""Unit tests for cascade routing matrix runner (Trilha A)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from benchmark import cascade_routing_matrix as cascade
from benchmark.cascade_routing_matrix import (
    MODELS,
    POLICIES,
    TASKS,
    build_repair_prompt,
    build_schedule,
    decide_escalation,
    server_command,
    summarize_cascade_results,
)


def test_build_schedule_structure() -> None:
    schedule = build_schedule()
    assert len(schedule) == 36

    # 12 trials per policy
    for policy in POLICIES:
        policy_trials = [t for t in schedule if t["policy"] == policy]
        assert len(policy_trials) == 12
        # 2 repeats of 6 tasks
        for task in TASKS:
            task_trials = [t for t in policy_trials if t["task"] == task]
            assert len(task_trials) == 2


def test_server_command_configurations() -> None:
    server_bin = Path("/usr/local/bin/llama-server")
    m4b_path = Path("/models/qwen3.5-4b.gguf")
    m9b_path = Path("/models/qwen3.5-9b.gguf")

    # 4B command: must include --cache-prompt and MTP speculation flags
    cmd_4b = server_command(server_bin, m4b_path, MODELS["qwen3.5-4b"])
    assert "--cache-prompt" in cmd_4b
    assert "--spec-type" in cmd_4b
    assert "draft-mtp" in cmd_4b
    assert "--spec-draft-n-max" in cmd_4b
    assert "3" in cmd_4b

    # 9B command: must include --cache-prompt, must NOT include MTP draft speculation
    cmd_9b = server_command(server_bin, m9b_path, MODELS["qwen3.5-9b"])
    assert "--cache-prompt" in cmd_9b
    assert "draft-mtp" not in cmd_9b


def test_decide_escalation() -> None:
    # Under always-4b: never escalates even on failure
    assert decide_escalation(policy="always-4b", initial_pass=False) is False
    assert decide_escalation(policy="always-4b", initial_pass=True) is False

    # Under always-9b: never escalates
    assert decide_escalation(policy="always-9b", initial_pass=False) is False
    assert decide_escalation(policy="always-9b", initial_pass=True) is False

    # Under dynamic-cascade: escalates if initial pass is False, does not escalate if True
    assert decide_escalation(policy="dynamic-cascade", initial_pass=True) is False
    assert decide_escalation(policy="dynamic-cascade", initial_pass=False) is True


def test_summarize_cascade_results() -> None:
    records = [
        # always-4b trials
        {"policy": "always-4b", "task": "calculator_division", "strict_pass": True, "task_wall_seconds": 18.0, "escalated": False, "peak_vram_mib": 4800},
        {"policy": "always-4b", "task": "retry_policy", "strict_pass": False, "task_wall_seconds": 120.0, "escalated": False, "peak_vram_mib": 4850},
        # always-9b trials
        {"policy": "always-9b", "task": "calculator_division", "strict_pass": True, "task_wall_seconds": 25.0, "escalated": False, "peak_vram_mib": 7100},
        {"policy": "always-9b", "task": "retry_policy", "strict_pass": True, "task_wall_seconds": 47.0, "escalated": False, "peak_vram_mib": 7200},
        # dynamic-cascade trials
        {"policy": "dynamic-cascade", "task": "calculator_division", "strict_pass": True, "task_wall_seconds": 18.2, "escalated": False, "peak_vram_mib": 4820},
        {"policy": "dynamic-cascade", "task": "retry_policy", "strict_pass": True, "task_wall_seconds": 52.0, "escalated": True, "swap_duration_seconds": 4.1, "peak_vram_mib": 7210},
    ]

    summary = summarize_cascade_results(records)
    assert "policies" in summary

    p4b = summary["policies"]["always-4b"]
    assert p4b["trials"] == 2
    assert p4b["strict_pass_count"] == 1
    assert p4b["escalation_count"] == 0

    p9b = summary["policies"]["always-9b"]
    assert p9b["trials"] == 2
    assert p9b["strict_pass_count"] == 2
    assert p9b["escalation_count"] == 0

    p_dyn = summary["policies"]["dynamic-cascade"]
    assert p_dyn["trials"] == 2
    assert p_dyn["strict_pass_count"] == 2
    assert p_dyn["escalation_count"] == 1
    assert p_dyn["escalation_rate_pct"] == 50.0


def test_build_repair_prompt_ignores_private_grade_diagnostics() -> None:
    private_grade = {
        "success": False,
        "behavioral_probe_stderr": "PRIVATE_ASSERTION_SENTINEL",
        "test_output": "PRIVATE_TEST_OUTPUT_SENTINEL",
        "grader_error": "PRIVATE_GRADER_ERROR_SENTINEL",
    }

    prompt = build_repair_prompt(private_grade)

    assert "PRIVATE_ASSERTION_SENTINEL" not in prompt
    assert "PRIVATE_TEST_OUTPUT_SENTINEL" not in prompt
    assert "PRIVATE_GRADER_ERROR_SENTINEL" not in prompt


def test_build_repair_prompt_uses_only_visible_phase_output() -> None:
    prompt = build_repair_prompt({
        "phase": "visible_development",
        "passed": False,
        "output": "VISIBLE_OUTPUT_SENTINEL",
        "exit_code": 1,
        "timed_out": False,
        "behavioral_probe_stderr": "PRIVATE_ORACLE_SENTINEL",
    })

    assert "VISIBLE_OUTPUT_SENTINEL" in prompt
    assert "PRIVATE_ORACLE_SENTINEL" not in prompt


def _run_fake_trial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    private_success: bool,
    initially_visible_passes: bool,
    agent_outcomes: list[dict[str, object]] | None = None,
    preexisting_output: bool = False,
) -> tuple[dict[str, object], list[str], list[str], list[dict[str, object]]]:
    timeline: list[str] = []
    prompts: list[str] = []
    private_grades: list[dict[str, object]] = []
    outcomes = list(agent_outcomes or [{"exit_code": 0}, {"exit_code": 0}])
    fake_binary = str(tmp_path / "fake-agent")
    real_popen = subprocess.Popen

    def prepare_run(harness, run_dir, install_root, prompt, model, server_url, context, fixture):
        del harness, install_root, prompt, model, server_url, context, fixture
        workspace = run_dir / "workspace"
        (workspace / "src").mkdir(parents=True)
        (workspace / "tests").mkdir()
        (run_dir / "home/.config/opencode").mkdir(parents=True)
        (run_dir / "home").mkdir(exist_ok=True)
        (workspace / "src/__init__.py").write_text("", encoding="utf-8")
        initial_value = "ready" if initially_visible_passes else "broken"
        (workspace / "src/check.py").write_text(f'VALUE = "{initial_value}"\n', encoding="utf-8")
        (workspace / "tests/__init__.py").write_text("", encoding="utf-8")
        (workspace / "tests/test_visible.py").write_text(
            "import unittest\nfrom src.check import VALUE\n\n"
            "class VisibleTests(unittest.TestCase):\n"
            "    def test_task_behavior(self):\n"
            "        self.assertEqual(VALUE, 'ready', 'VISIBLE_WORKSPACE_FAILURE_SENTINEL')\n",
            encoding="utf-8",
        )
        return run_dir / "TASK_PROMPT.md"

    monkeypatch.setattr(cascade, "_prepare_run", prepare_run)

    class FakeProcess:
        def __init__(self, command, kwargs, *, sampler: bool = False) -> None:
            self.command = command
            self.stdout = kwargs.get("stdout")
            self.sampler = sampler
            self.timed_out = False
            self.finished = False
            self.killed = False
            if sampler:
                self.model = "sampler"
                self.outcome: dict[str, object] = {"exit_code": 0}
                return
            self.model = str(command[command.index("--model") + 1])
            prompts.append(str(command[-1]))
            timeline.append(f"agent_start:{self.model}")
            self.workspace = Path(command[command.index("--dir") + 1])
            self.outcome = outcomes.pop(0) if outcomes else {"exit_code": 0}

        def wait(self, timeout=None):
            if self.sampler:
                return 0
            if self.outcome.get("timed_out") and not self.timed_out:
                self.timed_out = True
                raise subprocess.TimeoutExpired(self.command, timeout)
            if self.model.endswith("9B-Q4_K_M") and self.outcome.get("write_fix", True):
                (self.workspace / "src/check.py").write_text('VALUE = "ready"\n', encoding="utf-8")
            if not self.finished:
                timeline.append(f"agent_end:{self.model}")
                self.finished = True
            if self.stdout is not None:
                self.stdout.flush()
            if self.outcome.get("timed_out"):
                return -9
            return int(self.outcome.get("exit_code", 0))

        def kill(self):
            self.killed = True
            timeline.append(f"agent_kill:{self.model}")

        def terminate(self):
            return None

    def fake_popen(command, **kwargs):
        sampler = any("resource_sampler.py" in str(part) for part in command)
        if sampler or str(command[0]) == fake_binary:
            return FakeProcess(command, kwargs, sampler=sampler)
        return real_popen(command, **kwargs)

    monkeypatch.setattr(cascade.subprocess, "Popen", fake_popen)
    original_feedback = getattr(cascade, "collect_visible_feedback", None)

    def visible_feedback(*args, **kwargs):
        timeline.append("visible_feedback")
        if original_feedback is None:
            raise AssertionError("cascade did not use visible workspace feedback")
        return original_feedback(*args, **kwargs)

    monkeypatch.setattr(cascade, "collect_visible_feedback", visible_feedback, raising=False)

    def private_grade(*args, **kwargs):
        del args, kwargs
        timeline.append("private_final_grade")
        grade = {
            "success": private_success,
            "behavioral_probe_stderr": "PRIVATE_ORACLE_ASSERTION_SENTINEL",
            "test_output": "PRIVATE_ORACLE_OUTPUT_SENTINEL",
            "grader_error": "PRIVATE_ORACLE_ERROR_SENTINEL",
        }
        private_grades.append(grade)
        return grade

    monkeypatch.setattr(cascade, "grade_workspace", private_grade)

    class FakeServerManager:
        def ensure_model(self, model: str) -> float:
            timeline.append(f"server:{model}")
            return 0.0

    trial = {
        "trial": 1,
        "policy": "dynamic-cascade",
        "task": "calculator_division",
        "repeat": 1,
    }
    output_root = tmp_path / "output"
    if preexisting_output:
        preserved_run = output_root / "runs/trial_01_dynamic-cascade_calculator_division_r1"
        preserved_run.mkdir(parents=True)
        (preserved_run / "marker.txt").write_text("preserve this run", encoding="utf-8")
    result = cascade.run_single_trial(
        binary=Path(fake_binary),
        install_root=tmp_path / "install",
        server_mgr=FakeServerManager(),
        trial_info=trial,
        output_root=output_root,
        round_deadline=0.0,
    )
    return result, timeline, prompts, private_grades


@pytest.mark.parametrize("private_success", [True, False])
def test_cascade_repair_and_routing_ignore_private_grade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    private_success: bool,
) -> None:
    result, timeline, prompts, private_grades = _run_fake_trial(
        monkeypatch,
        tmp_path,
        private_success=private_success,
        initially_visible_passes=False,
    )

    assert result["escalated"] is True
    assert result["strict_pass"] is private_success
    assert len(prompts) == 2
    assert "VISIBLE_WORKSPACE_FAILURE_SENTINEL" in prompts[1]
    assert all("PRIVATE_ORACLE_" not in prompt for prompt in prompts)
    assert len(private_grades) == 1
    assert timeline.index("visible_feedback") < timeline.index("server:qwen3.5-9b")
    assert timeline[-1] == "private_final_grade"


def test_cascade_does_not_repair_after_visible_success_and_grades_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result, timeline, prompts, private_grades = _run_fake_trial(
        monkeypatch,
        tmp_path,
        private_success=True,
        initially_visible_passes=True,
        agent_outcomes=[{"exit_code": 0}],
    )

    assert result["escalated"] is False
    assert result["strict_pass"] is True
    assert len(prompts) == 1
    assert len(private_grades) == 1
    assert timeline[-1] == "private_final_grade"


@pytest.mark.parametrize(
    ("repair_outcome", "expected_exit_code", "expected_timeout"),
    [
        ({"exit_code": 23, "write_fix": True}, 23, False),
        ({"timed_out": True, "write_fix": True}, -9, True),
    ],
)
def test_failed_final_agent_cannot_pass_on_stale_visible_tests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repair_outcome: dict[str, object],
    expected_exit_code: int,
    expected_timeout: bool,
) -> None:
    result, _, _, _ = _run_fake_trial(
        monkeypatch,
        tmp_path,
        private_success=True,
        initially_visible_passes=False,
        agent_outcomes=[{"exit_code": 0}, repair_outcome],
    )

    assert result["strict_pass"] is False
    assert result["agent_attempts"][-1] == {
        "model": "qwen3.5-9b",
        "exit_code": expected_exit_code,
        "timed_out": expected_timeout,
    }


def test_existing_run_output_is_preserved_and_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "output/runs/trial_01_dynamic-cascade_calculator_division_r1"

    with pytest.raises(FileExistsError):
        _run_fake_trial(
            monkeypatch,
            tmp_path,
            private_success=True,
            initially_visible_passes=True,
            preexisting_output=True,
        )

    assert (run_dir / "marker.txt").read_text(encoding="utf-8") == "preserve this run"

