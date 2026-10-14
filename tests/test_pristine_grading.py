from __future__ import annotations

import importlib.util
import json
import marshal
import shutil
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import pristine_grading
from benchmark.harness_eval import grade_workspace


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmark" / "fixtures" / "harness_task"


class PristineGradingRegressionTests(unittest.TestCase):
    def test_scoped_candidate_imports_restore_preexisting_sys_modules_bindings(self) -> None:
        previous_src_names = {
            name: module
            for name, module in sys.modules.items()
            if name == "src" or name.startswith("src.")
        }
        prior_package = types.ModuleType("src")
        prior_package.__path__ = []  # type: ignore[attr-defined]
        prior_calculator = types.ModuleType("src.calculator")
        prior_package.calculator = prior_calculator
        sys.modules["src"] = prior_package
        sys.modules["src.calculator"] = prior_calculator
        try:
            with tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary) / "workspace"
                shutil.copytree(FIXTURE, workspace)
                result = grade_workspace(workspace, FIXTURE)

            self.assertTrue(result["regression_pass"], result)
            restored_src_names = {
                name: module
                for name, module in sys.modules.items()
                if name == "src" or name.startswith("src.")
            }
            self.assertEqual(restored_src_names, {**previous_src_names, "src": prior_package,
                                                  "src.calculator": prior_calculator})
            self.assertIs(sys.modules["src"], prior_package)
            self.assertIs(sys.modules["src.calculator"], prior_calculator)
        finally:
            for name in tuple(sys.modules):
                if name == "src" or name.startswith("src."):
                    sys.modules.pop(name, None)
            sys.modules.update(previous_src_names)

    def test_runner_forgery_is_rejected_before_any_trusted_test_executes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            marker = root / "candidate-test-ran.txt"
            shutil.copytree(FIXTURE, workspace)
            (workspace / "src" / "calculator.py").write_text(
                "import unittest\n"
                "unittest.TestResult.wasSuccessful = lambda self: True\n\n"
                "def add(a: float, b: float) -> float:\n    return a + b\n\n"
                "def multiply(a: float, b: float) -> float:\n    return a * b\n\n"
                "def divide(a: float, b: float) -> float:\n    return 0.0\n",
                encoding="utf-8",
            )
            (workspace / "tests" / "test_calculator.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('candidate tests ran')\n"
                "class CandidateTests:\n"
                "    def test_divide_positive(self): pass\n"
                "    def test_divide_negative(self): pass\n"
                "    def test_divide_by_zero(self): pass\n",
                encoding="utf-8",
            )

            result = grade_workspace(workspace, FIXTURE)

            self.assertFalse(result["success"], result)
            self.assertEqual(result.get("candidate_language_contract"), "restricted-python-workspace-v2")
            self.assertEqual(result.get("evaluation_status"), "unsupported_syntax")
            self.assertEqual(result.get("regression_details", {}).get("test_count"), 0)
            self.assertFalse(result["runtime_result_authenticated"], result)
            self.assertFalse(result["candidate_tests_executed"], result)
            self.assertFalse(marker.exists())

    def test_alternative_native_import_side_effect_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            marker = root / "candidate-import-ran.txt"
            shutil.copytree(FIXTURE, workspace)
            (workspace / "src" / "calculator.py").write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('candidate import ran')\n"
                "def add(a: float, b: float) -> float:\n    return a + b\n\n"
                "def multiply(a: float, b: float) -> float:\n    return a * b\n\n"
                "def divide(a, b): return a / b\n",
                encoding="utf-8",
            )

            result = grade_workspace(workspace, FIXTURE)

            self.assertEqual(result.get("evaluation_status"), "unsupported_syntax")
            self.assertFalse(result["runtime_result_authenticated"], result)
            self.assertFalse(marker.exists())

    def test_interpreter_budget_exhaustion_is_not_reported_as_a_functional_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            shutil.copytree(FIXTURE, workspace)
            (workspace / "src" / "calculator.py").write_text(
                "def add(a: float, b: float) -> float:\n    return a + b\n\n"
                "def multiply(a: float, b: float) -> float:\n    return a * b\n\n"
                "def divide(a, b):\n    while True:\n        pass\n",
                encoding="utf-8",
            )

            result = grade_workspace(workspace, FIXTURE)

            self.assertEqual(result["functional_details"]["status"], "execution_limit", result)
            self.assertEqual(result["evaluation_status"], "execution_limit", result)
            self.assertTrue(result["runtime_result_authenticated"], result)

    def test_temporary_cleanup_failure_reports_empty_retained_root_and_allows_manual_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            shutil.copytree(FIXTURE, workspace)
            cleanup_roots: list[Path] = []
            real_rmtree = shutil.rmtree

            def fail_cleanup(path: Path, *_args: object, **_kwargs: object) -> None:
                cleanup_roots.append(Path(path))
                raise OSError("cleanup denied")

            try:
                with patch.object(pristine_grading.shutil, "rmtree", side_effect=fail_cleanup):
                    result = grade_workspace(workspace, FIXTURE)

                self.assertEqual(result["artifact_retention"], "failed", result)
                self.assertEqual(result["artifact_cleanup_error"], "OSError", result)
                self.assertFalse(result["artifacts_retained"], result)
                self.assertFalse(result["partial_artifacts_retained"], result)
                self.assertEqual(Path(result["artifact_path"]), cleanup_roots[0])
                self.assertTrue(cleanup_roots[0].is_dir())
            finally:
                if cleanup_roots and cleanup_roots[0].exists():
                    real_rmtree(cleanup_roots[0])

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
            self.assertEqual(result["candidate_language_contract"], "restricted-python-workspace-v2")
            self.assertFalse(result["adversarial_evaluation_validated"], result)
            self.assertFalse(result["aggregate_is_security_proof"], result)
            self.assertEqual(
                result["integrity_semantics"],
                "static_workspace_structure_and_protected_files_only",
            )
        self.assertTrue(normal["runtime_result_authenticated"], normal)
        self.assertFalse(preflight_failure["runtime_result_authenticated"], preflight_failure)
        self.assertIn("not a security proof", normal["aggregate_interpretation"])

    def test_missing_fingerprinted_probe_is_an_infrastructure_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            shutil.copytree(FIXTURE, workspace)
            with patch.object(pristine_grading, "_verify_probe", side_effect=OSError("missing probe")):
                result = grade_workspace(workspace, FIXTURE)

            self.assertTrue(result["regression_pass"], result)
            self.assertFalse(result["functional_pass"], result)
            self.assertEqual(result["functional_details"]["status"], "infrastructure_failure")
            self.assertFalse(result["runtime_result_authenticated"], result)

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
            self.assertEqual(manifest["grader_protocol_version"], "restricted-python-workspace-v2")
            self.assertFalse(manifest["candidate_tests_executed"])
            self.assertTrue(manifest["runtime_result_authenticated"])
            self.assertFalse(manifest["adversarial_evaluation_validated"])
            self.assertFalse(manifest["aggregate_is_security_proof"])
            self.assertIn("not a security proof", manifest["aggregate_interpretation"])
            self.assertEqual(manifest["candidate_language_contract"], "restricted-python-workspace-v2")
            self.assertEqual(
                manifest["integrity_semantics"],
                "static_workspace_structure_and_protected_files_only",
            )
            self.assertEqual(source_path.read_bytes(), candidate_source)
            second = grade_workspace(workspace, FIXTURE, artifact_dir=artifact_parent)
            self.assertNotEqual(second["artifact_path"], result["artifact_path"])

            def write_partial_then_fail(artifact_root: Path, *_args: object) -> None:
                (artifact_root / "partial.txt").write_text("partial", encoding="utf-8")
                raise OSError("disk error")

            with patch.object(pristine_grading, "_write_replay_artifacts", side_effect=write_partial_then_fail):
                failed_write = grade_workspace(workspace, FIXTURE, artifact_dir=artifact_parent)
            self.assertEqual(failed_write["artifact_retention"], "failed", failed_write)
            self.assertFalse(failed_write["artifacts_retained"], failed_write)
            self.assertFalse(failed_write["artifacts_written"], failed_write)
            self.assertTrue(failed_write["partial_artifacts_retained"], failed_write)
            failed_root = Path(failed_write["artifact_path"])
            self.assertTrue((failed_root / "partial.txt").is_file())
            self.assertNotIn(failed_write["artifact_path"], {result["artifact_path"], second["artifact_path"]})

            with patch.object(pristine_grading, "_grade_in_root", side_effect=OSError("replay failed")):
                empty_failure = grade_workspace(workspace, FIXTURE, artifact_dir=artifact_parent)
            self.assertEqual(empty_failure["artifact_retention"], "failed", empty_failure)
            self.assertFalse(empty_failure["artifacts_retained"], empty_failure)
            self.assertFalse(empty_failure["artifacts_written"], empty_failure)
            self.assertFalse(empty_failure["partial_artifacts_retained"], empty_failure)
            empty_root = Path(empty_failure["artifact_path"])
            self.assertTrue(empty_root.is_dir())

            def fail_after_partial_replay(
                _workspace: Path,
                _baseline: Path,
                _task: str,
                grade_root: Path,
                *_args: object,
            ) -> None:
                (grade_root / "partial-replay.txt").write_text("partial", encoding="utf-8")
                raise OSError("replay failed after writing")

            with patch.object(pristine_grading, "_grade_in_root", side_effect=fail_after_partial_replay):
                failed_replay = grade_workspace(workspace, FIXTURE, artifact_dir=artifact_parent)
            self.assertEqual(failed_replay["artifact_retention"], "failed", failed_replay)
            self.assertFalse(failed_replay["artifacts_retained"], failed_replay)
            self.assertFalse(failed_replay["artifacts_written"], failed_replay)
            self.assertTrue(failed_replay["partial_artifacts_retained"], failed_replay)
            replay_root = Path(failed_replay["artifact_path"])
            self.assertTrue((replay_root / "partial-replay.txt").is_file())
            self.assertEqual(
                len({
                    result["artifact_path"], second["artifact_path"],
                    failed_write["artifact_path"], empty_failure["artifact_path"],
                    failed_replay["artifact_path"],
                }),
                5,
            )


if __name__ == "__main__":
    unittest.main()
