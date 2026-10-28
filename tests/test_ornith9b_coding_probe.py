from __future__ import annotations

import importlib
import importlib.util
import unittest


class Ornith9BCodingProbeTests(unittest.TestCase):
    def _probe(self):
        module_name = "benchmark.ornith9b_coding_probe"
        self.assertIsNotNone(importlib.util.find_spec(module_name),
                             "the protected Ornith screen must be implemented")
        return importlib.import_module(module_name)

    def test_pilot_freezes_one_warmup_and_three_practical_tasks(self) -> None:
        probe = self._probe()
        self.assertEqual(probe.MODEL_KEY, "ornith-1.0-9b")
        self.assertEqual([row["task"] for row in probe.build_rows()], [
            "whitespace_normalization",
            "config_precedence",
            "retry_policy",
            "whitespace_normalization",
        ])
        rows = probe.build_rows()
        self.assertEqual([row["stage"] for row in rows], [
            "warmup", "measurement", "measurement", "measurement",
        ])
        self.assertEqual([row["repeat"] for row in rows], [0, 1, 1, 1])

    def test_profile_pins_only_ornith_and_official_sampling(self) -> None:
        probe = self._probe()
        profile = probe.build_profile()
        self.assertEqual(profile["model"], f"local/{probe.MODEL['alias']}")
        models = profile["provider"]["local"]["models"]
        self.assertEqual(set(models), {probe.MODEL["alias"]})
        self.assertEqual(models[probe.MODEL["alias"]]["options"]["temperature"], 0.6)
        self.assertEqual(models[probe.MODEL["alias"]]["options"]["top_p"], 0.95)
        self.assertEqual(models[probe.MODEL["alias"]]["limit"]["output"], 1024)

    def test_server_keeps_template_reasoning_and_recommended_top_k(self) -> None:
        probe = self._probe()
        command = probe._server_command(probe.Path("/llama-server"), probe.Path("/ornith.gguf"))
        self.assertEqual(command[command.index("--reasoning") + 1], "auto")
        self.assertEqual(command[command.index("--top-k") + 1], "20")


if __name__ == "__main__":
    unittest.main()
