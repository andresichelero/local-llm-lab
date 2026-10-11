from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from benchmark.summarize_harness_results import summarize_records, write_outputs
except ImportError:
    summarize_records = None  # type: ignore[assignment]
    write_outputs = None  # type: ignore[assignment]


class HarnessSummaryTests(unittest.TestCase):
    def test_aggregates_measurements_and_excludes_warmup(self) -> None:
        self.assertTrue(callable(summarize_records), "harness result summarizer is not implemented")
        records = [
            {"harness": "pi", "run_kind": "warmup", "success": True, "wall_s": 900},
            {"harness": "pi", "run_kind": "measurement", "git_sha": "a" * 40, "success": True, "wall_s": 10, "prompt_tokens": 100, "first_prompt_tokens": 50, "vram_used_mb_peak": 6000, "swap_used_mb_peak": 100},
            {"harness": "pi", "run_kind": "measurement", "git_sha": "a" * 40, "success": True, "wall_s": 20, "prompt_tokens": 200, "first_prompt_tokens": 50, "vram_used_mb_peak": 6200, "swap_used_mb_peak": 200},
            {"harness": "pi", "run_kind": "measurement", "git_sha": "a" * 40, "success": False, "wall_s": 30, "prompt_tokens": 300, "first_prompt_tokens": 50, "vram_used_mb_peak": 6400, "swap_used_mb_peak": 300},
            {"harness": "pi", "run_kind": "measurement", "benchmark_valid": False, "git_sha": "a" * 40, "success": False, "wall_s": 999},
            {"harness": "pi", "run_kind": "measurement", "success": True, "wall_s": 888},
        ]

        result = summarize_records(records)

        self.assertEqual(len(result), 1)
        summary = result[0]
        self.assertEqual(summary["measurement_count"], 3)
        self.assertEqual(summary["success_count"], 2)
        self.assertAlmostEqual(summary["success_rate"], 2 / 3)
        self.assertEqual(summary["wall_s_median"], 20)
        self.assertEqual(summary["wall_s_mean"], 20)
        self.assertEqual(summary["wall_s_stddev"], 10)
        self.assertEqual(summary["prompt_tokens_median"], 200)
        self.assertEqual(summary["vram_used_mb_peak_median"], 6200)
        self.assertEqual(summary["swap_used_mb_peak_median"], 200)

    def test_separates_models_and_writes_multi_source_labels(self) -> None:
        self.assertTrue(callable(summarize_records), "harness result summarizer is not implemented")
        self.assertTrue(callable(write_outputs), "harness report writer is not implemented")
        records = [
            {"harness": "pi", "model": "Qwen", "git_sha": "a" * 40, "success": True, "wall_s": 20},
            {"harness": "pi", "model": "Ornith", "git_sha": "b" * 40, "success": True, "wall_s": 25},
        ]
        summaries = summarize_records(records)
        self.assertEqual({row["model"] for row in summaries}, {"Qwen", "Ornith"})
        with tempfile.TemporaryDirectory() as temp:
            csv_path = Path(temp) / "summary.csv"
            markdown_path = Path(temp) / "summary.md"
            sources = [Path("runs-qwen.jsonl"), Path("runs-ornith.jsonl")]
            write_outputs(summaries, csv_path, markdown_path, sources)
            markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("runs-qwen.jsonl", markdown)
        self.assertIn("runs-ornith.jsonl", markdown)
        self.assertIn("| Model | Harness |", markdown)
        self.assertIn("Qwen", markdown)
        self.assertIn("Ornith", markdown)

    def test_separates_task_profiles_in_aggregates_and_report(self) -> None:
        self.assertTrue(callable(summarize_records), "harness result summarizer is not implemented")
        self.assertTrue(callable(write_outputs), "harness report writer is not implemented")
        shared = {
            "harness": "pi",
            "harness_version": "1.1.0",
            "model": "Qwen",
            "runtime": "llama.cpp",
            "quant": "Q4_K_M",
            "context_tokens": 16384,
            "kv_cache": "Q4_0",
            "storage_profile": "ssd-wsl-ext4-c",
            "git_sha": "a" * 40,
            "success": True,
        }
        records = [
            {**shared, "task": "calculator_division", "wall_s": 10},
            {**shared, "task": "whitespace_normalization", "wall_s": 20},
        ]

        summaries = summarize_records(records)

        self.assertEqual(len(summaries), 2)
        self.assertEqual({row["task"] for row in summaries}, {"calculator_division", "whitespace_normalization"})
        with tempfile.TemporaryDirectory() as temp:
            markdown_path = Path(temp) / "summary.md"
            write_outputs(summaries, Path(temp) / "summary.csv", markdown_path, [Path("runs.jsonl")])
            markdown = markdown_path.read_text(encoding="utf-8")
        self.assertIn("| Task | Model | Harness |", markdown)
        self.assertIn("Swap peak MB median", markdown)
        self.assertIn("calculator_division", markdown)
        self.assertIn("whitespace_normalization", markdown)
        self.assertIn("2 fixed coding tasks", markdown)

    def test_assigns_legacy_harness_rows_to_the_original_task(self) -> None:
        self.assertTrue(callable(summarize_records), "harness result summarizer is not implemented")
        rows = summarize_records(
            [
                {
                    "experiment": "harness-coding-task-smoke",
                    "harness": "pi",
                    "git_sha": "a" * 40,
                    "success": True,
                    "wall_s": 12,
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task"], "calculator_division")


if __name__ == "__main__":
    unittest.main()
