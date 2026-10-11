import json
import tempfile
import unittest
from pathlib import Path

from benchmark.qlora_quality import load_tasks, run_generated_code, strip_code_fence


TASK = {
    "function": "difference_of_cubes",
    "arguments": ["a", "b"],
    "tests": [
        {"inputs": [3, 2], "expected": 19},
        {"inputs": [2, 3], "expected": -19},
    ],
}


class QloraQualityTests(unittest.TestCase):
    def test_valid_function_passes_multiple_held_out_cases(self):
        result = run_generated_code("def difference_of_cubes(a, b):\n    return a ** 3 - b ** 3", TASK)
        self.assertEqual(result, (True, 2, None))

    def test_function_with_wrong_behavior_fails_exact_cases(self):
        passed, count, error = run_generated_code(
            "def difference_of_cubes(a, b):\n    return a ** 3 + b ** 3", TASK
        )
        self.assertFalse(passed)
        self.assertEqual(count, 0)
        self.assertIsNone(error)

    def test_rejects_imports_calls_and_attribute_access(self):
        sources = [
            "import os\ndef difference_of_cubes(a, b):\n    return a - b",
            "def difference_of_cubes(a, b):\n    return __import__('os').system('true')",
            "def difference_of_cubes(a, b):\n    return a.real - b",
        ]
        for source in sources:
            with self.subTest(source=source):
                passed, count, error = run_generated_code(source, TASK)
                self.assertFalse(passed)
                self.assertEqual(count, 0)
                self.assertTrue(error and any(term in error for term in ("unsupported syntax", "output must", "call to unsupported function")))

    def test_allows_only_safe_positional_builtins(self):
        task = {"function": "clamp", "arguments": ["value", "lower", "upper"], "tests": [{"inputs": [7, 0, 5], "expected": 5}]}
        self.assertEqual(run_generated_code("def clamp(value, lower, upper):\n    return min(max(value, lower), upper)", task), (True, 1, None))
        passed, count, error = run_generated_code("def clamp(value, lower, upper):\n    return open(value)", task)
        self.assertFalse(passed)
        self.assertEqual(count, 0)
        self.assertIn("call to unsupported function", error)

    def test_rejects_signature_mismatch(self):
        passed, count, error = run_generated_code("def difference_of_cubes(a):\n    return a ** 3", TASK)
        self.assertFalse(passed)
        self.assertEqual(count, 0)
        self.assertEqual(error, "function arguments do not match the task signature")

    def test_strips_only_closed_code_fences(self):
        self.assertEqual(strip_code_fence("```python\nreturn 1\n```"), "return 1")
        self.assertEqual(strip_code_fence("```python\nreturn 1"), "```python\nreturn 1")

    def test_loads_jsonl_tasks_and_rejects_empty_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.jsonl"
            path.write_text(json.dumps({"task_id": "one", **TASK, "prompt": "do task"}) + "\n", encoding="utf-8")
            self.assertEqual(load_tasks(path)[0]["task_id"], "one")
            path.write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                load_tasks(path)

    def test_quality_fixture_has_disjoint_task_ids_and_nonempty_cases(self):
        fixture = Path(__file__).parents[1] / "benchmark/data/qlora-quality-heldout.jsonl"
        tasks = load_tasks(fixture)
        self.assertEqual(len(tasks), 5)
        self.assertEqual(len({task["task_id"] for task in tasks}), len(tasks))
        self.assertTrue(all(task["tests"] for task in tasks))


if __name__ == "__main__":
    unittest.main()
