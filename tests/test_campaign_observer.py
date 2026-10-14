from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from benchmark.campaign_observer import ResourceMonitor


@unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux sampler")
class ResourceMonitorTests(unittest.TestCase):
    def test_real_sampler_is_correlated_outside_workspace_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            monitor = ResourceMonitor.start(Path(temporary) / "observer", run_id="control",
                                            phase_id="agent", agent_id="native", interval=0.25)
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if monitor.samples_path.stat().st_size > 0:
                        break
                    time.sleep(0.05)
            finally:
                result = monitor.stop()
            self.assertEqual(result["status"], "measured", monitor.log_path.read_text())
            self.assertTrue(result["cleanup_verified"])
            self.assertGreater(result["sample_count"], 0)
            sample = json.loads(monitor.samples_path.read_text().splitlines()[0])
            self.assertEqual(sample["run_id"], "control")
            self.assertEqual(sample["phase_id"], "agent")
            self.assertIn("metrics", sample)
            self.assertEqual(result, monitor.stop())

    def test_existing_evidence_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "observer"
            directory.mkdir()
            sentinel = directory / "resources.jsonl"
            sentinel.write_text("preserve")
            with self.assertRaises(FileExistsError):
                ResourceMonitor.start(directory, run_id="control", phase_id="agent", agent_id="native")
            self.assertEqual(sentinel.read_text(), "preserve")
