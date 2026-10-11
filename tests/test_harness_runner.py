from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

try:
    from benchmark.harness_runner import (
        build_command,
        parse_server_prompt_eval_tokens,
        _isolated_environment,
        _prepare_run,
        summarize_resources,
        summarize_usage,
    )
except ImportError:
    build_command = None  # type: ignore[assignment]
    parse_server_prompt_eval_tokens = None  # type: ignore[assignment]
    _isolated_environment = None  # type: ignore[assignment]
    _prepare_run = None  # type: ignore[assignment]
    summarize_resources = None  # type: ignore[assignment]
    summarize_usage = None  # type: ignore[assignment]


class HarnessRunnerTests(unittest.TestCase):
    def test_opencode_config_is_outside_task_workspace(self) -> None:
        self.assertTrue(callable(_prepare_run), "harness workspace preparation is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            fixture = repo / "benchmark/fixtures/harness_task"
            fixture.parent.mkdir(parents=True)
            source_fixture = Path(__file__).resolve().parents[1] / "benchmark/fixtures/harness_task"
            import shutil
            shutil.copytree(source_fixture, fixture)
            configs = repo / "benchmark/configs/harnesses"
            configs.mkdir(parents=True)
            source_config = Path(__file__).resolve().parents[1] / "benchmark/configs/harnesses/opencode.json"
            shutil.copy2(source_config, configs / "opencode.json")
            prompt = repo / "benchmark/configs/harnesses/task_prompt.md"
            prompt.write_text("Do the task.", encoding="utf-8")
            run_dir = root / "ssd-run"
            run_dir.mkdir()
            with patch("benchmark.harness_runner.REPO_ROOT", repo):
                _prepare_run("opencode", run_dir, root, "Do the task.")
            self.assertFalse((run_dir / "workspace/opencode.json").exists())
            self.assertTrue((run_dir / "home/.config/opencode/opencode.json").is_file())

    def test_isolated_environment_points_pwd_at_benchmark_workspace(self) -> None:
        self.assertTrue(callable(_isolated_environment), "isolated environment builder is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "run" / "workspace"
            workspace.mkdir(parents=True)
            env = _isolated_environment("opencode", root / "run", root, workspace)
            self.assertEqual(env["PWD"], str(workspace))

    def test_build_command_targets_local_model_for_each_harness(self) -> None:
        self.assertTrue(callable(build_command), "harness command builder is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prompt_file = root / "TASK.md"
            prompt_file.write_text("Do the controlled task.", encoding="utf-8")
            kwargs = {
                "harness": "pi",
                "install_root": root,
                "prompt_file": prompt_file,
                "workspace": root / "workspace",
                "output_dir": root / "output",
            }
            pi = build_command(**kwargs)
            self.assertIn("--provider", pi)
            self.assertIn("local-llama", pi)
            self.assertIn("--model", pi)
            self.assertIn("Qwen3.5-9B-Q4_K_M", pi)

            kwargs["harness"] = "opencode"
            opencode = build_command(**kwargs)
            self.assertIn("--auto", opencode)
            self.assertIn("--format", opencode)
            self.assertIn("json", opencode)
            self.assertIn("local/Qwen3.5-9B-Q4_K_M", opencode)

            kwargs["harness"] = "vibe"
            vibe = build_command(**kwargs)
            self.assertIn("--prompt-file", vibe)
            self.assertIn("--workdir", vibe)
            self.assertIn("--output-dir", vibe)

    def test_pi_usage_includes_cached_prompt_tokens_and_tool_errors(self) -> None:
        self.assertTrue(callable(summarize_usage), "usage parser is not implemented")
        events = [
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "usage": {"input": 80, "cacheRead": 40, "output": 12},
                },
            },
            {"type": "tool_execution_start", "toolName": "edit"},
            {"type": "tool_execution_end", "result": {"isError": True}},
        ]

        result = summarize_usage("pi", events)

        self.assertEqual(result["model_calls"], 1)
        self.assertEqual(result["prompt_tokens"], 120)
        self.assertEqual(result["first_prompt_tokens"], 120)
        self.assertEqual(result["completion_tokens"], 12)
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(result["tool_failures"], 1)

    def test_opencode_usage_counts_failed_tool_call(self) -> None:
        self.assertTrue(callable(summarize_usage), "usage parser is not implemented")
        events = [
            {
                "type": "step_finish",
                "part": {
                    "tokens": {"input": 100, "output": 20, "cache": {"read": 30}}
                },
            },
            {
                "type": "tool_use",
                "part": {"tool": "invalid", "state": {"status": "completed"}},
            },
        ]

        result = summarize_usage("opencode", events)

        self.assertEqual(result["prompt_tokens"], 130)
        self.assertEqual(result["completion_tokens"], 20)
        self.assertEqual(result["tool_calls"], 1)
        self.assertEqual(result["tool_failures"], 1)

    def test_vibe_usage_keeps_aggregate_and_unknown_first_prompt_distinct(self) -> None:
        self.assertTrue(callable(summarize_usage), "usage parser is not implemented")
        result = summarize_usage(
            "vibe",
            [],
            {
                "steps": 4,
                "usage": {
                    "input_tokens": 400,
                    "cached_input_tokens": 100,
                    "output_tokens": 60,
                },
            },
        )

        self.assertEqual(result["model_calls"], 4)
        self.assertEqual(result["prompt_tokens"], 500)
        self.assertEqual(result["first_prompt_tokens"], None)
        self.assertEqual(result["completion_tokens"], 60)

    def test_vibe_usage_reads_first_call_from_journal_events(self) -> None:
        self.assertTrue(callable(summarize_usage), "usage parser is not implemented")
        events = [
            {
                "type": "action_result",
                "payload": {
                    "result": {
                        "result": {
                            "usage": {"input_tokens": 8089, "cached_input_tokens": 10, "output_tokens": 26},
                            "parts": [],
                        }
                    }
                },
            }
        ]

        result = summarize_usage("vibe", events, {"steps": 1, "usage": {"input_tokens": 8089, "cached_input_tokens": 10, "output_tokens": 26}})

        self.assertEqual(result["first_prompt_tokens"], 8099)

    def test_server_prompt_eval_parser_reads_llama_server_work(self) -> None:
        self.assertTrue(callable(parse_server_prompt_eval_tokens), "server token work parser is not implemented")
        server_log = (
            "I slot print_timing: prompt processing, n_tokens = 7949, progress = 0.98\n"
            "I slot print_timing: eval time = 3183.30 ms / 182 tokens\n"
            "I slot print_timing: prompt processing, n_tokens = 8481, progress = 1.00\n"
        )
        self.assertEqual(parse_server_prompt_eval_tokens(server_log), [7949, 8481])

    def test_resource_summary_reports_sample_averages_and_peaks(self) -> None:
        self.assertTrue(callable(summarize_resources), "resource summary is not implemented")
        rows = [
            {
                "cpu_util_pct": 10,
                "ram_used_mb": 1200,
                "gpu": {"vram_used_mb": "6000", "gpu_util_pct": "70", "temperature_c": "55", "power_w": "150"},
            },
            {
                "cpu_util_pct": 30,
                "ram_used_mb": 1800,
                "gpu": {"vram_used_mb": "7000", "gpu_util_pct": "90", "temperature_c": "65", "power_w": "230"},
            },
        ]

        result = summarize_resources(rows)

        self.assertEqual(result["sample_count"], 2)
        self.assertEqual(result["cpu_util_pct_avg"], 20)
        self.assertEqual(result["ram_used_mb_peak"], 1800)
        self.assertEqual(result["vram_used_mb_avg"], 6500)
        self.assertEqual(result["gpu_util_pct_peak"], 90)
        self.assertEqual(result["temperature_c_peak"], 65)
        self.assertEqual(result["power_w_avg"], 190)


if __name__ == "__main__":
    unittest.main()
