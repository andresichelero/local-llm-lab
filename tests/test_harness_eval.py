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


if __name__ == "__main__":
    unittest.main()
