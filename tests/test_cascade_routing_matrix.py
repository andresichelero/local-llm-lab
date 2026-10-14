"""Unit tests for cascade routing matrix runner (Trilha A)."""
from __future__ import annotations

import subprocess
import os
import json
import shutil
import sys
import time
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


def _observer_manifest_for_test(tmp_path: Path) -> dict[str, object]:
    from benchmark.harness_runner import resolve_task

    fixture, prompt_source = resolve_task("calculator_division")
    run_dir = tmp_path / "run"
    profiles_dir = run_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    prompt_copy = run_dir / "TASK_PROMPT.md"
    prompt_copy.write_text("synthetic task prompt\n", encoding="utf-8")
    profiles = {}
    for name in ("initial", "repair"):
        profiles[name] = profiles_dir / f"{name}.json"
        profiles[name].write_text("{}\n", encoding="utf-8")
    return cascade._observer_manifest(
        task="calculator_division", fixture=fixture, prompt_source=prompt_source,
        prompt_copy=prompt_copy, run_dir=run_dir, profiles=profiles,
    )


def test_observer_manifest_records_mocked_git_provenance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_sha = "a" * 40
    monkeypatch.setattr(cascade, "git_provenance", lambda _root: (expected_sha, True))

    manifest = _observer_manifest_for_test(tmp_path)

    assert manifest["source_revision"] == {"value": expected_sha, "status": "measured"}
    assert manifest["source_tree_dirty"] == {"value": True, "status": "measured"}


def test_observer_manifest_records_actual_repository_head(tmp_path: Path) -> None:
    expected_sha = subprocess.run(
        ["git", "-C", str(cascade.REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    manifest = _observer_manifest_for_test(tmp_path)

    assert manifest["source_revision"] == {"value": expected_sha, "status": "measured"}
    assert manifest["source_tree_dirty"]["status"] == "measured"
    assert type(manifest["source_tree_dirty"]["value"]) is bool


def test_observer_manifest_marks_git_provenance_unavailable_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_git_provenance(_root: Path) -> tuple[str, bool]:
        raise OSError("synthetic git failure")

    monkeypatch.setattr(cascade, "git_provenance", fail_git_provenance)

    manifest = _observer_manifest_for_test(tmp_path)

    expected = {"value": None, "status": "unavailable", "reason": "git_provenance_failed"}
    assert manifest["source_revision"] == expected
    assert manifest["source_tree_dirty"] == expected


def test_fixture_hash_allowlist_skips_secret_directories_and_never_opens_them(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from benchmark import run_observer

    fixture = tmp_path / "fixture"
    safe_file = fixture / "src/calculator.py"
    secret_file = fixture / "secret-store/config.json"
    safe_file.parent.mkdir(parents=True)
    secret_file.parent.mkdir(parents=True)
    safe_file.write_text("SAFE_FIXTURE", encoding="utf-8")
    secret_file.write_text("SYNTHETIC_SECRET_SENTINEL", encoding="utf-8")
    allowed_paths = cascade._fixture_file_paths(fixture)

    opened: list[Path] = []
    real_hash_file = run_observer._hash_file

    def track_hash(path: Path) -> tuple[int, str]:
        opened.append(Path(path))
        return real_hash_file(path)

    monkeypatch.setattr(run_observer, "_hash_file", track_hash)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_observer.RunObserver(
        run_dir,
        {
            "hash_allowlist": [
                {
                    "category": "task_fixture",
                    "path": path.relative_to(fixture).as_posix(),
                    "file": path,
                }
                for path in allowed_paths
            ],
            "snapshot_hash_allowlist": [],
        },
    )

    manifest_text = (run_dir / "observer-manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    hash_paths = {item["path"] for item in manifest["hashes"]}
    assert safe_file in opened
    assert secret_file not in opened
    assert "secret-store/config.json" not in hash_paths
    assert "SYNTHETIC_SECRET_SENTINEL" not in manifest_text


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
    sampler_start_error: bool = False,
    sampler_stop_error: bool = False,
    sampler_exit_code: int = 0,
    agent_spawn_error: bool = False,
    visible_execution_error: bool = False,
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
            self.stop_error = sampler and sampler_stop_error
            self.timed_out = False
            self.finished = False
            self.killed = False
            if sampler:
                self.model = "sampler"
                self.outcome: dict[str, object] = {"exit_code": sampler_exit_code}
                return
            self.model = str(command[command.index("--model") + 1])
            prompts.append(str(command[-1]))
            timeline.append(f"agent_start:{self.model}")
            self.workspace = Path(command[command.index("--dir") + 1])
            self.outcome = outcomes.pop(0) if outcomes else {"exit_code": 0}

        def wait(self, timeout=None):
            if self.sampler:
                if self.stop_error:
                    raise OSError("synthetic sampler stop failure")
                return int(self.outcome["exit_code"])
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
        if sampler:
            timeline.append(
                "sampler_start:"
                f"{command[command.index('--phase-id') + 1]}:"
                f"{command[command.index('--agent-id') + 1]}:"
                f"{command[command.index('--run-id') + 1]}"
            )
            if sampler_start_error:
                raise OSError("synthetic sampler startup failure")
        elif str(command[0]) == fake_binary and agent_spawn_error and not any(
            item.startswith("agent_start:") for item in timeline
        ):
            raise FileNotFoundError("synthetic agent startup failure")
        if sampler or str(command[0]) == fake_binary:
            return FakeProcess(command, kwargs, sampler=sampler)
        return real_popen(command, **kwargs)

    monkeypatch.setattr(cascade.subprocess, "Popen", fake_popen)
    original_feedback = getattr(cascade, "collect_visible_feedback", None)

    def visible_feedback(*args, **kwargs):
        timeline.append("visible_feedback")
        if visible_execution_error:
            return {
                "phase": "visible_development", "passed": False, "output": "",
                "exit_code": None, "timed_out": False,
                "process_group_stopped": True, "execution_error": True,
            }
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
    sampler_stages = [item for item in timeline if item.startswith("sampler_start:")]
    assert len(sampler_stages) == 2
    assert sampler_stages[0].startswith("sampler_start:initial_agent:initial-agent:")
    assert sampler_stages[1].startswith("sampler_start:repair_agent:repair-agent:")


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


def test_sampler_start_failure_keeps_agent_and_grade_result_but_marks_evidence_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result, timeline, _, private_grades = _run_fake_trial(
        monkeypatch, tmp_path, private_success=True, initially_visible_passes=True,
        sampler_start_error=True,
    )

    assert any(item.startswith("agent_start:") for item in timeline)
    assert len(private_grades) == 1
    assert result["strict_pass"] is True
    assert result["benchmark_valid"] is True
    assert result["evidence_status"] == "incomplete"


def test_agent_spawn_failure_stops_sampler_and_preserves_one_final_grade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result, timeline, _, private_grades = _run_fake_trial(
        monkeypatch, tmp_path, private_success=True, initially_visible_passes=True,
        agent_spawn_error=True,
    )

    assert any(item.startswith("sampler_start:initial_agent") for item in timeline)
    assert not any(item.startswith("agent_start:") for item in timeline)
    assert len(private_grades) == 1
    assert result["strict_pass"] is False
    assert result["evidence_status"] == "incomplete"


def test_sampler_stop_failure_does_not_replace_final_grade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result, _, _, private_grades = _run_fake_trial(
        monkeypatch, tmp_path, private_success=True, initially_visible_passes=True,
        sampler_stop_error=True,
    )

    assert len(private_grades) == 1
    assert result["strict_pass"] is True
    assert result["benchmark_valid"] is True
    assert result["evidence_status"] == "incomplete"


def test_sampler_early_nonzero_exit_marks_evidence_incomplete_without_changing_grade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result, _, _, private_grades = _run_fake_trial(
        monkeypatch, tmp_path, private_success=True, initially_visible_passes=True,
        sampler_exit_code=1,
    )

    run_dir = tmp_path / "output/runs/trial_01_dynamic-cascade_calculator_division_r1"
    observer_events = [
        json.loads(line)
        for line in (run_dir / "observer-events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    sampler_end = [event for event in observer_events if event["event_type"] == "sampler_end"]
    assert len(private_grades) == 1
    assert result["grader_pass"] is True
    assert result["benchmark_valid"] is True
    assert result["evidence_status"] == "incomplete"
    assert sampler_end[0]["details"]["status"] == "failed"
    assert sampler_end[0]["details"]["reason"] == "nonzero_exit"
    assert sampler_end[0]["details"]["exit_code"] == 1


def test_visible_feedback_execution_error_skips_final_private_grade(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result, timeline, _, private_grades = _run_fake_trial(
        monkeypatch, tmp_path, private_success=True, initially_visible_passes=True,
        visible_execution_error=True,
    )

    assert "visible_feedback" in timeline
    assert not private_grades
    assert "private_final_grade" not in timeline
    assert result["grader_pass"] is None
    assert result["benchmark_valid"] is False


def test_observer_write_failure_after_launch_does_not_replace_benchmark_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_record = cascade.RunObserver.record
    did_fail = False

    def failing_record(self, event_type, *args, **kwargs):
        nonlocal did_fail
        if event_type == "agent_exit" and not did_fail:
            did_fail = True
            raise OSError("synthetic observer write failure")
        return original_record(self, event_type, *args, **kwargs)

    monkeypatch.setattr(cascade.RunObserver, "record", failing_record)
    result, _, _, private_grades = _run_fake_trial(
        monkeypatch, tmp_path, private_success=True, initially_visible_passes=True,
    )

    assert did_fail
    assert len(private_grades) == 1
    assert result["strict_pass"] is True
    assert result["benchmark_valid"] is True
    assert result["evidence_status"] == "incomplete"


def test_manifest_failure_is_fail_closed_before_any_agent_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fail_observer(*args, **kwargs):
        del args, kwargs
        raise OSError("synthetic manifest creation failure")

    monkeypatch.setattr(cascade, "RunObserver", fail_observer)
    with pytest.raises(OSError):
        _run_fake_trial(
            monkeypatch, tmp_path, private_success=True, initially_visible_passes=True,
        )

    run_dir = tmp_path / "output/runs/trial_01_dynamic-cascade_calculator_division_r1"
    assert not (run_dir / "events.jsonl").exists()
    assert not (run_dir / "stderr.log").exists()
    assert not (run_dir / "resources.jsonl").exists()


@pytest.mark.skipif(os.name == "nt", reason="the lifecycle test validates POSIX process groups")
def test_timeout_stops_agent_descendants_before_final_grading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "fake-opencode"
    ready = tmp_path / "descendant-ready"
    child_marker = tmp_path / "child-wrote-after-timeout"
    grandchild_marker = tmp_path / "grandchild-wrote-after-timeout"
    grandchild_code = (
        "import sys,time\nfrom pathlib import Path\n"
        "time.sleep(1.2)\nPath(sys.argv[1]).write_text('late')\n"
    )
    child_code = (
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild_code!r}, sys.argv[1]])\n"
        "Path(sys.argv[2]).write_text('ready')\n"
        "time.sleep(30)\n"
        "Path(sys.argv[3]).write_text('late')\n"
    )
    agent_code = (
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        "print('FAKE_AGENT_STDOUT_SENTINEL', flush=True)\n"
        "print('FAKE_AGENT_STDERR_SENTINEL', file=sys.stderr, flush=True)\n"
        f"subprocess.Popen([sys.executable, '-c', {child_code!r}, {str(grandchild_marker)!r}, "
        f"{str(ready)!r}, {str(child_marker)!r}])\n"
        f"deadline=time.monotonic()+3\nwhile not Path({str(ready)!r}).exists() and time.monotonic()<deadline:\n"
        " time.sleep(0.01)\n"
        "time.sleep(30)\n"
    )
    binary.write_text(f"#!{sys.executable}\n{agent_code}", encoding="utf-8")
    binary.chmod(0o755)

    def prepare_synthetic_run(harness, run_dir, install_root, prompt, model, server_url, context, fixture):
        del harness, install_root, model, server_url, context
        workspace = run_dir / "workspace"
        for relative in ("TASK.md", "src/calculator.py", "tests/test_calculator.py"):
            source = fixture / relative
            destination = workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        (run_dir / "home/.config/opencode").mkdir(parents=True)
        (run_dir / "home").mkdir(exist_ok=True)
        (run_dir / "output").mkdir()
        prompt_file = run_dir / "TASK_PROMPT.md"
        prompt_file.write_text(prompt + "\n", encoding="utf-8")
        return prompt_file

    monkeypatch.setattr(cascade, "_prepare_run", prepare_synthetic_run)
    monkeypatch.setattr(cascade, "TASK_LIMIT_SECONDS", 0.8)
    grade_calls: list[str] = []

    def final_grade(*args, **kwargs):
        del args, kwargs
        grade_calls.append("called")
        time.sleep(1.8)
        assert not child_marker.exists(), "an agent child wrote during final grading"
        assert not grandchild_marker.exists(), "an agent grandchild wrote during final grading"
        return {"success": False}

    monkeypatch.setattr(cascade, "grade_workspace", final_grade)

    result = cascade.run_single_trial(
        binary=binary,
        install_root=tmp_path / "install",
        server_mgr=type("Server", (), {"ensure_model": lambda self, _model: 0.0})(),
        trial_info={"trial": 1, "policy": "always-4b", "task": "calculator_division", "repeat": 1},
        output_root=tmp_path / "output",
        round_deadline=0.0,
    )

    assert len(grade_calls) == 1
    assert result["agent_attempts"][0]["timed_out"] is True
    assert not child_marker.exists()
    assert not grandchild_marker.exists()
    run_dir = tmp_path / "output/runs/trial_01_always-4b_calculator_division_r1"
    assert (run_dir / "observer-manifest.json").is_file()
    assert (run_dir / "observer-events.jsonl").is_file()
    assert (run_dir / "workspace-snapshots.jsonl").is_file()
    assert "FAKE_AGENT_STDOUT_SENTINEL" in (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "FAKE_AGENT_STDERR_SENTINEL" in (run_dir / "stderr.log").read_text(encoding="utf-8")
    observer_events = [
        json.loads(line)
        for line in (run_dir / "observer-events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    sampler_end = [event for event in observer_events if event["event_type"] == "sampler_end"]
    assert len(sampler_end) == 1
    assert sampler_end[0]["details"] == {"status": "completed", "exit_code": 0}

    artifact_root = os.environ.get("CASCADE_OBSERVER_E2E_DIR")
    if artifact_root:
        root = Path(artifact_root)
        root.mkdir(parents=True, exist_ok=True)
        destination = root / f"synthetic-no-model-{time.time_ns()}"
        destination.mkdir()
        for name in (
            "observer-manifest.json", "observer-events.jsonl", "workspace-snapshots.jsonl",
            "resources.jsonl", "events.jsonl", "stderr.log",
        ):
            shutil.copy2(run_dir / name, destination / name)
        (destination / "synthetic-validation.json").write_text(
            json.dumps({
                "validation_scope": "synthetic_fake_agent_no_model",
                "model_execution": False,
                "grader": "synthetic_test_stub",
                "performance_claim": "none",
                "agent_exit_code": result["agent_attempts"][0]["exit_code"],
                "observer_total_seconds": result["observer_total_seconds"],
            }, sort_keys=True) + "\n",
            encoding="utf-8",
        )

