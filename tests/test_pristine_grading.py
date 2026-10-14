from __future__ import annotations

import importlib.util
import json
import marshal
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from benchmark import pristine_grading
from benchmark.harness_eval import grade_workspace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmark" / "fixtures" / "harness_task"


class PristineGradingRegressionTests(unittest.TestCase):
    def test_results_state_authentication_and_integrity_limits_even_on_preflight_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            copied_fixture = root / "fixture-copy"
            shutil.copytree(FIXTURE, workspace)
            shutil.copytree(FIXTURE, copied_fixture)

            normal = grade_workspace(workspace, FIXTURE)
            preflight_failure = grade_workspace(workspace, copied_fixture)

        for result in (normal, preflight_failure):
            self.assertFalse(result["runtime_result_authenticated"], result)
            self.assertFalse(result["adversarial_evaluation_validated"], result)
            self.assertFalse(result["aggregate_is_security_proof"], result)
            self.assertIn("false_positives_possible", result["aggregate_interpretation"])
            self.assertEqual(
                result["result_authentication_semantics"],
                "not_authenticated_against_hostile_candidate_source",
            )
            self.assertEqual(
                result["integrity_semantics"],
                "static_workspace_structure_and_protected_files_only",
            )

    def test_trusted_suite_does_not_accept_candidate_printed_unittest_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_fake.py").write_text(
                "print('Ran 4 tests in 0.001s\\n\\nOK')\n"
                "raise SystemExit(0)\n",
                encoding="utf-8",
            )
            grade_root = root / "grade"
            grade_root.mkdir()
            command = pristine_grading._trusted_unittest_command(tests, "test*.py")

            result = pristine_grading._run_trusted_suite(
                command,
                cwd=root,
                environment=pristine_grading._isolated_environment(grade_root, root),
                timeout_seconds=5,
            )

            self.assertFalse(result["passed"], result)
            self.assertFalse(result["runner_success"], result)
            self.assertGreater(result["test_count"], 0, result)

    def test_runner_io_error_still_stops_spawned_process_group(self) -> None:
        process = Mock()
        process.communicate.side_effect = OSError("pipe read failed")
        process.returncode = 0
        with patch.object(pristine_grading.subprocess, "Popen", return_value=process), patch.object(
            pristine_grading, "stop_process_group", return_value=0
        ) as stop_group:
            result = pristine_grading._run_trusted_suite(
                ["python", "-c", "pass"],
                cwd=Path.cwd(),
                environment={},
                timeout_seconds=1,
            )

        stop_group.assert_called_once_with(process, grace_seconds=0.5)
        self.assertTrue(result["cleanup_verified"], result)
        self.assertFalse(result["passed"], result)

    def test_unverified_regression_cleanup_skips_final_behavior_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            shutil.copytree(FIXTURE, workspace)
            fake_regression = {
                "passed": False,
                "reason": "process_group_cleanup_unverified",
                "output": "",
                "test_count": None,
                "cleanup_verified": False,
            }
            with patch.object(
                pristine_grading, "_run_trusted_suite", return_value=fake_regression
            ) as run_suite:
                result = grade_workspace(workspace, FIXTURE)

            run_suite.assert_called_once()
            self.assertIsNone(result["functional_pass"], result)
            self.assertTrue(result["grader_skipped"], result)

    def test_timestamp_valid_cached_implementation_cannot_replace_candidate_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            shutil.copytree(FIXTURE, workspace)
            source_path = workspace / "src" / "calculator.py"
            original_source = (FIXTURE / "src" / "calculator.py").read_bytes()
            source_path.write_bytes(original_source)
            good_source = (
                "def add(a: float, b: float) -> float:\n"
                "    return a + b\n\n"
                "def multiply(a: float, b: float) -> float:\n"
                "    return a * b\n\n"
                "def divide(a: float, b: float) -> float:\n"
                "    if b == 0:\n"
                "        raise ValueError('division by zero')\n"
                "    return a / b\n"
            )
            (workspace / "tests" / "test_calculator.py").write_text(
                "import unittest\n"
                "from src.calculator import add, divide, multiply\n\n"
                "class CalculatorTests(unittest.TestCase):\n"
                "    def test_divide_positive(self):\n"
                "        self.assertEqual(divide(10, 2), 5)\n"
                "    def test_divide_negative(self):\n"
                "        self.assertEqual(divide(-10, 2), -5)\n"
                "    def test_divide_by_zero(self):\n"
                "        with self.assertRaisesRegex(ValueError, 'division by zero'):\n"
                "            divide(10, 0)\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n"
                "    def test_multiply(self):\n"
                "        self.assertEqual(multiply(2, 3), 6)\n",
                encoding="utf-8",
            )

            cache_path = Path(importlib.util.cache_from_source(str(source_path)))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            source_stat = source_path.stat()
            code = compile(good_source, str(source_path), "exec")
            cache_path.write_bytes(
                struct.pack(
                    "<4sIII",
                    importlib.util.MAGIC_NUMBER,
                    0,
                    int(source_stat.st_mtime),
                    source_stat.st_size,
                )
                + marshal.dumps(code)
            )

            result = grade_workspace(workspace, FIXTURE)

            self.assertEqual(source_path.read_bytes(), original_source)
            self.assertFalse(result["success"], result)

    def test_candidate_authored_tests_are_inspected_but_never_imported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            marker = workspace / "candidate-test-ran.txt"
            shutil.copytree(FIXTURE, workspace)
            (workspace / "src" / "calculator.py").write_text(
                "def add(a, b): return a + b\n"
                "def multiply(a, b): return a * b\n"
                "def divide(a, b):\n"
                "    if b == 0: raise ValueError('division by zero')\n"
                "    return a / b\n",
                encoding="utf-8",
            )
            (workspace / "tests" / "test_calculator.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('executed')\n"
                "import unittest\n"
                "from src.calculator import divide\n"
                "class CandidateTests(unittest.TestCase):\n"
                "    def test_divide_positive(self): self.assertEqual(divide(4, 2), 2)\n"
                "    def test_divide_negative(self): self.assertEqual(divide(-4, 2), -2)\n"
                "    def test_divide_by_zero(self):\n"
                "        with self.assertRaises(ValueError): divide(4, 0)\n",
                encoding="utf-8",
            )

            result = grade_workspace(workspace, FIXTURE)

            self.assertTrue(result["workflow_pass"], result)
            self.assertFalse(result["candidate_tests_executed"], result)
            self.assertIsNone(result["workspace_tests_passed"], result)
            self.assertEqual(result["artifact_retention"], "not_requested", result)
            self.assertFalse(marker.exists())

    def test_secret_named_addition_fails_scope_without_opening_its_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            shutil.copytree(FIXTURE, workspace)
            secret_path = workspace / ".env"
            secret_path.write_text("DO_NOT_READ=sentinel", encoding="utf-8")
            original_reader = pristine_grading._read_regular_file
            opened: list[Path] = []

            def tracking_reader(path: Path, **kwargs: object):
                opened.append(path)
                return original_reader(path, **kwargs)

            with patch.object(pristine_grading, "_read_regular_file", side_effect=tracking_reader):
                result = grade_workspace(workspace, FIXTURE)

            self.assertFalse(result["integrity_pass"], result)
            self.assertFalse(result["scope_pass"], result)
            self.assertNotIn(secret_path, opened)

    def test_symlinked_candidate_source_is_rejected_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            outside = root / "outside.py"
            shutil.copytree(FIXTURE, workspace)
            source_path = workspace / "src" / "calculator.py"
            source_path.unlink()
            outside.write_text("sentinel = 'must not be read'\n", encoding="utf-8")
            try:
                source_path.symlink_to(outside)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            original_reader = pristine_grading._read_regular_file
            opened: list[Path] = []

            def tracking_reader(path: Path, **kwargs: object):
                opened.append(path)
                return original_reader(path, **kwargs)

            with patch.object(pristine_grading, "_read_regular_file", side_effect=tracking_reader):
                result = grade_workspace(workspace, FIXTURE)

            self.assertFalse(result["integrity_pass"], result)
            self.assertTrue(result["grader_skipped"], result)
            self.assertNotIn(source_path, opened)
            self.assertNotIn(outside, opened)

    def test_copied_fixture_path_is_not_accepted_as_a_trusted_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            copied_fixture = root / "fixture-copy"
            shutil.copytree(FIXTURE, workspace)
            shutil.copytree(FIXTURE, copied_fixture)

            result = grade_workspace(workspace, copied_fixture, artifact_dir=root / "artifacts")

            self.assertFalse(result["success"], result)
            self.assertEqual(result["artifact_retention"], "failed", result)
            self.assertTrue(any("baseline_path_does_not_match" in reason for reason in result["skip_reasons"]))

    def test_artifact_sink_keeps_non_overwriting_source_only_replay_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            artifact_parent = root / "artifacts"
            shutil.copytree(FIXTURE, workspace)
            source_path = workspace / "src" / "calculator.py"
            source_path.write_text(
                "def add(a: float, b: float) -> float:\n"
                "    return a + b\n\n"
                "def multiply(a: float, b: float) -> float:\n"
                "    return a * b\n\n"
                "def divide(a: float, b: float) -> float:\n"
                "    if b == 0:\n"
                "        raise ValueError('division by zero')\n"
                "    return a / b\n",
                encoding="utf-8",
            )
            (workspace / "tests" / "test_calculator.py").write_text(
                "import unittest\nfrom src.calculator import divide\n"
                "class CalculatorTests(unittest.TestCase):\n"
                "    def test_divide_positive(self): self.assertEqual(divide(4, 2), 2)\n"
                "    def test_divide_negative(self): self.assertEqual(divide(-4, 2), -2)\n"
                "    def test_divide_by_zero(self):\n"
                "        with self.assertRaises(ValueError): divide(4, 0)\n",
                encoding="utf-8",
            )
            candidate_source = source_path.read_bytes()

            result = grade_workspace(workspace, FIXTURE, artifact_dir=artifact_parent)

            self.assertTrue(result["success"], result)
            self.assertEqual(result["artifact_retention"], "retained", result)
            artifact_root = Path(result["artifact_path"])
            self.assertTrue((artifact_root / "replay-manifest.json").is_file())
            self.assertIn("src/calculator.py", (artifact_root / "source-only.patch").read_text(encoding="utf-8"))
            self.assertNotIn("tests/test_calculator.py", (artifact_root / "source-only.patch").read_text(encoding="utf-8"))
            manifest = json.loads((artifact_root / "replay-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["grader_protocol_version"], "pristine-workspace-v1")
            self.assertFalse(manifest["candidate_tests_executed"])
            self.assertFalse(manifest["runtime_result_authenticated"])
            self.assertFalse(manifest["adversarial_evaluation_validated"])
            self.assertFalse(manifest["aggregate_is_security_proof"])
            self.assertIn("false_positives_possible", manifest["aggregate_interpretation"])
            self.assertEqual(
                manifest["integrity_semantics"],
                "static_workspace_structure_and_protected_files_only",
            )
            self.assertEqual(source_path.read_bytes(), candidate_source)
            second = grade_workspace(workspace, FIXTURE, artifact_dir=artifact_parent)
            self.assertNotEqual(second["artifact_path"], result["artifact_path"])
            with patch.object(pristine_grading, "_write_replay_artifacts", side_effect=OSError("disk error")):
                failed_write = grade_workspace(workspace, FIXTURE, artifact_dir=artifact_parent)
            self.assertEqual(failed_write["artifact_retention"], "failed", failed_write)
            self.assertFalse(failed_write["artifacts_retained"], failed_write)


if __name__ == "__main__":
    unittest.main()
