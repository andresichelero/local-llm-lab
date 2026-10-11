"""Consolidate successful, clean-source Qwen3.5 SSD context/KV runs."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MEASURE_METRICS = ("prompt_tokens", "prompt_tps", "generation_tps", "ttft_ms", "wall_time_s")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def summarize_series(measurements: list[dict[str, Any]], samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a complete >=3-run series and its external sampler rows."""
    valid = [
        run for run in measurements
        if run.get("success") is True
        and run.get("source_tree_dirty") is False
        and bool(run.get("git_sha"))
        and bool(run.get("runtime_commit"))
    ]
    if len(valid) < 3:
        raise ValueError(f"Need at least 3 successful clean-source measurements; found {len(valid)}")
    contexts = {run.get("context_tokens") for run in valid}
    kv_pairs = {(run.get("kv_cache_k"), run.get("kv_cache_v")) for run in valid}
    git_shas = {run.get("git_sha") for run in valid}
    if len(contexts) != 1 or len(kv_pairs) != 1 or len(git_shas) != 1:
        raise ValueError("Series mixes context, KV format, or source revisions")

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
        "success_count": len(valid),
    }
    for metric in MEASURE_METRICS:
        values = [float(run[metric]) for run in valid if run.get(metric) is not None]
        if len(values) != len(valid):
            raise ValueError(f"Missing {metric} in one or more valid measurements")
        row[f"{metric}_median"] = round(statistics.median(values), 3)
        row[f"{metric}_mean"] = round(statistics.mean(values), 3)
        row[f"{metric}_stddev"] = round(statistics.stdev(values), 3) if len(values) > 1 else 0
        row[f"{metric}_min"] = round(min(values), 3)
        row[f"{metric}_max"] = round(max(values), 3)

    gpu_key_map = {
        "vram_used_mb": "sampler_vram_mb",
        "gpu_util_pct": "sampler_gpu_util_pct",
        "temperature_c": "sampler_temperature_c",
        "power_w": "sampler_power_w",
    }
    sample_values: dict[str, list[float]] = {value: [] for value in gpu_key_map.values()}
    sample_values.update({"cpu_util_pct": [], "ram_used_mb": [], "swap_used_mb": []})
    for sample in samples:
        for key in sample_values:
            value = sample.get(key)
            source_key = next((k for k, v in gpu_key_map.items() if v == key), None)
            if source_key:
                value = sample.get("gpu", {}).get(source_key)
            try:
                if value is not None:
                    sample_values[key].append(float(value))
            except (TypeError, ValueError):
                continue
    for key, values in sample_values.items():
        if not values:
            continue
        row[f"{key}_peak"] = round(max(values), 2)
        row[f"{key}_mean"] = round(statistics.mean(values), 2)
    return row


def generate(input_dir: Path, csv_path: Path, markdown_path: Path | None = None) -> list[dict[str, Any]]:
    raw_files = sorted(
        path for path in input_dir.glob("qwen35-ssd-*.jsonl")
        if path.name.startswith(("qwen35-ssd-context-", "qwen35-ssd-kv-"))
        and not path.name.endswith("-resources.jsonl")
    )
    summaries = []
    for raw_path in raw_files:
        records = read_jsonl(raw_path)
        resource_path = raw_path.with_name(f"{raw_path.stem}-resources.jsonl")
        samples = read_jsonl(resource_path) if resource_path.is_file() else []
        try:
            summaries.append(summarize_series(records, samples))
        except ValueError as error:
            raise ValueError(f"{raw_path.name}: {error}") from error
    if not summaries:
        raise ValueError(f"No qwen35-ssd measurement files found in {input_dir}")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in summaries for key in row))
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# SSD context and KV-cache measurements",
            "",
            "Generated from successful, clean-source Qwen3.5-9B Q4_K_M runs. Each row has one warm-up plus three measured repetitions; prompt caching was off, Flash Attention on, all 99 layers on the RTX 3070, temperature 0, seed 1234, and generation capped at 64 tokens. Active model, runtime, logs, and raw measurements were stored on the C:-hosted WSL ext4 SSD.",
            "",
            "These are throughput and memory measurements, not a quality comparison. The prompts are deterministic generated text, not a semantic long-context recall test. Sampler peak/mean fields come from one-second external samples and include idle intervals around each server process.",
            "",
            "| Series | Context | KV K/V | Prompt tokens | Prefill tok/s median (mean ± sd) | Generation tok/s median (mean ± sd) | TTFT ms median | Wall s median | Sampler VRAM peak MiB | Sampler GPU util mean % | Power mean W | RAM peak MiB | Success |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in summaries:
            lines.append(
                f"| `{row['experiment']}` | {row['context_tokens']} | {row['kv_cache_k']}/{row['kv_cache_v']} | {row['prompt_tokens_median']:.0f} | "
                f"{row['prompt_tps_median']:.1f} ({row['prompt_tps_mean']:.1f} ± {row['prompt_tps_stddev']:.1f}) | "
                f"{row['generation_tps_median']:.2f} ({row['generation_tps_mean']:.2f} ± {row['generation_tps_stddev']:.2f}) | "
                f"{row['ttft_ms_median']:.0f} | {row['wall_time_s_median']:.2f} | "
                f"{row.get('sampler_vram_mb_peak', 'n/a')} | {row.get('sampler_gpu_util_pct_mean', 'n/a')} | "
                f"{row.get('sampler_power_w_mean', 'n/a')} | {row.get('ram_used_mb_peak', 'n/a')} | {row['success_count']}/{row['measurement_count']} |"
            )
        source_revisions = ", ".join(f"`{sha}`" for sha in sorted({row["git_sha"] for row in summaries}))
        lines.extend([
            "",
            "Interpretation: compare KV formats only when context and prompt sizes match. The 64K rows are capacity/throughput observations; they do not establish semantic long-context recall. Any earlier HDD-backed values remain historical context; no HDD benchmark was run for this report. All active benchmark I/O for these rows was on the C:-hosted WSL ext4 SSD; E: is archival storage only. Raw runs are archived at `E:\\LocalLLMLabArchive\\2026-10-11\\qwen35-ssd-context-extreme-20261011\\results.tar.gz` and `E:\\LocalLLMLabArchive\\2026-10-11\\qwen35-ssd-context-q8-64k-20261011\\results.tar.gz`, each with a SHA-256 sidecar.",
            "",
            f"Raw JSONL and one-second sampler files are in `results/raw/`; the consolidated CSV is `results/csv/{csv_path.name}`. Source revisions represented: {source_revisions}. llama.cpp `{summaries[0]['runtime_commit']}`, model revision `{summaries[0]['model_revision']}`.",
            "",
        ])
        markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "results/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "results/csv/ssd-context-kv.csv")
    parser.add_argument("--markdown-output", type=Path, default=ROOT / "results/reports/ssd-context-kv.md")
    args = parser.parse_args()
    rows = generate(args.input_dir, args.output, args.markdown_output)
    print(f"Wrote {len(rows)} series to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
