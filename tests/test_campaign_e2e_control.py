from __future__ import annotations

import ast
import unittest

from benchmark.campaign_e2e_control import _task_files, _tool_arguments


class CanonicalControlTests(unittest.TestCase):
    def test_control_writes_real_assertions_and_compatible_source(self) -> None:
        files = _task_files()
        source = ast.parse(files["src/calculator.py"])
        self.assertIn("divide", {node.name for node in source.body if isinstance(node, ast.FunctionDef)})
        tests = ast.parse(files["tests/test_calculator.py"])
        names = {node.name for node in ast.walk(tests) if isinstance(node, ast.FunctionDef)}
        self.assertTrue({"test_divide_positive", "test_divide_negative", "test_divide_by_zero"} <= names)
        self.assertIn("assertRaisesRegex", files["tests/test_calculator.py"])

    def test_commands_are_created_from_actual_schema_required_fields(self) -> None:
        schema = {"properties": {"command": {"type": "string"}, "description": {"type": "string"}},
                  "required": ["command", "description"]}
        initial = _tool_arguments(schema, "bash", 0)
        self.assertTrue(initial["command"].startswith("python3 -c "))
        self.assertEqual(_tool_arguments(schema, "bash", 2)["command"],
                         "python3 -m unittest discover -s tests -v")
