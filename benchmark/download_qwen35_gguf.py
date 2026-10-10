#!/usr/bin/env python3
"""Download a pinned Qwen3.5 GGUF and verify its upstream size and SHA-256."""
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
from pathlib import Path

MODEL = {
    "repo": "unsloth/Qwen3.5-9B-GGUF",
    "revision": "3885219b6810b007914f3a7950a8d1b469d598a5",
    "filename": "Qwen3.5-9B-Q4_K_M.gguf",
    "size_bytes": 5680522464,
    "sha256": "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8",
    "license": "apache-2.0",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_success(record_path: Path, target: Path) -> None:
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "model": MODEL, "destination": str(target), "verified": True}
    with record_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, sort_keys=True) + "\n")


def download(model_dir: Path, record_path: Path, dry_run: bool) -> None:
    directory = model_dir / "Qwen3.5-9B-GGUF"
    target = directory / MODEL["filename"]
    part = target.with_suffix(target.suffix + ".part")
    directory.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.stat().st_size == MODEL["size_bytes"] and sha256(target) == MODEL["sha256"]:
            print(f"Already verified: {target}")
            if not dry_run:
                record_success(record_path, target)
            return
        raise RuntimeError(f"Refusing to overwrite an existing unverified file: {target}")
    free = shutil.disk_usage(directory).free
    offset = part.stat().st_size if part.exists() else 0
    needed = max(0, MODEL["size_bytes"] - offset)
    print(json.dumps({**MODEL, "destination": str(target), "free_bytes": free,
                      "partial_bytes": offset, "additional_bytes_needed": needed}, sort_keys=True))
    if free < needed + 512 * 1024 * 1024:
        raise RuntimeError("Insufficient free space (requires remaining file size plus 512 MiB).")
    if dry_run:
        return
    url = f"https://huggingface.co/{MODEL['repo']}/resolve/{MODEL['revision']}/{MODEL['filename']}?download=true"
    headers = {"User-Agent": "local-llm-lab/0.1"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            if offset and response.status != 206:
                raise RuntimeError("Server did not honor resume request; partial file preserved.")
            started = time.monotonic()
            last_report = started
            written = offset
            with part.open("ab" if offset else "wb") as output:
                while chunk := response.read(8 * 1024 * 1024):
                    output.write(chunk)
                    written += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= 10:
                        rate = (written - offset) / max(now - started, 0.1) / 1024 / 1024
                        print(f"downloaded={written}/{MODEL['size_bytes']} bytes rate={rate:.1f} MiB/s", flush=True)
                        last_report = now
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Download failed; resumable partial remains at {part}: {exc}") from exc
    actual_size = part.stat().st_size
    if actual_size != MODEL["size_bytes"]:
        raise RuntimeError(f"Size mismatch: expected {MODEL['size_bytes']}, received {actual_size}; partial preserved.")
    actual_hash = sha256(part)
    if actual_hash != MODEL["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch: expected {MODEL['sha256']}, received {actual_hash}; partial preserved.")
    part.replace(target)
    print(f"Verified and saved: {target}")
    record_success(record_path, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=Path(os.environ.get("MODEL_DIR", "/mnt/e/local-llm-models")))
    parser.add_argument("--record", type=Path, default=Path(__file__).resolve().parents[1] / "results/raw/model-downloads.jsonl")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        download(args.model_dir.expanduser(), args.record.expanduser(), args.dry_run)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
