from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from benchmark.harness_eval import grade_workspace
except ImportError:
    grade_workspace = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmark" / "fixtures" / "harness_task"
WHITESPACE_FIXTURE = ROOT / "benchmark" / "fixtures" / "harness_whitespace"


class HarnessEvaluationTests(unittest.TestCase):
    def workspace(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp = tempfile.TemporaryDirectory()
        target = Path(temp.name) / "workspace"
        shutil.copytree(FIXTURE, target)
        return temp, target

    def implement_divide(self, workspace: Path) -> None:
        (workspace / "src" / "calculator.py").write_text(
            "def add(a: float, b: float) -> float:\n"
            "    return a + b\n\n\n"
            "def multiply(a: float, b: float) -> float:\n"
            "    return a * b\n\n\n"
            "def divide(a: float, b: float) -> float:\n"
            "    if b == 0:\n"
            "        raise ValueError(\"division by zero\")\n"
            "    return a / b\n",
            encoding="utf-8",
        )
        (workspace / "tests" / "test_calculator.py").write_text(
            "import unittest\n\n"
            "from src.calculator import add, multiply, divide\n\n\n"
            "class CalculatorTests(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n\n"
            "    def test_multiply(self):\n        self.assertEqual(multiply(2, 3), 6)\n\n"
            "    def test_divide_positive(self):\n        self.assertEqual(divide(10, 2), 5)\n\n"
            "    def test_divide_negative(self):\n        self.assertEqual(divide(-10, 2), -5)\n\n"
            "    def test_divide_by_zero(self):\n"
            "        with self.assertRaisesRegex(ValueError, 'division by zero'):\n"
            "            divide(10, 0)\n",
            encoding="utf-8",
        )

    def test_grade_workspace_is_callable(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")

    def test_correct_change_passes_tests_and_behavior_probe(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")
        temp, workspace = self.workspace()
        self.addCleanup(temp.cleanup)
        self.implement_divide(workspace)

        result = grade_workspace(workspace, FIXTURE)

        self.assertTrue(result["unit_tests_passed"])
        self.assertTrue(result["behavioral_probe_passed"])
        self.assertTrue(result["divide_tests_present"])
        self.assertTrue(result["unchanged_helpers"])
        self.assertTrue(result["changes_scoped"])
        self.assertTrue(result["success"])

    def test_unexpected_file_change_fails_scope_check(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")
        temp, workspace = self.workspace()
        self.addCleanup(temp.cleanup)
        self.implement_divide(workspace)
        (workspace / "unrequested.txt").write_text("outside task\n", encoding="utf-8")

        result = grade_workspace(workspace, FIXTURE)

        self.assertFalse(result["changes_scoped"])
        self.assertFalse(result["success"])

    def implement_normalize_whitespace(self, workspace: Path, canonical_names: bool = True) -> None:
        (workspace / "src" / "text_utils.py").write_text(
            "def word_count(text: str) -> int:\n"
            "    return len(text.split())\n\n\n"
            "def normalize_whitespace(text: str) -> str:\n"
            "    return ' '.join(text.split())\n",
            encoding="utf-8",
        )
        positive_name = "test_collapses_mixed_whitespace" if canonical_names else "test_collapses_spaces"
        negative_name = "test_preserves_unicode_text" if canonical_names else "test_unicode"
        (workspace / "tests" / "test_text_utils.py").write_text(
            "import unittest\n\n"
            "from src.text_utils import normalize_whitespace, word_count\n\n\n"
            "class TextUtilsTests(unittest.TestCase):\n"
            "    def test_word_count(self):\n"
            "        self.assertEqual(word_count('two\\twords'), 2)\n\n"
            "    def test_empty_input(self):\n"
            "        self.assertEqual(normalize_whitespace('  \\t\\n'), '')\n\n"
            f"    def {positive_name}(self):\n"
            "        self.assertEqual(normalize_whitespace('  alpha\\tbeta\\n gamma  '), 'alpha beta gamma')\n\n"
            f"    def {negative_name}(self):\n"
            "        self.assertEqual(normalize_whitespace('\\u00a0café\\u2003x'), 'café x')\n",
            encoding="utf-8",
        )

    def test_whitespace_task_checks_behavior_scope_and_preserved_helper(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(WHITESPACE_FIXTURE, workspace)
            self.implement_normalize_whitespace(workspace)

            result = grade_workspace(workspace, WHITESPACE_FIXTURE, task="whitespace_normalization")

        self.assertTrue(result["unit_tests_passed"])
        self.assertTrue(result["behavioral_probe_passed"])
        self.assertTrue(result["required_tests_present"])
        self.assertTrue(result["unchanged_helpers"])
        self.assertTrue(result["changes_scoped"])
        self.assertTrue(result["success"])

    def test_whitespace_task_rejects_noncanonical_test_names(self) -> None:
        self.assertTrue(callable(grade_workspace), "grade_workspace is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            shutil.copytree(WHITESPACE_FIXTURE, workspace)
            self.implement_normalize_whitespace(workspace, canonical_names=False)

            result = grade_workspace(workspace, WHITESPACE_FIXTURE, task="whitespace_normalization")

        self.assertTrue(result["unit_tests_passed"])
        self.assertTrue(result["behavioral_probe_passed"])
        self.assertFalse(result["required_tests_present"])
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
