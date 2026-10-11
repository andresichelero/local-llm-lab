from __future__ import annotations

import unittest

from benchmark.summarize_context_recall import summarize_series


class ContextRecallSummaryTests(unittest.TestCase):
    def test_summary_uses_measurements_and_counts_exact_matches(self) -> None:
        runs = [
            {"run_kind": "warmup", "success": True, "quality_pass": True},
            {"run_kind": "measurement", "success": True, "quality_pass": True, "source_tree_dirty": False, "git_sha": "s", "runtime_commit": "r", "kv_cache_k": "q4_0", "kv_cache_v": "q4_0", "ttft_ms": 100, "wall_time_s": 1.1},
            {"run_kind": "measurement", "success": True, "quality_pass": False, "source_tree_dirty": False, "git_sha": "s", "runtime_commit": "r", "kv_cache_k": "q4_0", "kv_cache_v": "q4_0", "ttft_ms": 120, "wall_time_s": 1.2},
            {"run_kind": "measurement", "success": True, "quality_pass": True, "source_tree_dirty": False, "git_sha": "s", "runtime_commit": "r", "kv_cache_k": "q4_0", "kv_cache_v": "q4_0", "ttft_ms": 110, "wall_time_s": 1.0},
        ]

        result = summarize_series(runs, [])

        self.assertEqual(result["measurement_count"], 3)
        self.assertEqual(result["quality_success_count"], 2)
        self.assertEqual(result["quality_success_rate"], 0.6667)
        self.assertEqual(result["ttft_ms_median"], 110)


if __name__ == "__main__":
    unittest.main()
