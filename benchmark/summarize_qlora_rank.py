#!/usr/bin/env python3
"""Validate and summarize a QLoRA rank sweep's SSD-side JSONL artifacts."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected a JSON object in {path}:{number}")
            rows.append(row)
    return rows


def summarize(raw_dir: Path, repo_raw_dir: Path) -> list[dict]:
    summaries = []
    for rank in (8, 16, 32):
        runs = [read_jsonl(raw_dir / f"train-r{rank}-rep-{repeat}.jsonl") for repeat in range(1, 4)]
        train = [rows[0] for rows in runs if len(rows) == 1]
        if len(train) != 3 or any(row.get("lora_rank") != rank or row.get("lora_alpha") != 2 * rank for row in train):
            raise ValueError(f"Rank {rank} must have exactly three correctly labeled measured training records")
        if any(not row.get("success") or row.get("storage_profile") != "ssd-wsl-ext4-c" for row in train):
            raise ValueError(f"Rank {rank} contains a failed or non-SSD training record")
        evaluation = read_jsonl(repo_raw_dir / f"quality-r{rank}.jsonl")
        base = [row for row in evaluation if row.get("phase") == "base_nf4"]
        adapter = [row for row in evaluation if row.get("phase") == "qlora_adapter"]
        if len(base) != 15 or len(adapter) != 15:
            raise ValueError(f"Rank {rank} must have 15 base and 15 adapter held-out task records")
        if any(row.get("adapter_training_rank") != rank or row.get("storage_profile") != "ssd-wsl-ext4-c" for row in adapter):
            raise ValueError(f"Rank {rank} held-out records have incorrect provenance")
        seconds = [float(row["training_seconds"]) for row in train]
        vram = [float(row["vram_peak_allocated_mib"]) for row in train]
        resources = []
        for repeat in range(1, 4):
            resources.extend(read_jsonl(raw_dir / f"resources-r{rank}-rep-{repeat}.jsonl"))
        sampled_vram = [float(row["gpu"]["vram_used_mb"]) for row in resources if row.get("gpu", {}).get("vram_used_mb") not in (None, "")]
        summaries.append({
            "rank": rank,
            "alpha": 2 * rank,
            "trainable_parameters": int(train[0]["trainable_parameters"]),
            "adapter_mib": round(int(train[0]["adapter_bytes"]) / 1048576, 2),
            "train_seconds_median": round(statistics.median(seconds), 3),
            "train_seconds_mean": round(statistics.mean(seconds), 3),
            "train_seconds_sd": round(statistics.stdev(seconds), 3),
            "torch_vram_peak_mib": round(max(vram), 1),
            "sampled_system_vram_peak_mib": round(max(sampled_vram), 1) if sampled_vram else "",
            "base_tests_passed": sum(int(row["tests_passed"]) for row in base),
            "base_tests_total": sum(int(row["tests_total"]) for row in base),
            "adapter_tests_passed": sum(int(row["tests_passed"]) for row in adapter),
            "adapter_tests_total": sum(int(row["tests_total"]) for row in adapter),
            "base_task_passes": sum(bool(row["success"]) for row in base),
            "adapter_task_passes": sum(bool(row["success"]) for row in adapter),
            "base_reference_nll_median": round(statistics.median(float(row["reference_nll_per_token"]) for row in base), 6),
            "adapter_reference_nll_median": round(statistics.median(float(row["reference_nll_per_token"]) for row in adapter), 6),
            "adapter_sha256": str(train[0]["adapter_sha256"]),
        })
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True, help="SSD-side directory containing training records and resource samples")
    parser.add_argument("--repo-raw-dir", type=Path, required=True, help="directory containing the held-out quality JSONL files")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = summarize(args.raw_dir, args.repo_raw_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with (args.output_dir / "qlora-rank-sweep.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = [
        "# QLoRA rank sweep (SSD only)", "",
        "Qwen2.5-Coder-0.5B-Instruct, NF4/double quantization, AdamW32, seed 42, 16 steps, sequence length 192, batch 1, gradient checkpointing, and the same eight-row synthetic training fixture. Each rank used alpha = 2 × rank, one warm-up, and three measured trainings. Each final adapter and the base were evaluated on five deterministic held-out function tasks over three repeats.", "",
        "All active model, runtime, cache, log, and result I/O used the C:-backed WSL ext4 filesystem. HDDs were not used for measurements. The held-out tasks are synthetic and the base model already performs strongly; this is a narrow adapter/configuration comparison, not a broad coding-quality benchmark.", "",
        "| Rank / alpha | Trainable params | Adapter MiB | Train seconds median ± SD | Torch VRAM peak MiB | Sampled system VRAM peak MiB | Base tests | Adapter tests | Base task passes | Adapter task passes | Median reference NLL base → adapter |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        report.append(
            f"| {row['rank']} / {row['alpha']} | {row['trainable_parameters']:,} | {row['adapter_mib']:.2f} | {row['train_seconds_median']:.3f} ± {row['train_seconds_sd']:.3f} | {row['torch_vram_peak_mib']:.1f} | {row['sampled_system_vram_peak_mib']} | {row['base_tests_passed']}/{row['base_tests_total']} | {row['adapter_tests_passed']}/{row['adapter_tests_total']} | {row['base_task_passes']}/15 | {row['adapter_task_passes']}/15 | {row['base_reference_nll_median']:.6f} → {row['adapter_reference_nll_median']:.6f} |"
        )
    report.extend(["", "The CSV records adapter SHA-256 values and mean/standard deviation. Training-run JSONL and one-second hardware samples remain the source of truth.", ""])
    (args.output_dir / "qlora-rank-sweep.md").write_text("\n".join(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
