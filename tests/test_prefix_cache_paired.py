import unittest
from pathlib import Path

from benchmark.prefix_cache_paired import (
    MODEL_KEY,
    TASKS,
    build_profile,
    build_schedule,
    server_command,
    summarize_prefix_cache_results,
)


class PrefixCachePairedTests(unittest.TestCase):
    def test_schedule_has_twelve_trials_balanced(self) -> None:
        schedule = build_schedule()
        self.assertEqual(len(schedule), 12)
        
        # Check task distribution
        calc_trials = [t for t in schedule if t["task"] == "calculator_division"]
        dotenv_trials = [t for t in schedule if t["task"] == "dotenv_line_parser"]
        self.assertEqual(len(calc_trials), 6)
        self.assertEqual(len(dotenv_trials), 6)
        
        # Check cache_prompt balance
        cache_on = [t for t in schedule if t["cache_prompt"]]
        cache_off = [t for t in schedule if not t["cache_prompt"]]
        self.assertEqual(len(cache_on), 6)
        self.assertEqual(len(cache_off), 6)
        
        # Each pair has exactly 1 on and 1 off
        for task in TASKS:
            for pair in (1, 2, 3):
                pair_items = [t for t in schedule if t["task"] == task and t["pair"] == pair]
                self.assertEqual(len(pair_items), 2)
                self.assertEqual({t["cache_prompt"] for t in pair_items}, {True, False})

    def test_server_command_applies_cache_flag_correctly(self) -> None:
        server = Path("/fake/llama-server")
        model_path = Path("/fake/model.gguf")
        
        cmd_on = server_command(server, model_path, MODEL_KEY, cache_prompt=True)
        self.assertIn("--cache-prompt", cmd_on)
        self.assertNotIn("--no-cache-prompt", cmd_on)
        
        cmd_off = server_command(server, model_path, MODEL_KEY, cache_prompt=False)
        self.assertIn("--no-cache-prompt", cmd_off)
        self.assertNotIn("--cache-prompt", cmd_off)

    def test_build_profile_contains_expected_permissions(self) -> None:
        profile = build_profile(MODEL_KEY)
        self.assertFalse(profile["autoupdate"])
        self.assertEqual(profile["default_agent"], "build")
        self.assertEqual(profile["subagent_depth"], 0)
        
        agent = profile["agent"]["build"]
        self.assertEqual(agent["steps"], 20)
        self.assertEqual(agent["permission"]["task"]["*"], "deny")
        self.assertEqual(agent["permission"]["bash"]["*"], "allow")
        self.assertEqual(agent["permission"]["edit"]["*"], "allow")

    def test_summarize_prefix_cache_results(self) -> None:
        records = [
            {"task": "calculator_division", "cache_prompt": False, "strict_pass": True, "task_wall_seconds": 30.0},
            {"task": "calculator_division", "cache_prompt": False, "strict_pass": True, "task_wall_seconds": 32.0},
            {"task": "calculator_division", "cache_prompt": True, "strict_pass": True, "task_wall_seconds": 20.0},
            {"task": "calculator_division", "cache_prompt": True, "strict_pass": True, "task_wall_seconds": 22.0},
            {"task": "dotenv_line_parser", "cache_prompt": False, "strict_pass": True, "task_wall_seconds": 40.0},
            {"task": "dotenv_line_parser", "cache_prompt": True, "strict_pass": False, "task_wall_seconds": 35.0},
        ]
        summary = summarize_prefix_cache_results(records)
        
        calc = summary["calculator_division"]
        self.assertEqual(calc["cache_off"]["passes"], 2)
        self.assertEqual(calc["cache_off"]["wall_median"], 31.0)
        self.assertEqual(calc["cache_on"]["passes"], 2)
        self.assertEqual(calc["cache_on"]["wall_median"], 21.0)
        self.assertAlmostEqual(calc["wall_speedup"], 31.0 / 21.0, places=2)
        
        dotenv = summary["dotenv_line_parser"]
        self.assertEqual(dotenv["cache_off"]["passes"], 1)
        self.assertEqual(dotenv["cache_on"]["passes"], 0)


if __name__ == "__main__":
    unittest.main()
