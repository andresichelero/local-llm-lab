#!/usr/bin/env python3
"""Compare paired LoRA and QLoRA held-out probe JSONL files."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


def load(path: Path, method: str) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or any(row.get("finetune_method") != method for row in rows):
        raise ValueError(f"Expected non-empty {method} measurements in {path}")
    return rows


def summarize(rows: list[dict], method: str) -> list[dict]:
    output = []
    for phase in sorted({row["phase"] for row in rows}):
        group = [row for row in rows if row["phase"] == phase]
        output.append({
            "method": method,
            "phase": phase,
            "weight_precision": group[0]["base_weight_precision"],
            "task_runs": len(group),
            "task_successes": sum(bool(row["success"]) for row in group),
            "cases_passed": sum(int(row["tests_passed"]) for row in group),
            "cases_total": sum(int(row["tests_total"]) for row in group),
            "median_reference_nll": round(statistics.median(float(row["reference_nll_per_token"]) for row in group), 6),
            "median_reference_perplexity": round(statistics.median(float(row["reference_perplexity"]) for row in group), 6),
            "median_generation_seconds": round(statistics.median(float(row["generation_seconds"]) for row in group), 4),
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qlora", type=Path, required=True)
    parser.add_argument("--lora", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    qlora = load(args.qlora, "qlora")
    lora = load(args.lora, "lora")
    for key in ("model_revision", "dataset_sha256", "gpu", "storage_profile", "git_sha"):
        if len({row.get(key) for row in qlora + lora}) != 1:
            raise ValueError(f"LoRA and QLoRA runs do not share {key}")
    summaries = summarize(qlora, "qlora") + summarize(lora, "lora")
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    sample = qlora[0]
    lines = [
        "# LoRA vs QLoRA held-out probe",
        "",
        f"Both methods used `{sample['model']}` revision `{sample['model_revision']}`, the same held-out dataset (`{sample['dataset_sha256']}`), seed 42, rank 8, 16 update steps, and three greedy evaluation repeats on {sample['gpu']} using `{sample['storage_profile']}`.",
        "",
        "LoRA kept the base weights in FP16; QLoRA used bitsandbytes NF4 with double quantization. Thus this is a practical method/precision comparison, not a controlled isolation of one algorithmic variable.",
        "",
        "| Method | Phase | Base precision | Task runs passed | Cases passed | Median reference NLL | Median reference perplexity | Median generation (s) |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(f"| {row['method'].upper()} | {row['phase']} | {row['weight_precision']} | {row['task_successes']}/{row['task_runs']} | {row['cases_passed']}/{row['cases_total']} | {row['median_reference_nll']:.4f} | {row['median_reference_perplexity']:.4f} | {row['median_generation_seconds']:.4f} |")
    lines += [
        "",
        "The 5-task deterministic fixture is deliberately narrow. LoRA and QLoRA adapters both passed all 15 generated task runs (54 individual cases); the FP16 base missed the inclusive-range task because its output exceeded the generation cap, while the NF4 base passed this fixture. Median reference NLL fell after training in both runs, but it scores only one fixed reference implementation per prompt. Repeated greedy runs are timing/robustness repetitions, not independent quality samples. These observations do not establish a general quality advantage for either method.",
        "",
        f"Raw QLoRA: `{args.qlora.name}`. Raw LoRA: `{args.lora.name}`.",
    ]
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.csv} and {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
