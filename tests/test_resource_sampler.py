from __future__ import annotations

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
        self.assertEqual(parsed["ram_total_mb"], 0)
        self.assertEqual(parsed["ram_used_mb"], 0)

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


if __name__ == "__main__":
    unittest.main()
