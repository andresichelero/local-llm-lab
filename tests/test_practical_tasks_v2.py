"""Run every v2 reference and mutant through its actual acceptance runtime."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark import practical_tasks_v2 as tasks
from benchmark import practical_grade_contract as grade

NODE = os.environ.get(
    "PRACTICAL_V2_NODE",
    "/home/foxtrot/local-llm-benchmark/runtimes/node-v22.23.3-linux-x64/bin/node",
)


class PracticalTasksV2Tests(unittest.TestCase):
    def test_mcp_prompts_explain_available_tools_without_cli_discovery(self):
        for task in ("C2", "M2", "D2", "H2"):
            with self.subTest(task=task), tempfile.TemporaryDirectory() as directory:
                prompt = tasks.seed_task(task, Path(directory))
                self.assertIn("already available in your tool list", prompt)
                self.assertIn("do not use shell commands to discover MCP", prompt)
                self.assertIn("reread /workspace/TASK.md", prompt)
                self.assertEqual((Path(directory) / "TASK.md").read_text().strip(), prompt.strip())

    def run_acceptance(self, task, files, phase=1, task_contract_id=None):
        contract = (task_contract_id if task_contract_id is not None
                    else tasks.HISTORICAL_CONTRACT)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            tasks.seed_task(task, workspace, task_contract_id=contract)
            for name, content in files.items():
                target = workspace / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            source = tasks.checks_source(task, phase, task_contract_id=contract)
            if tasks.TASK_SPECS[task]["language"] in ("python", "mcp"):
                return subprocess.run(
                    [sys.executable, "-I", "-c", source],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
            if not Path(NODE).is_file() and shutil.which(NODE) is None:
                self.fail(f"Node.js executable not found: {NODE}")
            hidden = Path(directory) / "acceptance.test.js"
            hidden.write_text(source, encoding="utf-8")
            return subprocess.run(
                [NODE, "--test", str(hidden)],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=20,
            )

    def test_task_catalog_and_seed_contracts(self):
        self.assertEqual(tasks.TASKS, ("B1", "B2", "C1", "C2", "M1", "M2", "D1", "D2"))
        self.assertEqual(tasks.HOLDOUTS, ("H1", "H2"))
        self.assertEqual(
            {task: spec["phases"] for task, spec in tasks.TASK_SPECS.items()},
            {
                "B1": 1,
                "B2": 1,
                "C1": 1,
                "C2": 1,
                "M1": 1,
                "M2": 1,
                "D1": 2,
                "D2": 1,
                "H1": 1,
                "H2": 1,
            },
        )
        self.assertEqual(tasks.TASK_SPECS["B1"]["seconds"], 180)
        self.assertEqual(tasks.TASK_SPECS["B1"]["max_requests"], 20)
        self.assertEqual(tasks.TASK_SPECS["D2"]["difficulty"], "hard")
        for task in tasks.ALL_TASKS:
            with self.subTest(task=task), tempfile.TemporaryDirectory() as directory:
                prompt = tasks.seed_task(task, Path(directory))
                self.assertGreater(len(prompt), 100)
                self.assertNotIn("acceptance.test.js", prompt)
                self.assertTrue((Path(directory) / "TASK.md").is_file())
                self.assertIsInstance(tasks.exports(task), tuple)

    def test_both_correct_solutions_pass_all_phases(self):
        for task in tasks.ALL_TASKS:
            for phase in range(1, tasks.TASK_SPECS[task]["phases"] + 1):
                for variant in (0, 1):
                    with self.subTest(task=task, phase=phase, variant=variant):
                        files = tasks.reference_files(task, variant, phase)
                        result = self.run_acceptance(task, files, phase)
                        self.assertEqual(
                            result.returncode, 0, result.stdout + result.stderr
                        )

    def test_every_plausible_mutant_is_rejected(self):
        for task in tasks.ALL_TASKS:
            phase = tasks.TASK_SPECS[task]["phases"]
            mutants = tasks.wrong_files(task)
            self.assertEqual(len(mutants), 2, task)
            for index, files in enumerate(mutants):
                with self.subTest(task=task, mutant=index):
                    result = self.run_acceptance(task, files, phase)
                    self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_b2_oracle_rejects_nonobjects_without_line_context(self):
        files = tasks.reference_files("B2")
        files["src/validate.js"] = """function validateRecord(row, line) {
  if (!row || typeof row !== 'object' || Array.isArray(row))
    throw new TypeError('invalid record');
  if (!Number.isSafeInteger(row.id) || row.id <= 0 || typeof row.name !== 'string')
    throw new TypeError('line ' + line + ': invalid record');
  return row;
}
module.exports = { validateRecord };
"""
        result = self.run_acceptance("B2", files)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_b2_oracle_rejects_a_wrong_line_number_with_expected_number_elsewhere(self):
        files = tasks.reference_files("B2")
        files["src/validate.js"] = files["src/validate.js"].replace(
            "'line ' + line + ': invalid record'",
            "'line ' + (line + 100) + ': invalid record version ' + line",
        )
        result = self.run_acceptance("B2", files)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_b2_oracle_rejects_fractional_positive_ids(self):
        files = tasks.reference_files("B2")
        files["src/validate.js"] = files["src/validate.js"].replace(
            "!Number.isSafeInteger(row.id) || row.id <= 0",
            "typeof row.id !== 'number' || row.id <= 0",
        )
        result = self.run_acceptance("B2", files)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_b2_oracle_accepts_four_space_and_tab_pretty_printing(self):
        for rounded in ("4", "'\\t'"):
            with self.subTest(indent=rounded):
                files = tasks.reference_files("B2")
                files["src/convert.js"] = files["src/convert.js"].replace(
                    "JSON.stringify(rows, null, 2)",
                    f"JSON.stringify(rows, null, {rounded})",
                )
                result = self.run_acceptance("B2", files)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_b2_oracle_rejects_records_compressed_onto_one_line(self):
        files = tasks.reference_files("B2")
        files["src/convert.js"] = files["src/convert.js"].replace(
            "return JSON.stringify(rows, null, 2);", "return JSON.stringify(rows);"
        )
        result = self.run_acceptance("B2", files)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_b2_oracle_accepts_portuguese_line_labels(self):
        files = tasks.reference_files("B2")
        files["src/validate.js"] = files["src/validate.js"].replace(
            "'line ' + line + ': invalid record'",
            "'linha ' + line + ': registro inválido'",
        )
        result = self.run_acceptance("B2", files)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_b2_oracle_rejects_the_record_id_used_as_line_number(self):
        files = tasks.reference_files("B2")
        files["src/validate.js"] = files["src/validate.js"].replace(
            "'line ' + line + ': invalid record'",
            "'line ' + row.id + ': invalid record'",
        )
        result = self.run_acceptance("B2", files)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    # --- Task 5: m1-independent-copy-v1 is a new contract, never retroactive ----------

    def test_m1_seed_states_the_independent_copy_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt = tasks.seed_task(
                "M1", Path(directory),
                task_contract_id=tasks.M1_INDEPENDENT_CONTRACT)
            self.assertIn("(Contract m1-independent-copy-v1)", prompt)
            self.assertIn("independent copy: every plain object and every array", prompt)
            self.assertIn("reference with defaults or with the caller-provided overrides",
                          prompt)
            self.assertIn("Do not implement\nthe copy through a JSON round-trip", prompt)
            self.assertIn("Cycles, Date, Map,", prompt)
            self.assertIn("Set, and other special classes are outside", prompt)
            self.assertEqual((Path(directory) / "TASK.md").read_text().strip(),
                             prompt.strip())
        with tempfile.TemporaryDirectory() as other:
            historical = tasks.seed_task("M1", Path(other))
            self.assertNotIn("m1-independent-copy-v1", historical)

    def test_seed_sources_match_the_seeded_workspace_files(self):
        for task in tasks.ALL_TASKS:
            sources = tasks.seed_sources(task)
            self.assertLessEqual(len(sources), 4)
            with tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                tasks.seed_task(task, workspace)
                for name, content in sources.items():
                    with self.subTest(task=task, file=name):
                        self.assertEqual(
                            (workspace / name).read_text(encoding="utf-8"),
                            content)

    def test_m1_contract_oracle_appends_independent_cases_with_stable_ids(self):
        historical = tasks.checks_source("M1")
        strict = tasks.checks_source(
            "M1", task_contract_id=tasks.M1_INDEPENDENT_CONTRACT)
        self.assertTrue(strict.startswith(historical))
        self.assertNotIn("independent result", historical)
        ids_historical = list(grade.node_check_case_ids(historical))
        ids_strict = list(grade.node_check_case_ids(strict))
        self.assertEqual(len(ids_historical), 4)
        self.assertEqual(len(ids_strict), 8)
        self.assertEqual(ids_strict[:4], ids_historical)
        self.assertIn("independent result: no alias with defaults at any depth",
                      ids_strict[4])

    def test_unknown_and_inapplicable_task_contracts_need_review(self):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            calls.append(lambda: tasks.seed_task("M1", Path(directory),
                                                 task_contract_id="future-m1-v9"))
            calls.append(lambda: tasks.seed_task(
                "B2", Path(directory),
                task_contract_id=tasks.M1_INDEPENDENT_CONTRACT))
        calls.append(lambda: tasks.checks_source("M1", task_contract_id="wrong-v0"))
        calls.append(lambda: tasks.reference_files(
            "M1", task_contract_id="mcp-no-confirmed-replay-v1"))
        calls.append(lambda: tasks.wrong_files("M1", task_contract_id="m1-independent"))
        calls.append(lambda: tasks.checks_source(
            "C1", task_contract_id=tasks.M1_INDEPENDENT_CONTRACT))
        for call in calls:
            with self.assertRaises(ValueError) as caught:
                call()
            self.assertIn("review required", str(caught.exception))

    def test_m1_independent_references_pass_the_strict_oracle(self):
        contract = tasks.M1_INDEPENDENT_CONTRACT
        for variant in (0, 1):
            with self.subTest(variant=variant):
                files = tasks.reference_files("M1", variant,
                                              task_contract_id=contract)
                result = self.run_acceptance("M1", files, 1, contract)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("# pass 8", result.stdout)

    def test_m1_independent_contract_rejects_aliasing_and_shallow_merges(self):
        contract = tasks.M1_INDEPENDENT_CONTRACT
        mutants = tasks.wrong_files("M1", task_contract_id=contract)
        self.assertEqual(len(mutants), 2)
        results = [self.run_acceptance("M1", files, 1, contract)
                   for files in mutants]
        for index, result in enumerate(results):
            with self.subTest(mutant=index):
                self.assertNotEqual(result.returncode, 0, result.stdout)
        # The alias mutant must die on the new independence rule itself, not
        # on a historical surface, so the contract keeps a dedicated killer.
        self.assertIn("independent result: no alias with defaults at any depth",
                      results[0].stdout)
        self.assertNotIn("not ok 3 -", results[0].stdout)
        self.assertIn("not ok 6 -", results[1].stdout)
        self.assertIn("not ok 7 -", results[1].stdout)

    def test_m1_historical_profile_keeps_the_four_case_oracle(self):
        files = tasks.reference_files("M1")
        result = self.run_acceptance("M1", files)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# pass 4", result.stdout)

    def test_d1_followup_is_same_session_and_adds_csv(self):
        first_phase = tasks.reference_files("D1", variant=0, phase=1)
        self.assertEqual(self.run_acceptance("D1", first_phase, 1).returncode, 0)
        self.assertNotEqual(self.run_acceptance("D1", first_phase, 2).returncode, 0)
        self.assertIn("format='csv'", tasks.followup_prompt("D1"))
        self.assertEqual(tasks.followup_prompt("B1"), "")
        self.assertEqual(
            tasks.reference_files("D1", phase=2)["exporter.py"],
            tasks.reference_files("D1", variant=0, phase=2)["exporter.py"],
        )

    def test_invalid_task_phase_and_variant_rejected(self):
        for call in (
            lambda: tasks.seed_task("missing", Path(".")),
            lambda: tasks.followup_prompt("missing"),
            lambda: tasks.checks_source("D1", 3),
            lambda: tasks.checks_source("B1", True),
            lambda: tasks.reference_files("B1", variant=2),
            lambda: tasks.reference_files("C2", phase=2),
            lambda: tasks.wrong_files("missing"),
        ):
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()


if __name__ == "__main__":
    unittest.main()
