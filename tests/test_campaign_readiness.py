from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import urllib.request
from unittest.mock import Mock, patch
from pathlib import Path

from benchmark import campaign_readiness


class CampaignReadinessTests(unittest.TestCase):
    def test_default_evidence_root_is_unique_and_under_benchmark_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            benchmark_root = Path(temporary) / "benchmark"
            benchmark_root.mkdir()
            with (
                patch.object(campaign_readiness.time, "time_ns", return_value=12345),
                patch.object(campaign_readiness.subprocess, "run",
                             return_value=Mock(returncode=0, stdout="ext4\n")),
            ):
                path = campaign_readiness._prepare_evidence_root(None, benchmark_root=benchmark_root)
            self.assertEqual(path, benchmark_root / "results/readiness-12345")
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_evidence_root_rejects_existing_directory_without_overwriting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "readiness"
            path.mkdir()
            marker = path / "readiness-report.json"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                campaign_readiness._prepare_evidence_root(path)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_current_readiness_returns_and_persists_self_validated_report(self) -> None:
        digest = "a" * 64
        snapshot = {"complete": True, "records": [], "digest": digest}
        grade_names = (
            "trusted_grader_scope", "six_references", "six_noops", "six_mutants",
            "mutation_identity_controls", "runner_forgery", "unsupported_side_effects",
        )
        sandbox_names = (
            "sandbox_sentinel", "host_file_oracle_observer_denial", "network_denial",
            "fake_broker", "detached_descendant_cleanup", "output_resource_scratch_caps",
            "workspace_export_modes", "observer_sampling",
        )
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            with (
                patch.object(campaign_readiness, "input_hash_manifest", return_value=snapshot),
                patch.object(campaign_readiness, "_grade_controls",
                             return_value={name: {"status": "passed"} for name in grade_names}),
                patch.object(campaign_readiness, "_sandbox_control_gates",
                             return_value={name: {"status": "passed"} for name in sandbox_names}),
                patch.object(campaign_readiness, "_fake_opencode_probe", return_value={"passed": True}),
                patch.object(campaign_readiness, "_canonical_trial_control",
                             return_value={"passed": True, "reason": "local_fake_task_trial"}),
                patch.object(campaign_readiness, "_model_bundle_audit",
                             return_value={"passed": True, "evidence": {}}),
                patch.object(campaign_readiness, "_workspace_checks", return_value={"passed": True}),
                patch.object(campaign_readiness.subprocess, "run",
                             return_value=Mock(returncode=0, stdout="ext4\n")),
            ):
                report = campaign_readiness.run_current_readiness(evidence_dir=evidence)
            saved = json.loads((evidence / "readiness-report.json").read_text(encoding="utf-8"))

        self.assertIsInstance(report, dict)
        self.assertTrue(report["ready"])
        self.assertEqual(report["verdict"], "READY")
        self.assertTrue(report["self_validation"]["ready"])
        self.assertEqual(saved, report)
        self.assertEqual(report["native_event_authority"], "untrusted_process_stream")
        self.assertEqual(report["gates"]["canonical_trial_end_to_end"]["status"], "passed")

    def test_usage_evidence_separates_native_counters_from_backend_token_usage(self) -> None:
        unavailable = campaign_readiness._opencode_usage_evidence([])
        self.assertEqual(unavailable["harness_reported_counts"]["token_counts_status"], "unavailable")
        self.assertIsNone(unavailable["harness_reported_counts"]["token_counts"]["input_tokens"])
        self.assertIsNone(unavailable["backend_token_usage"]["prompt_tokens"])

        reported_zero = campaign_readiness._opencode_usage_evidence([
            {"type": "step_finish", "part": {"tokens": {"input": 0, "output": 0}}}
        ])
        self.assertEqual(reported_zero["harness_reported_counts"]["token_counts_status"], "reported")
        self.assertEqual(reported_zero["harness_reported_counts"]["token_counts"]["input_tokens"], 0)
        self.assertEqual(reported_zero["backend_token_usage"]["status"], "unavailable")

    def test_fake_endpoint_emits_tools_only_when_request_has_supported_tools(self) -> None:
        server, thread, state = campaign_readiness._fake_endpoint("readiness-model")
        endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
        tools = [
            {"type": "function", "function": {"name": "bash", "parameters": {
                "type": "object", "properties": {"command": {"type": "string"}},
                "required": ["command"],
            }}},
            {"type": "function", "function": {"name": "edit", "parameters": {
                "type": "object", "properties": {
                    "filePath": {"type": "string"}, "oldString": {"type": "string"},
                    "newString": {"type": "string"},
                }, "required": ["filePath", "oldString", "newString"],
            }}},
        ]

        def post(payload: dict[str, object]) -> dict[str, object]:
            request = urllib.request.Request(
                endpoint, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                return json.load(response)

        try:
            tool_response = post({"model": "readiness-model", "tools": tools})
            tool_message = tool_response["choices"][0]["message"]
            self.assertEqual(state["tool_calls"], ["bash", "edit"])
            self.assertEqual(tool_message["content"], None)
            calls = tool_message["tool_calls"]
            bash_arguments = json.loads(calls[0]["function"]["arguments"])
            self.assertEqual(bash_arguments["command"], "printf fake-bash-ok > src/bash-probe.txt")

            final_response = post({"model": "readiness-model", "messages": []})
            final_message = final_response["choices"][0]["message"]
            self.assertEqual(final_message["content"], "fake endpoint roundtrip complete")
            self.assertNotIn("tool_calls", final_message)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

    def test_pytest_gate_counts_skips_as_unavailable_outcomes(self) -> None:
        passed = campaign_readiness._pytest_summary_counts("8 passed, 2 subtests passed in 0.31s")
        self.assertEqual(passed["passed"], 8)
        self.assertEqual(passed["skipped"], 0)
        skipped = campaign_readiness._pytest_summary_counts("7 passed, 1 skipped, 2 xfailed")
        self.assertEqual(skipped["passed"], 7)
        self.assertEqual(skipped["skipped"], 1)
        self.assertEqual(skipped["xfailed"], 2)

    def test_runtime_input_hashes_verified_symlink_target_and_link_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "python-runtime"
            target.write_bytes(b"trusted runtime fixture")
            link = root / "python3"
            link.symlink_to(target.name)

            record = campaign_readiness._runtime_file_record("runtime/test-python", link)

        self.assertEqual(record["status"], "measured")
        self.assertEqual(record["type"], "symlink")
        self.assertEqual(record["link_target"], "python-runtime")
        self.assertEqual(record["sha256"], hashlib.sha256(b"trusted runtime fixture").hexdigest())

    def test_runtime_input_rejects_dangling_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            link = Path(temporary) / "python3"
            link.symlink_to("missing-python")
            record = campaign_readiness._runtime_file_record("runtime/test-python", link)

        self.assertEqual(record["status"], "unavailable")

    def test_current_task_prompt_sources_are_in_the_input_manifest(self) -> None:
        from benchmark.harness_runner import TASK_PATHS

        files = campaign_readiness._manifest_files()
        for _fixture, prompt in TASK_PATHS.values():
            self.assertIn(prompt.as_posix(), files)

    def test_missing_or_unavailable_gate_never_yields_ready(self) -> None:
        report = {
            "verdict": "READY",
            "input_digest": "same",
            "gates": {
                name: {"status": "passed"}
                for name in campaign_readiness.REQUIRED_GATES
            },
        }
        report["gates"].pop("fake_opencode_roundtrip")
        result = campaign_readiness.validate_readiness_report(report, current_input_digest="same")
        self.assertFalse(result["ready"])
        self.assertIn("fake_opencode_roundtrip", result["failed_gates"])

        report["gates"]["fake_opencode_roundtrip"] = {"status": "unavailable"}
        result = campaign_readiness.validate_readiness_report(report, current_input_digest="same")
        self.assertFalse(result["ready"])
        self.assertIn("fake_opencode_roundtrip", result["failed_gates"])

    def test_saved_ready_evidence_is_rejected_after_any_input_change(self) -> None:
        report = {
            "verdict": "READY",
            "input_digest": "before",
            "gates": {name: {"status": "passed"} for name in campaign_readiness.REQUIRED_GATES},
        }
        result = campaign_readiness.validate_readiness_report(report, current_input_digest="after")
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "input_digest_mismatch")

    def test_non_ready_source_verdict_cannot_be_promoted_by_successful_gates(self) -> None:
        report = {
            "verdict": "BLOCKED",
            "input_digest": "same",
            "gates": {name: {"status": "passed"} for name in campaign_readiness.REQUIRED_GATES},
        }
        result = campaign_readiness.validate_readiness_report(report, current_input_digest="same")
        self.assertFalse(result["ready"])
        self.assertEqual(result["reason"], "source_verdict_not_ready")


if __name__ == "__main__":
    unittest.main()
