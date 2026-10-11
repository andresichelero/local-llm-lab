#!/usr/bin/env python3
"""Download the pinned official Qwen2.5-Coder-14B Q4_K_M GGUF with resume and SHA checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MODEL = {
    "repo": "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
    "revision": "d0a692ef765eefbf2fabb130b3cb2e8917e3d225",
    "filename": "qwen2.5-coder-14b-instruct-q4_k_m.gguf",
    "size_bytes": 8_988_110_272,
    "sha256": "c1e659736d89ac1065fb495330fb824d94001974a4bfa78e7270e43476a8d940",
    "quant": "Q4_K_M",
    "parameters": "14B",
    "license": "Apache-2.0",
}
BENCH_STORAGE_ROOT = Path(os.environ.get("BENCH_STORAGE_ROOT", Path.home() / "local-llm-benchmark"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(destination: Path, dry_run: bool) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / MODEL["filename"]
    part = target.with_suffix(target.suffix + ".part")
    if target.exists():
        actual = sha256(target) if target.stat().st_size == MODEL["size_bytes"] else "size-mismatch"
        if actual == MODEL["sha256"]:
            print(f"Already verified: {target}")
            return
        raise RuntimeError(f"Refusing to overwrite unverified existing file: {target} (sha256={actual})")

    partial_bytes = part.stat().st_size if part.exists() else 0
    if partial_bytes >= MODEL["size_bytes"]:
        raise RuntimeError(f"Partial file is not smaller than the expected model; inspect it: {part}")
    free = shutil.disk_usage(destination).free
    additional = MODEL["size_bytes"] - partial_bytes
    required = additional + 512 * 1024 * 1024
    print(json.dumps({**MODEL, "destination": str(target), "free_bytes": free,
                      "partial_bytes": partial_bytes, "additional_bytes_needed": additional,
                      "minimum_free_bytes": required}, sort_keys=True))
    if free < required:
        raise RuntimeError("Insufficient C: SSD space; requires remaining file size plus a 512 MiB margin.")
    if dry_run:
        return

    url = f"https://huggingface.co/{MODEL['repo']}/resolve/{MODEL['revision']}/{MODEL['filename']}?download=true"
    headers = {"User-Agent": "local-llm-lab/0.1"}
    if partial_bytes:
        headers["Range"] = f"bytes={partial_bytes}-"
    request = urllib.request.Request(url, headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if partial_bytes and response.status != 206:
                raise RuntimeError("Hugging Face did not honor the resume request; partial file was preserved.")
            written = partial_bytes
            last_report = started
            with part.open("ab" if partial_bytes else "wb") as output:
                while True:
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    written += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= 10:
                        rate = (written - partial_bytes) / max(now - started, 0.1) / 1024 / 1024
                        print(f"downloaded={written}/{MODEL['size_bytes']} bytes rate={rate:.1f} MiB/s", flush=True)
                        last_report = now
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Download failed; resumable part remains at {part}: {exc}") from exc

    actual_size = part.stat().st_size
    if actual_size != MODEL["size_bytes"]:
        raise RuntimeError(f"Size mismatch: expected {MODEL['size_bytes']}, received {actual_size}; part preserved.")
    actual_sha = sha256(part)
    if actual_sha != MODEL["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch: expected {MODEL['sha256']}, received {actual_sha}; part preserved.")
    part.replace(target)
    record = {**MODEL, "timestamp": datetime.now(timezone.utc).isoformat(), "path": str(target), "verified": True}
    log = Path(os.environ.get("MODEL_DOWNLOAD_LOG", BENCH_STORAGE_ROOT / "results/raw/model-downloads-hybrid.jsonl"))
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"Downloaded and verified: {target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path,
                        default=Path(os.environ.get("MODEL_DIR", BENCH_STORAGE_ROOT / "models/hybrid")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        download(args.model_dir.expanduser(), args.dry_run)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
