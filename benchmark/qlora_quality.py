#!/usr/bin/env python3
"""Compare a local LoRA/QLoRA base model and adapter on held-out code tasks."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.provenance import git_provenance

DEFAULT_MODEL = Path(os.environ.get("TRAINING_MODEL_DIR", Path.home() / "local-llm-benchmark/models/Qwen2.5-Coder-0.5B-Instruct"))
DEFAULT_DATASET = ROOT / "benchmark/data/qlora-quality-heldout.jsonl"
DEFAULT_OUTPUT = Path(os.environ.get("QLORA_QUALITY_RESULT_JSONL", Path.home() / "local-llm-benchmark/results/raw/qlora-quality.jsonl"))

ALLOWED_AST_NODES = {
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.If, ast.Pass,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.BoolOp, ast.IfExp, ast.Call, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.Pow, ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or, ast.Lt, ast.LtE, ast.Gt,
    ast.GtE, ast.Eq, ast.NotEq,
}
SAFE_CALLS = {"abs", "max", "min"}


def require_ext4(path: Path, label: str) -> None:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.exists():
        raise FileNotFoundError(f"{label} path does not exist: {path}")
    filesystem = subprocess.run(
        ["findmnt", "-n", "-o", "FSTYPE", "-T", str(candidate)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if filesystem != "ext4":
        raise RuntimeError(f"{label} must be on SSD-backed WSL ext4, found {filesystem}: {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_id_from_manifest(manifest: dict) -> str:
    return manifest.get("repo_id") or manifest.get("repo") or "Qwen/Qwen2.5-Coder-0.5B-Instruct"


def load_tasks(path: Path) -> list[dict]:
    tasks = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        task = json.loads(line)
        required = {"task_id", "function", "arguments", "prompt", "reference", "tests"}
        if not isinstance(task, dict) or not required <= task.keys() or not task["tests"]:
            raise ValueError(f"Invalid held-out task at line {line_number}")
        tasks.append(task)
    if not tasks:
        raise ValueError("Held-out task set is empty")
    return tasks


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return text


def run_generated_code(source: str, task: dict) -> tuple[bool, int, str | None]:
    """Run a narrow expression-only function; reject imports, calls, attributes and I/O."""
    source = strip_code_fence(source)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, 0, f"syntax: {exc.msg}"
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return False, 0, "output must contain exactly one function definition"
    function = tree.body[0]
    if function.name != task["function"]:
        return False, 0, f"expected function {task['function']}, got {function.name}"
    if [arg.arg for arg in function.args.args] != task["arguments"] or function.args.defaults or function.args.kw_defaults:
        return False, 0, "function arguments do not match the task signature"
    for node in ast.walk(tree):
        if type(node) not in ALLOWED_AST_NODES:
            return False, 0, f"unsupported syntax: {type(node).__name__}"
        if isinstance(node, ast.Name) and node.id not in {task["function"], *task["arguments"], *SAFE_CALLS}:
            return False, 0, f"unknown identifier: {node.id}"
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                return False, 0, "only direct calls to abs, max, and min are allowed"
            if node.func.id not in SAFE_CALLS:
                return False, 0, f"call to unsupported function: {node.func.id}"
            if node.keywords:
                return False, 0, "keyword arguments are not allowed in generated calls"
    namespace: dict[str, object] = {}
    try:
        exec(compile(tree, "<held-out-model-output>", "exec"), {"__builtins__": {"abs": abs, "max": max, "min": min}}, namespace)
        function_impl = namespace[task["function"]]
        passed = 0
        for case in task["tests"]:
            actual = function_impl(*case["inputs"])
            expected = case["expected"]
            if type(actual) is type(expected) and actual == expected:
                passed += 1
        return passed == len(task["tests"]), passed, None
    except Exception as exc:  # generated implementation errors become measured failures
        return False, 0, f"execution: {type(exc).__name__}: {exc}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--method", choices=("qlora", "lora"), default="qlora")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    return args


def main() -> int:
    args = parse_args()
    require_ext4(ROOT, "source checkout")
    require_ext4(args.model_dir, "model weights")
    require_ext4(args.adapter, "adapter")
    require_ext4(args.dataset, "quality dataset")
    require_ext4(args.output.parent, "result directory")
    if not (args.model_dir / "download-manifest.json").is_file():
        raise FileNotFoundError(f"Pinned local model manifest is missing: {args.model_dir}")
    adapter_file = args.adapter / "adapter_model.safetensors"
    if not adapter_file.is_file():
        raise FileNotFoundError(f"PEFT adapter weights are missing: {adapter_file}")
    tasks = load_tasks(args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available() or "RTX 3070" not in torch.cuda.get_device_name(0):
        raise RuntimeError("This experiment requires the visible RTX 3070 CUDA device")
    model_manifest = json.loads((args.model_dir / "download-manifest.json").read_text(encoding="utf-8"))
    git_sha, source_dirty = git_provenance(ROOT)
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    quantization_label = "bitsandbytes NF4 with double quantization"
    base_precision = "NF4"
    if args.method == "qlora":
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.model_dir, quantization_config=quant_config, dtype=torch.float16,
            device_map={"": 0}, low_cpu_mem_usage=True, local_files_only=True,
        )
    else:
        quantization_label = "none (FP16 base weights)"
        base_precision = "FP16"
        model = AutoModelForCausalLM.from_pretrained(
            args.model_dir, dtype=torch.float16, device_map={"": 0},
            low_cpu_mem_usage=True, local_files_only=True,
        )

    def reference_nll(task: dict) -> tuple[float, int]:
        messages = [
            {"role": "system", "content": "You write correct Python code and follow output constraints exactly."},
            {"role": "user", "content": task["prompt"]},
        ]
        prompt_ids = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
        )["input_ids"].to("cuda")
        full_ids = tokenizer.apply_chat_template(
            messages + [{"role": "assistant", "content": task["reference"]}],
            tokenize=True, add_generation_prompt=False, return_tensors="pt",
        )["input_ids"].to("cuda")
        if not torch.equal(full_ids[:, :prompt_ids.shape[1]], prompt_ids):
            raise ValueError(f"Reference completion boundary mismatch for task {task['task_id']}")
        labels = full_ids.clone()
        labels[:, :prompt_ids.shape[1]] = -100
        with torch.inference_mode():
            output = model(input_ids=full_ids, labels=labels)
        tokens = int((labels != -100).sum().item())
        return float(output.loss.detach().cpu()), tokens

    def generate(prompt: str) -> tuple[str, int, int, float]:
        messages = [
            {"role": "system", "content": "You write correct Python code and follow output constraints exactly."},
            {"role": "user", "content": prompt},
        ]
        encoded = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
        )["input_ids"].to("cuda")
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                encoded, max_new_tokens=128, do_sample=False,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
        elapsed = time.perf_counter() - started
        result_ids = generated[0, encoded.shape[1]:]
        return tokenizer.decode(result_ids, skip_special_tokens=True), int(encoded.shape[1]), int(result_ids.numel()), elapsed

    rows: list[dict] = []
    model.eval()
    if args.warmup:
        generate("Write a Python function that returns x + 1. Output code only.")
    base_phase = "base_nf4" if args.method == "qlora" else "base_fp16"
    adapter_phase = "qlora_adapter" if args.method == "qlora" else "lora_adapter"
    for phase in (base_phase, adapter_phase):
        if phase == adapter_phase:
            model = PeftModel.from_pretrained(model, args.adapter, is_trainable=False, local_files_only=True)
            model.eval()
        for repeat in range(1, args.repeats + 1):
            for task in tasks:
                reference_loss, reference_tokens = reference_nll(task)
                output, prompt_tokens, completion_tokens, elapsed = generate(task["prompt"])
                success, passed, error = run_generated_code(output, task)
                row = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "experiment": "finetune_heldout_quality",
                    "phase": phase,
                    "finetune_method": args.method,
                    "base_weight_precision": base_precision,
                    "repeat": repeat,
                    "task_id": task["task_id"],
                    "model": model_id_from_manifest(model_manifest),
                    "model_revision": model_manifest.get("revision"),
                    "quantization": quantization_label,
                    "runtime": "Transformers + PEFT + bitsandbytes",
                    "torch_version": torch.__version__,
                    "transformers_version": __import__("transformers").__version__,
                    "peft_version": __import__("peft").__version__,
                    "bitsandbytes_version": __import__("bitsandbytes").__version__,
                    "gpu": torch.cuda.get_device_name(0),
                    "storage_profile": "ssd-wsl-ext4-c",
                    "git_sha": git_sha,
                    "source_tree_dirty": source_dirty,
                    "context_window_tokens": int(model.config.max_position_embeddings),
                    "max_new_tokens": 128,
                    "do_sample": False,
                    "reference_nll_per_token": round(reference_loss, 6),
                    "reference_perplexity": round(float(torch.exp(torch.tensor(reference_loss)).item()), 6),
                    "reference_tokens": reference_tokens,
                    "adapter_sha256": sha256_file(adapter_file) if phase == adapter_phase else None,
                    "dataset_sha256": sha256_file(args.dataset),
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "generation_seconds": round(elapsed, 4),
                    "tests_passed": passed,
                    "tests_total": len(task["tests"]),
                    "success": success,
                    "error": error,
                    "output": output,
                }
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)
    with args.output.open("a", encoding="utf-8") as destination:
        for row in rows:
            destination.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    del model
    torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
