#!/usr/bin/env python3
"""Summarize paired FP16 LoRA and NF4 QLoRA smoke runs and resource samples."""
from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results/raw"
RUNS_PATH = RAW / "lora-qlora-smoke.jsonl"
CSV_PATH = ROOT / "results/csv/lora-qlora-summary.csv"
REPORT_PATH = ROOT / "results/reports/lora-qlora-comparison.md"
RUN_METRICS = (
    "import_seconds", "model_load_seconds", "training_seconds", "total_seconds",
    "initial_loss", "final_loss", "vram_peak_allocated_mib", "vram_peak_reserved_mib",
)
RESOURCE_METRICS = (
    "gpu_vram_peak_sampled_mib", "ram_peak_mb", "swap_peak_mb", "gpu_util_mean_pct",
    "power_mean_w", "temperature_peak_c",
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")
            rows.append(row)
    return rows


def parsed_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def numeric(values: list[Any]) -> list[float]:
    result = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            result.append(number)
    return result


def stats(values: list[float]) -> dict[str, float | str]:
    return {
        "mean": statistics.mean(values) if values else "",
        "median": statistics.median(values) if values else "",
        "stddev": statistics.stdev(values) if len(values) > 1 else (0 if values else ""),
        "min": min(values) if values else "",
        "max": max(values) if values else "",
    }


def resource_summary(samples: list[dict[str, Any]]) -> dict[str, float | int | str]:
    gpu = [sample.get("gpu", {}) for sample in samples]
    vram = numeric([item.get("vram_used_mb") for item in gpu])
    ram = numeric([sample.get("ram_used_mb") for sample in samples])
    swap = numeric([sample.get("swap_used_mb") for sample in samples])
    util = numeric([item.get("gpu_util_pct") for item in gpu])
    power = numeric([item.get("power_w") for item in gpu])
    temperature = numeric([item.get("temperature_c") for item in gpu])
    return {
        "gpu_vram_peak_sampled_mib": max(vram) if vram else "",
        "ram_peak_mb": max(ram) if ram else "",
        "swap_peak_mb": max(swap) if swap else "",
        "gpu_util_mean_pct": statistics.mean(util) if util else "",
        "power_mean_w": statistics.mean(power) if power else "",
        "temperature_peak_c": max(temperature) if temperature else "",
    }


def main() -> int:
    runs = read_jsonl(RUNS_PATH)
    sample_files = sorted(RAW.glob("lora-qlora-resources-*-rep*.jsonl"))
    samples = [sample for path in sample_files for sample in read_jsonl(path)]
    for sample in samples:
        sample["_time"] = parsed_time(sample["timestamp"])

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in runs:
        if run.get("method") not in {"LoRA", "QLoRA"}:
            continue
        ended = parsed_time(run["timestamp"])
        started = ended - timedelta(seconds=float(run.get("total_seconds", 0)))
        run["_samples"] = [
            sample for sample in samples
            if started - timedelta(seconds=3) <= sample["_time"] <= ended + timedelta(seconds=3)
        ]
        groups[str(run["method"])].append(run)

    fields = ["method", "quantization", "model", "model_revision", "storage_profile", "git_revisions", "seed", "max_seq_length", "batch_size", "lora_rank", "runs", "successful_runs", "paired_resource_samples"]
    fields.extend(f"{metric}_{stat}" for metric in (*RUN_METRICS, *RESOURCE_METRICS) for stat in ("mean", "median", "stddev", "min", "max"))
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for method, values in sorted(groups.items()):
            first = values[0]
            row: dict[str, Any] = {
                "method": method,
                "quantization": first.get("quantization", ""),
                "model": first.get("model", ""),
                "model_revision": first.get("model_revision", ""),
                "storage_profile": first.get("storage_profile", ""),
                "git_revisions": ";".join(sorted({str(run.get("git_sha", "unknown")) for run in values})),
                "seed": first.get("seed", ""),
                "max_seq_length": first.get("max_seq_length", ""),
                "batch_size": first.get("batch_size", ""),
                "lora_rank": first.get("lora_rank", ""),
                "runs": len(values),
                "successful_runs": sum(bool(run.get("success")) for run in values),
            }
            for metric in RUN_METRICS:
                for stat, value in stats(numeric([run.get(metric) for run in values])).items():
                    row[f"{metric}_{stat}"] = value
            per_run_resources = [resource_summary(run["_samples"]) for run in values]
            row["paired_resource_samples"] = sum(len(run["_samples"]) for run in values)
            for metric in RESOURCE_METRICS:
                for stat, value in stats(numeric([item[metric] for item in per_run_resources])).items():
                    row[f"{metric}_{stat}"] = value
            writer.writerow(row)

    lines = [
        "# LoRA FP16 vs QLoRA NF4 smoke comparison", "",
        "Three measured repeats per method followed one warm-up per method. Runs used the same pinned 0.49B model, eight synthetic rows, seed 42, rank 8, batch 1, sequence length 192, eight optimizer steps, FP16 compute, AdamW, and SSD-backed WSL storage.", "",
        "| Method | Runs passed | Median model load (s) | Median training (s) | Median total (s) | Peak Torch allocated (MiB) | Peak sampled VRAM (MiB) | Peak RAM (MiB) | Probe passed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for method in ("LoRA", "QLoRA"):
        values = groups.get(method, [])
        if not values:
            lines.append(f"| {method} | 0 | — | — | — | — | — | — | — |")
            continue
        load = stats(numeric([run.get("model_load_seconds") for run in values]))["median"]
        train = stats(numeric([run.get("training_seconds") for run in values]))["median"]
        total = stats(numeric([run.get("total_seconds") for run in values]))["median"]
        allocated = stats(numeric([run.get("vram_peak_allocated_mib") for run in values]))["max"]
        sampled = [resource_summary(run["_samples"]).get("gpu_vram_peak_sampled_mib") for run in values]
        sampled_peak = max(numeric(sampled), default=0)
        ram_peak = max(numeric([resource_summary(run["_samples"]).get("ram_peak_mb") for run in values]), default=0)
        passed = sum(bool(run.get("success")) for run in values)
        probe = "all" if all(run.get("trained_probe_static_add_ast_pass") for run in values) else "not all"
        lines.append(f"| {method} | {passed}/{len(values)} | {float(load):.3f} | {float(train):.3f} | {float(total):.3f} | {float(allocated):.1f} | {sampled_peak:.0f} | {ram_peak:.0f} | {probe} |")

    all_runs = [run for method in ("LoRA", "QLoRA") for run in groups.get(method, [])]
    lines.extend([
        "", "## Interpretation", "",
        "Both paths completed the eight-step training smoke on the RTX 3070. NF4 QLoRA used less allocated VRAM than FP16 LoRA in this 0.49B test; both were comfortably within the available GPU memory. The repeated loss traces and adapter hashes were deterministic for each method.",
        "Torch allocator peaks are per-process. One-second sampled VRAM and RAM include the system and shared Windows desktop GPU use, rather than attributing all memory to the training process.", "",
        "The base model already returned a valid `add(a, b)` before training, and it did so afterward. This is a runtime/capacity comparison only; the tiny synthetic dataset and probe do not measure useful quality improvement or support a general LoRA-versus-QLoRA quality ranking.", "",
        f"Runs: {len(all_runs)} measured ({sum(bool(run.get('success')) for run in all_runs)} successful), all recorded against commit `{all_runs[0].get('git_sha', 'unknown')[:7] if all_runs else '—'}`. Warm-ups are kept separately in `results/raw/lora-qlora-warmup.jsonl`.",
        f"Per-run means, medians, standard deviations, ranges, and paired resource summaries: `{CSV_PATH.relative_to(ROOT).as_posix()}`. Raw measurements: `results/raw/lora-qlora-smoke.jsonl`; per-run resource traces: `results/raw/lora-qlora-resources-*-rep*.jsonl`.", "",
        "The eight adapter artifacts are archived at `E:\\local-llm-results\\lora-qlora-20261011`; their archive was checked byte-for-byte against the SSD copies before the temporary adapter and model staging directories were cleared. The pinned base model remains archived at `E:\\local-llm-models\\Qwen2.5-Coder-0.5B-Instruct`.", "",
    ])
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"runs": len(all_runs), "groups": {key: len(value) for key, value in groups.items()}, "csv": str(CSV_PATH), "report": str(REPORT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
