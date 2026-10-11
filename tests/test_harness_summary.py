from __future__ import annotations

import unittest

try:
    from benchmark.summarize_harness_results import summarize_records
except ImportError:
    summarize_records = None  # type: ignore[assignment]


class HarnessSummaryTests(unittest.TestCase):
    def test_aggregates_measurements_and_excludes_warmup(self) -> None:
        self.assertTrue(callable(summarize_records), "harness result summarizer is not implemented")
        records = [
            {"harness": "pi", "run_kind": "warmup", "success": True, "wall_s": 900},
            {"harness": "pi", "run_kind": "measurement", "success": True, "wall_s": 10, "prompt_tokens": 100, "first_prompt_tokens": 50, "vram_used_mb_peak": 6000},
            {"harness": "pi", "run_kind": "measurement", "success": True, "wall_s": 20, "prompt_tokens": 200, "first_prompt_tokens": 50, "vram_used_mb_peak": 6200},
            {"harness": "pi", "run_kind": "measurement", "success": False, "wall_s": 30, "prompt_tokens": 300, "first_prompt_tokens": 50, "vram_used_mb_peak": 6400},
            {"harness": "pi", "run_kind": "measurement", "benchmark_valid": False, "success": False, "wall_s": 999},
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


if __name__ == "__main__":
    unittest.main()
