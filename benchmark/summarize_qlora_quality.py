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
    lines = [
        "# Held-out QLoRA quality probe",
        "",
        "This report compares a pinned local NF4 base checkpoint with its adapter on the same deterministic, held-out Python tasks. Each generated function is parsed and run only after an AST allowlist rejects imports, calls, attributes, and other non-expression code. Results measure this narrow task set, not general coding ability or adapter quality across domains.",
        "",
        f"Raw input: `{args.input}`. Measurements: {len(rows)}. Tasks: {len(task_ids)}.",
        "",
        "| Phase | Task | Runs | Passes | Pass rate | Cases passed | Median generation (s) |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['phase']} | {item['task_id']} | {item['runs']} | {item['successes']} | {item['success_rate']:.0%} | {item['tests_passed_total']}/{item['tests_total']} | {item['median_generation_seconds']:.4f} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "Compare `base_nf4` and `qlora_adapter` under identical prompts and deterministic decoding. Repeated identical outputs are retained as repeated observations but are not independent samples of model quality. A pass requires the exact function signature, allowed syntax, successful execution, and every listed test case. This synthetic arithmetic/code set is a pipeline and narrow generalization probe; it does not establish useful real-world fine-tuning gains.",
        "",
    ]
    args.report.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.csv} and {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
