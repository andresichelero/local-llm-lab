"""Read the Qwen comparison queue without dumping prompts or model responses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess

LAB = Path("/home/foxtrot/local-llm-benchmark")
DEFAULT = LAB / "results/qwen-quant-harness-optimization-v4-recovery-r3-dns"


def status(output=DEFAULT):
    output = Path(output)
    manifest = json.loads((output / "manifest.json").read_text())
    state = json.loads((output / "state.json").read_text())
    protocol = manifest["immutable"]["protocol_id"]
    pause_requested = (output / "PAUSE").is_file()
    attempts = state["attempts"]
    units = state.get("units", [])
    finished_ids = {
        attempt.get("unit_id")
        for attempt in attempts
        if attempt.get("status") == "finished"
    }
    scheduled_stages = {}
    for unit in units:
        stage = unit.get("stage", "unknown")
        stage_status = scheduled_stages.setdefault(
            stage, {"scheduled": 0, "finished": 0, "pending": 0}
        )
        stage_status["scheduled"] += 1
        if unit.get("unit_id") in finished_ids:
            stage_status["finished"] += 1
        else:
            stage_status["pending"] += 1
    stages = {}
    for attempt in attempts:
        item = stages.setdefault(
            attempt["unit"]["stage"],
            {"finished": 0, "running": 0, "resource_waiting": 0},
        )
        item[attempt["status"]] = item.get(attempt["status"], 0) + 1
    latest = attempts[-1] if attempts else None
    current = None
    if latest:
        row, unit = latest, latest["unit"]
        path = output / "units" / row["unit_id"] / str(row["number"])
        checks = path / "checks.json"
        current = {
            "stage": unit["stage"],
            "model": unit["model_id"],
            "engine": unit["engine"],
            "artifact": unit["artifact_id"],
            "context": unit["context"],
            "attempt_status": row["status"],
            "completed_checks": (
                sum(bool(x.get("passed")) for x in json.loads(checks.read_text()))
                if checks.exists()
                else None
            ),
        }
        sample = path / "resource-samples.json"
        if sample.exists():
            values = [
                x["device_free_mib"]
                for x in json.loads(sample.read_text())
                if "device_free_mib" in x
            ]
            current["device_free_mib_min"] = min(values) if values else None
            current["resource_telemetry_samples"] = len(values)
            current["resource_scope"] = "whole GPU device including host applications"
    try:
        gpu = subprocess.run(
            [
                "/usr/lib/wsl/lib/nvidia-smi",
                "--query-gpu=memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        gpu = "unavailable"
    try:
        unit = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                f"qwen-quant-optimization-v{protocol.rsplit('-v', 1)[-1]}.service",
                "-p",
                "ActiveState",
                "-p",
                "SubState",
                "-p",
                "MainPID",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        unit = "unavailable"
    return {
        "protocol": protocol,
        "status": "paused" if pause_requested else state["status"],
        "recorded_status": state["status"],
        "pause_requested": pause_requested,
        "attempts": len(attempts),
        "finished_records": sum(a["status"] == "finished" for a in attempts),
        "scheduled_units": len(units),
        "pending_units": sum(stage["pending"] for stage in scheduled_stages.values()),
        "scheduled_stages": scheduled_stages,
        "resource_waiting": state.get("resource_wait", {}),
        "stages": stages,
        "current": current,
        "gpu_device": gpu,
        "service": unit,
        "ext4_available_bytes": shutil.disk_usage(LAB).free,
        "output": str(output),
        "native_harness_stage": "pending_quantization_finalists",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT)
    args = parser.parse_args()
    print(json.dumps(status(args.output), indent=2))


if __name__ == "__main__":
    main()
