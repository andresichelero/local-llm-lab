from __future__ import annotations

import json
import unittest
import stat
import tempfile
from types import MappingProxyType
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from collections import Counter

from benchmark import safe_campaign


class SafeCampaignPlanTests(unittest.TestCase):
    def _run_synthetic_campaign(self, *, fail_after_two_rows: bool = False) -> dict:
        """Traverse real orchestration/persistence with zero model or task execution."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output_root = root / "campaign"
            starts = []
            stops = []
            task_calls = []

            def start_server(benchmark_root, model, output_root):
                process = object()
                starts.append((model, process))
                return process, output_root / f"synthetic-server-{len(starts)}.log"

            def execute_task(row, **kwargs):
                task_calls.append(dict(row))
                if (fail_after_two_rows and row["block"] == 2
                        and row["stage"] == "measurement"
                        and row["task"] == safe_campaign.build_schedule()[8]["task"]):
                    raise RuntimeError("synthetic interrupted session after two measured rows")
                run_dir = output_root / f"synthetic-{row['block']}-{row['stage']}-{row['task']}"
                run_dir.mkdir()
                record = {**row, "experiment": kwargs["experiment"], "attempted": True,
                          "denominator_eligible": row["stage"] == "measurement",
                          "strict_pass": True, "failure_category": "passed",
                          "model_requests": 0, "successful_model_responses": 0,
                          "run_dir": str(run_dir),
                          "synthetic_partial_evidence": f"preserved-block-{row['block']}-{row['task']}",
                          "resource_sampling": {"server_session": kwargs["session_resource"]}}
                safe_campaign._json_write(run_dir / "record.json", record)
                safe_campaign._record_jsonl(output_root / "records.jsonl", record)
                return record

            def start_monitor(path, **kwargs):
                return path.name, {"status": "running", "sample_count": 1}

            def stop_monitor(handle, startup):
                return {"status": "measured", "sample_count": 2,
                        "cleanup_verified": True, "synthetic_monitor": handle}

            snapshot = {"complete": True, "digest": "a" * 64, "records": []}
            with (
                patch.object(safe_campaign, "_port_is_free", return_value=True),
                patch.object(safe_campaign.campaign_readiness, "input_hash_manifest", return_value=snapshot),
                patch.object(safe_campaign.campaign_readiness, "validate_readiness_report", return_value={"ready": True}),
                patch.object(safe_campaign.campaign_readiness, "_model_bundle_audit", return_value={"passed": True}),
                patch.object(safe_campaign, "_is_ext4", return_value=True),
                patch.object(safe_campaign.shutil, "disk_usage", return_value=SimpleNamespace(free=16 * 1024**3)),
                patch.object(safe_campaign, "_start_server", side_effect=start_server),
                patch.object(safe_campaign, "_stop_server", side_effect=stops.append),
                patch.object(safe_campaign, "_execute_task", side_effect=execute_task),
                patch.object(safe_campaign, "_resource_monitor_start", side_effect=start_monitor),
                patch.object(safe_campaign, "_resource_monitor_stop", side_effect=stop_monitor),
            ):
                result = safe_campaign.execute_campaign(
                    benchmark_root=root, output_root=output_root,
                    readiness_runner=lambda **kwargs: {"ready": True, "synthetic_control": True})
            records = [json.loads(line) for line in (output_root / "records.jsonl").read_text().splitlines()]
            summary = json.loads((output_root / "summary.json").read_text())
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["measurement_rows"], 48)
            self.assertEqual(len(records), 56)
            self.assertEqual(result["model_sessions_started"], 8)
            self.assertEqual([model for model, _process in starts], list(safe_campaign.BLOCK_MODELS))
            self.assertEqual(stops, [process for _model, process in starts])
            self.assertEqual(len(stops), 8)
            self.assertFalse(result["inference_performed"])
            self.assertEqual(result["model_requests"], 0)
            self.assertEqual(result["successful_model_responses"], 0)
            self.assertEqual(summary["strict_passes"], result["strict_passes"])
            measured = [row for row in records if row["denominator_eligible"]]
            warmups = [row for row in records if not row["denominator_eligible"]]
            self.assertEqual(len(warmups), 8)
            self.assertEqual({row["block"] for row in warmups}, set(range(1, 9)))
            self.assertTrue(all(row["stage"] == "warmup" and row["repeat"] == 0 for row in warmups))
            keys = [(row["block"], row["model"], row["task"], row["repeat"]) for row in measured]
            expected = [(row["block"], row["model"], row["task"], row["repeat"])
                        for row in safe_campaign.build_schedule()]
            self.assertCountEqual(keys, expected)
            self.assertEqual(len(set(keys)), 48)
            self.assertEqual(Counter((row["model"], row["task"]) for row in measured),
                             Counter({(model, task): 4 for model in safe_campaign.MODELS
                                      for task in safe_campaign.TASKS}))
            for row in records:
                session = json.loads((output_root / "resource-sessions" /
                                      f"block-{row['block']}" / "summary.json").read_text())
                self.assertEqual(row["resource_sampling"]["server_session"], session)
                self.assertEqual(session["status"], "measured")
                self.assertTrue(session["cleanup_verified"])
                if row.get("run_dir"):
                    saved = json.loads((Path(row["run_dir"]) / "record.json").read_text())
                    self.assertEqual(saved, row)
                    self.assertEqual(saved["synthetic_partial_evidence"],
                                     f"preserved-block-{row['block']}-{row['task']}")
            return {"result": result, "records": records, "task_calls": task_calls}

    def test_no_model_full_campaign_preserves_all_sessions_rows_and_final_sampling(self) -> None:
        control = self._run_synthetic_campaign()
        self.assertEqual(len(control["task_calls"]), 56)
        self.assertEqual(control["result"]["strict_passes"], 48)
        self.assertEqual(control["result"]["failure_categories"]["passed"], 48)
        self.assertEqual(control["result"]["failure_categories"]["infrastructure"], 0)

    def test_no_model_session_interruption_preserves_completed_rows_and_full_denominator(self) -> None:
        control = self._run_synthetic_campaign(fail_after_two_rows=True)
        self.assertEqual(control["result"]["strict_passes"], 44)
        self.assertEqual(control["result"]["failure_categories"]["passed"], 44)
        self.assertEqual(control["result"]["failure_categories"]["infrastructure"], 4)
        failed = [row for row in control["records"] if row["failure_category"] == "infrastructure"]
        self.assertEqual(len(failed), 4)
        self.assertTrue(all(row["block"] == 2 and not row["attempted"] for row in failed))
        self.assertTrue(all("synthetic interrupted session" in row["infrastructure_error"] for row in failed))
        preserved = [row for row in control["records"] if row["block"] == 2
                     and row["denominator_eligible"] and row["strict_pass"]]
        self.assertEqual(len(preserved), 2)
        self.assertTrue(all(row["synthetic_partial_evidence"] for row in preserved))

    def test_server_accepts_installed_nine_character_revision_and_rejects_mismatch(self) -> None:
        from benchmark.model_quality_paired import MODELS, RUNTIME_REVISION

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = next(iter(MODELS))
            model_path = root / MODELS[model]["path"]
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"synthetic model identity control")
            for revision, accepted in ((RUNTIME_REVISION[:9], True), ("000000000", False)):
                with (
                    self.subTest(revision=revision),
                    patch.object(safe_campaign, "_port_is_free", return_value=True),
                    patch.object(safe_campaign.campaign_readiness, "_sha256_file",
                                 return_value=MODELS[model]["sha256"]),
                    patch("benchmark.opencode_controlled_probe._assert_server_bundle"),
                    patch.object(safe_campaign.subprocess, "run", return_value=SimpleNamespace(
                        returncode=0, stdout=f"version: 9999 ({revision})", stderr="")),
                    patch.object(safe_campaign.subprocess, "Popen") as launch,
                    patch.object(safe_campaign, "_port_has_model", return_value=True),
                ):
                    launch.return_value.poll.return_value = None
                    if accepted:
                        process, log_path = safe_campaign._start_server(root, model, root)
                        self.assertIs(process, launch.return_value)
                        self.assertTrue(log_path.is_file())
                        launch.assert_called_once()
                    else:
                        with self.assertRaisesRegex(RuntimeError, "Unexpected llama.cpp build"):
                            safe_campaign._start_server(root, model, root)
                        launch.assert_not_called()

    def test_schedule_is_seeded_six_task_abba_with_two_measurements_per_pair(self) -> None:
        first = safe_campaign.build_schedule(seed=1234)
        self.assertEqual(first, safe_campaign.build_schedule(seed=1234))
        self.assertEqual(len(first), 48)
        self.assertEqual(
            [first[index * 6]["model"] for index in range(8)],
            ["qwen3.5-4b", "qwen3.5-9b", "qwen3.5-9b", "qwen3.5-4b"] * 2,
        )
        self.assertEqual({row["task"] for row in first}, set(safe_campaign.TASKS))
        for model in safe_campaign.MODELS:
            for task in safe_campaign.TASKS:
                rows = [row for row in first if row["model"] == model and row["task"] == task]
                self.assertEqual(len(rows), 4)
                self.assertEqual({row["repeat"] for row in rows}, {1, 2, 3, 4})
        for block in range(8):
            self.assertEqual(
                [row["task"] for row in first[block * 6 : (block + 1) * 6]],
                [row["task"] for row in first[:6]],
            )

    def test_protocol_freezes_required_language_and_generation_contract(self) -> None:
        protocol = safe_campaign.frozen_protocol(seed=1234)
        self.assertEqual(protocol["grader_protocol_version"], "restricted-python-workspace-v2")
        self.assertEqual(protocol["candidate_language_contract"], "restricted-python-workspace-v2")
        self.assertEqual(protocol["generation"], {"temperature": 0, "seed": 1234, "max_output_tokens": 1024})
        self.assertEqual(protocol["context_tokens"], 16384)
        self.assertEqual(protocol["kv_cache"], "q4_0")
        self.assertTrue(protocol["flash_attention"])
        self.assertEqual(protocol["reasoning"], "off")
        self.assertFalse(protocol["prompt_cache"])
        self.assertFalse(protocol["mtp"])
        self.assertEqual(protocol["measured_repeats_per_model_task"], 4)
        self.assertEqual(protocol["warmup"]["count_per_model_session"], 1)
        self.assertTrue(protocol["warmup"]["excluded_from_denominator"])
        self.assertEqual(protocol["runtime"]["agent_environment"], safe_campaign.AGENT_ENVIRONMENT)
        self.assertEqual(protocol["runtime"]["agent_environment"]["PYTHONDONTWRITEBYTECODE"], "1")

    def test_candidate_prompt_declares_restricted_language_and_limits_claims(self) -> None:
        prompt = safe_campaign.build_task_prompt("calculator_division")
        self.assertIn("restricted-python-workspace-v2", prompt)
        self.assertIn("unsupported implementation syntax", prompt.lower())
        self.assertIn("not general", prompt.lower())
        self.assertIn("cpython compatibility", prompt.lower())
        self.assertIn("unseen training data", prompt)
        self.assertIn("nested function definitions", prompt)
        self.assertIn("262,144 bytes per module", prompt)

    def test_workspace_export_reconciliation_applies_modes_and_deletions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            preserved = workspace / "src/main.py"
            deleted = workspace / "tests/test_main.py"
            preserved.parent.mkdir()
            deleted.parent.mkdir()
            preserved.write_text("seed", encoding="utf-8")
            deleted.write_text("seed test", encoding="utf-8")
            safe_campaign._apply_workspace_exports(
                workspace,
                {"src/main.py": b"candidate"},
                {"src/main.py": 0o640},
                ("src/main.py", "tests/test_main.py"),
            )
            self.assertEqual(preserved.read_bytes(), b"candidate")
            self.assertEqual(stat.S_IMODE(preserved.stat().st_mode), 0o640)
            self.assertFalse(deleted.exists())

    def test_workspace_export_reconciliation_accepts_read_only_runtime_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "src").mkdir()
            safe_campaign._apply_workspace_exports(
                workspace,
                MappingProxyType({"src/main.py": b"candidate"}),
                MappingProxyType({"src/main.py": 0o640}),
                ("src/main.py",),
            )
            self.assertEqual((workspace / "src/main.py").read_bytes(), b"candidate")
            self.assertEqual(stat.S_IMODE((workspace / "src/main.py").stat().st_mode), 0o640)

    def test_workspace_export_rejects_missing_or_invalid_mode_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with self.assertRaises(RuntimeError):
                safe_campaign._apply_workspace_exports(
                    workspace, {"src/main.py": b"candidate"}, {}, ("src/main.py",))
            with self.assertRaises(RuntimeError):
                safe_campaign._apply_workspace_exports(
                    workspace, {"src/main.py": b"candidate"}, {"src/main.py": 0o4755},
                    ("src/main.py",))

    def test_broker_transcript_requires_complete_matching_request_count(self) -> None:
        evidence = {"complete": True, "request_count": 3}
        self.assertEqual(safe_campaign._broker_transcript_status(evidence, 3), "measured")
        self.assertEqual(safe_campaign._broker_transcript_status(evidence, 2), "unavailable")
        self.assertEqual(safe_campaign._broker_transcript_status({"request_count": 3}, 3), "unavailable")

    def test_candidate_test_edits_are_allowed_but_protected_file_changes_fail(self) -> None:
        audit = {
            "complete": True,
            "entry_count": 2,
            "seed_inventory": [
                {"path": "src/calculator.py", "sha256": "source-before"},
                {"path": "tests/test_calculator.py", "sha256": "tests-before"},
            ],
            "final_inventory": [
                {"path": "src/calculator.py", "sha256": "source-after"},
                {"path": "tests/test_calculator.py", "sha256": "tests-after"},
            ],
            "protected_changed": [], "protected_missing": [], "unauthorized_extra_paths": [],
            "missing_exports": [], "unsafe_paths": [],
        }
        changed_test_result = safe_campaign._workspace_audit_result(audit)
        self.assertTrue(changed_test_result["passed"])

        audit["protected_changed"] = ["TASK.md"]
        protected_change_result = safe_campaign._workspace_audit_result(audit)
        self.assertFalse(protected_change_result["passed"])
        self.assertEqual(protected_change_result["failures"]["protected_changed"], ["TASK.md"])

    def test_failure_categories_are_separate(self) -> None:
        self.assertEqual(safe_campaign.classify_failure({"evaluation_status": "unsupported_syntax"}), "unsupported_language")
        self.assertEqual(safe_campaign.classify_failure({"evaluation_status": "execution_limit"}), "resource")
        self.assertEqual(safe_campaign.classify_failure({"agent_exit_code": 1, "grade": {"success": False}}), "agent")
        self.assertEqual(safe_campaign.classify_failure({"agent_exit_code": 0, "grade": {"success": False}}), "grade")
        self.assertEqual(safe_campaign.classify_failure({"protocol_error": "bad input"}), "protocol")
        self.assertEqual(safe_campaign.classify_failure({
            "agent_exit_code": 0, "workflow_complete": False, "grade": {"success": True},
        }), "agent")

    def test_execution_gate_fails_before_server_start_when_current_readiness_fails(self) -> None:
        with (
            patch.object(safe_campaign, "run_current_readiness", return_value={"ready": False, "failures": ["sandbox"]}),
            patch.object(safe_campaign, "_start_server") as start_server,
        ):
            result = safe_campaign.execute_campaign(
                benchmark_root=safe_campaign.DEFAULT_BENCHMARK_ROOT,
                output_root=safe_campaign.DEFAULT_BENCHMARK_ROOT / "results" / "never-created",
            )
        start_server.assert_not_called()
        self.assertFalse(result["started"])
        self.assertEqual(result["status"], "not_ready")

    def test_task_prompt_manifest_uses_repo_paths_for_all_six_tasks(self) -> None:
        from benchmark.harness_runner import resolve_task
        from benchmark.pristine_grading import _load_manifest, _verify_fixture

        manifest = _load_manifest()
        with tempfile.TemporaryDirectory() as temporary:
            for task in safe_campaign.TASKS:
                workspace = Path(temporary) / task
                fixture, _prompt = resolve_task(task)
                trusted_files, _modes = _verify_fixture(task, fixture, manifest)
                task_prompt = safe_campaign._seed_workspace(task, workspace)
                record = safe_campaign._task_prompt_hash_record(task_prompt)

                self.assertEqual(record["category"], "task_prompt")
                self.assertEqual(record["path"], task_prompt.resolve().relative_to(
                    safe_campaign.REPO_ROOT.resolve()).as_posix())
                self.assertTrue((workspace / "TASK.md").is_file())
                self.assertFalse(task_prompt.resolve().is_relative_to(workspace.resolve()))
                actual_files = {
                    path.relative_to(workspace).as_posix()
                    for path in workspace.rglob("*") if path.is_file()
                }
                self.assertEqual(actual_files, set(trusted_files))
                self.assertFalse(any(path.name == "__pycache__" for path in workspace.rglob("*")))

    def test_runtime_profile_copy_is_private_external_and_short_lived(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "opencode.json"
            source.write_text('{"provider": {}}', encoding="utf-8")
            copied_path = None
            with safe_campaign._temporary_profile_copy(source) as bound_profile:
                copied_path = bound_profile
                self.assertEqual(bound_profile.read_bytes(), source.read_bytes())
                self.assertEqual(stat.S_IMODE(bound_profile.stat().st_mode), 0o600)
                self.assertNotIn(Path.home().resolve(), bound_profile.parents)
                self.assertNotIn(safe_campaign.REPO_ROOT.resolve(), bound_profile.parents)
            self.assertIsNotNone(copied_path)
            self.assertFalse(copied_path.exists())

    def test_resource_sampling_uses_supported_observer_sampler_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "observer"
            run_dir.mkdir()
            observer = safe_campaign.RunObserver(
                run_dir, {"hash_allowlist": [], "snapshot_hash_allowlist": []})
            agent_phase = observer.start_phase("initial_agent", source="agent_process")
            grade_phase = observer.start_phase("grading", source="final_grader")
            safe_campaign._record_resource_sampler_ends(
                observer, agent_phase, grade_phase,
                {"status": "measured", "sample_count": 3},
                {"status": "unavailable", "sample_count": 0},
            )
            observer.end_phase(agent_phase, "completed", source="agent_process")
            observer.end_phase(grade_phase, "completed", source="final_grader")
            observer.finalize("pass", "complete")
            events = [json.loads(line) for line in (run_dir / "observer-events.jsonl").read_text().splitlines()]

        sampler_events = [event for event in events if event["event_type"] == "sampler_end"]
        self.assertEqual([event["details"]["sample_count"] for event in sampler_events], [3, 0])
        self.assertEqual([event["phase_id"] for event in sampler_events], ["initial_agent", "grading"])

    def test_mocked_timeout_and_invalid_spec_keep_distinct_failure_categories(self) -> None:
        for case, timed_out, infrastructure_error, expected in (
            ("timeout", True, None, "resource"),
            ("invalid-spec", False, "invalid_spec:ValueError", "infrastructure"),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                output_root = root / "campaign"
                output_root.mkdir()
                result = SimpleNamespace(
                    returncode=None, timed_out=timed_out, cleanup_verified=True,
                    output_limited=False, output=b"", namespace_evidence={}, file_evidence={},
                    network_evidence={}, resource_evidence={}, broker_events=(),
                    broker_transcript_evidence=MappingProxyType({}),
                    workspace_outputs=MappingProxyType({}),
                    workspace_output_modes=MappingProxyType({}),
                    workspace_audit=MappingProxyType({"complete": False}),
                    infrastructure_error=infrastructure_error,
                )
                with (
                    patch.object(safe_campaign, "_safe_runtime_binds", return_value=()),
                    patch.object(safe_campaign, "_resource_monitor_start",
                                 return_value=(None, {"status": "unavailable"})),
                    patch("benchmark.linux_sandbox.SandboxSupervisor.run", return_value=result),
                ):
                    record = safe_campaign._execute_task(
                        {"block": 1, "model": "qwen3.5-4b", "task": "calculator_division",
                         "repeat": 1, "stage": "measurement"},
                        install_root=root, binary=root / "opencode", server_log=root / "server.log",
                        output_root=output_root, experiment=f"mocked-{case}",
                    )

                self.assertEqual(record["failure_category"], expected)
                self.assertEqual(record["timed_out"], timed_out)


if __name__ == "__main__":
    unittest.main()
