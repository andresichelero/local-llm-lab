#!/usr/bin/env python3
"""Create a deterministic, offline long-context QLoRA fixture for a local model tokenizer."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def input_ids(encoded):
    ids = encoded["input_ids"] if isinstance(encoded, dict) else encoded
    return ids.tolist() if hasattr(ids, "tolist") else ids


def count_tokens(tokenizer, messages, *, add_generation_prompt):
    encoded = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=add_generation_prompt,
    )
    return len(input_ids(encoded))


def build_example(tokenizer, row: int, prompt_target: int, sequence_target: int):
    user = f"Transform this calibration input for record {row}:\n"
    prompt_messages = [{"role": "user", "content": user}]
    while count_tokens(tokenizer, prompt_messages, add_generation_prompt=True) < prompt_target:
        user += f"Context block {row}: alpha beta gamma delta epsilon zeta eta theta.\n"
        prompt_messages[0]["content"] = user
    prompt_tokens = count_tokens(tokenizer, prompt_messages, add_generation_prompt=True)
    if prompt_tokens >= sequence_target:
        raise ValueError("Prompt target leaves no room for assistant completion")

    answer = f"Record {row} calibration output: alpha beta gamma delta epsilon zeta eta theta.\n"
    messages = [*prompt_messages, {"role": "assistant", "content": answer}]
    while count_tokens(tokenizer, messages, add_generation_prompt=False) < sequence_target:
        answer += f"Checksum phrase for record {row}: alpha beta gamma delta epsilon zeta eta theta.\n"
        messages[-1]["content"] = answer
    full_tokens = count_tokens(tokenizer, messages, add_generation_prompt=False)
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
    samples = [build_example(tokenizer, row, args.prompt_tokens, args.sequence_tokens) for row in range(args.rows)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"messages": messages}, ensure_ascii=False) for messages, _, _ in samples]
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
        "prompt_token_lengths": [prompt for _, prompt, _ in samples],
        "full_token_lengths": [full for _, _, full in samples],
        "offline": True,
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
