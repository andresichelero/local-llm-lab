#!/usr/bin/env python3
"""Consolidate paired QLoRA optimizer training and held-out evaluation JSONL."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


def read_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            rows.extend(json.loads(line) for line in stream if line.strip())
    return rows


def median(rows: list[dict], key: str) -> float:
    return round(statistics.median(float(row[key]) for row in rows), 4)


def descriptive(rows: list[dict], key: str) -> dict[str, float]:
    values = [float(row[key]) for row in rows]
    return {
        f"{key}_mean": round(statistics.mean(values), 4),
        f"{key}_stddev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
        f"{key}_min": round(min(values), 4),
        f"{key}_max": round(max(values), 4),
    }


def resource_rows(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        resource_path = path.with_name(f"{path.stem}-resources.jsonl")
        if not resource_path.exists():
            continue
        rows.extend(read_rows([resource_path]))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", nargs="+", type=Path, required=True, help="warmup and measured training JSONL files")
    parser.add_argument("--quality", nargs="+", type=Path, required=True, help="held-out quality JSONL files")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    training = read_rows(args.training)
    quality = read_rows(args.quality)
    optimizers = ("adamw32", "adamw8bit")
    summary = []
    for optimizer in optimizers:
        train_rows = [row for row in training if optimizer in str(row.get("optimizer", "")).lower() or row.get("optimizer_id") == optimizer]
        measured = [row for row in train_rows if "warmup" not in row.get("run_id", "") and row.get("phase") != "warmup"]
        # Filenames are authoritative because older training JSONL rows predate optimizer_id/run_id fields.
        train_paths = [path for path in args.training if optimizer in path.name]
        train_rows = [row for path in train_paths for row in read_rows([path])]
        measured = [row for path in train_paths if "warmup" not in path.name for row in read_rows([path])]
        samples = resource_rows([path for path in train_paths if "warmup" not in path.name])
        gpu_samples = [row.get("gpu", {}) for row in samples if row.get("gpu")]
        sampled_vram = [float(row["vram_used_mb"]) for row in gpu_samples if row.get("vram_used_mb") is not None]
        sampled_gpu = [float(row["gpu_util_pct"]) for row in gpu_samples if row.get("gpu_util_pct") is not None]
        sampled_temp = [float(row["temperature_c"]) for row in gpu_samples if row.get("temperature_c") is not None]
        sampled_ram = [float(row["ram_used_mb"]) for row in samples if row.get("ram_used_mb") is not None]
        quality_rows = [row for row in quality if row.get("adapter_training_optimizer") == optimizer]
        task_results = [row for row in quality_rows if row.get("phase") == "qlora_adapter"]
        reference_nll = [row for row in task_results if row.get("reference_nll_per_token") is not None]
        unique_adapters = sorted({row.get("adapter_sha256") for row in train_rows if row.get("adapter_sha256")})
        if len(task_results) != 15 or len(reference_nll) != 15:
            raise SystemExit(f"Expected 15 successful held-out adapter rows for {optimizer}, got {len(task_results)}")
        if any(not row.get("success") for row in task_results):
            raise SystemExit(f"Held-out adapter evaluation failed for {optimizer}")
        sample = measured[0]
        item = {
            "optimizer": optimizer,
            "training_repetitions": len(measured),
            "successful_training_repetitions": sum(bool(row.get("success")) for row in measured),
            "median_training_seconds": median(measured, "training_seconds"),
            "median_total_seconds": median(measured, "total_seconds"),
            "median_peak_vram_allocated_mib": median(measured, "vram_peak_allocated_mib"),
            "median_peak_vram_reserved_mib": median(measured, "vram_peak_reserved_mib"),
            "sampled_total_vram_peak_mb": max(sampled_vram) if sampled_vram else "",
            "sampled_gpu_util_mean_pct": round(statistics.mean(sampled_gpu), 2) if sampled_gpu else "",
            "sampled_temperature_peak_c": max(sampled_temp) if sampled_temp else "",
            "sampled_ram_peak_mb": max(sampled_ram) if sampled_ram else "",
            "heldout_runs": len(task_results),
            "heldout_success_rate": round(sum(bool(row.get("success")) for row in task_results) / len(task_results), 4),
            "heldout_tests_passed": sum(int(row.get("tests_passed", 0)) for row in task_results),
            "heldout_tests_total": sum(int(row.get("tests_total", 0)) for row in task_results),
            "median_reference_nll": round(statistics.median(float(row["reference_nll_per_token"]) for row in reference_nll), 6),
            "adapter_hash_count": len(unique_adapters),
            "adapter_sha256": unique_adapters[0] if len(unique_adapters) == 1 else "inconsistent",
            "storage_profile": sample["storage_profile"],
            "model_revision": sample["model_revision"],
            "dataset_sha256": sample["dataset_sha256"],
            "seed": sample["seed"],
            "steps": sample["max_steps"],
            "sequence_length": sample["max_seq_length"],
        }
        item.update(descriptive(measured, "training_seconds"))
        item.update(descriptive(measured, "total_seconds"))
        if item["training_repetitions"] != 3 or item["successful_training_repetitions"] != 3:
            raise SystemExit(f"Expected three successful measured training repetitions for {optimizer}, got {item['successful_training_repetitions']}/{item['training_repetitions']}")
        if item["storage_profile"] != "ssd-wsl-ext4-c":
            raise SystemExit(f"Refusing non-SSD data for {optimizer}: {item['storage_profile']}")
        summary.append(item)

    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    a, b = summary
    lines = [
        "# QLoRA optimizer comparison: Qwen2.5-Coder-7B-Instruct",
        "",
        "This is a paired local experiment on the RTX 3070 8 GB using the pinned 7B model, NF4 double quantization, rank 8, alpha 16, sequence length 192, batch 1, eight optimizer steps, seed 42, and the same eight-row training fixture. Storage is WSL ext4 on C: (SSD). One warm-up was excluded; each optimizer has three measured repetitions.",
        "",
        "| Optimizer | Median train (s) | Mean ± SD (s) | Median total (s) | Peak allocated VRAM (MiB) | Sampled VRAM peak (MiB) | Held-out success | Tests passed | Median reference NLL | Adapter hashes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary:
        lines.append(f"| {item['optimizer']} | {item['median_training_seconds']} | {item['training_seconds_mean']} ± {item['training_seconds_stddev']} | {item['median_total_seconds']} | {item['median_peak_vram_allocated_mib']} | {item['sampled_total_vram_peak_mb']} | {item['heldout_success_rate']:.0%} ({item['heldout_runs']} runs) | {item['heldout_tests_passed']}/{item['heldout_tests_total']} | {item['median_reference_nll']} | {item['adapter_hash_count']} |")
    lines += [
        "",
        "The 8-bit optimizer uses bitsandbytes AdamW8bit with `min_8bit_size=4096`; tensors below that threshold retain 32-bit states by default, so this is not a claim that every optimizer state is quantized. See [official bitsandbytes optimizer documentation](https://huggingface.co/docs/bitsandbytes/main/optimizers).",
        "",
        "These short smoke runs establish compatibility and a directional resource comparison, not convergence quality or a general training-speed ranking. The held-out fixture is small and synthetic; passing it does not establish broad coding capability.",
        "",
        "## Provenance",
        "",
        f"Model revision: `{a['model_revision']}`; train dataset SHA-256: `{a['dataset_sha256']}`; seed: `{a['seed']}`; steps: `{a['steps']}`; sequence length: `{a['sequence_length']}`; storage: `{a['storage_profile']}`.",
        "",
        "Raw JSONL inputs are named in the CSV-generation command and retained under `results/raw/`.",
        "",
        "The earlier 32-bit run `20261011T191434Z` is retained as preliminary raw evidence but excluded because its storage profile was not recorded; all figures above use the corrected `ssd-wsl-ext4-c` series.",
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.csv} and {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
