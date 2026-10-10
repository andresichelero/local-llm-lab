#!/usr/bin/env python3
"""Deterministic single-request EXL3 inference benchmark using the upstream generation API."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from exllamav3 import Cache, Config, GreedySampler, Model, Tokenizer

PROMPT = (
    "<|im_start|>user\nReturn exactly one short sentence explaining why a fixed random seed "
    "helps reproduce an inference benchmark.<|im_end|>\n<|im_start|>assistant\n"
)
MODEL_REVISION = "d35e580c801b276c4d5ff97f27bd0fa79a0ef3b3"
WEIGHT_SHA256 = "19e38d592d439a19205469aba6f477355aaa17d81f1f516b222a2abc7ba76d23"


def git_metadata(root: Path) -> tuple[str | None, bool | None]:
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal", "--", ".", ":(exclude)results/**"],
            cwd=root, check=True, text=True, capture_output=True,
        ).stdout
        return sha, bool(status.strip())
    except (OSError, subprocess.SubprocessError):
        return None, None


def run_once(model: Model, cache: Cache, tokenizer: Tokenizer, max_context: int, max_new_tokens: int, repetition: int, warmup: bool) -> dict:
    context_ids = tokenizer.encode(PROMPT, encode_special_tokens=True)
    prompt_tokens = int(context_ids.shape[-1])
    if prompt_tokens + max_new_tokens > max_context:
        raise ValueError("prompt plus generation exceeds configured context")
    params = {"attn_mode": "flash_attn", "cache": cache, "past_len": 0, "batch_shape": (1, max_context)}
    torch.cuda.synchronize()
    start = time.perf_counter()
    if prompt_tokens > 1:
        model.prefill(input_ids=context_ids[:, :-1], params=params)
    recurrent_states = params.get("recurrent_states")
    sampler = GreedySampler()
    stop_ids = set(model.config.eos_token_id_list)
    generated: list[int] = []
    first_token_ms: float | None = None
    generation_start = None

    # The first output token is produced by forwarding the final prompt token, as in the
    # upstream generation_loop example, so prompt-prefill cost is included in TTFT.
    for index in range(max_new_tokens):
        current_params = {
            "attn_mode": "flash_attn",
            "cache": cache,
            "past_len": prompt_tokens + index - 1,
            "batch_shape": (1, max_context),
            "recurrent_states": recurrent_states,
        }
        logits = model.forward(input_ids=context_ids[:, -1:], params=current_params)
        sample = sampler.forward(logits, tokenizer=tokenizer)
        token_id = int(sample.item())
        torch.cuda.synchronize()
        now = time.perf_counter()
        if first_token_ms is None:
            first_token_ms = (now - start) * 1000
            generation_start = now
        if token_id in stop_ids:
            break
        generated.append(token_id)
        context_ids = torch.cat((context_ids, sample.cpu()), dim=-1)

    torch.cuda.synchronize()
    end = time.perf_counter()
    output_text = tokenizer.decode(generated, decode_special_tokens=False)
    generated_tokens = len(generated)
    generation_seconds = max(end - (generation_start or end), 1e-9)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": "exllamav3-qwen35-9b-exl3-2.5bpw",
        "model": "Qwen3.5-9B",
        "model_repo": "turboderp/Qwen3.5-9B-exl3",
        "model_revision": MODEL_REVISION,
        "model_weights_sha256": WEIGHT_SHA256,
        "quant": "EXL3 2.50bpw",
        "runtime": "ExLlamaV3 1.6.0",
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
        "context": max_context,
        "kv_cache": "fp16 default",
        "gpu_layers": "all (runtime placement)",
        "flash_attention": True,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": generated_tokens,
        "max_new_tokens": max_new_tokens,
        "ttft_ms": round(first_token_ms or 0, 3),
        "generation_tps": round(generated_tokens / generation_seconds, 3),
        "wall_seconds": round(end - start, 4),
        "vram_peak_process_mb": round(torch.cuda.max_memory_reserved() / 1024**2, 1),
        "warmup": warmup,
        "repetition": repetition,
        "temperature": 0,
        "seed": 1234,
        "success": bool(output_text.strip()),
        "response": output_text,
    }
    for state in recurrent_states or []:
        state.free()
    cache.reset_states()
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=Path(os.environ.get("MODEL_DIR", "/mnt/e/local-llm-models/exllama/Qwen3.5-9B-exl3-2.5bpw")))
    parser.add_argument("--output", type=Path, default=Path("results/raw/exllama-qwen35-9b.jsonl"))
    parser.add_argument("--context", type=int, default=2048)
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.context < 256 or args.context % 256:
        parser.error("context must be a multiple of 256")
    if args.dry_run:
        print(json.dumps({"model_dir": str(args.model_dir), "output": str(args.output), "context": args.context, "warmups": args.warmups, "repetitions": args.repetitions}, sort_keys=True))
        return 0
    weights = args.model_dir / "model.safetensors"
    if not weights.is_file():
        parser.error(f"missing model weights: {weights}")

    root = Path(__file__).resolve().parents[1]
    git_sha, source_dirty = git_metadata(root)
    config = Config.from_directory(str(args.model_dir))
    model = Model.from_config(config)
    cache = Cache(model, max_num_tokens=args.context, max_batch_size=1)
    model.load(progressbar=True)
    tokenizer = Tokenizer.from_config(config)
    torch.cuda.reset_peak_memory_stats()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as output:
        for warmup_index in range(args.warmups):
            row = run_once(model, cache, tokenizer, args.context, args.max_new_tokens, warmup_index, True)
            row.update(git_sha=git_sha, source_tree_dirty=source_dirty)
            print(json.dumps(row, sort_keys=True), file=output, flush=True)
            print(f"warmup {warmup_index + 1}: {row['generation_tps']} tok/s; TTFT {row['ttft_ms']} ms")
        torch.cuda.reset_peak_memory_stats()
        for repetition in range(1, args.repetitions + 1):
            row = run_once(model, cache, tokenizer, args.context, args.max_new_tokens, repetition, False)
            row.update(git_sha=git_sha, source_tree_dirty=source_dirty)
            print(json.dumps(row, sort_keys=True), file=output, flush=True)
            print(f"run {repetition}/{args.repetitions}: {row['generation_tps']} tok/s; TTFT {row['ttft_ms']} ms")
            if not row["success"]:
                raise RuntimeError("model returned empty output")
    model.unload()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
