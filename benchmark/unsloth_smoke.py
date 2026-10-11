#!/usr/bin/env python3
"""Small deterministic QLoRA run through Unsloth for a PEFT comparison."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

BENCH_STORAGE_ROOT = Path(os.environ.get("BENCH_STORAGE_ROOT", Path.home() / "local-llm-benchmark"))
DEFAULT_MODEL = BENCH_STORAGE_ROOT / "models/Qwen2.5-Coder-0.5B-Instruct"
DEFAULT_DATASET = BENCH_STORAGE_ROOT / "data/qlora-smoke.jsonl"
DEFAULT_OUTPUT = BENCH_STORAGE_ROOT / "results/unsloth"
DEFAULT_RESULT = BENCH_STORAGE_ROOT / "results/raw/unsloth-smoke.jsonl"
ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(os.environ.get("LAB_REPOSITORY_ROOT", ROOT))
PROBE_PROMPT = "Write a Python function called add(a, b) that returns their sum. Output only Python code."
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_add_function(source: str) -> bool:
    cleaned = source.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            cleaned = "\n".join(lines[1:-1])
    try:
        tree = ast.parse(cleaned)
    except SyntaxError:
        return False
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "add"]
    if len(functions) != 1 or len(functions[0].body) != 1:
        return False
    statement = functions[0].body[0]
    if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.BinOp) or not isinstance(statement.value.op, ast.Add):
        return False
    value = statement.value
    names = (value.left.id, value.right.id) if isinstance(value.left, ast.Name) and isinstance(value.right, ast.Name) else (None, None)
    return names in {("a", "b"), ("b", "a")}


def successful_unsloth_run(steps_completed: int, expected_steps: int, losses: list[float], probe: str) -> bool:
    return (
        steps_completed == expected_steps
        and len(losses) == expected_steps
        and all(math.isfinite(value) for value in losses)
        and expected_add_function(probe)
    )


def token_ids(encoded: object) -> object:
    return encoded["input_ids"] if isinstance(encoded, dict) else encoded


def load_rows(dataset: Path, tokenizer: object, max_length: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(dataset.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        messages = row.get("messages")
        if not isinstance(messages, list) or len(messages) < 2 or messages[-1].get("role") != "assistant":
            raise ValueError(f"Invalid conversational training example at line {line_number}")
        prompt_encoded = tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True)
        full_encoded = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
        prompt_ids = token_ids(prompt_encoded)
        full_ids = token_ids(full_encoded)
        full_ids = full_ids[:max_length]
        if full_ids[: len(prompt_ids)] != prompt_ids[: len(full_ids)]:
            raise ValueError(f"Prompt/completion token boundary mismatch at line {line_number}")
        prompt_length = min(len(prompt_ids), len(full_ids))
        labels = [-100] * prompt_length + full_ids[prompt_length:]
        if not any(token != -100 for token in labels):
            raise ValueError(f"No completion tokens remain after truncation at line {line_number}")
        rows.append({"input_ids": full_ids, "labels": labels})
    if not rows:
        raise ValueError("The training dataset is empty")
    return rows


def git_provenance() -> tuple[str, bool]:
    commit = subprocess.run(["git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(REPOSITORY_ROOT), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip())
    return commit, dirty


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--model-id", default="Qwen/Qwen2.5-Coder-0.5B-Instruct")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--result-jsonl", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-seq-length", type=int, default=192)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.steps < 1 or args.max_seq_length < 16 or not 0 <= args.lora_dropout < 1:
        parser.error("--steps must be positive, --max-seq-length at least 16, and --lora-dropout in [0, 1)")
    run_label = "warmup" if args.warmup else "measured"
    adapter_path = args.output_root / f"qwen25-coder-05b-unsloth-qlora-r8-{run_label}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-seed{args.seed}"
    preflight = {
        "backend": "unsloth",
        "model_dir": str(args.model_dir),
        "model": args.model_id,
        "dataset": str(args.dataset),
        "steps": args.steps,
        "seed": args.seed,
        "max_seq_length": args.max_seq_length,
        "lora_rank": 8,
        "lora_dropout": args.lora_dropout,
        "quantization": "bitsandbytes NF4 with double quantization",
        "optimizer": "torch.optim.AdamW (32-bit states)",
        "warmup": args.warmup,
        "adapter_output": str(adapter_path),
        "result_jsonl": str(args.result_jsonl),
    }
    print(json.dumps(preflight, sort_keys=True), flush=True)
    if args.dry_run:
        return 0
    if not (args.model_dir / "model.safetensors").is_file():
        raise FileNotFoundError(f"Model weights missing: {args.model_dir / 'model.safetensors'}")
    if not args.dataset.is_file():
        raise FileNotFoundError(f"Dataset missing: {args.dataset}")

    process_started = time.perf_counter()
    imports_started = time.perf_counter()
    from unsloth import FastLanguageModel
    import torch
    import transformers
    import peft
    import bitsandbytes
    import unsloth
    import unsloth_zoo
    imports_seconds = time.perf_counter() - imports_started
    if not torch.cuda.is_available() or "RTX 3070" not in torch.cuda.get_device_name(0):
        raise RuntimeError("Training requires the audited RTX 3070 CUDA device")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    setup_started = time.perf_counter()
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(args.model_dir),
        max_seq_length=args.max_seq_length,
        dtype=torch.float16,
        load_in_4bit=True,
        local_files_only=True,
        device_map={"": 0},
        random_state=args.seed,
        max_lora_rank=8,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    rows = load_rows(args.dataset, tokenizer, args.max_seq_length)
    model = FastLanguageModel.get_peft_model(
        model,
        r=8,
        target_modules=TARGET_MODULES,
        lora_alpha=16,
        lora_dropout=args.lora_dropout,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
        max_seq_length=args.max_seq_length,
    )
    model.config.use_cache = False
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    trainable_parameters, total_parameters = model.get_nb_trainable_parameters()
    if not trainable or trainable_parameters == 0:
        raise RuntimeError("Unsloth produced no trainable LoRA parameters")

    def generate_probe() -> str:
        FastLanguageModel.for_inference(model)
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": PROBE_PROMPT}],
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )
        prompt = token_ids(prompt).to("cuda")
        model.eval()
        with torch.inference_mode():
            output = model.generate(prompt, max_new_tokens=64, do_sample=False, pad_token_id=tokenizer.pad_token_id)
        return tokenizer.decode(output[0, prompt.shape[1]:], skip_special_tokens=True).strip()

    model_load_seconds = time.perf_counter() - setup_started
    probe_started = time.perf_counter()
    before_probe = generate_probe()
    before_probe_seconds = time.perf_counter() - probe_started
    FastLanguageModel.for_training(model)
    model.config.use_cache = False
    optimizer = torch.optim.AdamW(trainable, lr=2e-4, weight_decay=0.0)
    order = list(range(len(rows)))
    random.Random(args.seed).shuffle(order)
    losses: list[float] = []
    torch.cuda.reset_peak_memory_stats()
    training_started = time.perf_counter()
    model.train()
    for step in range(args.steps):
        row = rows[order[step % len(rows)]]
        input_ids = torch.tensor([row["input_ids"]], dtype=torch.long, device="cuda")
        labels = torch.tensor([row["labels"]], dtype=torch.long, device="cuda")
        attention_mask = torch.ones_like(input_ids)
        optimizer.zero_grad(set_to_none=True)
        loss = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels).loss
        if not torch.isfinite(loss):
            raise RuntimeError(f"Non-finite loss at step {step + 1}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        optimizer.step()
        losses.append(float(loss.detach().cpu()))
        print(f"step={step + 1}/{args.steps} loss={losses[-1]:.6f}", flush=True)
    torch.cuda.synchronize()
    training_seconds = time.perf_counter() - training_started
    adapter_path.mkdir(parents=True, exist_ok=False)
    model.save_pretrained(adapter_path, safe_serialization=True)
    adapter_file = adapter_path / "adapter_model.safetensors"
    if not adapter_file.is_file():
        raise RuntimeError("Unsloth did not produce adapter_model.safetensors")
    probe_started = time.perf_counter()
    after_probe = generate_probe()
    after_probe_seconds = time.perf_counter() - probe_started
    torch.cuda.synchronize()
    manifest_path = args.model_dir / "download-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    git_sha, source_tree_dirty = git_provenance()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": "unsloth-qlora-smoke",
        "method": "Unsloth QLoRA",
        "model": args.model_id,
        "model_revision": manifest.get("revision", "unrecorded-local-model"),
        "model_parameters": "0.49B",
        "quantization": "bitsandbytes NF4 with double quantization",
        "compute_dtype": "float16",
        "runtime": "Transformers + Unsloth + bitsandbytes",
        "storage_profile": os.environ.get("QLORA_STORAGE_PROFILE", "unspecified"),
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "transformers_version": transformers.__version__,
        "peft_version": peft.__version__,
        "bitsandbytes_version": bitsandbytes.__version__,
        "unsloth_version": unsloth.__version__,
        "unsloth_zoo_version": unsloth_zoo.__version__,
        "xformers_version": __import__("xformers").__version__,
        "gpu": torch.cuda.get_device_name(0),
        "dataset_sha256": sha256(args.dataset),
        "dataset_rows": len(rows),
        "max_seq_length": args.max_seq_length,
        "batch_size": 1,
        "gradient_accumulation_steps": 1,
        "gradient_checkpointing": "unsloth",
        "optimizer": "torch.optim.AdamW (32-bit states)",
        "learning_rate": 2e-4,
        "lora_rank": 8,
        "lora_alpha": 16,
        "lora_dropout": args.lora_dropout,
        "lora_target_modules": TARGET_MODULES,
        "trainable_parameters": trainable_parameters,
        "total_parameters": total_parameters,
        "seed": args.seed,
        "warmup": args.warmup,
        "max_steps": args.steps,
        "steps_completed": len(losses),
        "initial_loss": losses[0],
        "final_loss": losses[-1],
        "losses": losses,
        "model_load_seconds": round(model_load_seconds, 3),
        "baseline_probe_seconds": round(before_probe_seconds, 3),
        "training_seconds": round(training_seconds, 3),
        "post_training_probe_seconds": round(after_probe_seconds, 3),
        "import_seconds": round(imports_seconds, 3),
        "total_seconds": round(time.perf_counter() - process_started, 3),
        "vram_peak_allocated_mib": round(torch.cuda.max_memory_allocated() / 1048576, 1),
        "vram_peak_reserved_mib": round(torch.cuda.max_memory_reserved() / 1048576, 1),
        "baseline_probe": before_probe,
        "trained_probe": after_probe,
        "trained_probe_static_add_ast_pass": expected_add_function(after_probe),
        "adapter_path": str(adapter_path),
        "adapter_bytes": adapter_file.stat().st_size,
        "adapter_sha256": sha256(adapter_file),
        "git_sha": git_sha,
        "source_tree_dirty": source_tree_dirty,
        "success": successful_unsloth_run(len(losses), args.steps, losses, after_probe),
    }
    args.result_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.result_jsonl.open("a", encoding="utf-8") as target:
        target.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True), flush=True)
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
