from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark.summarize_context_kv import generate, summarize_series


class ContextKvSummaryTests(unittest.TestCase):
    def measurement(self, repetition: int, *, dirty: bool = False) -> dict:
        return {
            "experiment": "ctx16-q4",
            "context_tokens": 16384,
            "kv_cache_k": "q4_0",
            "kv_cache_v": "q4_0",
            "model": "qwen",
            "model_revision": "rev",
            "runtime_commit": "runtime",
            "git_sha": "source",
            "source_tree_dirty": dirty,
            "success": True,
            "repetition": repetition,
            "prompt_tokens": 14352,
            "prompt_tps": 2000 + repetition,
            "generation_tps": 60 + repetition,
            "ttft_ms": 7000 + repetition,
            "wall_time_s": 8 + repetition / 10,
        }

    def test_summary_excludes_dirty_records_and_aggregates_sampler(self) -> None:
        rows = [self.measurement(i) for i in range(1, 4)] + [self.measurement(4, dirty=True)]
        samples = [
            {"cpu_util_pct": 20, "ram_used_mb": 1000, "swap_used_mb": 0,
             "gpu": {"vram_used_mb": "6000", "gpu_util_pct": "90", "power_w": "220"}},
            {"cpu_util_pct": 30, "ram_used_mb": 1200, "swap_used_mb": 0,
             "gpu": {"vram_used_mb": "6200", "gpu_util_pct": "95", "power_w": "230"}},
        ]

        summary = summarize_series(rows, samples)

        self.assertEqual(summary["measurement_count"], 3)
        self.assertEqual(summary["generation_tps_median"], 62)
        self.assertEqual(summary["sampler_vram_mb_peak"], 6200)
        self.assertEqual(summary["sampler_power_w_mean"], 225)

    def test_summary_rejects_incomplete_series(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 3"):
            summarize_series([self.measurement(1, dirty=True)], [])

    def test_generate_skips_context_recall_series(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            raw = Path(temp)
            records = [self.measurement(i) for i in range(1, 4)]
            (raw / "qwen35-ssd-context-16384-q4_0.jsonl").write_text(
                "\n".join(json.dumps(row) for row in records), encoding="utf-8"
            )
            (raw / "qwen35-ssd-recall-16k-f16.jsonl").write_text(
                '{"run_kind":"warmup"}\n', encoding="utf-8"
            )
            output = raw / "summary.csv"

            rows = generate(raw, output)

            self.assertEqual(len(rows), 1)
            self.assertIn("ctx16-q4", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
