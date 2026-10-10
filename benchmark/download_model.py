#!/usr/bin/env python3
"""Download one pinned public GGUF with size checks and SHA-256 verification."""
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
    "repo": "ibm-granite/granite-4.1-3b-GGUF",
    "revision": "ab4701481089b58a082ef63cc1cee738887293ff",
    "filename": "granite-4.1-3b-Q4_K_M.gguf",
    "size_bytes": 2099501664,
    "sha256": "662b0626cd58f443baea23559b469df6576a81d349649c59413b36a9fb32eb29",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(destination: Path, dry_run: bool) -> None:
    expected = MODEL["size_bytes"]
    target = destination / MODEL["filename"]
    part = target.with_suffix(target.suffix + ".part")
    destination.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(destination).free
    existing = part.stat().st_size if part.exists() else 0
    if target.exists():
        if target.stat().st_size == expected and sha256(target) == MODEL["sha256"]:
            print(f"Already verified: {target}")
            return
        raise RuntimeError(f"Refusing to overwrite an existing unverified file: {target}")
    needed = max(0, expected - existing)
    print(json.dumps({**MODEL, "destination": str(target), "free_bytes": free, "partial_bytes": existing, "additional_bytes_needed": needed}, sort_keys=True))
    if free < needed + 256 * 1024 * 1024:
        raise RuntimeError("Insufficient free space (requires file size plus a 256 MiB safety margin).")
    if dry_run:
        return
    url = f"https://huggingface.co/{MODEL['repo']}/resolve/{MODEL['revision']}/{MODEL['filename']}?download=true"
    offset = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "local-llm-lab/0.1"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if offset and response.status != 206:
                raise RuntimeError("Server did not honor resume request; partial file was preserved.")
            mode = "ab" if offset else "wb"
            written = offset
            started = time.monotonic()
            last_report = started
            with part.open(mode) as out:
                while True:
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    written += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= 10:
                        rate = (written - offset) / max(now - started, 0.1) / 1024 / 1024
                        print(f"downloaded={written}/{expected} bytes rate={rate:.1f} MiB/s", flush=True)
                        last_report = now
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Download failed; resumable part remains at {part}: {exc}") from exc
    actual_size = part.stat().st_size
    if actual_size != expected:
        raise RuntimeError(f"Size mismatch: expected {expected}, received {actual_size}; part preserved.")
    actual_hash = sha256(part)
    if actual_hash != MODEL["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch: expected {MODEL['sha256']}, received {actual_hash}; part preserved.")
    part.replace(target)
    print(f"Verified and saved: {target}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=Path(os.environ.get("MODEL_DIR", "/mnt/e/local-llm-models")))
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

