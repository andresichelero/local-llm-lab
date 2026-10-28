#!/usr/bin/env python3
"""Read-only WSL snapshot for the Windows local-LLM status monitor."""
from __future__ import annotations

import argparse
import csv
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Za-z_()]+):\s+(\d+)\s+kB\b", line)
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    return values


def parse_cpu_counters(text: str) -> tuple[int, int] | None:
    line = next((item for item in text.splitlines() if item.startswith("cpu ")), None)
    if not line:
        return None
    try:
        fields = [int(value) for value in line.split()[1:]]
    except ValueError:
        return None
    if len(fields) < 4:
        return None
    return sum(fields[:8]), fields[3] + (fields[4] if len(fields) > 4 else 0)


def cpu_busy_percent(before: tuple[int, int] | None,
                     after: tuple[int, int] | None) -> float | None:
    if before is None or after is None:
        return None
    total_delta, idle_delta = after[0] - before[0], after[1] - before[1]
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0, 100 * (total_delta - idle_delta) / total_delta)), 1)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def derive_run_summary(run_dir: Path, status: dict[str, Any],
                       manifest: dict[str, Any] | None = None,
                       *, mtime: float | None = None) -> dict[str, Any]:
    manifest = manifest or {}
    immutable = manifest.get("immutable") or {}
    repair_schedule = immutable.get("repair_schedule")
    stage_schedules = manifest.get("stage_schedules") or {}
    immutable_total = len(repair_schedule) if isinstance(repair_schedule, list) else 0
    stage_total = sum(len(items) for items in stage_schedules.values()
                      if isinstance(items, list)) if isinstance(stage_schedules, dict) else 0
    manifest_total = max(immutable_total, stage_total)
    try:
        status_scheduled = (int(status.get("scheduled_episodes"))
                            if status.get("scheduled_episodes") is not None else None)
    except (TypeError, ValueError):
        status_scheduled = None
    by_stage = status.get("episodes_by_stage") or {}
    completed = status.get("completed_episodes", status.get("scheduled_complete"))
    if completed is None:
        completed = sum(int(item.get("complete") or 0)
                        for item in by_stage.values() if isinstance(item, dict))
    completed = int(completed or 0)
    if manifest_total:
        scheduled = manifest_total
        schedule_source = ("manifest.immutable.repair_schedule" if immutable_total >= stage_total and immutable_total
                           else "manifest.stage_schedules")
    elif status_scheduled:
        scheduled = status_scheduled
        schedule_source = "status.json"
    else:
        scheduled = completed
        schedule_source = "completed_count"
    schedule_mismatch = bool(
        manifest_total and status_scheduled is not None
        and manifest_total != status_scheduled
    )
    updated = _parse_time(status.get("updated_at_utc"))
    updated_source = "status.updated_at_utc" if updated is not None else "status.json mtime"
    if updated is None:
        stamp = mtime if mtime is not None else run_dir.stat().st_mtime
        updated = datetime.fromtimestamp(stamp, tz=timezone.utc)
    latest = status.get("latest_episode") or manifest.get("latest_episode") or {}
    immutable_schedule = immutable.get("schedule")
    agenda_denominator = (immutable_schedule.get("maximum_episodes")
                          if isinstance(immutable_schedule, dict) else None)
    if agenda_denominator is None:
        agenda_denominator = status.get("maximum_episodes")
    capacity_wait = None
    if (run_dir / "capacity-wait.json").is_file():
        try:
            capacity_wait = json.loads((run_dir / "capacity-wait.json")
                                       .read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            capacity_wait = None
    return {
        "name": run_dir.name,
        "path": str(run_dir),
        "protocol": status.get("protocol_id") or manifest.get("protocol_id") or "-",
        "status": status.get("status") or status.get("state") or "unknown",
        "completed": completed,
        "scheduled": scheduled,
        "manifest_scheduled": manifest_total or None,
        "status_scheduled": status_scheduled,
        "schedule_source": schedule_source,
        "schedule_mismatch": schedule_mismatch,
        "progress_percent": round(100 * completed / scheduled, 1) if scheduled else None,
        "stage": status.get("current_stage") or "-",
        "updated_at_utc": updated.isoformat(timespec="seconds"),
        "updated_at_source": updated_source,
        "sort_timestamp": updated.timestamp(),
        "records": int(status.get("records") or manifest.get("record_count") or 0),
        "latest_episode": {
            "model": latest.get("model") or "-",
            "task": latest.get("task") or "-",
            "profile": latest.get("profile") or "-",
            "repetition": latest.get("repetition") or "-",
            "episode_status": latest.get("status") or "-",
            "failure": latest.get("failure"),
            "seconds": latest.get("seconds"),
        },
        "episodes_by_stage": by_stage,
        'task_quarantines': status.get('task_quarantines') or manifest.get('task_quarantines') or {},
        'maximum_episodes': status.get('maximum_episodes'),
        'coverage_complete': status.get('coverage_complete', False),
        'last_completed_budget': status.get('last_completed_budget'),
        'outcome_counts': status.get('outcome_counts', {}),
        'agenda_denominator': agenda_denominator,
        'active_error': manifest.get('error') or None,
        'resolved_errors': len(manifest.get('resolved_errors') or []),
        'operator_retry_blocked': bool(manifest.get('operator_retry_blocked')),
        'capacity_wait': capacity_wait,
    }


def load_recent_runs(results_root: Path, limit: int = 6) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    try:
        for status_path in results_root.glob("*/status.json"):
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
                manifest_path = status_path.parent / "manifest.json"
                manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                            if manifest_path.is_file() else {})
                if not isinstance(status, dict) or not isinstance(manifest, dict):
                    continue
                runs.append(derive_run_summary(
                    status_path.parent, status, manifest, mtime=status_path.stat().st_mtime
                ))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
    except OSError:
        return []
    runs.sort(key=lambda item: item["sort_timestamp"], reverse=True)
    return runs[:max(0, limit)]


def _process_kind(command: str) -> str | None:
    lowered = command.lower()
    if "llama-server" in lowered:
        return "llama-server"
    if any(token in lowered for token in (
        "benchmark.practical_repair", "benchmark.practical_campaign_v2", "benchmark.practical_review_replay",
        "benchmark.practical_queue", "benchmark.qwen_quant_runner", "benchmark.qwen_final_runner", "benchmark.qwen_final_oom_runner", "run-practical",
    )):
        return "benchmark-runner"
    if "opencode" in lowered:
        return "opencode"
    return None


def _output_path_from_command(command: str, cwd: str = "") -> str | None:
    """Return a normalized runner --output path, including relative paths."""
    try:
        arguments = shlex.split(command)
    except ValueError:
        return None
    output: str | None = None
    for index, argument in enumerate(arguments):
        if argument == "--output" and index + 1 < len(arguments):
            output = arguments[index + 1]
            break
        if argument.startswith("--output="):
            output = argument.partition("=")[2]
            break
    if not output:
        return None
    output = output.replace("\\", "/")
    if not output.startswith("/") and cwd:
        output = posixpath.join(cwd.replace("\\", "/"), output)
    return posixpath.normpath(output)


def correlate_run_with_processes(run: dict[str, Any],
                                 processes: list[dict[str, Any]],
                                 *, observed_at: datetime | None = None) -> dict[str, Any]:
    """Mark a run active only when a runner names that run's output directory."""
    expected = str(run.get("path") or "").replace("\\", "/")
    expected = posixpath.normpath(expected) if expected else ""
    matching_family = False
    matching_run = False
    has_unidentifiable_runner = False
    matching_process: dict[str, Any] | None = None
    tokens = (
        "benchmark.practical_repair", "benchmark.practical_campaign_v2",
        "benchmark.practical_queue", "benchmark.practical_review_replay",
        "benchmark.qwen_quant_runner", "benchmark.qwen_final_runner", "benchmark.qwen_final_oom_runner",
    )
    for process in processes:
        if process.get("kind") != "benchmark-runner":
            continue
        command = str(process.get("command") or "")
        if not any(token in command for token in tokens):
            continue
        matching_family = True
        output_path = _output_path_from_command(command, str(process.get("cwd") or ""))
        if output_path is None:
            has_unidentifiable_runner = True
        elif output_path == expected:
            matching_run = True
            matching_process = process
    active: bool | None
    if matching_run:
        active = True
    elif matching_family and has_unidentifiable_runner:
        active = None
    else:
        active = False
    status = str(run.get("status") or "unknown")
    display_status = status
    if status == "running" and active is False:
        display_status = "stale?"
    elif status == "running" and active is None:
        display_status = "unverified?"
    observed_at = observed_at or datetime.now(timezone.utc)
    status_updated = _parse_time(run.get("updated_at_utc"))
    status_age = (max(0.0, (observed_at - status_updated).total_seconds())
                  if status_updated else None)
    return {
        **run,
        "runner_active": active,
        "display_status": display_status,
        "status_age_seconds": round(status_age, 1) if status_age is not None else None,
        "runner_pid": matching_process.get("pid") if matching_process else None,
        "runner_elapsed": matching_process.get("elapsed") if matching_process else None,
        "runner_observed_at_utc": (observed_at.isoformat(timespec="seconds")
                                    if matching_process else None),
    }


def parse_relevant_processes(ps_output: str, proc_root: Path = Path("/proc")) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for line in ps_output.splitlines():
        fields = line.strip().split(None, 6)
        if len(fields) != 7 or fields[0].upper() == "PID":
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
            cpu_pct, mem_pct = float(fields[2]), float(fields[3])
            rss_mib = round(int(fields[4]) / 1024, 1)
        except ValueError:
            continue
        try:
            cwd = os.readlink(proc_root / str(pid) / "cwd")
        except OSError:
            cwd = ""
        processes.append({
            "pid": pid, "ppid": ppid, "cpu_percent": cpu_pct,
            "memory_percent": mem_pct, "rss_mib": rss_mib,
            "elapsed": fields[5], "command": fields[6],
            "kind": _process_kind(fields[6]), "cwd": cwd,
        })
    selected_ids = {item["pid"] for item in processes if item["kind"]}
    changed = True
    while changed:
        changed = False
        for item in processes:
            if item["pid"] not in selected_ids and item["ppid"] in selected_ids:
                selected_ids.add(item["pid"])
                item["kind"] = "child"
                changed = True
    priority = {"benchmark-runner": 0, "llama-server": 1, "opencode": 2, "child": 3}
    result = [item for item in processes if item["pid"] in selected_ids]
    return sorted(result, key=lambda item: (priority.get(item["kind"], 9),
                                            -item["cpu_percent"], -item["rss_mib"]))[:16]


def _sample_cpu_percent() -> float | None:
    try:
        before = parse_cpu_counters(Path("/proc/stat").read_text(encoding="ascii"))
        time.sleep(0.2)
        after = parse_cpu_counters(Path("/proc/stat").read_text(encoding="ascii"))
        return cpu_busy_percent(before, after)
    except OSError:
        return None


def _gib(value: int | None) -> float | None:
    return round(value / (1024 ** 3), 2) if value is not None else None


def _wsl_memory(meminfo: dict[str, int]) -> dict[str, Any]:
    total, available = meminfo.get("MemTotal"), meminfo.get("MemAvailable")
    swap_total, swap_free = meminfo.get("SwapTotal", 0), meminfo.get("SwapFree", 0)
    used = max(0, total - available) if total is not None and available is not None else None
    return {
        "total_gib": _gib(total), "available_gib": _gib(available),
        "used_gib": _gib(used),
        "used_percent": round(100 * used / total, 1) if total and used is not None else None,
        "swap_total_gib": _gib(swap_total),
        "swap_used_gib": _gib(max(0, swap_total - swap_free)),
    }


def _cgroup_memory() -> dict[str, float | None] | None:
    root = Path("/sys/fs/cgroup")
    try:
        raw_max = (root / "memory.max").read_text(encoding="ascii").strip()
        current = int((root / "memory.current").read_text(encoding="ascii").strip())
        maximum = int(raw_max) if raw_max != "max" else None
        return {"current_gib": _gib(current), "limit_gib": _gib(maximum)}
    except (OSError, ValueError):
        return None


def _gpu_snapshot() -> dict[str, Any] | None:
    query = (
        "name,driver_version,pstate,utilization.gpu,utilization.memory,"
        "memory.total,memory.used,memory.free,temperature.gpu,power.draw,"
        "power.limit,fan.speed,clocks.current.graphics,clocks.current.memory,"
        "clocks_throttle_reasons.active"
    )
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=4,
        )
        row = next(csv.reader(result.stdout.splitlines(), skipinitialspace=True))
        keys = [
            "name", "driver", "pstate", "gpu_util_percent", "memory_util_percent",
            "vram_total_mib", "vram_used_mib", "vram_free_mib", "temperature_c",
            "power_w", "power_limit_w", "fan_percent", "graphics_clock_mhz",
            "memory_clock_mhz", "throttle_reasons",
        ]
        gpu = dict(zip(keys, row))
        for key in (
            "gpu_util_percent", "memory_util_percent", "vram_total_mib",
            "vram_used_mib", "vram_free_mib", "temperature_c", "power_w",
            "power_limit_w", "fan_percent", "graphics_clock_mhz", "memory_clock_mhz",
        ):
            try:
                gpu[key] = float(gpu[key])
            except (ValueError, TypeError):
                gpu[key] = None
        full = subprocess.run(["nvidia-smi"], check=False, capture_output=True,
                              text=True, timeout=4)
        gpu.update(parse_nvidia_smi_metadata(full.stdout + "\n" + full.stderr))
        apps = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_gpu_memory",
             "--format=csv,noheader,nounits"],
            check=False, capture_output=True, text=True, timeout=4,
        )
        gpu["compute_processes"] = [
            [value.strip() for value in app]
            for app in csv.reader(apps.stdout.splitlines(), skipinitialspace=True)
            if len(app) >= 3
        ]
        return gpu
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            StopIteration, csv.Error):
        return None


def _cuda_toolkit() -> dict[str, str | None]:
    executable = shutil.which("nvcc")
    if not executable:
        candidates = [Path("/usr/local/cuda/bin/nvcc"), Path("/opt/cuda/bin/nvcc")]
        candidates.extend(Path("/usr/local").glob("cuda-*/bin/nvcc"))
        executable = next((str(path) for path in candidates if path.is_file()), None)
    if not executable:
        return {"path": None, "version": None}
    try:
        result = subprocess.run([executable, "--version"], check=False,
                                 capture_output=True, text=True, timeout=3)
        match = re.search(r"release\s+([0-9.]+)", result.stdout + result.stderr)
        return {"path": executable, "version": match.group(1) if match else "instalado"}
    except (OSError, subprocess.TimeoutExpired):
        return {"path": executable, "version": "indisponível"}


def parse_nvidia_smi_metadata(text: str) -> dict[str, str | None]:
    """Parse legacy and current NVIDIA version labels without conflating them."""
    smi = re.search(r"NVIDIA-SMI\s+([^\s|]+)", text)
    kmd = re.search(r"KMD Version:\s*([0-9.]+)", text)
    umd = re.search(r"CUDA UMD Version:\s*([0-9.]+)", text)
    cuda_max = re.search(r"CUDA Version:\s*([0-9.]+)", text)
    return {
        "nvidia_smi_version": smi.group(1) if smi else None,
        "kernel_driver_version": kmd.group(1) if kmd else None,
        "cuda_umd_version": umd.group(1) if umd else None,
        "cuda_driver_max": cuda_max.group(1) if cuda_max else None,
    }


def collect_snapshot(results_root: Path, recent: int = 6) -> dict[str, Any]:
    try:
        meminfo = parse_meminfo(Path("/proc/meminfo").read_text(encoding="ascii"))
    except OSError:
        meminfo = {}
    try:
        ps = subprocess.run(
            ["ps", "-eo", "pid,ppid,%cpu,%mem,rss,etime,args", "--sort=-%cpu"],
            check=True, capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        ps = ""
    try:
        disk = shutil.disk_usage(results_root)
        disk_info = {"total_gib": _gib(disk.total), "used_gib": _gib(disk.used),
                     "free_gib": _gib(disk.free)}
    except OSError:
        disk_info = None
    processes = parse_relevant_processes(ps)
    cpu_percent = _sample_cpu_percent()
    cuda_toolkit = _cuda_toolkit()
    gpu = _gpu_snapshot()
    sampled_at = datetime.now(timezone.utc)
    recent_runs = [
        correlate_run_with_processes(run, processes, observed_at=sampled_at)
        for run in load_recent_runs(results_root, recent)
    ]
    return {
        "sampled_at_utc": sampled_at.isoformat(timespec="seconds"),
        "results_root": str(results_root),
        "cpu_percent": cpu_percent,
        "memory": _wsl_memory(meminfo),
        "cgroup_memory": _cgroup_memory(),
        "disk": disk_info,
        "cuda_toolkit": cuda_toolkit,
        "gpu": gpu,
        "processes": processes,
        "recent_runs": recent_runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--recent", type=int, default=6)
    args = parser.parse_args()
    try:
        print(json.dumps(collect_snapshot(args.results_root, args.recent),
                         ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}",
                          "sampled_at_utc": datetime.now(timezone.utc).isoformat()}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

