#!/usr/bin/env python3
"""Summarize QLoRA JSONL runs and their paired resource samples."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS = ROOT / "results/raw/qlora-7b-smoke.jsonl"
DEFAULT_CSV = ROOT / "results/csv/qlora-7b-summary.csv"
DEFAULT_REPORT = ROOT / "results/reports/qlora-7b-summary.md"
GROUP_FIELDS = (
    "model", "model_revision", "quantization", "max_seq_length", "batch_size",
    "lora_rank", "seed", "source_tree_dirty", "storage_profile",
)
RUN_METRICS = (
    "initial_loss", "final_loss", "total_seconds", "import_seconds", "model_load_seconds",
    "training_seconds", "baseline_probe_seconds", "post_training_probe_seconds",
    "vram_peak_allocated_mib", "vram_peak_reserved_mib",
)
RESOURCE_METRICS = (
    "gpu_vram_peak_sampled_mib", "ram_peak_mb", "swap_peak_mb", "gpu_util_mean_pct",
    "power_mean_w", "temperature_peak_c",
)


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def storage_profile(run: dict[str, Any]) -> str:
    profile = run.get("storage_profile")
    if profile:
        return str(profile)
    # Legacy records predate this field; their adapter output path identifies E:.
    if str(run.get("adapter_path", "")).startswith("/mnt/e/local-llm-results/"):
        return "hdd-e"
    return "unrecorded"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"Expected a JSON object in {path}:{line_number}")
        rows.append(row)
    return rows


def resource_rows(raw_dir: Path) -> list[dict[str, Any]]:
    samples = []
    for path in sorted(raw_dir.glob("qlora-7b-smoke-resources*.jsonl")):
        samples.extend(read_jsonl(path))
    for sample in samples:
        sample["_timestamp"] = timestamp(sample["timestamp"])
    return samples


def paired_samples(run: dict[str, Any], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ended = timestamp(run["timestamp"])
    started = ended - timedelta(seconds=float(run.get("total_seconds", 0)))
    return [sample for sample in samples if started - timedelta(seconds=3) <= sample["_timestamp"] <= ended + timedelta(seconds=3)]


def summarize(values: list[float]) -> dict[str, float | str]:
    return {
        "mean": statistics.mean(values) if values else "",
        "median": statistics.median(values) if values else "",
        "stddev": statistics.stdev(values) if len(values) > 1 else (0 if values else ""),
        "min": min(values) if values else "",
        "max": max(values) if values else "",
    }


def summarize_resources(samples: list[dict[str, Any]]) -> dict[str, list[float]]:
    gpu_used = [v for s in samples if (v := number(s.get("gpu", {}).get("vram_used_mb"))) is not None]
    ram_used = [v for s in samples if (v := number(s.get("ram_used_mb"))) is not None]
    swap_used = [v for s in samples if (v := number(s.get("swap_used_mb"))) is not None]
    gpu_util = [v for s in samples if (v := number(s.get("gpu", {}).get("gpu_util_pct"))) is not None]
    power = [v for s in samples if (v := number(s.get("gpu", {}).get("power_w"))) is not None]
    temperature = [v for s in samples if (v := number(s.get("gpu", {}).get("temperature_c"))) is not None]
    return {
        "gpu_vram_peak_sampled_mib": [max(gpu_used)] if gpu_used else [],
        "ram_peak_mb": [max(ram_used)] if ram_used else [],
        "swap_peak_mb": [max(swap_used)] if swap_used else [],
        "gpu_util_mean_pct": [statistics.mean(gpu_util)] if gpu_util else [],
        "power_mean_w": [statistics.mean(power)] if power else [],
        "temperature_peak_c": [max(temperature)] if temperature else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    runs = read_jsonl(args.input)
    samples = resource_rows(args.input.parent)
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run.get("model") != "Qwen/Qwen2.5-Coder-7B-Instruct":
            continue
        run["storage_profile"] = storage_profile(run)
        run["_resources"] = paired_samples(run, samples)
        key = tuple(run.get(field, "") for field in GROUP_FIELDS)
        grouped[key].append(run)

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(GROUP_FIELDS) + ["git_revisions", "runs", "successful_runs", "paired_resource_samples"]
    fieldnames += [f"{metric}_{stat}" for metric in (*RUN_METRICS, *RESOURCE_METRICS) for stat in ("mean", "median", "stddev", "min", "max")]
    with args.csv.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for key, values in sorted(grouped.items(), key=lambda item: str(item[0])):
            row = dict(zip(GROUP_FIELDS, key))
            row["git_revisions"] = ";".join(sorted({str(run.get("git_sha", "unknown")) for run in values}))
            row["runs"] = len(values)
            row["successful_runs"] = sum(bool(run.get("success")) for run in values)
            metric_values: dict[str, list[float]] = {
                metric: [v for run in values if (v := number(run.get(metric))) is not None]
                for metric in RUN_METRICS
            }
            resources = [sample for run in values for sample in run["_resources"]]
            per_run_resource = [summarize_resources(run["_resources"]) for run in values]
            for metric in RESOURCE_METRICS:
                metric_values[metric] = [series[metric][0] for series in per_run_resource if series[metric]]
            for metric, data in metric_values.items():
                for stat, value in summarize(data).items():
                    row[f"{metric}_{stat}"] = value
            row["paired_resource_samples"] = len(resources)
            writer.writerow(row)

    lines = [
        "# QLoRA 7B capacity smoke summary", "",
        "Runs are grouped by storage location and source cleanliness. Keep the HDD archive-backed and SSD ext4-backed series separate.", "",
        "| Storage | Git revision | Clean source | Runs | Passed | Median load (s) | Median train (s) | Median total (s) | Peak sampled VRAM (MiB) | Peak RAM (MiB) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    clean_groups = 0
    for key, values in sorted(grouped.items(), key=lambda item: str(item[0])):
        summary = {metric: summarize([v for run in values if (v := number(run.get(metric))) is not None]) for metric in RUN_METRICS}
        resource_data = [summarize_resources(run["_resources"]) for run in values]
        peak_vram = [r["gpu_vram_peak_sampled_mib"][0] for r in resource_data if r["gpu_vram_peak_sampled_mib"]]
        peak_ram = [r["ram_peak_mb"][0] for r in resource_data if r["ram_peak_mb"]]
        clean = key[GROUP_FIELDS.index("source_tree_dirty")] is False
        clean_groups += int(clean)
        storage = key[GROUP_FIELDS.index("storage_profile")]
        revisions = "; ".join(sorted({str(run.get("git_sha", "unknown"))[:7] for run in values}))
        lines.append(
            f"| {storage} | {revisions} | {'yes' if clean else 'no'} | {len(values)} | "
            f"{sum(bool(run.get('success')) for run in values)} | {summary['model_load_seconds']['median']:.1f} | "
            f"{summary['training_seconds']['median']:.1f} | {summary['total_seconds']['median']:.1f} | "
            f"{max(peak_vram):.0f} | {max(peak_ram):.0f} |"
        )
    if not grouped:
        lines.extend(["| No matching runs | — | — | 0 | 0 | — | — | — | — | — |"])
    lines.extend([
        "", f"CSV with per-run mean, median, standard deviation, minimum, and maximum: `{args.csv.relative_to(ROOT).as_posix() if args.csv.is_relative_to(ROOT) else args.csv}`.",
        "The system sampler records total VRAM at one-second intervals; the Torch allocator's allocated and reserved peaks are separate fields. The first run reported reserved memory above physical VRAM, so use sampled total VRAM for capacity decisions.",
        "All runs use the same seed and eight-row synthetic task. Identical loss traces establish deterministic execution here, not adapter quality or general coding performance.",
        "",
    ])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"groups": len(grouped), "clean_groups": clean_groups, "csv": str(args.csv), "report": str(args.report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
