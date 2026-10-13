"""Held-out behavioral probe suite for config_precedence task."""
from __future__ import annotations

import unittest

from src.config import resolve_config, validate_schema


class ConfigPrecedenceBehavioralProbe(unittest.TestCase):
    def test_validate_schema_preserved_helper(self) -> None:
        self.assertTrue(validate_schema({"k": "v"}))
        self.assertFalse(validate_schema({}))

    def test_precedence_and_falsy_preservation(self) -> None:
        defaults = {"a": 1, "b": 2, "flag": True}
        file_config = {"b": 20, "flag": False, "empty": ""}
        cli_args = {"b": 200, "count": 0}
        res = resolve_config(defaults, file_config, cli_args)
        self.assertEqual(
            res,
            {"a": 1, "b": 200, "flag": False, "empty": "", "count": 0},
        )

    def test_none_treated_as_absent(self) -> None:
        self.assertEqual(resolve_config({"x": 10}, None, None), {"x": 10})
        self.assertEqual(resolve_config({"x": 10}, {"x": None}, None), {"x": 10})
        self.assertEqual(resolve_config({"x": 10}, None, {"x": None}), {"x": 10})

    def test_immutability_of_inputs(self) -> None:
        defaults = {"a": 1, "b": 2, "flag": True}
        file_config = {"b": 20, "flag": False, "empty": ""}
        cli_args = {"b": 200, "count": 0}
        resolve_config(defaults, file_config, cli_args)
        self.assertEqual(defaults, {"a": 1, "b": 2, "flag": True})
        self.assertEqual(file_config, {"b": 20, "flag": False, "empty": ""})
        self.assertEqual(cli_args, {"b": 200, "count": 0})


if __name__ == "__main__":
    unittest.main()
