from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark.summarize_qlora_7b_rank import summarize


class QLoRA7BRankSummaryTests(unittest.TestCase):
    def test_preserves_and_reports_rank_failure_without_quality_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw"
            quality = root / "quality"
            raw.mkdir()
            quality.mkdir()
            failure = {
                "rank": 32,
                "phase": "training",
                "label": "warmup",
                "exit_code": 137,
                "storage_profile": "ssd-wsl-ext4-c",
                "success": False,
            }
            (raw / "failures.jsonl").write_text(json.dumps(failure) + "\n", encoding="utf-8")

            result = summarize(raw, quality)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["rank"], 32)
        self.assertEqual(result[0]["training_status"], "incomplete (0/3)")
        self.assertEqual(result[0]["quality_status"], "not run")
        self.assertIn("training:warmup exit=137", result[0]["failure_phases"])


if __name__ == "__main__":
    unittest.main()
