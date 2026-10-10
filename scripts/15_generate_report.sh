#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - "$ROOT" <<'PY'
import csv, json, statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

root = Path(sys.argv[1])
source_dir = root / "results/raw"
target = root / "results/reports/tier0-summary.md"
all_rows = []
for source in sorted(source_dir.glob("*.jsonl")) if source_dir.exists() else []:
    if source.name.endswith("-resources.jsonl"):
        continue
    resource_path = source.with_name(source.stem + "-resources.jsonl")
    monitor_rows = []
    if resource_path.exists():
        for line in resource_path.read_text(encoding="utf-8").splitlines():
            try:
                sample = json.loads(line)
                if isinstance(sample, dict): monitor_rows.append(sample)
            except json.JSONDecodeError:
                continue
    for line in source.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict) and "ttft_ms" in item:
                try:
                    ended = datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00"))
                    started = ended - timedelta(seconds=float(item.get("wall_time_s", 0)))
                    item["_monitor_rows"] = [
                        sample for sample in monitor_rows
                        if started - timedelta(seconds=1) <= datetime.fromisoformat(sample["timestamp"].replace("Z", "+00:00")) <= ended + timedelta(seconds=1)
                    ]
                except (KeyError, TypeError, ValueError):
                    item["_monitor_rows"] = monitor_rows
                all_rows.append(item)
        except json.JSONDecodeError:
            continue
rows = [row for row in all_rows if row.get("source_tree_dirty") is False]
if not rows:
    target.write_text("# Tier 0 summary\n\nNo completed benchmark records yet.\n", encoding="utf-8")
    print(target)
    raise SystemExit(0)
group_keys = ("experiment", "model", "quant", "runtime", "git_sha", "source_tree_dirty", "runtime_commit", "context_tokens", "kv_cache_k", "kv_cache_v", "flash_attention")
groups = {}
for row in all_rows:
    key = tuple(row.get(field, "") for field in group_keys)
    groups.setdefault(key, []).append(row)
csv_path = root / "results/csv/summary.csv"
csv_path.parent.mkdir(parents=True, exist_ok=True)
metric_names = ("ttft_ms", "prompt_tps", "generation_tps", "wall_time_s")
fieldnames = list(group_keys) + [f"{metric}_{stat}" for metric in metric_names for stat in ("mean", "median", "stddev", "min", "max", "p95")] + ["gpu_vram_max_sampled_mb", "power_avg_sampled_w", "gpu_vram_peak_process_mb", "runs"]
clean_groups = {}
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
        samples = [sample for item in values for sample in item.get("_monitor_rows", [])]
        vram = [int(sample["gpu"]["vram_used_mb"]) for sample in samples if str(sample.get("gpu", {}).get("vram_used_mb", "")).isdigit()]
        power = [float(sample["gpu"]["power_w"]) for sample in samples if str(sample.get("gpu", {}).get("power_w", "")).replace(".", "", 1).isdigit()]
        process_vram = [int(item["vram_peak_process_mb"]) for item in values if isinstance(item.get("vram_peak_process_mb"), (int, float))]
        row["gpu_vram_max_sampled_mb"] = max(vram) if vram else ""
        row["power_avg_sampled_w"] = statistics.mean(power) if power else ""
        row["gpu_vram_peak_process_mb"] = max(process_vram) if process_vram else ""
        row["runs"] = len(values)
        writer.writerow(row)
        if values[0].get("source_tree_dirty") is False:
            clean_groups[key] = values
lines = [
    "# Tier 0 summary",
    "",
    f"Clean-source measured runs: {len(rows)} across {len(clean_groups)} configurations.",
    f"Preliminary or dirty-source runs excluded from the table: {len(all_rows) - len(rows)} (all records remain separated by experiment and commit in the CSV).",
    "",
    "| Experiment | Context | KV K/V | Runs | TTFT median (ms) | Prompt median (tok/s) | Generation median (tok/s) | Max sampled VRAM (MiB) |",
    "|---|---:|---|---:|---:|---:|---:|---:|",
]
for key, values in sorted(clean_groups.items(), key=lambda item: str(item[0])):
    experiment = values[0].get("experiment", "")
    context = values[0].get("context_tokens", "")
    kv = f"{values[0].get('kv_cache_k', '')}/{values[0].get('kv_cache_v', '')}"
    def median(metric):
        numbers = [float(item[metric]) for item in values if isinstance(item.get(metric), (int, float))]
        return f"{statistics.median(numbers):.2f}" if numbers else "—"
    samples = [sample for item in values for sample in item.get("_monitor_rows", [])]
    vram = [int(sample["gpu"]["vram_used_mb"]) for sample in samples if str(sample.get("gpu", {}).get("vram_used_mb", "")).isdigit()]
    lines.append(f"| {experiment} | {context} | {kv} | {len(values)} | {median('ttft_ms')} | {median('prompt_tps')} | {median('generation_tps')} | {max(vram) if vram else '—'} |")
text = [
    *lines,
    "",
    f"Per-run means, standard deviations, ranges and approximate p95 values: `{csv_path.relative_to(root)}`.",
    "VRAM values in the table are peaks from the paired low-frequency system/GPU time-series samples. The CSV also records the Torch allocator's per-process peak separately where available.",
    "The short prompt does not validate reasoning, tool use or quality under long-context load.",
    "",
]
target.write_text("\n".join(text), encoding="utf-8")
print(target)
PY
