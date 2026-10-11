#!/usr/bin/env python3
"""Create deterministic CSV and Markdown summaries for held-out QLoRA quality runs."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def summarize(rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["phase"], row["task_id"])].append(row)
    output = []
    for (phase, task_id), items in sorted(groups.items()):
        output.append({
            "phase": phase,
            "task_id": task_id,
            "runs": len(items),
            "successes": sum(bool(item["success"]) for item in items),
            "success_rate": round(sum(bool(item["success"]) for item in items) / len(items), 4),
            "tests_passed_total": sum(int(item["tests_passed"]) for item in items),
            "tests_total": sum(int(item["tests_total"]) for item in items),
            "median_generation_seconds": round(statistics.median(float(item["generation_seconds"]) for item in items), 4),
            "median_reference_nll_per_token": round(statistics.median(float(item["reference_nll_per_token"]) for item in items), 6),
            "median_reference_perplexity": round(statistics.median(float(item["reference_perplexity"]) for item in items), 6),
            "median_prompt_tokens": round(statistics.median(int(item["prompt_tokens"]) for item in items), 1),
            "median_completion_tokens": round(statistics.median(int(item["completion_tokens"]) for item in items), 1),
        })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"No quality measurements found in {args.input}")
    summaries = summarize(rows)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)

    phases = sorted({row["phase"] for row in rows})
    task_ids = sorted({row["task_id"] for row in rows})
    sample = rows[0]
    adapter_hashes = sorted({row["adapter_sha256"] for row in rows if row.get("adapter_sha256")})
    lines = [
        f"# Held-out {rows[0]['finetune_method'].upper()} quality probe",
        "",
        "This report compares a pinned local base checkpoint with its adapter on the same deterministic, held-out Python tasks. Each generated function is parsed and run only after an AST allowlist rejects imports, unsafe calls, attributes, and other non-expression code; positional calls to `abs`, `max`, and `min` are permitted. It also records per-token negative log likelihood for a fixed reference completion. These metrics cover a narrow synthetic task set, not general coding ability.",
        "",
        f"Raw input: `{args.input.name}`. Measurements: {len(rows)}. Tasks: {len(task_ids)}.",
        f"Model: `{sample['model']}` at revision `{sample['model_revision']}`; quantization: {sample['quantization']}; runtime: {sample['runtime']} (PyTorch {sample['torch_version']}, Transformers {sample['transformers_version']}, PEFT {sample['peft_version']}, bitsandbytes {sample['bitsandbytes_version']}).",
        f"GPU: {sample['gpu']}; storage: `{sample['storage_profile']}`; source commit: `{sample['git_sha']}` (dirty: {sample['source_tree_dirty']}); context limit: {sample['context_window_tokens']} tokens; greedy decoding, max {sample['max_new_tokens']} generated tokens.",
        f"Dataset SHA-256: `{sample['dataset_sha256']}`; adapter SHA-256: `{adapter_hashes[0] if len(adapter_hashes) == 1 else 'inconsistent'}`.",
        "",
        "| Phase | Task | Runs | Passes | Pass rate | Cases passed | Reference NLL/token | Median generation (s) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['phase']} | {item['task_id']} | {item['runs']} | {item['successes']} | {item['success_rate']:.0%} | {item['tests_passed_total']}/{item['tests_total']} | {item['median_reference_nll_per_token']:.4f} | {item['median_generation_seconds']:.4f} |"
        )
    for phase in phases:
        phase_rows = [row for row in rows if row["phase"] == phase]
        successes = sum(bool(row["success"]) for row in phase_rows)
        lines.append("")
        lines.append(
            f"Overall `{phase}` success: {successes}/{len(phase_rows)} task runs; "
            f"{sum(int(row['tests_passed']) for row in phase_rows)}/{sum(int(row['tests_total']) for row in phase_rows)} individual cases passed."
        )
        lines.append(
            f"Median reference NLL/perplexity: {statistics.median(float(row['reference_nll_per_token']) for row in phase_rows):.4f} / {statistics.median(float(row['reference_perplexity']) for row in phase_rows):.4f}."
        )
    lines += [
        "",
        "## Interpretation",
        "",
        f"Compare `{phases[0]}` with `{phases[1]}` within this {sample['finetune_method'].upper()} run. The base uses {sample['base_weight_precision']} weights; the adapter was trained with the same precision. Repeated identical generations are retained as repeated observations but are not independent samples of model quality. A pass requires the exact function signature, allowed syntax, successful execution, and every listed test case. NLL scores only the fixed reference code, not all correct solutions. This synthetic arithmetic/code set is a pipeline and narrow generalization probe; it does not establish useful real-world fine-tuning gains.",
        "",
    ]
    args.report.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.csv} and {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
