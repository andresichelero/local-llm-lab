#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import csv, json, statistics
import sys
from pathlib import Path

root = Path(sys.argv[1])
source_dir = root / "results/raw"
target = root / "results/reports/tier0-summary.md"
all_rows = []
for source in sorted(source_dir.glob("*.jsonl")) if source_dir.exists() else []:
    if source.name.endswith("-resources.jsonl"):
        continue
    for line in source.read_text(encoding="utf-8").splitlines():
        try:
            all_rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
rows = [row for row in all_rows if row.get("source_tree_dirty") is False]
if not rows:
    target.write_text("# Tier 0 summary\n\nNo completed benchmark records yet.\n", encoding="utf-8")
    print(target)
    raise SystemExit(0)
def stats(key):
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return {"mean": "", "median": "", "stddev": "", "min": "", "max": "", "p95": ""}
    return {
        "mean": f"{statistics.mean(values):.3f}",
        "median": f"{statistics.median(values):.3f}",
        "stddev": f"{statistics.stdev(values):.3f}" if len(values) > 1 else "0.000",
        "min": f"{min(values):.3f}",
        "max": f"{max(values):.3f}",
        "p95": f"{sorted(values)[min(len(values)-1, int(0.95 * (len(values)-1)))]:.3f}",
    }
group_keys = ("experiment", "model", "quant", "runtime", "git_sha", "source_tree_dirty", "runtime_commit", "context_tokens", "kv_cache_k", "kv_cache_v", "flash_attention")
groups = {}
for row in all_rows:
    key = tuple(row.get(field, "") for field in group_keys)
    groups.setdefault(key, []).append(row)
csv_path = root / "results/csv/summary.csv"
csv_path.parent.mkdir(parents=True, exist_ok=True)
metric_names = ("ttft_ms", "prompt_tps", "generation_tps", "wall_time_s")
fieldnames = list(group_keys) + [f"{metric}_{stat}" for metric in metric_names for stat in ("mean", "median", "stddev", "min", "max", "p95")] + ["runs"]
with csv_path.open("w", newline="", encoding="utf-8") as output:
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for key, values in sorted(groups.items(), key=lambda item: str(item[0])):
        row = dict(zip(group_keys, key))
        for metric in metric_names:
            numbers = [float(item[metric]) for item in values if isinstance(item.get(metric), (int, float))]
            calculated = {
                "mean": statistics.mean(numbers) if numbers else "",
                "median": statistics.median(numbers) if numbers else "",
                "stddev": statistics.stdev(numbers) if len(numbers) > 1 else (0 if numbers else ""),
                "min": min(numbers) if numbers else "",
                "max": max(numbers) if numbers else "",
                "p95": sorted(numbers)[min(len(numbers)-1, int(0.95 * (len(numbers)-1)))] if numbers else "",
            }
            for name, value in calculated.items(): row[f"{metric}_{name}"] = value
        row["runs"] = len(values)
        writer.writerow(row)
def report_stats(key):
    summary = stats(key)
    return ", ".join(f"{name} {value}" for name, value in summary.items() if value)
text = [
    "# Tier 0 summary",
    "",
    f"Successful measured runs: {len(rows)}",
    f"Model: {rows[0].get('model')} ({rows[0].get('quant')})",
    f"Runtime: {rows[0].get('runtime')}",
    f"Preliminary or dirty-source runs excluded from this summary: {len(all_rows) - len(rows)} (retained and separated in CSV by experiment and commit)",
    f"TTFT ms: {report_stats('ttft_ms')}",
    f"Prompt tokens/s: {report_stats('prompt_tps')}",
    f"Generation tokens/s: {report_stats('generation_tps')}",
    f"Wall seconds: {report_stats('wall_time_s')}",
    f"Consolidated CSV: `{csv_path.relative_to(root)}`",
    "",
    "These results measure throughput and latency only; they do not establish model quality.",
    "",
]
target.write_text("\n".join(text), encoding="utf-8")
print(target)
PY
