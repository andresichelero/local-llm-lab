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


def long_prompt(url: str, target_tokens: int) -> tuple[str, int]:
    prefix = "Read these fixed benchmark records, then answer the question at the end.\n"
    suffix = "Return exactly one short sentence explaining why a fixed random seed helps reproduce an inference benchmark."

    def make_text(record_count: int) -> str:
        records = "".join(
            f"Reference record {i:05d}: cycle {i % 17}, seed 1234, tokens_per_second {40 + i % 71}.\n"
            for i in range(record_count)
        )
        return prefix + records + suffix

    def count_tokens(content: str) -> int:
        request = urllib.request.Request(
            url.rstrip("/") + "/tokenize",
            data=json.dumps({"content": content, "add_special": True}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return len(json.loads(response.read()).get("tokens", []))

    low, high = 0, 1
    while count_tokens(make_text(high)) < target_tokens:
        low, high = high, high * 2
    while low < high:
        middle = (low + high) // 2
        if count_tokens(make_text(middle)) < target_tokens:
            low = middle + 1
        else:
            high = middle
    content = make_text(low)
    return content, count_tokens(content)


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


def run_once(url: str, model: str, max_tokens: int, seed: int, repetition: int, prompt: str, target_prompt_tokens: int | None) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
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
    timings: dict[str, float | int] = {}
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
                if isinstance(event.get("timings"), dict):
                    timings = event["timings"]
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
    prompt_ms = timings.get("prompt_ms")
    predicted_ms = timings.get("predicted_ms")
    prompt_count = prompt_tokens or timings.get("prompt_n")
    generated_count = completion_tokens or timings.get("predicted_n")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": os.environ.get("LAB_EXPERIMENT", "tier0_streaming_smoke"),
        "repetition": repetition,
        "model": model,
        "quant": "GGUF Q4_K_M",
        "runtime": "llama.cpp",
        "runtime_path": os.environ.get("LAB_RUNTIME_PATH"),
        "runtime_storage_profile": os.environ.get("LAB_RUNTIME_STORAGE_PROFILE", "unknown"),
        "model_path": os.environ.get("LAB_MODEL_PATH"),
        "model_revision": os.environ.get("LAB_MODEL_REVISION") or None,
        "model_storage_profile": os.environ.get("LAB_STORAGE_PROFILE", "unknown"),
        "server_startup_to_ready_ms": int(os.environ["LAB_SERVER_STARTUP_MS"]) if os.environ.get("LAB_SERVER_STARTUP_MS", "").isdigit() else None,
        "git_sha": os.environ.get("LAB_GIT_SHA"),
        "source_tree_dirty": os.environ.get("LAB_SOURCE_DIRTY", "unknown") == "true",
        "runtime_commit": os.environ.get("LAB_RUNTIME_COMMIT"),
        "context_tokens": int(os.environ.get("LAB_CTX_SIZE", "0")),
        "kv_cache_k": os.environ.get("LAB_KV_TYPE_K", "f16"),
        "kv_cache_v": os.environ.get("LAB_KV_TYPE_V", "f16"),
        "gpu_layers": int(os.environ.get("LAB_GPU_LAYERS", "0")),
        "batch_size": int(os.environ.get("LAB_BATCH_SIZE", "0")),
        "ubatch_size": int(os.environ.get("LAB_UBATCH_SIZE", "0")),
        "flash_attention": os.environ.get("LAB_FLASH_ATTN", "unknown"),
        "reasoning": os.environ.get("LAB_REASONING", "auto"),
        "prompt_cache": os.environ.get("LAB_CACHE_PROMPT", "off"),
        "seed": seed,
        "temperature": 0,
        "max_new_tokens": max_tokens,
        "prompt_target_tokens": target_prompt_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "ttft_ms": round(ttft * 1000, 2),
        "prompt_eval_ms": prompt_ms,
        "prompt_tps": round(prompt_count / (prompt_ms / 1000), 3) if prompt_count and prompt_ms else None,
        "generation_eval_ms": predicted_ms,
        "generation_tps": round(generated_count / (predicted_ms / 1000), 3) if generated_count and predicted_ms else (round(max(completion_tokens - 1, 0) / generation_time, 3) if generation_time > 0 else None),
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
    parser.add_argument("--input-tokens", type=int, default=0, help="Build deterministic long prompt near this token count (0 uses the short smoke prompt).")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--experiment", default="tier0_streaming_smoke")
    parser.add_argument("--output", type=Path, default=Path("results/raw/tier0.jsonl"))
    args = parser.parse_args()
    if args.repetitions < 1 or args.warmups < 0:
        parser.error("repetitions must be >= 1 and warmups must be >= 0")
    if args.input_tokens < 0:
        parser.error("input-tokens must be >= 0")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        prompt, target_prompt_tokens = long_prompt(args.url, args.input_tokens) if args.input_tokens else (PROMPT, None)
        for index in range(args.warmups):
            run_once(args.url, args.model, args.max_tokens, args.seed, -index - 1, prompt, target_prompt_tokens)
            print(f"warm-up {index + 1}/{args.warmups} complete", file=sys.stderr)
        with args.output.open("a", encoding="utf-8") as output:
            for index in range(args.repetitions):
                record = run_once(args.url, args.model, args.max_tokens, args.seed, index + 1, prompt, target_prompt_tokens)
                output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                print(json.dumps(record, ensure_ascii=False))
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"benchmark failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

