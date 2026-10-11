#!/usr/bin/env python3
"""Download one pinned public EXL3 snapshot after a disk-space preflight."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

MODEL = {
    "repo": "turboderp/Qwen3.5-9B-exl3",
    "revision": "d35e580c801b276c4d5ff97f27bd0fa79a0ef3b3",
    "quant": "2.50bpw",
    "weights_bytes": 5_889_564_052,
    "weights_sha256": "19e38d592d439a19205469aba6f477355aaa17d81f1f516b222a2abc7ba76d23",
    "license": "Apache-2.0",
}
BENCH_STORAGE_ROOT = Path(os.environ.get("BENCH_STORAGE_ROOT", Path.home() / "local-llm-benchmark"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(model_dir: Path, dry_run: bool) -> None:
    target = model_dir / "Qwen3.5-9B-exl3-2.5bpw"
    weights = target / "model.safetensors"
    free = shutil.disk_usage(model_dir if model_dir.exists() else model_dir.parent).free
    required = MODEL["weights_bytes"] + 512 * 1024 * 1024
    print(json.dumps({**MODEL, "target": str(target), "free_bytes": free, "minimum_bytes": required}, sort_keys=True))
    if free < required:
        raise RuntimeError("Insufficient free space; requires model size plus a 512 MiB safety margin.")
    if weights.exists():
        actual = sha256(weights)
        if weights.stat().st_size == MODEL["weights_bytes"] and actual == MODEL["weights_sha256"]:
            print(f"Already verified: {weights}")
            return
        raise RuntimeError(f"Refusing to overwrite existing unverified weights: {weights} (sha256={actual})")
    if dry_run:
        return

    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(os.environ.get("HF_HOME", BENCH_STORAGE_ROOT / "cache/huggingface"))
    snapshot_download(
        repo_id=MODEL["repo"],
        revision=MODEL["revision"],
        local_dir=str(target),
        cache_dir=str(cache_dir),
    )
    actual_size = weights.stat().st_size
    actual_hash = sha256(weights)
    if actual_size != MODEL["weights_bytes"] or actual_hash != MODEL["weights_sha256"]:
        raise RuntimeError(
            f"Weight verification failed: size={actual_size}, sha256={actual_hash}; files preserved for diagnosis."
        )
    record = {
        **MODEL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "path": str(weights),
        "verified": True,
    }
    results = Path(os.environ.get("MODEL_DOWNLOAD_LOG", BENCH_STORAGE_ROOT / "results/raw/model-downloads.jsonl"))
    results.parent.mkdir(parents=True, exist_ok=True)
    with results.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"Downloaded and verified: {weights}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=Path(os.environ.get("MODEL_DIR", BENCH_STORAGE_ROOT / "models/exllama")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.model_dir.mkdir(parents=True, exist_ok=True)
    try:
        download(args.model_dir.expanduser(), args.dry_run)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
