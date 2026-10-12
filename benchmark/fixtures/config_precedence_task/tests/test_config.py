import unittest

from src.config import resolve_config, validate_schema


class ConfigPrecedenceTests(unittest.TestCase):
    def test_validate_schema_helper(self):
        self.assertTrue(validate_schema({"a": 1}))
        self.assertFalse(validate_schema({}))

    def test_cli_overrides_file_and_defaults(self):
        defaults = {"host": "localhost", "port": 8000, "debug": True}
        file_cfg = {"port": 9000, "debug": False}
        cli_args = {"port": 9090}
        resolved = resolve_config(defaults, file_cfg, cli_args)
        self.assertEqual(resolved["port"], 9090)
        self.assertEqual(resolved["debug"], False)
        self.assertEqual(resolved["host"], "localhost")

    def test_preserves_falsy_values(self):
        defaults = {"retries": 3, "verbose": True, "prefix": "app"}
        file_cfg = {"retries": 0, "verbose": False, "prefix": ""}
        resolved = resolve_config(defaults, file_cfg)
        self.assertEqual(resolved["retries"], 0)
        self.assertIs(resolved["verbose"], False)
        self.assertEqual(resolved["prefix"], "")

    def test_does_not_mutate_inputs(self):
        defaults = {"a": 1}
        file_cfg = {"b": 2}
        cli_args = {"c": 3}
        resolved = resolve_config(defaults, file_cfg, cli_args)
        self.assertEqual(defaults, {"a": 1})
        self.assertEqual(file_cfg, {"b": 2})
        self.assertEqual(cli_args, {"c": 3})
        resolved["a"] = 99
        self.assertEqual(defaults["a"], 1)


if __name__ == "__main__":
    unittest.main()
