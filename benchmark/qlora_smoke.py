#!/usr/bin/env python3
"""Run a deterministic tiny LoRA/QLoRA SFT smoke test; save only adapters outside Git."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.provenance import git_provenance

BENCH_STORAGE_ROOT = Path(os.environ.get("BENCH_STORAGE_ROOT", Path.home() / "local-llm-benchmark"))
DEFAULT_MODEL = Path(os.environ.get("TRAINING_MODEL_DIR", BENCH_STORAGE_ROOT / "models/Qwen2.5-Coder-0.5B-Instruct"))
DEFAULT_DATASET = ROOT / "benchmark/data/qlora-smoke.jsonl"
DEFAULT_OUTPUT = Path(os.environ.get("QLORA_OUTPUT_ROOT", BENCH_STORAGE_ROOT / "results/qlora"))
DEFAULT_RESULT = Path(os.environ.get("QLORA_RESULT_JSONL", BENCH_STORAGE_ROOT / "results/raw/qlora-smoke.jsonl"))
DEFAULT_MODEL_ID = os.environ.get("TRAINING_MODEL_ID", "Qwen/Qwen2.5-Coder-0.5B-Instruct")
DEFAULT_MODEL_PARAMETERS = os.environ.get("TRAINING_MODEL_PARAMETERS", "0.49B")
PROBE_PROMPT = "Write a Python function called add(a, b) that returns their sum. Output only Python code."


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
    if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.BinOp):
        return False
    value = statement.value
    if not isinstance(value.op, ast.Add):
        return False
    names = (value.left.id, value.right.id) if isinstance(value.left, ast.Name) and isinstance(value.right, ast.Name) else (None, None)
    return names in {("a", "b"), ("b", "a")}


def git_metadata() -> tuple[str, bool]:
    return git_provenance(ROOT)


def successful_training(
    steps_completed: int,
    expected_steps: int,
    losses: list[float],
    trained_probe_passed: bool,
) -> bool:
    return (
        steps_completed == expected_steps
        and len(losses) == expected_steps
        and all(math.isfinite(value) for value in losses)
        and trained_probe_passed
    )


def valid_lora_config(rank: int, alpha: int) -> bool:
    return rank > 0 and alpha > 0


def load_rows(dataset: Path, tokenizer: object, max_length: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(dataset.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        messages = row.get("messages")
        if not isinstance(messages, list) or len(messages) < 2 or messages[-1].get("role") != "assistant":
            raise ValueError(f"Invalid conversational training example at line {line_number}")
        prompt_ids = tokenizer.apply_chat_template(
            messages[:-1], tokenize=True, add_generation_prompt=True
        )["input_ids"]
        full_ids = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=False
        )["input_ids"]
        full_ids = full_ids[:max_length]
        if full_ids[: len(prompt_ids)] != prompt_ids[: len(full_ids)]:
            raise ValueError(f"Prompt/completion token boundary does not match the chat template at line {line_number}")
        prompt_length = min(len(prompt_ids), len(full_ids))
        labels = [-100] * prompt_length + full_ids[prompt_length:]
        if not any(token != -100 for token in labels):
            raise ValueError(f"No completion tokens remain after truncation at line {line_number}")
        rows.append({"input_ids": full_ids, "labels": labels})
    if not rows:
        raise ValueError("The training dataset is empty")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--model-parameters", default=DEFAULT_MODEL_PARAMETERS)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--result-jsonl", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--method", choices=("lora", "qlora"), default="qlora")
    parser.add_argument("--optimizer", choices=("adamw32", "adamw8bit"), default="adamw32")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--max-seq-length", type=int, default=int(os.environ.get("TRAINING_MAX_SEQ_LENGTH", "192")))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.steps < 1 or args.max_seq_length < 16 or not valid_lora_config(args.rank, args.alpha):
        parser.error("--steps, --rank, and --alpha must be positive; --max-seq-length must be at least 16")
    model_slug = args.model_id.rsplit("/", 1)[-1].lower().replace(".", "").replace("-instruct", "")
    method_slug = "nf4" if args.method == "qlora" else "fp16"
    adapter_path = args.output_root / f"{model_slug}-{args.method}-{method_slug}-r{args.rank}-a{args.alpha}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-seed{args.seed}"
    preflight = {
        "model_dir": str(args.model_dir),
        "model": args.model_id,
        "model_parameters": args.model_parameters,
        "method": args.method,
        "optimizer": args.optimizer,
        "dataset": str(args.dataset),
        "steps": args.steps,
        "seed": args.seed,
        "lora_rank": args.rank,
        "lora_alpha": args.alpha,
        "max_seq_length": args.max_seq_length,
        "adapter_output": str(adapter_path),
        "result_jsonl": str(args.result_jsonl),
    }
    print(json.dumps(preflight, sort_keys=True), flush=True)
    if args.dry_run:
        return 0
    if not any(args.model_dir.glob("*.safetensors")):
        raise FileNotFoundError(f"No safetensors model weights found in {args.model_dir}")
    if not args.dataset.is_file():
        raise FileNotFoundError(f"Dataset missing: {args.dataset}")

    process_started = time.perf_counter()
    imports_started = time.perf_counter()
    import bitsandbytes
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    imports_seconds = time.perf_counter() - imports_started

    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch does not see a CUDA device")
    if "RTX 3070" not in torch.cuda.get_device_name(0):
        raise RuntimeError(f"Unexpected CUDA device: {torch.cuda.get_device_name(0)}")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    setup_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    rows = load_rows(args.dataset, tokenizer, args.max_seq_length)
    if args.method == "qlora":
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.model_dir,
            quantization_config=quantization,
            dtype=torch.float16,
            device_map={"": 0},
            low_cpu_mem_usage=True,
            local_files_only=True,
        )
        model = prepare_model_for_kbit_training(
            model,
            use_gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
        )
        quantization_label = "bitsandbytes NF4 with double quantization"
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.model_dir,
            dtype=torch.float16,
            device_map={"": 0},
            low_cpu_mem_usage=True,
            local_files_only=True,
        )
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        model.enable_input_require_grads()
        quantization_label = "none (FP16 base weights)"
    model.config.use_cache = False
    gradient_checkpointing_kwargs = {"use_reentrant": False}
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj"]
    available_suffixes = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
    absent = [name for name in target_modules if name not in available_suffixes]
    if absent:
        raise RuntimeError(f"Expected LoRA target modules are absent: {absent}")
    model = get_peft_model(
        model,
        LoraConfig(
            r=args.rank,
            lora_alpha=args.alpha,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=target_modules,
        ),
    )
    trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
    trainable_parameters, total_parameters = model.get_nb_trainable_parameters()
    if not trainable or trainable_parameters == 0:
        raise RuntimeError("LoRA produced no trainable parameters")
    model.print_trainable_parameters()

    def generate_probe() -> str:
        model.config.use_cache = True
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": PROBE_PROMPT}],
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        )["input_ids"].to("cuda")
        model.eval()
        with torch.inference_mode():
            output = model.generate(prompt, max_new_tokens=64, do_sample=False, pad_token_id=tokenizer.pad_token_id)
        return tokenizer.decode(output[0, prompt.shape[1]:], skip_special_tokens=True).strip()

    load_seconds = time.perf_counter() - setup_started
    probe_start = time.perf_counter()
    before_probe = generate_probe()
    before_probe_seconds = time.perf_counter() - probe_start
    model.config.use_cache = False
    if args.optimizer == "adamw8bit":
        optimizer = bitsandbytes.optim.AdamW8bit(trainable, lr=2e-4, weight_decay=0.0)
        optimizer_label = "bitsandbytes.optim.AdamW8bit (8-bit states; min_8bit_size=4096)"
    else:
        optimizer = torch.optim.AdamW(trainable, lr=2e-4, weight_decay=0.0)
        optimizer_label = "torch.optim.AdamW (32-bit states)"
    order = list(range(len(rows)))
    random.Random(args.seed).shuffle(order)
    losses: list[float] = []
    torch.cuda.reset_peak_memory_stats()
    train_started = time.perf_counter()
    model.train()
    for step in range(args.steps):
        row = rows[order[step % len(order)]]
        input_ids = torch.tensor([row["input_ids"]], dtype=torch.long, device="cuda")
        labels = torch.tensor([row["labels"]], dtype=torch.long, device="cuda")
        attention_mask = torch.ones_like(input_ids)
        optimizer.zero_grad(set_to_none=True)
        output = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
        loss = output.loss
        if not torch.isfinite(loss):
            raise RuntimeError(f"Non-finite training loss at step {step + 1}")
        loss.backward()
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        optimizer.step()
        losses.append(float(loss.detach().cpu()))
        print(f"step={step + 1}/{args.steps} loss={losses[-1]:.6f}", flush=True)
    torch.cuda.synchronize()
    train_seconds = time.perf_counter() - train_started
    adapter_path.mkdir(parents=True, exist_ok=False)
    model.save_pretrained(adapter_path, safe_serialization=True)
    adapter_file = adapter_path / "adapter_model.safetensors"
    if not adapter_file.is_file():
        raise RuntimeError("PEFT did not produce adapter_model.safetensors")
    probe_start = time.perf_counter()
    after_probe = generate_probe()
    after_probe_seconds = time.perf_counter() - probe_start
    torch.cuda.synchronize()
    manifest_path = args.model_dir / "download-manifest.json"
    model_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    model_revision = model_manifest.get("revision", "unrecorded-local-model")
    git_sha, source_tree_dirty = git_metadata()
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": f"{args.method}-smoke",
        "method": "QLoRA" if args.method == "qlora" else "LoRA",
        "model": args.model_id,
        "model_revision": model_revision,
        "model_parameters": args.model_parameters,
        "quantization": quantization_label,
        "compute_dtype": "float16",
        "runtime": "Transformers + PEFT + bitsandbytes",
        "storage_profile": os.environ.get("QLORA_STORAGE_PROFILE", "unspecified"),
        "torch_version": torch.__version__,
        "transformers_version": __import__("transformers").__version__,
        "peft_version": __import__("peft").__version__,
        "bitsandbytes_version": __import__("bitsandbytes").__version__,
        "gpu": torch.cuda.get_device_name(0),
        "dataset": str(args.dataset.relative_to(ROOT)),
        "dataset_sha256": sha256(args.dataset),
        "dataset_rows": len(rows),
        "max_seq_length": args.max_seq_length,
        "batch_size": 1,
        "gradient_accumulation_steps": 1,
        "gradient_checkpointing": True,
        "gradient_checkpointing_kwargs": gradient_checkpointing_kwargs,
        "optimizer": optimizer_label,
        "learning_rate": 2e-4,
        "lora_rank": args.rank,
        "lora_alpha": args.alpha,
        "lora_target_modules": target_modules,
        "trainable_parameters": trainable_parameters,
        "total_parameters": total_parameters,
        "seed": args.seed,
        "max_steps": args.steps,
        "steps_completed": len(losses),
        "initial_loss": losses[0],
        "final_loss": losses[-1],
        "losses": losses,
        "model_load_seconds": round(load_seconds, 3),
        "baseline_probe_seconds": round(before_probe_seconds, 3),
        "training_seconds": round(train_seconds, 3),
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
        "success": successful_training(
            len(losses), args.steps, losses, expected_add_function(after_probe)
        ),
    }
    args.result_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with args.result_jsonl.open("a", encoding="utf-8") as target:
        target.write(json.dumps(record, sort_keys=True) + "\n")
    print(json.dumps(record, sort_keys=True), flush=True)
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
