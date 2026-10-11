#!/usr/bin/env python3
"""Needle-recall probe for a long context served by llama.cpp."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from benchmark.provenance import git_provenance


TARGET_STATION = "Relay Nacre-17"
TARGET_CODE = "FROST-9K2M-VALE-317"
QUERY = f"Return only the maintenance code for {TARGET_STATION}. If absent, return NOT FOUND."


def make_prompt(record_count: int) -> str:
    if record_count < 1:
        raise ValueError("record_count must be positive")
    lines = [
        "Read the maintenance log and answer the question at the end. Use only the log.",
        "Each entry has a relay name and its maintenance code.",
    ]
    target_index = record_count // 2
    for index in range(record_count):
        station = TARGET_STATION if index == target_index else f"Relay {index:05d}"
        code = TARGET_CODE if index == target_index else f"AUX-{index % 10000:04d}-NODE-{(index * 37) % 997:03d}"
        lines.append(f"Entry {index:05d}: station={station}; maintenance_code={code}; status=verified.")
    lines.append(QUERY)
    return "\n".join(lines)


def answer_matches(response: str, expected: str = TARGET_CODE) -> bool:
    return response.strip().upper() == expected.upper()


def post_json(url: str, payload: dict[str, Any], timeout: int = 600) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {body}") from error


def token_count(url: str, prompt: str) -> int:
    result = post_json(url.rstrip("/") + "/tokenize", {"content": prompt, "add_special": True}, 120)
    return len(result.get("tokens", []))


def prompt_for_tokens(url: str, target_tokens: int) -> tuple[str, int, int]:
    """Find a deterministic prompt at or just above the requested token count."""
    low, high = 1, 1
    while token_count(url, make_prompt(high)) < target_tokens:
        low, high = high, high * 2
    while low < high:
        middle = (low + high) // 2
        if token_count(url, make_prompt(middle)) < target_tokens:
            low = middle + 1
        else:
            high = middle
    prompt = make_prompt(low)
    return prompt, token_count(url, prompt), low


def request_once(url: str, model: str, prompt: str, repetition: int, run_kind: str, args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "seed": 1234,
        "max_tokens": 24,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    first_token = None
    prompt_tokens = completion_tokens = None
    parts: list[str] = []
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                usage = event.get("usage") or {}
                prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                completion_tokens = usage.get("completion_tokens", completion_tokens)
                choices = event.get("choices") or []
                if choices:
                    content = ((choices[0].get("delta") or {}).get("content"))
                    if content:
                        if first_token is None:
                            first_token = time.perf_counter()
                        parts.append(content)
        end = time.perf_counter()
        output = "".join(parts).strip()
        if first_token is None:
            raise RuntimeError("server returned no text")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "experiment": args.experiment,
            "run_kind": run_kind,
            "repetition": repetition,
            "model": args.model_id,
            "model_revision": args.model_revision,
            "runtime": "llama.cpp",
            "runtime_commit": args.runtime_commit,
            "git_sha": args.git_sha,
            "source_tree_dirty": args.source_tree_dirty,
            "storage_profile": "ssd-wsl-ext4-c",
            "context_tokens": args.context,
            "target_prompt_tokens": args.target_tokens,
            "tokenizer_prompt_tokens": args.actual_prompt_tokens,
            "prompt_tokens": prompt_tokens,
            "record_count": args.record_count,
            "kv_cache_k": args.kv_type,
            "kv_cache_v": args.kv_type,
            "seed": 1234,
            "temperature": 0,
            "expected_answer": TARGET_CODE,
            "response": output,
            "quality_pass": answer_matches(output),
            "ttft_ms": round((first_token - start) * 1000, 2),
            "wall_time_s": round(end - start, 4),
            "prompt_tokens_reported": prompt_tokens,
            "completion_tokens": completion_tokens,
            "success": True,
        }
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "experiment": args.experiment,
            "run_kind": run_kind,
            "repetition": repetition,
            "model": args.model_id,
            "model_revision": args.model_revision,
            "runtime": "llama.cpp",
            "runtime_commit": args.runtime_commit,
            "git_sha": args.git_sha,
            "source_tree_dirty": args.source_tree_dirty,
            "storage_profile": "ssd-wsl-ext4-c",
            "context_tokens": args.context,
            "target_prompt_tokens": args.target_tokens,
            "tokenizer_prompt_tokens": args.actual_prompt_tokens,
            "record_count": args.record_count,
            "kv_cache_k": args.kv_type,
            "kv_cache_v": args.kv_type,
            "seed": 1234,
            "temperature": 0,
            "expected_answer": TARGET_CODE,
            "response": "",
            "quality_pass": False,
            "wall_time_s": round(time.perf_counter() - start, 4),
            "success": False,
            "error": str(error),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18300")
    parser.add_argument("--model-id", default="Qwen3.5-9B-Q4_K_M")
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--runtime-source", type=Path, required=True)
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--target-tokens", type=int, default=14000)
    parser.add_argument("--kv-type", choices=("q4_0", "q8_0", "f16"), required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 1 or args.warmups < 0 or args.context <= args.target_tokens:
        parser.error("Require repetitions >= 1, warmups >= 0, and context > target tokens")

    args.git_sha, args.source_tree_dirty = git_provenance(REPO_ROOT)
    try:
        args.runtime_commit = subprocess.run(
            ["git", "-C", str(args.runtime_source), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        prompt, actual_tokens, args.record_count = prompt_for_tokens(args.url, args.target_tokens)
        args.actual_prompt_tokens = actual_tokens
        if actual_tokens + 24 >= args.context:
            raise ValueError("tokenized prompt plus generation limit exceeds context")
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"context-recall setup failed: {error}\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with args.output.open("a", encoding="utf-8") as output:
        for index in range(args.warmups):
            row = request_once(args.url, args.model_id, prompt, index + 1, "warmup", args)
            rows.append(row)
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            output.flush()
            print(json.dumps(row, ensure_ascii=False))
        for repetition in range(1, args.repetitions + 1):
            row = request_once(args.url, args.model_id, prompt, repetition, "measurement", args)
            rows.append(row)
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            output.flush()
            print(json.dumps(row, ensure_ascii=False))
    return 0 if all(row.get("success") and row.get("quality_pass") for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
