from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import unittest
from benchmark.resource_sampler import parse_meminfo_kib, parse_nvidia_smi


class ResourceSamplerTests(unittest.TestCase):
    def test_parse_meminfo_kib_calculates_mib_and_sets_unit(self) -> None:
        sample_meminfo = (
            "MemTotal:        8134656 kB\n"
            "MemFree:         7311360 kB\n"
            "MemAvailable:    7623680 kB\n"
            "Buffers:           10240 kB\n"
            "Cached:           307200 kB\n"
            "SwapTotal:       4194304 kB\n"
            "SwapFree:        4194304 kB\n"
        )
        parsed = parse_meminfo_kib(sample_meminfo)
        self.assertEqual(parsed["memory_unit"], "MiB")
        self.assertEqual(parsed["ram_total_mb"], 7944)
        self.assertEqual(parsed["wsl_ram_total_mib"], 7944)
        # used = (8134656 - 7623680) // 1024 = 510976 // 1024 = 499 MiB
        self.assertEqual(parsed["ram_used_mb"], 499)
        self.assertEqual(parsed["wsl_ram_used_mib"], 499)
        self.assertEqual(parsed["swap_total_mb"], 4096)
        self.assertEqual(parsed["wsl_swap_total_mib"], 4096)
        self.assertEqual(parsed["swap_used_mb"], 0)
        self.assertEqual(parsed["wsl_swap_used_mib"], 0)

    def test_parse_meminfo_kib_handles_empty_or_malformed(self) -> None:
        parsed = parse_meminfo_kib("")
        self.assertEqual(parsed["memory_unit"], "MiB")
        self.assertIsNone(parsed["ram_total_mb"])
        self.assertIsNone(parsed["ram_used_mb"])

    def test_parse_nvidia_smi_extracts_metrics_and_aliases(self) -> None:
        sample_smi = "1127, 2, 45, 1500, 25.5\n"
        parsed = parse_nvidia_smi(sample_smi)
        self.assertEqual(parsed["vram_used_mb"], "1127")
        self.assertEqual(parsed["system_vram_used_mib"], "1127")
        self.assertEqual(parsed["gpu_util_pct"], "2")
        self.assertEqual(parsed["temperature_c"], "45")
        self.assertEqual(parsed["gpu_clock_mhz"], "1500")
        self.assertEqual(parsed["power_w"], "25.5")

    def test_parse_nvidia_smi_handles_malformed_output(self) -> None:
        parsed = parse_nvidia_smi("incomplete output")
        self.assertIsNone(parsed["vram_used_mb"])
        self.assertIsNone(parsed["system_vram_used_mib"])

    def test_sampler_rows_include_phase_correlation_and_metric_status(self) -> None:
        if os.name == "nt":
            self.skipTest("the system sampler reads Linux /proc telemetry")
        script = Path(__file__).resolve().parents[1] / "benchmark/resource_sampler.py"
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "resources.jsonl"
            process = subprocess.Popen(
                [
                    sys.executable, str(script), "--output", str(output), "--interval", "0.25",
                    "--run-id", "run-test", "--phase-id", "phase-test", "--agent-id", "initial-agent",
                    "--parent-agent-id", "cascade-runner",
                ],
                start_new_session=True,
            )
            try:
                time.sleep(0.65)
            finally:
                process.terminate()
                process.wait(timeout=3)

            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual([row["sample_seq"] for row in rows], list(range(1, len(rows) + 1)))
        self.assertTrue(all(row["run_id"] == "run-test" for row in rows))
        self.assertTrue(all(row["phase_id"] == "phase-test" for row in rows))
        self.assertTrue(all(row["agent_id"] == "initial-agent" for row in rows))
        self.assertTrue(all(row["parent_agent_id"] == "cascade-runner" for row in rows))
        self.assertTrue(all(row["turn_id"] is None for row in rows))
        self.assertTrue(all(row["event_id"].startswith("run-test:") for row in rows))
        self.assertTrue(all(row["scope"] == "system_wide" for row in rows))
        self.assertTrue(all(row["source"] == "sampler" for row in rows))
        self.assertTrue(all(isinstance(row["monotonic_ns"], int) for row in rows))
        self.assertIn(rows[0]["metrics"]["cpu_util_pct"]["status"], {"measured", "unavailable", "error"})
        for metric in rows[0]["metrics"].values():
            if metric["status"] in {"unavailable", "error"}:
                self.assertTrue(metric["reason"])


if __name__ == "__main__":
    unittest.main()
