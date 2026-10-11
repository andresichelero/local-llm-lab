"""Consolidate pinned Qwen3.5-4B SSD throughput, memory and recall results."""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "Qwen3.5-4B-Q4_K_M"
METRICS = ("prompt_tokens", "ttft_ms", "prompt_tps", "generation_tps", "wall_time_s")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def generate(input_dir: Path, output: Path) -> list[dict[str, Any]]:
    runs: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    samples: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    recall: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)

    for path in input_dir.glob("qwen35-4b-*.jsonl"):
        if "-resources" in path.name:
            continue
        records = read_jsonl(path)
        for record in records:
            if record.get("model") != MODEL_ID or record.get("storage_profile", record.get("model_storage_profile")) != "ssd-wsl-ext4-c":
                continue
            key = (int(record["context_tokens"]), str(record["kv_cache_k"]))
            if record.get("run_kind") == "measurement":
                recall[key].append(record)
            elif record.get("run_kind") is None and "repetition" in record:
                runs[key].append(record)
                resource_path = path.with_name(f"{path.stem}-resources.jsonl")
                samples[key].extend(read_jsonl(resource_path))

    rows: list[dict[str, Any]] = []
    for key in sorted(runs):
        context, kv_type = key
        measurements = [row for row in runs[key] if row.get("success") is True and row.get("source_tree_dirty") is False]
        if len(measurements) < 3:
            raise ValueError(f"{context}/{kv_type}: expected at least 3 clean successful throughput runs")
        revisions = {(row.get("git_sha"), row.get("runtime_commit"), row.get("model_revision")) for row in measurements}
        if len(revisions) != 1:
            raise ValueError(f"{context}/{kv_type}: mixed source, runtime, or model revisions")
        row: dict[str, Any] = {
            "model": MODEL_ID,
            "context_tokens": context,
            "kv_cache_k_v": kv_type,
            "prompt_tokens_median": round(statistics.median(float(r["prompt_tokens"]) for r in measurements), 3),
            "measurement_count": len(measurements),
            "success_count": len(measurements),
            "recall_matches": sum(r.get("quality_pass") is True for r in recall[key]),
            "recall_measurements": len(recall[key]),
            "sampler_vram_peak_mb": "",
            "git_sha": next(iter(revisions))[0],
            "runtime_commit": next(iter(revisions))[1],
            "model_revision": next(iter(revisions))[2],
        }
        for metric in METRICS[1:]:
            row[f"{metric}_median"] = round(statistics.median(float(r[metric]) for r in measurements), 3)
        vram = []
        for sample in samples[key]:
            try:
                vram.append(float(sample["gpu"]["vram_used_mb"]))
            except (KeyError, TypeError, ValueError):
                continue
        if vram:
            row["sampler_vram_peak_mb"] = round(max(vram), 2)
        rows.append(row)

    if not rows:
        raise ValueError(f"No valid {MODEL_ID} SSD throughput data found in {input_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "results/raw")
    parser.add_argument("--output", type=Path, default=ROOT / "results/csv/qwen35-4b-ssd-context-kv.csv")
    args = parser.parse_args()
    rows = generate(args.input_dir, args.output)
    print(f"Wrote {len(rows)} model/context/KV rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
