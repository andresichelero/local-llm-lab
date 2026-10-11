#!/usr/bin/env python3
"""Create a deterministic, offline long-context QLoRA fixture for a local model tokenizer."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path


def token_ids(encoded):
    ids = encoded["input_ids"] if isinstance(encoded, Mapping) else encoded
    return ids.tolist() if hasattr(ids, "tolist") else ids


def count_tokens(tokenizer, messages, *, add_generation_prompt):
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=add_generation_prompt,
    )
    return len(token_ids(encoded))


def extend_to_target(tokenizer, messages, role_index, field, target, *, add_generation_prompt):
    chunk = "Context calibration phrase: alpha beta gamma delta epsilon zeta eta theta.\n"
    chunk_tokens = len(token_ids(tokenizer(chunk, add_special_tokens=False)))
    if chunk_tokens < 1:
        raise ValueError("Tokenizer produced no tokens for the calibration phrase")
    for _ in range(5):
        current = count_tokens(tokenizer, messages, add_generation_prompt=add_generation_prompt)
        if current >= target:
            return current
        repeats = max(1, math.ceil((target - current) / chunk_tokens))
        messages[role_index]["content"] += chunk * repeats
    current = count_tokens(tokenizer, messages, add_generation_prompt=add_generation_prompt)
    if current < target:
        raise ValueError(f"Could not reach token target {target}; reached {current}")
    return current


def build_example(tokenizer, prompt_target: int, sequence_target: int):
    messages = [{"role": "user", "content": "Transform this deterministic calibration fixture.\n"}]
    prompt_tokens = extend_to_target(
        tokenizer, messages, 0, "content", prompt_target, add_generation_prompt=True
    )
    if prompt_tokens >= sequence_target:
        raise ValueError("Prompt target leaves no room for assistant completion")
    messages.append({"role": "assistant", "content": "Calibration result: alpha beta gamma delta.\n"})
    full_tokens = extend_to_target(
        tokenizer, messages, 1, "content", sequence_target, add_generation_prompt=False
    )
    return messages, prompt_tokens, full_tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=8)
    parser.add_argument("--prompt-tokens", type=int, default=350)
    parser.add_argument("--sequence-tokens", type=int, default=1024)
    args = parser.parse_args()
    if args.rows < 1 or args.prompt_tokens < 1 or args.sequence_tokens <= args.prompt_tokens:
        parser.error("rows/prompt must be positive and sequence-tokens must exceed prompt-tokens")

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(args.model_dir), local_files_only=True)
    messages, prompt_tokens, full_tokens = build_example(tokenizer, args.prompt_tokens, args.sequence_tokens)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"messages": messages}, ensure_ascii=False) for _ in range(args.rows)]
    payload = "\n".join(lines) + "\n"
    args.output.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    manifest = {
        "model_dir": str(args.model_dir),
        "tokenizer": tokenizer.name_or_path,
        "dataset": str(args.output),
        "dataset_sha256": digest,
        "rows": args.rows,
        "prompt_target_tokens": args.prompt_tokens,
        "sequence_target_tokens": args.sequence_tokens,
        "prompt_token_lengths": [prompt_tokens] * args.rows,
        "full_token_lengths": [full_tokens] * args.rows,
        "offline": True,
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
