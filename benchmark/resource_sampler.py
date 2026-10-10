#!/usr/bin/env python3
"""Low-frequency system/GPU sampler for an active benchmark window."""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

running = True


def stop(_signum: int, _frame: object) -> None:
    global running
    running = False


def memory_kib() -> dict[str, int | None]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", encoding="ascii") as source:
        for line in source:
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                values[key] = int(raw.strip().split()[0])
    return {
        "ram_total_mb": values.get("MemTotal", 0) // 1024,
        "ram_used_mb": (values.get("MemTotal", 0) - values.get("MemAvailable", 0)) // 1024,
        "swap_total_mb": values.get("SwapTotal", 0) // 1024,
        "swap_used_mb": (values.get("SwapTotal", 0) - values.get("SwapFree", 0)) // 1024,
    }


def cpu_ticks() -> tuple[int, int]:
    fields = open("/proc/stat", encoding="ascii").readline().split()[1:]
    numbers = [int(value) for value in fields]
    idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
    return sum(numbers), idle


def gpu() -> dict[str, str | None]:
    query = "memory.used,utilization.gpu,temperature.gpu,clocks.gr,power.draw"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        fields = [part.strip() for part in result.stdout.strip().split(",")]
        return dict(zip(["vram_used_mb", "gpu_util_pct", "temperature_c", "gpu_clock_mhz", "power_w"], fields))
    except (OSError, subprocess.SubprocessError):
        return {key: None for key in ["vram_used_mb", "gpu_util_pct", "temperature_c", "gpu_clock_mhz", "power_w"]}


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
