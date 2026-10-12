#!/usr/bin/env python3
"""Low-frequency system/GPU sampler for an active benchmark window."""
from __future__ import annotations

import argparse
import json
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def parse_meminfo_kib(content: str) -> dict[str, int | str | None]:
    values: dict[str, int] = {}
    for line in content.splitlines():
        if not line or ":" not in line:
            continue
        key, raw = line.split(":", 1)
        if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
            parts = raw.strip().split()
            if parts:
                values[key] = int(parts[0])
    total_ram_mib = values.get("MemTotal", 0) // 1024
    used_ram_mib = (values.get("MemTotal", 0) - values.get("MemAvailable", 0)) // 1024
    total_swap_mib = values.get("SwapTotal", 0) // 1024
    used_swap_mib = (values.get("SwapTotal", 0) - values.get("SwapFree", 0)) // 1024
    return {
        "memory_unit": "MiB",
        # Historical compatibility keys
        "ram_total_mb": total_ram_mib,
        "ram_used_mb": used_ram_mib,
        "swap_total_mb": total_swap_mib,
        "swap_used_mb": used_swap_mib,
        # Explicit modern aliases
        "wsl_ram_total_mib": total_ram_mib,
        "wsl_ram_used_mib": used_ram_mib,
        "wsl_swap_total_mib": total_swap_mib,
        "wsl_swap_used_mib": used_swap_mib,
    }


def memory_kib() -> dict[str, int | str | None]:
    try:
        with open("/proc/meminfo", encoding="ascii") as source:
            return parse_meminfo_kib(source.read())
    except OSError:
        return parse_meminfo_kib("")


def cpu_ticks() -> tuple[int, int]:
    fields = open("/proc/stat", encoding="ascii").readline().split()[1:]
    numbers = [int(value) for value in fields]
    idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
    return sum(numbers), idle


def parse_nvidia_smi(output: str) -> dict[str, str | None]:
    parts = [part.strip() for part in output.strip().split(",")]
    if len(parts) >= 5:
        data = dict(zip(["vram_used_mb", "gpu_util_pct", "temperature_c", "gpu_clock_mhz", "power_w"], parts[:5]))
        data["system_vram_used_mib"] = data["vram_used_mb"]
        return data
    return {key: None for key in ["vram_used_mb", "gpu_util_pct", "temperature_c", "gpu_clock_mhz", "power_w", "system_vram_used_mib"]}


def gpu() -> dict[str, str | None]:
    query = "memory.used,utilization.gpu,temperature.gpu,clocks.gr,power.draw"
    try:
        executable = shutil.which("nvidia-smi") or ("/usr/lib/wsl/lib/nvidia-smi" if Path("/usr/lib/wsl/lib/nvidia-smi").is_file() else "nvidia-smi")
        result = subprocess.run(
            [executable, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return parse_nvidia_smi(result.stdout)
    except (OSError, subprocess.SubprocessError):
        return {key: None for key in ["vram_used_mb", "gpu_util_pct", "temperature_c", "gpu_clock_mhz", "power_w", "system_vram_used_mib"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval < 0.25:
        parser.error("interval must be at least 0.25 seconds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    previous_total, previous_idle = cpu_ticks()
    with args.output.open("a", encoding="utf-8") as output:
        while running:
            time.sleep(args.interval)
            total, idle = cpu_ticks()
            elapsed, idle_elapsed = total - previous_total, idle - previous_idle
            previous_total, previous_idle = total, idle
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cpu_util_pct": round((1 - idle_elapsed / elapsed) * 100, 2) if elapsed else None,
                **memory_kib(),
                "gpu": gpu(),
            }
            output.write(json.dumps(record) + "\n")
            output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
