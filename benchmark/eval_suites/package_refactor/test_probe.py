"""Held-out behavioral probe suite for package_refactor task."""
from __future__ import annotations

import unittest

import src.metrics
import src.service


class PackageRefactorBehavioralProbe(unittest.TestCase):
    def test_metrics_module_reexport(self) -> None:
        self.assertIs(
            src.service.summarize_metrics,
            src.metrics.summarize_metrics,
        )

    def test_summarize_metrics_behavior(self) -> None:
        self.assertEqual(
            src.metrics.summarize_metrics([]),
            {"count": 0.0, "mean": 0.0, "min": 0.0, "max": 0.0},
        )
        res = src.metrics.summarize_metrics([10.0, 30.0])
        self.assertEqual(
            res,
            {"count": 2.0, "mean": 20.0, "min": 10.0, "max": 30.0},
        )

    def test_generate_service_summary(self) -> None:
        records = [
            {"latency": 5.0},
            {"latency": None},
            {"no_latency": 1},
            {"latency": 15.0},
        ]
        summary = src.service.generate_service_summary(records)
        self.assertEqual(
            summary,
            {"count": 2.0, "mean": 10.0, "min": 5.0, "max": 15.0},
        )
        if hasattr(src.service, "serve"):
            serve_fn = getattr(src.service, "serve")
            self.assertIsNotNone(serve_fn)

    def test_sanitize_record_helper_intact(self) -> None:
        self.assertEqual(
            src.service.sanitize_record({" a ": " b "}),
            {" a ": "b"},
        )
        if hasattr(src.service, "render_banner"):
            banner_fn = getattr(src.service, "render_banner")
            self.assertIsNotNone(banner_fn)


if __name__ == "__main__":
    unittest.main()
