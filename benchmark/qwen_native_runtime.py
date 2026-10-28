"""Stage only trusted native runner files outside the source worktree."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


NATIVE_RUNTIME_FILES = (
    "qwen_native_driver.py",
    "qwen_native_gateway.py",
    "qwen_native_protocols.py",
    "qwen_native_mcp.py",
)


def stage_native_runtime(episode_root: Path, repo_root: Path, adapter: dict) -> Path:
    """Copy the allowlisted runner bundle into a private episode temp directory."""
    episode_root = Path(episode_root).resolve(strict=True)
    repo_root = Path(repo_root).resolve(strict=True)
    runtime_root = episode_root / "qwen-native-runtime"
    runtime_root.mkdir(mode=0o700)
    if repo_root == runtime_root or repo_root in runtime_root.parents:
        raise ValueError("native runtime staging directory cannot be in the repository")

    for name in NATIVE_RUNTIME_FILES:
        source = repo_root / "benchmark" / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"native runtime source is not a regular file: {name}")
        content = source.read_bytes()
        target = runtime_root / name
        target.write_bytes(content)
        os.chmod(target, 0o444)
        if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(content).digest():
            raise OSError(f"native runtime copy failed digest verification: {name}")

    adapter_path = runtime_root / "adapter.json"
    adapter_path.write_text(
        json.dumps(adapter, separators=(",", ":"), ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    os.chmod(adapter_path, 0o444)
    return runtime_root
