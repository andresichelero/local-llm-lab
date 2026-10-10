#!/usr/bin/env python3
"""Deterministic LoRA/QLoRA fine-tuning run with a small local code dataset.

The heavy ML imports stay inside the functions so the dataset and label logic can be
unit-tested without PyTorch. `--tiny-random` builds a randomly initialised Qwen2-shaped
model on CPU; it validates the training code path only and is not a quality or GPU result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE_INDEX = -100

# Each family yields a Python function name, a natural-language request and a reference body.
FAMILIES = (
    ("sum_to_n", "return the sum of the integers from 1 to n inclusive",
     "def {name}(n):\n    return n * (n + 1) // 2\n"),
    ("count_vowels", "return how many vowels a, e, i, o, u the string s contains, ignoring case",
     "def {name}(s):\n    return sum(1 for c in s.lower() if c in 'aeiou')\n"),
    ("reverse_text", "return the string s reversed",
     "def {name}(s):\n    return s[::-1]\n"),
    ("factorial", "return n factorial for a non-negative integer n, computed iteratively",
     "def {name}(n):\n    result = 1\n    for k in range(2, n + 1):\n        result *= k\n    return result\n"),
    ("largest_item", "return the largest element of the non-empty list xs",
     "def {name}(xs):\n    return max(xs)\n"),
)


def build_dataset(count: int, seed: int) -> list[dict[str, str]]:
    """Return `count` deterministic prompt/completion pairs; the same seed gives the same list."""
    examples = []
    for index in range(count):
        family_name, request, template = FAMILIES[index % len(FAMILIES)]
        name = f"{family_name}_{index:03d}"
        examples.append({
            "prompt": f"Write a Python function named `{name}` that will {request}.",
            "completion": template.format(name=name),
        })
    random.Random(seed).shuffle(examples)
    return examples


def dataset_sha256(examples: list[dict[str, str]]) -> str:
    payload = json.dumps(examples, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ByteTokenizer:
    """Byte-level tokenizer for the offline random-weight smoke test (no download needed)."""

    eos_id = 256
    pad_id = 257
    vocab_size = 258

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))


def encode_example(tokenizer, example: dict[str, str], max_len: int, eos_id: int) -> tuple[list[int], list[int]]:
    """Tokenise prompt+completion; prompt positions get IGNORE_INDEX so only the completion is learned."""
    prompt_ids = tokenizer.encode(example["prompt"] + "\n")
    completion_ids = tokenizer.encode(example["completion"]) + [eos_id]
    ids = (prompt_ids + completion_ids)[:max_len]
    labels = ([IGNORE_INDEX] * len(prompt_ids) + completion_ids)[:max_len]
    if all(label == IGNORE_INDEX for label in labels):
        raise ValueError(f"max_len={max_len} truncates the completion of an example; raise --max-seq-len")
    return ids, labels


def collate(batch: list[tuple[list[int], list[int]]], pad_id: int) -> dict[str, list[list[int]]]:
    width = max(len(ids) for ids, _ in batch)
    input_ids = [ids + [pad_id] * (width - len(ids)) for ids, _ in batch]
    labels = [labels + [IGNORE_INDEX] * (width - len(labels)) for _, labels in batch]
    attention = [[1] * len(ids) + [0] * (width - len(ids)) for ids, _ in batch]
    return {"input_ids": input_ids, "labels": labels, "attention_mask": attention}


def batch_schedule(encoded_count: int, batch_size: int, micro_batches: int, seed: int) -> list[list[int]]:
    """Deterministic indices per micro-batch, reshuffling each pass over the dataset."""
    rng = random.Random(seed)
    schedule: list[list[int]] = []
    pool: list[int] = []
    while len(schedule) < micro_batches:
        if len(pool) < batch_size:
            fresh = list(range(encoded_count))
            rng.shuffle(fresh)
            pool.extend(fresh)
        schedule.append(pool[:batch_size])
        pool = pool[batch_size:]
    return schedule


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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-dir", type=Path, help="Local Hugging Face model directory (required unless --tiny-random)")
    parser.add_argument("--model-id", default="tiny-random-qwen2", help="Label recorded in the output")
    parser.add_argument("--model-revision", default="unrecorded", help="Pinned model revision recorded in the output")
    parser.add_argument("--tiny-random", action="store_true", help="CPU smoke test with random Qwen2-shaped weights")
    parser.add_argument("--qlora", action="store_true", help="Load the base model in 4-bit NF4 (CUDA + bitsandbytes only)")
    parser.add_argument("--optimizer", choices=("adamw", "adamw8bit"), default="adamw")
    parser.add_argument("--gradient-checkpointing", action="store_true")
    parser.add_argument("--examples", type=int, default=32)
    parser.add_argument("--max-seq-len", type=int, default=256)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--grad-accum", type=int, default=1)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--target-modules", default="q_proj,k_proj,v_proj,o_proj")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--adapter-dir", type=Path, default=ROOT / "logs" / "lora-adapter")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "raw" / "finetune-lora.jsonl")
    parser.add_argument("--experiment", default="finetune-lora")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved plan and dataset hash, then exit")
    args = parser.parse_args(argv)
    if not args.tiny_random and args.model_dir is None:
        parser.error("--model-dir is required unless --tiny-random is set")
    if args.qlora and args.tiny_random:
        parser.error("--qlora needs a real CUDA model; it cannot be combined with --tiny-random")
    return args


def load_model_and_tokenizer(args: argparse.Namespace):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Qwen2Config, Qwen2ForCausalLM

    if args.tiny_random:
        torch.manual_seed(args.seed)
        config = Qwen2Config(
            vocab_size=ByteTokenizer.vocab_size, hidden_size=64, intermediate_size=128,
            num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=2,
            max_position_embeddings=512, tie_word_embeddings=False,
        )
        return Qwen2ForCausalLM(config), ByteTokenizer(), ByteTokenizer.eos_id, ByteTokenizer.pad_id

    if not torch.cuda.is_available():
        # Refuse rather than silently training on CPU: the lab's question is about the RTX 3070.
        raise SystemExit("CUDA is not available; refusing to run a real-model fine-tune on CPU")
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    quantization = None
    if args.qlora:
        quantization = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_dir, local_files_only=True, quantization_config=quantization,
        dtype=torch.bfloat16, device_map={"": 0},
    )
    eos_id = tokenizer.eos_token_id
    pad_id = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else eos_id
    return model, tokenizer, eos_id, pad_id


def peak_memory_mb(device: str) -> float:
    if device == "cuda":
        import torch
        return round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1)
    # ru_maxrss is KiB on Linux: process peak resident set, not GPU memory.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def train(args: argparse.Namespace) -> dict:
    import torch
    import peft
    import transformers
    from peft import LoraConfig, get_peft_model

    torch.manual_seed(args.seed)
    random.seed(args.seed)
    model, tokenizer, eos_id, pad_id = load_model_and_tokenizer(args)
    device = "cuda" if (not args.tiny_random and torch.cuda.is_available()) else "cpu"
    if args.qlora:
        from peft import prepare_model_for_kbit_training
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=args.gradient_checkpointing)
    elif args.gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(
        r=args.rank, lora_alpha=args.alpha, lora_dropout=0.0, bias="none", task_type="CAUSAL_LM",
        target_modules=args.target_modules.split(","),
    ))
    if not args.qlora:
        # 4-bit bitsandbytes models are placed by device_map at load time and cannot be moved.
        model.to(device)
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())

    examples = build_dataset(args.examples, args.seed)
    encoded = [encode_example(tokenizer, ex, args.max_seq_len, eos_id) for ex in examples]
    micro_batches = args.steps * args.grad_accum
    schedule = batch_schedule(len(encoded), args.batch_size, micro_batches, args.seed)

    params = [p for p in model.parameters() if p.requires_grad]
    if args.optimizer == "adamw8bit":
        import bitsandbytes as bnb
        optimizer = bnb.optim.AdamW8bit(params, lr=args.lr)
    else:
        optimizer = torch.optim.AdamW(params, lr=args.lr)

    model.train()
    losses: list[float] = []
    step_seconds: list[float] = []
    started = time.perf_counter()
    for step in range(args.steps):
        step_start = time.perf_counter()
        step_loss = 0.0
        for micro in range(args.grad_accum):
            indices = schedule[step * args.grad_accum + micro]
            batch = collate([encoded[i] for i in indices], pad_id)
            tensors = {key: torch.tensor(value, device=device) for key, value in batch.items()}
            output = model(**tensors)
            loss = output.loss / args.grad_accum
            loss.backward()
            step_loss += float(loss.detach())
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)
        if device == "cuda":
            torch.cuda.synchronize()
        losses.append(step_loss)
        step_seconds.append(time.perf_counter() - step_start)
        print(f"step={step + 1} loss={step_loss:.6f} step_s={step_seconds[-1]:.3f}", flush=True)
    wall_seconds = time.perf_counter() - started

    args.adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.adapter_dir)
    adapter_file = args.adapter_dir / "adapter_model.safetensors"
    adapter_sha = file_sha256(adapter_file) if adapter_file.exists() else None

    finite = all(math.isfinite(value) for value in losses)
    sha, dirty = git_metadata(ROOT)
    ordered_steps = sorted(step_seconds)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "experiment": args.experiment,
        "model": args.model_id,
        "model_revision": args.model_revision,
        "runtime": "transformers+peft",
        "quant": "nf4-qlora" if args.qlora else "bf16-lora",
        "device": device,
        "optimizer": args.optimizer,
        "gradient_checkpointing": args.gradient_checkpointing,
        "tiny_random_smoke": args.tiny_random,
        "lora_rank": args.rank,
        "lora_alpha": args.alpha,
        "target_modules": args.target_modules,
        "steps": args.steps,
        "batch_size": args.batch_size,
        "grad_accum": args.grad_accum,
        "max_seq_len": args.max_seq_len,
        "examples": args.examples,
        "lr": args.lr,
        "seed": args.seed,
        "dataset_sha256": dataset_sha256(examples),
        "trainable_params": trainable_params,
        "total_params": total_params,
        "loss_first": losses[0],
        "loss_last": losses[-1],
        "loss_curve": [round(value, 6) for value in losses],
        "loss_finite": finite,
        "loss_decreased": finite and losses[-1] < losses[0],
        "step_time_median_s": round(ordered_steps[len(ordered_steps) // 2], 4),
        "wall_time_s": round(wall_seconds, 3),
        "peak_memory_mb": peak_memory_mb(device),
        "peak_memory_source": "torch.cuda.max_memory_allocated" if device == "cuda" else "process_maxrss",
        "adapter_dir": str(args.adapter_dir.relative_to(ROOT)) if args.adapter_dir.is_relative_to(ROOT) else str(args.adapter_dir),
        "adapter_sha256": adapter_sha,
        "torch_version": torch.__version__,
        "transformers_version": transformers.__version__,
        "peft_version": peft.__version__,
        "git_sha": sha,
        "source_tree_dirty": dirty,
        "success": finite,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    examples = build_dataset(args.examples, args.seed)
    plan = {
        "model": args.model_id,
        "tiny_random": args.tiny_random,
        "qlora": args.qlora,
        "optimizer": args.optimizer,
        "examples": len(examples),
        "dataset_sha256": dataset_sha256(examples),
        "steps": args.steps,
        "batch_size": args.batch_size,
        "grad_accum": args.grad_accum,
        "max_seq_len": args.max_seq_len,
        "rank": args.rank,
        "alpha": args.alpha,
        "lr": args.lr,
        "seed": args.seed,
        "output": str(args.output),
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return 0
    record = train(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({k: record[k] for k in ("loss_first", "loss_last", "loss_decreased", "peak_memory_mb", "adapter_sha256", "success")}, indent=2))
    return 0 if record["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
