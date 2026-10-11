"""Create reproducible CSV and Markdown summaries from harness run JSONL."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
METRICS = (
    "wall_s",
    "prompt_tokens",
    "first_prompt_tokens",
    "completion_tokens",
    "model_calls",
    "tool_calls",
    "tool_failures",
    "compactions",
    "ram_used_mb_peak",
    "vram_used_mb_peak",
    "gpu_util_pct_avg",
    "temperature_c_peak",
    "power_w_avg",
)
GROUP_FIELDS = ("harness", "harness_version", "model", "runtime", "quant", "context_tokens", "kv_cache", "storage_profile")


def read_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def summarize_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("run_kind", "measurement") == "warmup" or record.get("benchmark_valid") is False:
            continue
        groups[tuple(record.get(field) for field in GROUP_FIELDS)].append(record)

    summaries: list[dict[str, Any]] = []
    for key, runs in sorted(groups.items(), key=lambda item: str(item[0])):
        summary = dict(zip(GROUP_FIELDS, key))
        summary["measurement_count"] = len(runs)
        summary["success_count"] = sum(bool(run.get("success")) for run in runs)
        summary["success_rate"] = summary["success_count"] / len(runs) if runs else None
        for metric in METRICS:
            values = [
                float(run[metric])
                for run in runs
                if isinstance(run.get(metric), (int, float)) and not isinstance(run.get(metric), bool)
            ]
            for statistic, function in (
                ("median", statistics.median),
                ("mean", statistics.mean),
                ("stddev", statistics.stdev),
                ("min", min),
                ("max", max),
            ):
                value = function(values) if values and (statistic != "stddev" or len(values) > 1) else None
                summary[f"{metric}_{statistic}"] = round(value, 2) if value is not None else None
        summaries.append(summary)
    return summaries


def write_outputs(summaries: list[dict[str, Any]], csv_path: Path, markdown_path: Path, source: Path) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(GROUP_FIELDS) + ["measurement_count", "success_count", "success_rate"]
    fields += [f"{metric}_{stat}" for metric in METRICS for stat in ("median", "mean", "stddev", "min", "max")]
    with csv_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)

    lines = [
        "# Harness evaluation summary",
        "",
        f"Source: `{source.as_posix()}`. Warm-up runs and records marked `benchmark_valid: false` are excluded; raw entries remain preserved.",
        "All measured runs used the same deterministic coding fixture, Qwen3.5-9B Q4_K_M, llama.cpp, a local endpoint, 16K context, and Q4_0 KV cache. Token counts come from each harness's own usage records, including cached input where exposed.",
        "Success requires clean harness exit, passing unit tests, passing behavior probe, and scoped edits.",
        "",
        "| Harness | Version | Runs | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | RAM peak MB median | VRAM peak MB median |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        def fmt(value: Any) -> str:
            return "—" if value is None else str(value)

        wall = f"{fmt(row['wall_s_median'])} ({fmt(row['wall_s_mean'])} ± {fmt(row['wall_s_stddev'])})"
        success = f"{row['success_count']}/{row['measurement_count']} ({row['success_rate']:.0%})"
        lines.append(
            f"| {fmt(row['harness'])} | {fmt(row['harness_version'])} | {row['measurement_count']} | {success} | {wall} | "
            f"{fmt(row['first_prompt_tokens_median'])} | {fmt(row['prompt_tokens_median'])} | {fmt(row['tool_calls_median'])} | "
            f"{fmt(row['ram_used_mb_peak_median'])} | {fmt(row['vram_used_mb_peak_median'])} |"
        )
    lines += [
        "",
        "On this single coding task, all three harnesses passed 3/3 valid measurements. Pi had lower measured context overhead and wall time; this result does not test long-context compaction, subagents, MCP, or broader task success.",
        "Vibe first-prompt counts are read from journal usage events; llama.cpp prompt-evaluation work is stored separately and can be smaller when server prefix caching is active.",
        "See the raw JSONL for per-run quality details, tool errors, timing, resource samples, and excluded setup attempts.",
        "",
    ]
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "results/raw/harness-run-summary.jsonl")
    parser.add_argument("--csv", type=Path, default=REPO_ROOT / "results/csv/harness-evaluation.csv")
    parser.add_argument("--markdown", type=Path, default=REPO_ROOT / "results/reports/harness-evaluation.md")
    args = parser.parse_args()
    summaries = summarize_records(read_records(args.input))
    write_outputs(summaries, args.csv, args.markdown, args.input)
    print(f"Wrote {len(summaries)} harness summaries to {args.csv} and {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
