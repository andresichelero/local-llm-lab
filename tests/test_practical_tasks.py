"""Exercise the practical-task oracles against real CPython implementations."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark import practical_tasks as tasks


class PracticalTasksTests(unittest.TestCase):
    def run_solution(self, task, files, phase=1):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            tasks.seed_task(task, workspace)
            for name, content in files.items():
                target = workspace / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            return subprocess.run(
                [sys.executable, "-I", "-c", tasks.checks_source(task, phase)],
                cwd=workspace, capture_output=True, text=True, timeout=15,
            )

    def test_seven_contracts_and_seed(self):
        self.assertEqual(tasks.TASKS, (
            "bugfix", "feature", "mcp_report", "recovery",
            "maintenance", "continuation", "tiebreak",
        ))
        for task in tasks.TASKS:
            with self.subTest(task=task), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                prompt = tasks.seed_task(task, workspace)
                self.assertGreater(len(prompt), 150)
                self.assertIn("tests/test_agent.py", tasks.exports(task))
                self.assertTrue((workspace / "tests/test_existing.py").is_file())
                self.assertNotIn("checker", prompt)
                self.assertFalse((workspace / "report.json").exists())

    def test_both_correct_styles_pass(self):
        for task in tasks.TASKS:
            phases = (1, 2) if task == "continuation" else (1,)
            for phase in phases:
                for variant in (0, 1):
                    with self.subTest(task=task, phase=phase, variant=variant):
                        result = self.run_solution(
                            task, tasks.reference_files(task, variant, phase), phase,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)

    def test_plausible_wrong_solutions_fail(self):
        for task in tasks.TASKS:
            phase = 2 if task == "continuation" else 1
            mutants = tasks.wrong_files(task)
            self.assertGreaterEqual(len(mutants), 1)
            for index, files in enumerate(mutants):
                with self.subTest(task=task, mutant=index):
                    result = self.run_solution(task, files, phase)
                    self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_continuation_really_changes_contract(self):
        first = tasks.reference_files("continuation", 0, 1)
        self.assertEqual(self.run_solution("continuation", first, 1).returncode, 0)
        self.assertNotEqual(self.run_solution("continuation", first, 2).returncode, 0)
        self.assertIn("csv", tasks.followup_prompt("continuation"))
        self.assertEqual(tasks.followup_prompt("bugfix"), "")

    def test_invalid_task_rejected(self):
        for operation in (tasks.exports, tasks.checks_source, tasks.reference_files,
                          tasks.wrong_files, tasks.followup_prompt):
            with self.assertRaises(ValueError):
                operation("missing")


if __name__ == "__main__":
    unittest.main()
