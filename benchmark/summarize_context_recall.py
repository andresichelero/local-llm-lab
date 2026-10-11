"""Consolidate exact-answer long-context probes across KV cache formats."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def summarize_series(runs: list[dict[str, Any]], samples: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [
        run for run in runs
        if run.get("run_kind") == "measurement"
        and run.get("success") is True
        and run.get("source_tree_dirty") is False
        and run.get("git_sha")
        and run.get("runtime_commit")
    ]
    if len(valid) < 3:
        raise ValueError(f"Need at least 3 successful clean-source measurements; found {len(valid)}")
    for field in ("kv_cache_k", "kv_cache_v", "git_sha", "runtime_commit"):
        if len({run.get(field) for run in valid}) != 1:
            raise ValueError(f"Series mixes {field}")
    row: dict[str, Any] = {
        "experiment": valid[0].get("experiment"),
        "context_tokens": valid[0].get("context_tokens"),
        "kv_cache_k": valid[0].get("kv_cache_k"),
        "kv_cache_v": valid[0].get("kv_cache_v"),
        "model": valid[0].get("model"),
        "model_revision": valid[0].get("model_revision"),
        "runtime_commit": valid[0].get("runtime_commit"),
        "git_sha": valid[0].get("git_sha"),
        "measurement_count": len(valid),
        "quality_success_count": sum(run.get("quality_pass") is True for run in valid),
        "quality_success_rate": round(sum(run.get("quality_pass") is True for run in valid) / len(valid), 4),
        "prompt_tokens": valid[0].get("prompt_tokens"),
        "tokenizer_prompt_tokens": valid[0].get("tokenizer_prompt_tokens"),
        "record_count": valid[0].get("record_count"),
    }
    for metric in ("ttft_ms", "wall_time_s"):
        values = [float(run[metric]) for run in valid if run.get(metric) is not None]
        if len(values) != len(valid):
            raise ValueError(f"Missing {metric}")
        row[f"{metric}_median"] = round(statistics.median(values), 3)
        row[f"{metric}_mean"] = round(statistics.mean(values), 3)
        row[f"{metric}_stddev"] = round(statistics.stdev(values), 3)
        row[f"{metric}_min"] = round(min(values), 3)
        row[f"{metric}_max"] = round(max(values), 3)

    nested = {"vram_used_mb": "vram_mb", "gpu_util_pct": "gpu_util_pct", "power_w": "power_w", "temperature_c": "temperature_c"}
    values_by_metric: dict[str, list[float]] = {"ram_used_mb": [], "cpu_util_pct": [], "swap_used_mb": []}
    values_by_metric.update({value: [] for value in nested.values()})
    for sample in samples:
        for key in values_by_metric:
            value = sample.get(key)
            source = next((source for source, target in nested.items() if target == key), None)
            if source:
                value = sample.get("gpu", {}).get(source)
            try:
                if value is not None:
                    values_by_metric[key].append(float(value))
            except (TypeError, ValueError):
                pass
    for key, values in values_by_metric.items():
        if values:
            row[f"{key}_peak"] = round(max(values), 2)
            row[f"{key}_mean"] = round(statistics.mean(values), 2)
    return row


def generate(input_dir: Path, csv_path: Path, markdown_path: Path) -> list[dict[str, Any]]:
    files = sorted(
        path for path in input_dir.glob("qwen35-ssd-recall-*.jsonl")
        if not path.name.endswith("-resources.jsonl")
    )
    rows = []
    for path in files:
        resource_path = path.with_name(f"{path.stem}-resources.jsonl")
        samples = read_jsonl(resource_path) if resource_path.is_file() else []
        try:
            rows.append(summarize_series(read_jsonl(path), samples))
        except ValueError as error:
            raise ValueError(f"{path.name}: {error}") from error
    if not rows:
        raise ValueError(f"No recall series found in {input_dir}")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with csv_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# SSD long-context exact-recall probe",
        "",
        "Each series uses the same invented maintenance code, placed once at the midpoint of a deterministic report. Context and prompt token counts are recorded per series in the CSV and table. Each run has one warm-up and three measured repetitions per KV format, temperature 0, seed 1234, with prompt caching disabled.",
        "",
        "| Context | Prompt tokens | KV K/V | Exact matches | TTFT median ms | Wall median s | Sampler VRAM peak MiB | RAM peak MiB | GPU utilization mean % |",
        "|---:|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['context_tokens']} | {row.get('prompt_tokens', 'n/a')} | {row['kv_cache_k']}/{row['kv_cache_v']} | {row['quality_success_count']}/{row['measurement_count']} | "
            f"{row['ttft_ms_median']:.2f} | {row['wall_time_s_median']:.3f} | "
            f"{row.get('vram_mb_peak', 'n/a')} | {row.get('ram_used_mb_peak', 'n/a')} | {row.get('gpu_util_pct_mean', 'n/a')} |"
        )
    lines.extend([
        "",
        "This deterministic synthetic probe checks one fact placed at the midpoint. Exact matches do not establish general long-context recall or quantization quality. Resource samples are one-second system-wide observations and include server startup and idle intervals.",
        "",
        f"Raw JSONL and resource samples are under `results/raw/`; consolidated data is in `results/csv/{csv_path.name}`. Model revision `{rows[0]['model_revision']}`, runtime commit `{rows[0]['runtime_commit']}`. Source revisions represented: {', '.join(f'`{sha}`' for sha in sorted({row['git_sha'] for row in rows}))}.",
        "All active benchmark I/O was on the C:-hosted WSL ext4 SSD; E: stores historical archives only. No HDD benchmark was run. The 64K recall logs and resource files are archived at `E:\\LocalLLMLabArchive\\2026-10-11\\qwen35-ssd-context-recall-64k-20261011\\results.tar.gz` with a SHA-256 sidecar.",
        "",
    ])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "results/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "results/csv/context-recall.csv")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "results/reports/context-recall.md")
    args = parser.parse_args()
    rows = generate(args.input_dir, args.output, args.markdown_output)
    print(f"Wrote {len(rows)} series to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
