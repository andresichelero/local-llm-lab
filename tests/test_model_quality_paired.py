from __future__ import annotations

import os
import shlex
import sys
import json
import unittest
import tempfile
import time
from pathlib import Path
from unittest import mock

from benchmark.model_quality_paired import (
    MAX_PRIMARY_STEPS,
    MODELS,
    EXPERIMENT,
    frozen_protocol,
    TASKS,
    build_profile,
    compatibility_gate,
    denominator_rows,
    fatal_diagnostic_stop,
    measured_schedule,
    pregrade_workspace_gate,
    strict_quality_pass,
    summarize_denominators,
    swap_growth_breach,
    PILOT_EXPERIMENT,
    PILOT_TASKS,
    V2_EXPERIMENT,
    V2_TASKS,
    build_pilot_schedule,
    build_v2_schedule,
    frozen_pilot_protocol,
    frozen_v2_protocol,
)
import benchmark.model_quality_paired as paired


class ModelQualityPairedTests(unittest.TestCase):
    def test_frozen_schedule_has_three_repeats_per_task_model_and_alternating_blocks(self) -> None:
        rows = measured_schedule()
        self.assertEqual(len(rows), 18)
        self.assertEqual([rows[index]["task"] for index in (0, 6, 12)], list(TASKS))
        for task in TASKS:
            for model in MODELS:
                selected = [row for row in rows if row["task"] == task and row["model"] == model]
                self.assertEqual([row["repeat"] for row in selected], [1, 2, 3])
                self.assertTrue(all(row["stage"] == "measurement" for row in selected))
        self.assertNotEqual(rows[0]["model"], rows[3]["model"])
        self.assertEqual(rows[6]["model"], rows[3]["model"])

    def test_pilot_schedule_and_protocol(self) -> None:
        pilot_rows = build_pilot_schedule()
        self.assertEqual(len(pilot_rows), 4)
        self.assertEqual([r["task"] for r in pilot_rows], list(PILOT_TASKS) + list(PILOT_TASKS))
        self.assertEqual([r["model"] for r in pilot_rows], ["qwen3.5-4b", "qwen3.5-4b", "qwen3.5-9b", "qwen3.5-9b"])
        self.assertTrue(all(r["repeat"] == 1 for r in pilot_rows))
        proto = frozen_pilot_protocol()
        self.assertEqual(proto["experiment"], PILOT_EXPERIMENT)
        self.assertEqual(proto["tasks"], list(PILOT_TASKS))
        self.assertEqual(proto["measured_repeats_per_model_task"], 1)
        self.assertEqual(proto["round_limit_seconds"], 25 * 60)

    def test_v2_schedule_and_protocol(self) -> None:
        v2_rows = build_v2_schedule()
        self.assertEqual(len(v2_rows), 24)
        # 4 blocks of 6 tasks
        self.assertEqual(len([r for r in v2_rows if r["model"] == "qwen3.5-4b" and r["repeat"] == 1]), 6)
        self.assertEqual(len([r for r in v2_rows if r["model"] == "qwen3.5-9b" and r["repeat"] == 1]), 6)
        self.assertEqual(len([r for r in v2_rows if r["model"] == "qwen3.5-9b" and r["repeat"] == 2]), 6)
        self.assertEqual(len([r for r in v2_rows if r["model"] == "qwen3.5-4b" and r["repeat"] == 2]), 6)
        # AB / BA block sequence
        self.assertEqual(v2_rows[0]["model"], "qwen3.5-4b")
        self.assertEqual(v2_rows[6]["model"], "qwen3.5-9b")
        self.assertEqual(v2_rows[12]["model"], "qwen3.5-9b")
        self.assertEqual(v2_rows[18]["model"], "qwen3.5-4b")
        proto = frozen_v2_protocol()
        self.assertEqual(proto["experiment"], V2_EXPERIMENT)
        self.assertEqual(proto["tasks"], list(V2_TASKS))
        self.assertEqual(proto["measured_repeats_per_model_task"], 2)
        self.assertEqual(proto["round_limit_seconds"], 120 * 60)

    def test_round0_failure_is_persisted_as_an_execution_gate(self) -> None:
        protocol = frozen_protocol()
        self.assertEqual(protocol["experiment"], EXPERIMENT)
        self.assertTrue(EXPERIMENT.endswith("r1d"))
        self.assertEqual(protocol["round0_prerequisite"]["status"], "failed")
        self.assertFalse(protocol["round0_prerequisite"]["measurement_eligible"])
        self.assertTrue(protocol["round0_prerequisite"]["not_a_single_agent_prerequisite"])
        self.assertEqual(protocol["single_agent_prerequisite"]["status"], "pending")

    def test_protocol_source_hash_allowlist_includes_grader_and_fixture_fingerprints(self) -> None:
        source_paths = {
            path.relative_to(paired.REPO_ROOT).as_posix()
            for path in paired.PROTOCOL_SOURCE_PATHS
        }
        self.assertIn("benchmark/pristine_grading.py", source_paths)
        self.assertIn("benchmark/configs/grading/fixture-fingerprints-v2.json", source_paths)
        self.assertIn("benchmark/restricted_python.py", source_paths)

    def test_profile_is_single_agent_local_no_update_and_explicitly_scoped(self) -> None:
        profile = build_profile("qwen3.5-4b")
        self.assertFalse(profile["autoupdate"])
        self.assertEqual(profile["provider"]["local"]["options"]["baseURL"], "http://127.0.0.1:8080/v1")
        self.assertEqual(profile["agent"].keys(), {"build"})
        permissions = profile["agent"]["build"]["permission"]
        self.assertEqual(profile["agent"]["build"]["steps"], MAX_PRIMARY_STEPS)
        self.assertEqual(permissions, {
            "task": {"*": "deny"}, "bash": {"*": "allow"}, "edit": {"*": "allow"},
            "external_directory": {"*": "deny"},
        })
        self.assertEqual(profile["model"], "local/" + MODELS["qwen3.5-4b"]["alias"])

    def test_calibration_and_warmup_are_excluded_but_failed_measurements_remain(self) -> None:
        records = [
            {"stage": "calibration", "model": "m", "task": "t", "strict_pass": False, "task_wall_seconds": 20},
            {"stage": "warmup", "model": "m", "task": "t", "strict_pass": True, "task_wall_seconds": 12},
            {"stage": "measurement", "model": "m", "task": "t", "strict_pass": True, "task_wall_seconds": 10},
            {"stage": "measurement", "model": "m", "task": "t", "strict_pass": False, "task_wall_seconds": 30},
            {"stage": "measurement", "model": "m", "task": "t", "attempted": False, "strict_pass": False},
        ]
        self.assertEqual(len(denominator_rows(records)), 3)
        summary = summarize_denominators(records)
        result = summary["by_model_task"]["m/t"]
        self.assertEqual(summary["measured_rows"], 2)
        self.assertEqual((result["passes"], result["attempts"], result["pass_fraction"]), (1, 2, 0.5))
        self.assertEqual(result["task_wall_median_seconds"], 20)

    def test_compatibility_gate_ignores_task_behavior_quality(self) -> None:
        required = {"server_loaded": True, "effective_profile_ok": True,
                    "bash_tool_round_trip": True, "edit_tool_round_trip": True}
        self.assertTrue(compatibility_gate(**required))
        self.assertFalse(compatibility_gate(**{**required, "bash_tool_round_trip": False}))
        self.assertFalse(compatibility_gate(**{**required, "edit_tool_round_trip": False}))

    def test_compatibility_edit_requires_completed_edit_targeting_task_md(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            bash_wrote_task = {
                "type": "tool_use",
                "part": {"tool": "bash", "state": {"status": "completed",
                         "input": {"command": "printf 'edit probe ok' > TASK.md"},
                         "metadata": {"exit": 0}}},
            }
            unrelated_edit = {
                "type": "tool_use",
                "part": {"tool": "edit", "state": {"status": "completed",
                         "input": {"filePath": str(workspace / "README.md")}}},
            }
            wrong_target = paired.compatibility_edit_evidence(
                [bash_wrote_task, unrelated_edit], workspace, file_verified=True)
            self.assertEqual(wrong_target["completed_edit_tool_calls"], 1)
            self.assertEqual(wrong_target["edit_task_md_tool_calls"], 0)
            self.assertFalse(wrong_target["edit_tool_round_trip"])

            task_md_edit = {**unrelated_edit, "part": {**unrelated_edit["part"], "state": {
                **unrelated_edit["part"]["state"],
                "input": {"filePath": str(workspace / "TASK.md")}}}}
            correct_target = paired.compatibility_edit_evidence(
                [bash_wrote_task, task_md_edit], workspace, file_verified=True)
            self.assertEqual(correct_target["edit_task_md_tool_calls"], 1)
            self.assertTrue(correct_target["edit_tool_round_trip"])

            task_md_write = {
                "type": "tool_use",
                "part": {"tool": "write", "state": {"status": "completed",
                         "input": {"filePath": str(workspace / "TASK.md"), "content": "edit probe ok\n"}}},
            }
            write_target = paired.compatibility_edit_evidence(
                [bash_wrote_task, task_md_write], workspace, file_verified=True)
            self.assertEqual(write_target["edit_task_md_tool_calls"], 1)
            self.assertTrue(write_target["edit_tool_round_trip"])

    def test_effective_permissions_reject_task_allow_overrides_and_external_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            home, tmpdir = str(Path(temporary) / "home"), str(Path(temporary) / "tmp")
            expected_external = [
                {"permission": "external_directory", "pattern": "*", "action": "deny"},
                {"permission": "external_directory", "pattern": f"{home}/.local/share/opencode/tool-output/*", "action": "allow"},
                {"permission": "external_directory", "pattern": f"{tmpdir}/opencode/*", "action": "allow"},
            ]
            permissions = [
                {"permission": "task", "pattern": "*", "action": "deny"},
                {"permission": "bash", "pattern": "*", "action": "allow"},
                {"permission": "edit", "pattern": "*", "action": "allow"},
                *expected_external,
            ]
            self.assertTrue(all(paired._permission_profile_checks(permissions, home, tmpdir).values()))
            task_override = [*permissions, {"permission": "task", "pattern": "repo-explorer", "action": "allow"}]
            self.assertFalse(paired._permission_profile_checks(task_override, home, tmpdir)["task_specific_overrides_denied"])
            outside_override = [*permissions, {"permission": "external_directory", "pattern": "/etc/*", "action": "allow"}]
            self.assertFalse(paired._permission_profile_checks(outside_override, home, tmpdir)["external_directory_overrides_scoped"])

    def test_strict_pass_requires_all_independent_gates(self) -> None:
        grade = {"success": True}
        self.assertTrue(strict_quality_pass(grade, modes_preserved=True, workflow_complete=True,
                                            tool_round_trip=True, command_ok=True))
        self.assertFalse(strict_quality_pass(grade, modes_preserved=False, workflow_complete=True,
                                             tool_round_trip=True, command_ok=True))
        self.assertFalse(strict_quality_pass({"success": False}, modes_preserved=True, workflow_complete=True,
                                             tool_round_trip=True, command_ok=True))

    def test_unit_completion_requires_real_successful_test_output_and_zero_exit(self) -> None:
        event = {"part": {"tool": "bash", "state": {"status": "completed", "input": {"command": "python -m unittest"},
                 "metadata": {"exit": 0, "output": "Ran 4 tests in 0.01s\n\nOK"}}}}
        self.assertTrue(paired._successful_test_event(event))
        event["part"]["state"]["metadata"]["output"] = "Ran 0 tests in 0.01s\n\nOK"
        self.assertFalse(paired._successful_test_event(event))
        event["part"]["state"]["metadata"]["output"] = "Ran 4 tests in 0.01s\n\nFAILED"
        self.assertFalse(paired._successful_test_event(event))
        event["part"]["state"]["metadata"]["output"] = "Ran 4 tests in 0.01s\n\nOK"
        event["part"]["state"]["metadata"]["exit"] = 1
        self.assertFalse(paired._successful_test_event(event))

    def test_swap_stop_requires_ten_consecutive_samples_over_threshold(self) -> None:
        baseline = 1000 * 1024**2
        low = {"swap_used_mb": 1500}
        high = {"swap_used_mb": 1513}
        self.assertFalse(swap_growth_breach([high] * 9, baseline))
        self.assertTrue(swap_growth_breach([low, *([high] * 10)], baseline))
        self.assertFalse(swap_growth_breach([*([high] * 9), low, *([high] * 9)], baseline))

    def test_pregrader_guard_rejects_mode_changes_before_any_grader_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "protected.py"
            target.write_text("value = 1\n", encoding="utf-8")
            baseline = {"protected.py": target.stat().st_mode & 0o777}
            target.chmod((baseline["protected.py"] ^ 0o111) & 0o777)
            gate = pregrade_workspace_gate(root, baseline)
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["mode_changes"], ["protected.py"])

    def test_final_grader_owns_mode_change_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "protected.py"
            target.write_text("value = 1\n", encoding="utf-8")
            baseline = {"protected.py": target.stat().st_mode & 0o777}
            target.chmod((baseline["protected.py"] ^ 0o111) & 0o777)
            result = {"success": False, "integrity_pass": False, "scope_pass": False, "grader_skipped": True}
            with mock.patch.object(paired, "_independent_grade", return_value=result) as grader:
                grade, _ = paired._grade_workspace_when_safe(root, root, "calculator_division", root, baseline)
        self.assertTrue(grade["grader_skipped"])
        grader.assert_called_once()

    def test_pregrader_guard_allows_new_allowed_file_with_normal_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            service = root / "src" / "service.py"
            service.write_text("def serve(): pass\n", encoding="utf-8")
            baseline_modes = {"src/service.py": service.stat().st_mode & 0o777}

            # Add newly allowed file for package_refactor (src/metrics.py)
            metrics = root / "src" / "metrics.py"
            metrics.write_text("def summarize_metrics(): pass\n", encoding="utf-8")

            allowed = {"src/service.py", "src/metrics.py", "tests/test_service.py"}
            gate = pregrade_workspace_gate(root, baseline_modes, allowed_files=allowed)
        self.assertTrue(gate["passed"], f"Gate failed with mode_changes: {gate.get('mode_changes')}")
        self.assertEqual(gate["mode_changes"], [])

    def test_grade_workspace_when_safe_allows_package_refactor_with_metrics_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline"
            workspace = root / "workspace"
            for d in (baseline, workspace):
                (d / "src").mkdir(parents=True)
                (d / "tests").mkdir()
                (d / "src" / "service.py").write_text("def serve(): pass\n", encoding="utf-8")
                (d / "tests" / "test_service.py").write_text("assert True\n", encoding="utf-8")
            # In workspace, create the new required metrics.py
            (workspace / "src" / "metrics.py").write_text("def summarize_metrics(): pass\n", encoding="utf-8")
            base_modes = paired._file_modes(baseline)

            with mock.patch.object(paired, "_independent_grade", return_value={
                "success": True, "integrity_pass": True, "scope_pass": True,
                "grader_protocol_version": "pristine-workspace-v1",
            }) as grader:
                grade, gate = paired._grade_workspace_when_safe(workspace, baseline, "package_refactor", root, base_modes)
        self.assertTrue(gate["passed"])
        self.assertFalse(grade.get("grader_skipped", False))
        grader.assert_called_once()

    def test_pregrader_guard_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root.parent / (root.name + "-outside")
            outside.write_text("do not read\n", encoding="utf-8")
            link = root / "linked.py"
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            gate = pregrade_workspace_gate(root, {})
            result = {"success": False, "integrity_pass": False, "scope_pass": False, "grader_skipped": True}
            with mock.patch.object(paired, "_independent_grade", return_value=result) as grader:
                grade, _ = paired._grade_workspace_when_safe(root, root, "calculator_division", root, {})
            outside.unlink()
        self.assertFalse(gate["passed"])
        self.assertEqual(gate["symlinks"], ["linked.py"])
        self.assertTrue(grade["grader_skipped"])
        grader.assert_called_once()

    def test_paired_report_uses_only_central_grade_inspection(self) -> None:
        grade = {
            "integrity_pass": False,
            "scope_pass": False,
            "candidate_inspection": {"problems": []},
            "integrity_details": {"protected_content_changes": ["README.txt"], "mode_changes": []},
            "scope_details": {"unlisted_files": ["notes.txt"]},
        }
        report = paired._protected_files_report(grade)
        self.assertFalse(report["passed"])
        self.assertEqual(report["protected_content_changes"], ["README.txt"])
        self.assertEqual(report["unscoped_added_files"], ["notes.txt"])

    def test_workspace_root_symlink_is_rejected_before_grader_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            (outside / "sentinel.py").write_text("must not be read\n", encoding="utf-8")
            link = root / "workspace-link"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            result = {"success": False, "integrity_pass": False, "scope_pass": False, "grader_skipped": True}
            with mock.patch.object(paired, "_independent_grade", return_value=result) as grader:
                grade, gate = paired._grade_workspace_when_safe(link, outside,
                                                                 "calculator_division", root, {})
        self.assertFalse(gate["passed"])
        self.assertTrue(grade["grader_skipped"])
        grader.assert_called_once()

    def test_diagnostic_stops_end_calibration_but_quality_failure_does_not(self) -> None:
        self.assertFalse(fatal_diagnostic_stop({"strict_pass": False}))
        self.assertFalse(fatal_diagnostic_stop({"strict_pass": False, "stop_reason": "task_timeout"}))
        for reason in ("server_lost_or_oom", "swap_growth_limit", "round_deadline",
                       "effective_profile_failed", "runner_error:OSError"):
            with self.subTest(reason=reason):
                self.assertTrue(fatal_diagnostic_stop({"strict_pass": False, "stop_reason": reason}))

    def test_calibration_stop_is_persisted_without_retry_and_quality_failure_continues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records: list[dict] = []
            quality_failure = {"stage": "calibration", "strict_pass": False}
            self.assertFalse(paired._record_diagnostic(root, records, quality_failure))
            lines = (root / "records.jsonl").read_text(encoding="utf-8").splitlines()
            stored = [json.loads(line) for line in lines]
            self.assertEqual(stored, [quality_failure])
            for stage, stop_reason in (("calibration", "server_lost_or_oom"), ("warmup", "round_deadline")):
                with self.subTest(stage=stage):
                    stage_root = root / stage
                    stage_root.mkdir()
                    stage_records: list[dict] = []
                    stopped = {"stage": stage, "strict_pass": False, "stop_reason": stop_reason}
                    self.assertTrue(paired._record_diagnostic(stage_root, stage_records, stopped))
                    raw = (stage_root / "records.jsonl").read_text(encoding="utf-8").splitlines()
                    self.assertEqual([json.loads(line) for line in raw], [stopped])
                    self.assertEqual(len(json.loads((stage_root / "records.json").read_text(encoding="utf-8"))), 1)
                    self.assertEqual(json.loads((stage_root / "summary.json").read_text(encoding="utf-8"))["measured_rows"], 0)

    def test_server_oom_segment_stops_even_when_health_is_not_part_of_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "server.log"
            log.write_text("started\n", encoding="utf-8")
            offset = log.stat().st_size
            with log.open("a", encoding="utf-8") as output:
                output.write("CUDA error: out of memory; endpoint still responds\n")
            self.assertTrue(paired._server_segment_has_oom(log, offset))
            self.assertEqual(paired._post_child_server_failure(log, offset, server_healthy=True), "server_lost_or_oom")

    def test_final_sampler_samples_are_checked_after_child_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "server.log"
            log.write_text("started\n", encoding="utf-8")
            baseline = 1000 * 1024**2
            final_samples = [{"swap_used_mb": 1513}] * 10
            self.assertEqual(
                paired._post_child_stop_reason(log, 0, server_healthy=True,
                                               existing_reason="task_timeout",
                                               resource_samples=final_samples,
                                               swap_baseline_bytes=baseline),
                "swap_growth_limit")
            with log.open("a", encoding="utf-8") as output:
                output.write("CUDA error: out of memory\n")
            self.assertEqual(
                paired._post_child_stop_reason(log, 0, server_healthy=True,
                                               existing_reason=None,
                                               resource_samples=final_samples,
                                               swap_baseline_bytes=baseline),
                "server_lost_or_oom")

    def test_cli_execute_without_release_fails_before_any_runner_setup(self) -> None:
        with mock.patch.object(paired, "run_series") as runner:
            with self.assertRaises(SystemExit) as raised:
                paired.main(["--execute", "--benchmark-root", "not-used"])
        self.assertEqual(raised.exception.code, 2)
        runner.assert_not_called()

    def test_pinned_runtime_accepts_exact_reported_nine_character_revision(self) -> None:
        reported = ("version: 0.6.0-dev (build 1, commit d81235049)\n"
                    "built with GNU 13.3.0 for Linux x86_64")
        accepted_prefix = paired.RUNTIME_REVISION[:9]
        self.assertEqual(accepted_prefix, "d81235049")
        self.assertEqual(paired.require_runtime_revision(reported, "", accepted_prefix), reported)
        with self.assertRaisesRegex(RuntimeError, "Unexpected llama.cpp build"):
            paired.require_runtime_revision(reported, "", paired.RUNTIME_REVISION[:10])

    def test_failed_effective_profile_blocks_compatibility_child_call(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def prepare_run(_harness, run_dir, *_args, **_kwargs):
                workspace = run_dir / "workspace"
                workspace.mkdir(parents=True)
                (run_dir / "home/.config/opencode").mkdir(parents=True)
                prompt = run_dir / "prompt.txt"
                prompt.write_text("do not call model\n", encoding="utf-8")
                return prompt

            server_log = root / "server.log"
            server_log.write_text("", encoding="utf-8")
            with (
                mock.patch.object(paired, "_prepare_run", side_effect=prepare_run),
                mock.patch.object(paired, "_isolated_environment", return_value={}),
                mock.patch.object(paired, "_profile_checks", return_value={"passed": False, "checks": {"task_denied": False}}),
                mock.patch.object(paired, "_model_loaded", return_value=True),
                mock.patch.object(paired.subprocess, "Popen") as child,
                mock.patch.object(paired, "block_legacy_execution"),
            ):
                record = paired._tool_round_trip(Path("opencode"), root, "qwen3.5-4b", server_log,
                                                  root / "output", time.monotonic() + 10, 0)
        self.assertFalse(record["passed"])
        self.assertEqual(record["stop_reason"], "effective_profile_failed")
        child.assert_not_called()

    def test_tool_round_trip_happy_path_records_real_bash_and_edit_evidence(self) -> None:
        class FakeProcess:
            pid = 123456

            def __init__(self, command, *, stdout=None, cwd=None, **_kwargs):
                self.command = command
                self.returncode = 0
                if "resource_sampler.py" not in " ".join(map(str, command)):
                    workspace = Path(cwd)
                    (workspace / "TASK.md").write_text("edit probe ok", encoding="utf-8")
                    events = [
                        {"type": "tool_use", "part": {"tool": "bash", "state": {
                            "status": "completed", "input": {"command": "python -c 'print(6 * 7)'"},
                            "metadata": {"exit": 0}, "output": "42"}}},
                        {"type": "tool_use", "part": {"tool": "edit", "state": {
                            "status": "completed", "input": {"filePath": str(workspace / "TASK.md")},
                            "metadata": {"exit": 0}}}},
                    ]
                    for event in events:
                        stdout.write(json.dumps(event) + "\n")

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_root = root / "output"
            server_log = root / "server.log"
            server_log.write_text("server ready\n", encoding="utf-8")

            def fake_popen(command, **kwargs):
                if isinstance(command, (list, tuple)) and command and command[0] == "git":
                    return real_popen(command, **kwargs)
                return FakeProcess(command, **kwargs)

            real_popen = paired.subprocess.Popen
            with (
                mock.patch.object(paired, "_isolated_environment", return_value={}),
                mock.patch.object(paired, "_profile_checks", return_value={"passed": True}),
                mock.patch.object(paired, "_model_loaded", return_value=True),
                mock.patch.object(paired, "_server_ready", return_value=True),
                mock.patch.object(paired.subprocess, "Popen", side_effect=fake_popen) as popen,
                mock.patch.object(paired, "_terminate_process_group"),
                mock.patch.object(paired, "block_legacy_execution"),
            ):
                record = paired._tool_round_trip(Path("opencode"), root, "qwen3.5-4b", server_log,
                                                  output_root, time.monotonic() + 30, 0)

            run_dir = output_root / "compatibility/qwen3.5-4b"
            workspace = run_dir / "workspace"
            launched = [call.args[0] for call in popen.call_args_list
                        if not (isinstance(call.args[0], (list, tuple)) and call.args[0]
                                and call.args[0][0] == "git")]
            self.assertEqual(len(launched), 2)
            self.assertTrue((run_dir / "TASK_PROMPT.md").is_file())
            self.assertEqual((workspace / "TASK.md").read_bytes(), b"edit probe ok")
            events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([event["part"]["tool"] for event in events], ["bash", "edit"])
            self.assertTrue(record["passed"])
            self.assertIsNone(record["stop_reason"])
            self.assertTrue(record["expected_output_seen"])
            self.assertEqual(record["completed_bash_tool_calls"], 1)
            self.assertEqual(record["edit_task_md_tool_calls"], 1)
            self.assertTrue(record["edit_file_verified"])
            self.assertTrue(record["edit_workspace_gate"]["passed"])
            self.assertEqual(record["events_sha256"], paired._sha256(run_dir / "events.jsonl"))
            self.assertEqual(record["events_path"], str(run_dir / "events.jsonl"))
            self.assertEqual(record["model_sha256"], MODELS["qwen3.5-4b"]["sha256"])

    def test_classify_failure_covers_all_categories(self) -> None:
        self.assertEqual(paired.classify_failure(runner_error=True), "runner")
        self.assertEqual(paired.classify_failure(transport_error=True), "transport")
        self.assertEqual(paired.classify_failure(resource_error=True), "resource")
        self.assertEqual(paired.classify_failure(tool_env_error=True), "tool_env")
        self.assertEqual(paired.classify_failure(timeout_error=True), "timeout")
        self.assertEqual(paired.classify_failure(scope_error=True), "scope")
        self.assertEqual(paired.classify_failure(contract_error=True), "model_contract")
        self.assertEqual(paired.classify_failure(functional_error=True), "functional")
        self.assertEqual(paired.classify_failure(), "none")

    def test_mechanical_preflight_validates_python3_and_fixture(self) -> None:
        result = paired.mechanical_preflight(python_executable=sys.executable,
                                             fixture_dir=Path(__file__).resolve().parents[1] / "benchmark/fixtures/harness_task")
        self.assertTrue(result["passed"])
        self.assertTrue(result["python_ok"])
        self.assertTrue(result["fixture_ok"])
        self.assertEqual(result["failure_class"], "none")

        missing = paired.mechanical_preflight(python_executable="non_existent_python_binary_xyz_123")
        self.assertFalse(missing["passed"])
        self.assertFalse(missing["python_ok"])
        self.assertEqual(missing["failure_class"], "tool_env")

    def test_isolated_environment_creates_guarded_edit_executable_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            workspace = run_dir / "workspace"
            install_root = Path(temp) / "install"
            workspace.mkdir(parents=True)
            env = paired._isolated_environment("opencode", run_dir, install_root, workspace)
            script = run_dir / "bin" / "guarded-edit"
            self.assertTrue(script.is_file())
            guarded_edit_path = Path(__file__).resolve().parents[1] / "benchmark/guarded_edit.py"
            self.assertEqual(
                script.read_text(encoding="utf-8"),
                f'#!/usr/bin/env bash\nexec python3 {shlex.quote(str(guarded_edit_path))} "$@"\n',
            )
            if os.name != "nt":
                self.assertEqual(script.stat().st_mode & 0o777, 0o755)
            self.assertTrue(env["PATH"].startswith(str(run_dir / "bin") + ":"))


if __name__ == "__main__":
    unittest.main()
