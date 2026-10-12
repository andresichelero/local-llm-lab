from __future__ import annotations

import unittest

from src.service import generate_service_summary, sanitize_record


class ServiceTests(unittest.TestCase):
    def test_sanitize_record_helper(self):
        cleaned = sanitize_record({"name": "  test  ", "code": 10})
        self.assertEqual(cleaned, {"name": "test", "code": 10})

    def test_summarize_metrics_empty_and_normal(self):
        from src.service import summarize_metrics

        empty = summarize_metrics([])
        self.assertEqual(empty, {"count": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0})
        normal = summarize_metrics([10.0, 20.0, 30.0])
        self.assertEqual(normal, {"count": 3.0, "mean": 20.0, "min": 10.0, "max": 30.0})

    def test_generate_service_summary_filters_missing(self):
        records = [
            {"id": "a", "latency": 10.0},
            {"id": "b"},
            {"id": "c", "latency": 30.0},
        ]
        summary = generate_service_summary(records)
        self.assertEqual(summary["count"], 2.0)
        self.assertEqual(summary["mean"], 20.0)

    def test_service_reexports_metrics(self):
        import src.metrics
        import src.service

        self.assertIs(src.service.summarize_metrics, src.metrics.summarize_metrics)


if __name__ == "__main__":
    unittest.main()
