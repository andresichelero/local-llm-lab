#!/usr/bin/env python3
"""Small OpenAI-compatible streaming benchmark for llama-server."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROMPT = "Return exactly one short sentence explaining why a fixed random seed helps reproduce an inference benchmark."


def gpu_sample() -> dict[str, str | None]:
    query = "memory.used,utilization.gpu,temperature.gpu,clocks.gr,power.draw"
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=5,
        )
        values = [item.strip() for item in result.stdout.strip().split(",")]
        return dict(zip(["vram_used_mb", "gpu_util_pct", "temperature_c", "gpu_clock_mhz", "power_w"], values))
    except (OSError, subprocess.SubprocessError):
        return {"vram_used_mb": None, "gpu_util_pct": None, "temperature_c": None, "gpu_clock_mhz": None, "power_w": None}


def run_once(url: str, model: str, max_tokens: int, seed: int, repetition: int) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "temperature": 0,
        "seed": seed,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    first_token = None
    completion_tokens = 0
    prompt_tokens = None
    chunks = 0
    content_parts: list[str] = []
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
                usage = event.get("usage")
                if usage:
                    prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                    completion_tokens = usage.get("completion_tokens", completion_tokens)
                choices = event.get("choices") or []
                if choices:
                    delta = choices[0].get("delta") or {}
                    text = delta.get("content")
                    if text:
                        if first_token is None:
                            first_token = time.perf_counter()
                        chunks += 1
                        content_parts.append(text)
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    end = time.perf_counter()
    if first_token is None:
        raise RuntimeError("Server returned no text content.")
    if completion_tokens == 0:
        completion_tokens = chunks
    ttft = first_token - start
    generation_time = end - first_token
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": "tier0_streaming_smoke",
        "repetition": repetition,
        "model": model,
        "quant": "GGUF Q4_K_M",
        "runtime": "llama.cpp",
        "git_sha": os.environ.get("LAB_GIT_SHA"),
        "seed": seed,
        "temperature": 0,
        "max_new_tokens": max_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "ttft_ms": round(ttft * 1000, 2),
        "generation_tps": round(max(completion_tokens - 1, 0) / generation_time, 3) if generation_time > 0 else None,
        "wall_time_s": round(end - start, 4),
        "gpu": gpu_sample(),
        "success": True,
        "response": "".join(content_parts),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18180")
    parser.add_argument("--model", default="local")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("results/raw/tier0.jsonl"))
    args = parser.parse_args()
    if args.repetitions < 1 or args.warmups < 0:
        parser.error("repetitions must be >= 1 and warmups must be >= 0")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        for index in range(args.warmups):
            run_once(args.url, args.model, args.max_tokens, args.seed, -index - 1)
            print(f"warm-up {index + 1}/{args.warmups} complete", file=sys.stderr)
        with args.output.open("a", encoding="utf-8") as output:
            for index in range(args.repetitions):
                record = run_once(args.url, args.model, args.max_tokens, args.seed, index + 1)
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                print(json.dumps(record, ensure_ascii=False))
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

