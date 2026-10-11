from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from benchmark.harness_runner import (
        build_command,
        parse_server_prompt_eval_tokens,
        resolve_task,
        _isolated_environment,
        _preflight,
        _prepare_run,
        summarize_resources,
        summarize_usage,
    )
except ImportError:
    build_command = None  # type: ignore[assignment]
    parse_server_prompt_eval_tokens = None  # type: ignore[assignment]
    resolve_task = None  # type: ignore[assignment]
    _isolated_environment = None  # type: ignore[assignment]
    _preflight = None  # type: ignore[assignment]
    _prepare_run = None  # type: ignore[assignment]
    summarize_resources = None  # type: ignore[assignment]
    summarize_usage = None  # type: ignore[assignment]


class HarnessRunnerTests(unittest.TestCase):
    def test_task_registry_resolves_distinct_fixture_and_prompt(self) -> None:
        self.assertTrue(callable(resolve_task), "harness task registry is not implemented")
        fixture, prompt = resolve_task("whitespace_normalization")
        self.assertEqual(fixture, Path(__file__).resolve().parents[1] / "benchmark/fixtures/harness_whitespace")
        self.assertEqual(prompt, fixture / "TASK.md")

    def test_task_registry_resolves_environment_parser_fixture(self) -> None:
        self.assertTrue(callable(resolve_task), "harness task registry is not implemented")
        fixture, prompt = resolve_task("dotenv_line_parser")
        self.assertEqual(fixture, Path(__file__).resolve().parents[1] / "benchmark/fixtures/harness_env_parser")
        self.assertEqual(prompt, fixture / "TASK.md")

    def test_task_registry_rejects_unknown_task(self) -> None:
        self.assertTrue(callable(resolve_task), "harness task registry is not implemented")
        with self.assertRaisesRegex(ValueError, "Unsupported task"):
            resolve_task("arbitrary-task")

    def test_preflight_rejects_non_ssd_log_or_result_destinations(self) -> None:
        self.assertTrue(callable(_preflight), "harness SSD preflight is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            model = root / "model.gguf"
            model.write_bytes(b"fixture")
            server_log = root / "logs/server.log"
            results = root / "results/summary.jsonl"
            with patch("benchmark.harness_runner.REPO_ROOT", source), patch(
                "benchmark.harness_runner._filesystem_type",
                side_effect=["ext4", "ext4", "ext4", "ext4", "drvfs"],
            ) as filesystem_type, patch("benchmark.harness_runner.urllib.request.urlopen") as urlopen:
                with self.assertRaisesRegex(RuntimeError, "results output must be on the WSL ext4 SSD"):
                    _preflight(root, "local-model", model, 4096, "http://127.0.0.1:8080", server_log, results)
            self.assertEqual(filesystem_type.call_count, 5)
            urlopen.assert_not_called()

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
            cache = fixture / "src/__pycache__"
            cache.mkdir(parents=True, exist_ok=True)
            (cache / "calculator.cpython-312.pyc").write_bytes(b"cache")
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
            self.assertFalse((run_dir / "workspace/src/__pycache__").exists())

    def test_prepare_run_copies_selected_task_fixture(self) -> None:
        self.assertTrue(callable(_prepare_run), "harness workspace preparation is not implemented")
        import shutil

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            fixture = repo / "benchmark/fixtures/harness_whitespace"
            fixture.parent.mkdir(parents=True)
            shutil.copytree(
                Path(__file__).resolve().parents[1] / "benchmark/fixtures/harness_whitespace",
                fixture,
            )
            configs = repo / "benchmark/configs/harnesses"
            configs.mkdir(parents=True)
            shutil.copy2(
                Path(__file__).resolve().parents[1] / "benchmark/configs/harnesses/opencode.json",
                configs / "opencode.json",
            )
            run_dir = root / "ssd-run"
            run_dir.mkdir()
            with patch("benchmark.harness_runner.REPO_ROOT", repo):
                _prepare_run("opencode", run_dir, root, "Do the whitespace task.", fixture=fixture)

            self.assertTrue((run_dir / "workspace/src/text_utils.py").is_file())
            self.assertFalse((run_dir / "workspace/src/calculator.py").exists())
            self.assertEqual(
                (run_dir / "workspace/TASK.md").read_text(encoding="utf-8"),
                (fixture / "TASK.md").read_text(encoding="utf-8"),
            )

    def test_prepare_run_uses_requested_local_model_and_ssd_endpoint(self) -> None:
        self.assertTrue(callable(_prepare_run), "harness workspace preparation is not implemented")
        model = "ornith-ai/Ornith-1.0-9B-GGUF"
        server_url = "http://127.0.0.1:8091"
        context = 8192
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for harness in ("pi", "opencode", "vibe"):
                run_dir = root / harness
                run_dir.mkdir()
                _prepare_run(harness, run_dir, root, "Do the controlled task.", model, server_url, context)

                if harness == "pi":
                    config = json.loads((run_dir / "home/.pi/agent/models.json").read_text(encoding="utf-8"))
                    provider = config["providers"]["local-llama"]
                    self.assertEqual(provider["baseUrl"], server_url + "/v1")
                    self.assertEqual(provider["models"][0]["id"], model)
                    self.assertEqual(provider["models"][0]["contextWindow"], context)
                elif harness == "opencode":
                    config = json.loads((run_dir / "home/.config/opencode/opencode.json").read_text(encoding="utf-8"))
                    self.assertEqual(config["model"], f"local/{model}")
                    self.assertEqual(config["provider"]["local"]["options"]["baseURL"], server_url + "/v1")
                    self.assertEqual(config["provider"]["local"]["models"][model]["limit"]["context"], context)
                else:
                    config = (run_dir / "home/config.toml").read_text(encoding="utf-8")
                    self.assertIn(f'active_model = "{model}"', config)
                    self.assertIn(f'api_base = "{server_url}/v1"', config)
                    self.assertIn(f"max_context_length = {context}", config)

    def test_isolated_environment_points_pwd_at_benchmark_workspace(self) -> None:
        self.assertTrue(callable(_isolated_environment), "isolated environment builder is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "run" / "workspace"
            workspace.mkdir(parents=True)
            env = _isolated_environment("opencode", root / "run", root, workspace)
            self.assertEqual(env["PWD"], str(workspace))

    def test_isolated_environment_does_not_inherit_credentials_or_parent_config(self) -> None:
        self.assertTrue(callable(_isolated_environment), "isolated environment builder is not implemented")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "run" / "workspace"
            workspace.mkdir(parents=True)
            with patch.dict(os.environ, {
                "GITHUB_TOKEN": "must-not-leak",
                "AWS_SECRET_ACCESS_KEY": "must-not-leak",
                "OPENAI_API_KEY": "must-not-leak",
                "GIT_CONFIG_GLOBAL": "/sensitive/config",
            }, clear=False):
                env = _isolated_environment("opencode", root / "run", root, workspace)
            self.assertIn(str(root / "runtimes/node-v22.23.3-linux-x64/bin"), env["PATH"])
            self.assertEqual(env["TMPDIR"], str(root / "run/tmp"))
            for key in ("GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "GIT_CONFIG_GLOBAL"):
                self.assertNotIn(key, env)

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
