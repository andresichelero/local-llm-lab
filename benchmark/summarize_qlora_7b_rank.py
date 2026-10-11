#!/usr/bin/env python3
"""Validate and summarize SSD-side QLoRA rank-capacity records, including failed ranks."""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected a JSON object in {path}:{number}")
            rows.append(row)
    return rows


def summarize(raw_dir: Path, repo_raw_dir: Path, expected_repeats: int = 3) -> list[dict]:
    failure_rows = read_jsonl(raw_dir / "failures.jsonl")
    rank_set = {
        int(match.group(1))
        for path in raw_dir.glob("train-r*-rep-*.jsonl")
        if (match := re.fullmatch(r"train-r(\d+)-rep-\d+\.jsonl", path.name))
    }
    rank_set.update(int(row["rank"]) for row in failure_rows if "rank" in row)
    ranks = sorted(rank_set)
    if not ranks:
        raise ValueError(f"No rank sweep records or failures found in {raw_dir}")

    summaries = []
    for rank in ranks:
        train = []
        for repeat in range(1, expected_repeats + 1):
            path = raw_dir / f"train-r{rank}-rep-{repeat}.jsonl"
            records = read_jsonl(path)
            if records:
                if len(records) != 1:
                    raise ValueError(f"Expected one training record in {path}")
                train.append(records[0])
        if any(
            row.get("lora_rank") != rank
            or row.get("lora_alpha") != 2 * rank
            or row.get("storage_profile") != "ssd-wsl-ext4-c"
            for row in train
        ):
            raise ValueError(f"Rank {rank} has mislabeled or non-SSD training data")
        if any(not row.get("success") for row in train):
            raise ValueError(f"Rank {rank} contains a failed record presented as successful training")
        training_complete = len(train) == expected_repeats
        failures = [row for row in failure_rows if row.get("rank") == rank]

        quality_path = repo_raw_dir / f"quality-r{rank}.jsonl"
        evaluation = read_jsonl(quality_path)
        base = [row for row in evaluation if row.get("phase") == "base_nf4"]
        adapter = [row for row in evaluation if row.get("phase") == "qlora_adapter"]
        expected_quality_rows = 5 * expected_repeats
        quality_complete = training_complete and len(base) == expected_quality_rows and len(adapter) == expected_quality_rows
        if evaluation and not training_complete:
            raise ValueError(f"Rank {rank} has held-out results without a complete training series")
        if any(
            row.get("adapter_training_rank") != rank
            or row.get("adapter_training_alpha") != 2 * rank
            or row.get("storage_profile") != "ssd-wsl-ext4-c"
            for row in adapter
        ):
            raise ValueError(f"Rank {rank} has mislabeled or non-SSD held-out results")
        adapter_hashes = {str(row["adapter_sha256"]) for row in train}
        if len(adapter_hashes) > 1:
            raise ValueError(f"Rank {rank} produced inconsistent adapter hashes across training repeats")
        if adapter and train and any(row.get("adapter_sha256") != train[0].get("adapter_sha256") for row in adapter):
            raise ValueError(f"Rank {rank} held-out results do not match the trained adapter hash")
        if evaluation and (len(base) != expected_quality_rows or len(adapter) != expected_quality_rows):
            raise ValueError(f"Rank {rank} held-out evaluation is incomplete")

        seconds = [float(row["training_seconds"]) for row in train]
        vram = [float(row["vram_peak_allocated_mib"]) for row in train]
        resources = []
        for repeat in range(1, expected_repeats + 1):
            resources.extend(read_jsonl(raw_dir / f"resources-r{rank}-rep-{repeat}.jsonl"))
        sampled_vram = [
            float(row["gpu"]["vram_used_mb"])
            for row in resources
            if row.get("gpu", {}).get("vram_used_mb") not in (None, "")
        ]
        source_rows = train + evaluation
        summaries.append({
            "rank": rank,
            "alpha": 2 * rank,
            "training_status": "complete" if training_complete else f"incomplete ({len(train)}/{expected_repeats})",
            "training_runs": len(train),
            "trainable_parameters": int(train[0]["trainable_parameters"]) if train else "",
            "adapter_mib": round(int(train[0]["adapter_bytes"]) / 1048576, 2) if train else "",
            "train_seconds_median": round(statistics.median(seconds), 3) if seconds else "",
            "train_seconds_mean": round(statistics.mean(seconds), 3) if seconds else "",
            "train_seconds_sd": round(statistics.stdev(seconds), 3) if len(seconds) > 1 else "",
            "torch_vram_peak_mib": round(max(vram), 1) if vram else "",
            "sampled_system_vram_peak_mib": round(max(sampled_vram), 1) if sampled_vram else "",
            "quality_status": "complete" if quality_complete else ("incomplete" if evaluation else "not run"),
            "base_tests_passed": sum(int(row["tests_passed"]) for row in base),
            "base_tests_total": sum(int(row["tests_total"]) for row in base),
            "adapter_tests_passed": sum(int(row["tests_passed"]) for row in adapter),
            "adapter_tests_total": sum(int(row["tests_total"]) for row in adapter),
            "base_task_passes": sum(bool(row["success"]) for row in base),
            "adapter_task_passes": sum(bool(row["success"]) for row in adapter),
            "base_reference_nll_median": round(statistics.median(float(row["reference_nll_per_token"]) for row in base), 6) if base else "",
            "adapter_reference_nll_median": round(statistics.median(float(row["reference_nll_per_token"]) for row in adapter), 6) if adapter else "",
            "adapter_sha256": str(train[0]["adapter_sha256"]) if train else "",
            "git_sha": str(source_rows[0]["git_sha"]) if source_rows else "",
            "model_revision": str(source_rows[0]["model_revision"]) if source_rows else "",
            "source_tree_dirty_rows": sum(bool(row.get("source_tree_dirty")) for row in source_rows),
            "failure_phases": "; ".join(f"{row.get('phase')}:{row.get('label')} exit={row.get('exit_code')}" for row in failures),
        })
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True, help="SSD-side training JSONL, sampler traces, and failures")
    parser.add_argument("--repo-raw-dir", type=Path, required=True, help="directory containing held-out quality JSONL files")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    rows = summarize(args.raw_dir, args.repo_raw_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with (args.output_dir / "qlora-7b-rank-sweep.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = [
        "# QLoRA 7B rank capacity sweep (SSD only)", "",
        "Pinned Qwen2.5-Coder-7B-Instruct, NF4/double quantization, AdamW32, seed 42, sequence length 192, batch 1, gradient checkpointing, and the same eight-row training fixture. Ranks use alpha = 2 × rank; each requested rank has one warm-up and three measured trainings. Complete ranks are evaluated against the base and final adapter on five deterministic held-out function tasks over three repeats.", "",
        "All active model, runtime, cache, log, and result I/O used the C:-backed WSL ext4 SSD. HDDs were not used for measurements. The held-out tasks are synthetic and the base model already performs strongly; this is a narrow capacity/configuration comparison, not a broad coding-quality benchmark.", "",
        "| Rank / alpha | Training | Trainable params | Adapter MiB | Train seconds median ± SD | Torch VRAM peak MiB | Sampled system VRAM peak MiB | Quality | Base tests | Adapter tests | Median reference NLL base → adapter | Failure |",
        "|---:|:---|---:|---:|---:|---:|---:|:---|---:|---:|---:|:---|",
    ]
    for row in rows:
        def display(key: str, fmt: str = "") -> str:
            value = row[key]
            return format(value, fmt) if value != "" and fmt else str(value)
        nll = ""
        if row["base_reference_nll_median"] != "" and row["adapter_reference_nll_median"] != "":
            nll = f"{row['base_reference_nll_median']:.6f} → {row['adapter_reference_nll_median']:.6f}"
        report.append(
            f"| {row['rank']} / {row['alpha']} | {row['training_status']} | {display('trainable_parameters', ',')} | {display('adapter_mib', '.2f')} | {display('train_seconds_median', '.3f')} ± {display('train_seconds_sd', '.3f')} | {display('torch_vram_peak_mib', '.1f')} | {display('sampled_system_vram_peak_mib', '.1f')} | {row['quality_status']} | {row['base_tests_passed']}/{row['base_tests_total']} | {row['adapter_tests_passed']}/{row['adapter_tests_total']} | {nll} | {row['failure_phases']} |"
        )
    source = next((row for row in rows if row["git_sha"]), rows[0])
    dirty = sum(int(row["source_tree_dirty_rows"]) for row in rows)
    report.extend([
        "",
        f"Source commit: `{source['git_sha'] or 'unrecorded'}`; pinned model revision: `{source['model_revision'] or 'unrecorded'}`; dirty source rows: {dirty}.",
        "Training JSONL, one-second resource samples, quality JSONL, and failure events remain the source of truth. Incomplete ranks are reported but excluded from any complete-configuration ranking.", "",
    ])
    (args.output_dir / "qlora-7b-rank-sweep.md").write_text("\n".join(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
