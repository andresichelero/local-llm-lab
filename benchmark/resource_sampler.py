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
    total_ram_kib = values.get("MemTotal")
    available_ram_kib = values.get("MemAvailable")
    total_swap_kib = values.get("SwapTotal")
    free_swap_kib = values.get("SwapFree")
    total_ram_mib = total_ram_kib // 1024 if total_ram_kib is not None else None
    used_ram_mib = (
        (total_ram_kib - available_ram_kib) // 1024
        if total_ram_kib is not None and available_ram_kib is not None else None
    )
    total_swap_mib = total_swap_kib // 1024 if total_swap_kib is not None else None
    used_swap_mib = (
        (total_swap_kib - free_swap_kib) // 1024
        if total_swap_kib is not None and free_swap_kib is not None else None
    )
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
    with open("/proc/meminfo", encoding="ascii") as source:
        return parse_meminfo_kib(source.read())


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
    return gpu_collection()[0]


def gpu_collection() -> tuple[dict[str, str | None], str, str | None]:
    query = "memory.used,utilization.gpu,temperature.gpu,clocks.gr,power.draw"
    executable = shutil.which("nvidia-smi")
    if executable is None:
        wsl_path = Path("/usr/lib/wsl/lib/nvidia-smi")
        if not wsl_path.is_file():
            empty = parse_nvidia_smi("")
            return empty, "unavailable", "nvidia_smi_not_found"
        executable = str(wsl_path)
    try:
        result = subprocess.run(
            [executable, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        parsed = parse_nvidia_smi(result.stdout)
        if all(value is None for value in parsed.values()):
            return parsed, "error", "nvidia_smi_output_unparseable"
        return parsed, "measured", None
    except FileNotFoundError:
        return parse_nvidia_smi(""), "unavailable", "nvidia_smi_not_found"
    except (OSError, subprocess.SubprocessError):
        return parse_nvidia_smi(""), "error", "nvidia_smi_query_failed"


def _metric(value: object, reason: str | None = None, *, error: bool = False) -> dict[str, object]:
    if value is None:
        return {"status": "error" if error else "unavailable", "value": None, "reason": reason}
    return {"status": "measured", "value": value, "reason": None}


def sample_metrics(previous_ticks: tuple[int, int] | None) -> tuple[dict[str, object], dict[str, object], tuple[int, int] | None]:
    """Collect system-wide metrics and explicit reasons for unavailable values."""
    metrics: dict[str, object] = {}
    legacy: dict[str, object] = {}
    next_ticks = previous_ticks

    try:
        current_ticks = cpu_ticks()
        if previous_ticks is None:
            cpu_value = None
            cpu_reason = "baseline_not_available"
        else:
            elapsed = current_ticks[0] - previous_ticks[0]
            idle = current_ticks[1] - previous_ticks[1]
            cpu_value = round((1 - idle / elapsed) * 100, 2) if elapsed > 0 else None
            cpu_reason = "no_cpu_tick_delta" if cpu_value is None else None
        next_ticks = current_ticks
        metrics["cpu_util_pct"] = _metric(cpu_value, cpu_reason)
    except FileNotFoundError:
        metrics["cpu_util_pct"] = _metric(None, "proc_stat_unavailable")
    except (OSError, ValueError, IndexError):
        metrics["cpu_util_pct"] = _metric(None, "proc_stat_read_failed", error=True)

    try:
        memory = memory_kib()
        for key in ("wsl_ram_total_mib", "wsl_ram_used_mib", "wsl_swap_total_mib", "wsl_swap_used_mib"):
            value = memory[key]
            metrics[key] = _metric(value, None if value is not None else "proc_meminfo_field_unavailable")
            legacy[key] = value
        legacy.update({
            "memory_unit": "MiB",
            "ram_total_mb": memory["ram_total_mb"],
            "ram_used_mb": memory["ram_used_mb"],
            "swap_total_mb": memory["swap_total_mb"],
            "swap_used_mb": memory["swap_used_mb"],
        })
    except FileNotFoundError:
        for key in ("wsl_ram_total_mib", "wsl_ram_used_mib", "wsl_swap_total_mib", "wsl_swap_used_mib"):
            metrics[key] = _metric(None, "proc_meminfo_unavailable")
            legacy[key] = None
        legacy.update({"memory_unit": "MiB", "ram_total_mb": None, "ram_used_mb": None,
                       "swap_total_mb": None, "swap_used_mb": None})
    except (OSError, ValueError):
        for key in ("wsl_ram_total_mib", "wsl_ram_used_mib", "wsl_swap_total_mib", "wsl_swap_used_mib"):
            metrics[key] = _metric(None, "proc_meminfo_read_failed", error=True)
            legacy[key] = None
        legacy.update({"memory_unit": "MiB", "ram_total_mb": None, "ram_used_mb": None,
                       "swap_total_mb": None, "swap_used_mb": None})

    gpu_values, gpu_status, gpu_reason = gpu_collection()
    legacy["gpu"] = gpu_values
    gpu_keys = {
        "vram_used_mb": "system_vram_used_mib",
        "gpu_util_pct": "gpu_util_pct",
        "temperature_c": "temperature_c",
        "gpu_clock_mhz": "gpu_clock_mhz",
        "power_w": "power_w",
    }
    for metric_key, legacy_key in gpu_keys.items():
        raw = gpu_values.get(metric_key)
        if raw is None:
            metrics[metric_key] = _metric(
                None, gpu_reason or "nvidia_smi_unavailable", error=gpu_status == "error",
            )
            legacy[legacy_key] = None
            continue
        if raw.strip() in {"[N/A]", "N/A"}:
            metrics[metric_key] = _metric(None, "nvidia_smi_metric_unavailable")
            legacy[legacy_key] = None
            continue
        try:
            value: int | float = float(raw) if "." in raw else int(raw)
        except ValueError:
            metrics[metric_key] = _metric(None, "nvidia_smi_value_unparseable", error=True)
            legacy[legacy_key] = None
        else:
            metrics[metric_key] = _metric(value)
            legacy[legacy_key] = raw
    return metrics, legacy, next_ticks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--run-id")
    parser.add_argument("--phase-id")
    parser.add_argument("--agent-id")
    parser.add_argument("--parent-agent-id")
    args = parser.parse_args()
    if args.interval < 0.25:
        parser.error("interval must be at least 0.25 seconds")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        previous_ticks = cpu_ticks()
    except (OSError, ValueError, IndexError):
        previous_ticks = None
    sample_seq = 0
    with args.output.open("a", encoding="utf-8") as output:
        while running:
            time.sleep(args.interval)
            metrics, legacy, previous_ticks = sample_metrics(previous_ticks)
            sample_seq += 1
            record = {
                "run_id": args.run_id,
                "event_id": f"{args.run_id}:{args.phase_id}:{sample_seq}",
                "phase_id": args.phase_id,
                "agent_id": args.agent_id,
                "parent_agent_id": args.parent_agent_id,
                "turn_id": None,
                "scope": "system_wide",
                "sample_seq": sample_seq,
                "source": "sampler",
                "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "monotonic_ns": time.monotonic_ns(),
                "cpu_util_pct": metrics["cpu_util_pct"]["value"],
                **legacy,
                "gpu": legacy["gpu"],
                "metrics": metrics,
            }
            output.write(json.dumps(record) + "\n")
            output.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
