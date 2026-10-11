#!/usr/bin/env python3
"""Download one revision-pinned QLoRA smoke model outside the Git checkout."""
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

ROOT = Path(__file__).resolve().parents[1]
REPO = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
REVISION = "ea3f2471cf1b1f0db85067f1ef93848e38e88c25"
FILES = (
    {"path": "LICENSE", "size": 11343, "blob_sha1": "6634c8cc3133b3848ec74b9f275acaaa1ea618ab"},
    {"path": "config.json", "size": 659, "blob_sha1": "e2aa18293b0dd66539341467fa454878a5adb2be"},
    {"path": "generation_config.json", "size": 243, "blob_sha1": "c28f9c697cbc09f047434efec57556505af31111"},
    {"path": "merges.txt", "size": 1671839, "blob_sha1": "20024bfe7c83998e9aeaf98a0cd6a2ce6306c2f0"},
    {
        "path": "model.safetensors",
        "size": 988097824,
        "sha256": "f9523886352217ded3aeeef552b381af79d568c6d49a4b9e423288cea56b0a44",
    },
    {"path": "tokenizer.json", "size": 7031645, "blob_sha1": "443909a61d429dff23010e5bddd28ff530edda00"},
    {"path": "tokenizer_config.json", "size": 7305, "blob_sha1": "acee076f49bf3c0298e15de0909d1da7b392f0c3"},
    {"path": "vocab.json", "size": 2776833, "blob_sha1": "4783fe10ac3adce15ac8f358ef5462739852c569"},
)
SAFETY_BYTES = 256 * 1024 * 1024


def file_hashes(path: Path, *, sha1: bool = False, sha256: bool = False) -> dict[str, str]:
    digest1 = hashlib.sha1() if sha1 else None
    digest256 = hashlib.sha256() if sha256 else None
    prefix = f"blob {path.stat().st_size}\0".encode() if digest1 else b""
    if digest1:
        digest1.update(prefix)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            if digest1:
                digest1.update(chunk)
            if digest256:
                digest256.update(chunk)
    return {
        **({"blob_sha1": digest1.hexdigest()} if digest1 else {}),
        **({"sha256": digest256.hexdigest()} if digest256 else {}),
    }


def valid_file(path: Path, spec: dict[str, object]) -> bool:
    if not path.is_file() or path.stat().st_size != spec["size"]:
        return False
    actual = file_hashes(path, sha1="blob_sha1" in spec, sha256="sha256" in spec)
    return all(actual[key] == spec[key] for key in actual)


def existing_mount(path: Path) -> Path:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def download_file(destination: Path, spec: dict[str, object]) -> dict[str, object]:
    target = destination / str(spec["path"])
    part = target.with_name(target.name + ".part")
    if target.exists():
        if valid_file(target, spec):
            return {"path": str(spec["path"]), "bytes": target.stat().st_size, **file_hashes(target, sha1="blob_sha1" in spec, sha256="sha256" in spec)}
        raise RuntimeError(f"Refusing to overwrite an existing unverified file: {target}")

    expected = int(spec["size"])
    offset = part.stat().st_size if part.exists() else 0
    if offset > expected:
        raise RuntimeError(f"Partial file is larger than expected; preserved: {part}")
    url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{spec['path']}?download=true"
    headers = {"User-Agent": "local-llm-lab/0.1"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if offset and response.status != 206:
                raise RuntimeError(f"Server did not resume {part}; partial file was preserved.")
            mode = "ab" if offset else "wb"
            started = time.monotonic()
            last_report = started
            received = offset
            with part.open(mode) as output:
                while True:
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    received += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= 10:
                        print(f"{spec['path']}: {received}/{expected} bytes", flush=True)
                        last_report = now
                output.flush()
                os.fsync(output.fileno())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Download failed; resumable partial remains at {part}: {exc}") from exc

    if part.stat().st_size != expected:
        raise RuntimeError(f"Size mismatch for {part}: expected {expected}, received {part.stat().st_size}; partial preserved.")
    actual = file_hashes(part, sha1="blob_sha1" in spec, sha256="sha256" in spec)
    for key, expected_hash in spec.items():
        if key in actual and actual[key] != expected_hash:
            raise RuntimeError(f"{key} mismatch for {part}; partial preserved.")
    part.replace(target)
    print(f"verified {target}", flush=True)
    return {"path": str(spec["path"]), "bytes": expected, **actual}


def download(model_dir: Path, dry_run: bool) -> None:
    destination = model_dir / "Qwen2.5-Coder-0.5B-Instruct"
    manifest = destination / "download-manifest.json"
    free = shutil.disk_usage(existing_mount(model_dir)).free
    required = 0
    for spec in FILES:
        target = destination / str(spec["path"])
        part = target.with_name(target.name + ".part")
        if target.exists() and not valid_file(target, spec):
            raise RuntimeError(f"Refusing to overwrite an existing unverified file: {target}")
        if not target.exists():
            partial = part.stat().st_size if part.exists() else 0
            if partial > int(spec["size"]):
                raise RuntimeError(f"Partial file exceeds expected size and was preserved: {part}")
            required += int(spec["size"]) - partial
    record = {
        "repo": REPO,
        "revision": REVISION,
        "destination": str(destination),
        "expected_bytes": sum(int(spec["size"]) for spec in FILES),
        "additional_bytes_needed": required,
        "free_bytes": free,
        "safety_margin_bytes": SAFETY_BYTES,
        "files": [dict(spec) for spec in FILES],
    }
    print(json.dumps(record, sort_keys=True), flush=True)
    if free < required + SAFETY_BYTES:
        raise RuntimeError("Insufficient free space for the pinned model plus a 256 MiB safety margin.")
    if dry_run:
        return

    destination.mkdir(parents=True, exist_ok=True)
    downloaded = [download_file(destination, spec) for spec in FILES]
    manifest_data = {
        "repo": REPO,
        "revision": REVISION,
        "files": downloaded,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    temporary_manifest = manifest.with_suffix(".json.tmp")
    temporary_manifest.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")
    temporary_manifest.replace(manifest)
    log_path = Path(os.environ.get("MODEL_DOWNLOAD_LOG", ROOT / "results/raw/model-downloads.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "repo": REPO,
        "revision": REVISION,
        "destination": str(destination),
        "license": "apache-2.0",
        "verified": True,
        "weights_bytes": next(item["bytes"] for item in downloaded if item["path"] == "model.safetensors"),
        "weights_sha256": next(item["sha256"] for item in downloaded if item["path"] == "model.safetensors"),
        "file_count": len(downloaded),
    }
    with log_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(event, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=Path(os.environ.get("MODEL_DIR", "/mnt/e/local-llm-models")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        download(args.model_dir.expanduser(), args.dry_run)
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
