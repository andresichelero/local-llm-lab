#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
TRAINING_ENV_DIR="${TRAINING_ENV_DIR:-$BENCH_STORAGE_ROOT/envs/training}"
PYTHON="${TRAINING_PYTHON_BIN:-$TRAINING_ENV_DIR/bin/python}"
MODEL_DIR="${TRAINING_MODEL_DIR:-$BENCH_STORAGE_ROOT/models/Qwen2.5-Coder-0.5B-Instruct}"
DATASET="$ROOT/benchmark/data/qlora-smoke.jsonl"
QUALITY_DATASET="$ROOT/benchmark/data/qlora-quality-heldout.jsonl"
DRY_RUN=0
METHOD=qlora
while (($#)); do
  case "$1" in
    --help|-h)
      echo "Usage: $0 [--method qlora|lora] [--dry-run]"
      echo "Runs one 16-step LoRA/QLoRA smoke and a 3-repeat held-out base/adapter quality probe on WSL ext4."
      exit 0
      ;;
    --dry-run) DRY_RUN=1; shift ;;
    --method) (($# >= 2)) || { echo "--method needs qlora or lora" >&2; exit 2; }; METHOD="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ "$METHOD" == qlora || "$METHOD" == lora ]] || { echo "--method must be qlora or lora" >&2; exit 2; }

source "$ROOT/scripts/lib/ssd_preflight.sh"
for path in "$ROOT" "$BENCH_STORAGE_ROOT" "$TRAINING_ENV_DIR" "$PYTHON" "$MODEL_DIR" "$DATASET" "$QUALITY_DATASET"; do
  require_wsl_ext4_path "$path" "benchmark input or runtime path"
done
[[ -x "$PYTHON" ]] || { echo "Training Python not found: $PYTHON" >&2; exit 1; }
[[ -f "$MODEL_DIR/model.safetensors" ]] || { echo "Pinned 0.5B model weights missing from SSD: $MODEL_DIR" >&2; exit 1; }

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
TRAIN_RESULT="$BENCH_STORAGE_ROOT/results/raw/$METHOD-quality-train-$RUN_ID.jsonl"
TRAIN_LOG="$BENCH_STORAGE_ROOT/logs/$METHOD-quality-train-$RUN_ID.log"
TRAIN_RESOURCES="$BENCH_STORAGE_ROOT/results/raw/$METHOD-quality-train-resources-$RUN_ID.jsonl"
QUALITY_RESULT="$BENCH_STORAGE_ROOT/results/raw/$METHOD-quality-heldout-$RUN_ID.jsonl"
QUALITY_RESOURCES="$BENCH_STORAGE_ROOT/results/raw/$METHOD-quality-resources-$RUN_ID.jsonl"
QUALITY_LOG="$BENCH_STORAGE_ROOT/logs/$METHOD-quality-$RUN_ID.log"

for path in "$TRAIN_RESULT" "$TRAIN_LOG" "$TRAIN_RESOURCES" "$QUALITY_RESULT" "$QUALITY_RESOURCES" "$QUALITY_LOG"; do
  require_wsl_ext4_destination "$path" "benchmark output path"
done

printf 'storage=WSL ext4 on C: only\nmethod=%s\nmodel=%s\ndataset=%s\nheldout=%s\nsteps=16\nsequence_length=192\neval_repeats=3\nrun_id=%s\n' \
  "$METHOD" "$MODEL_DIR" "$DATASET" "$QUALITY_DATASET" "$RUN_ID"
if ((DRY_RUN)); then
  echo "SSD preflight passed; no training or evaluation started."
  exit 0
fi

export BENCH_STORAGE_ROOT TRAINING_ENV_DIR TRAINING_PYTHON_BIN="$PYTHON" TRAINING_MODEL_DIR="$MODEL_DIR"
export TRAINING_MODEL_ID=Qwen/Qwen2.5-Coder-0.5B-Instruct TRAINING_MODEL_PARAMETERS=0.49B
export QLORA_STEPS=16 QLORA_MAX_SEQ_LENGTH=192 TRAINING_METHOD="$METHOD"
export QLORA_OUTPUT_ROOT="$BENCH_STORAGE_ROOT/results/qlora"
export QLORA_RESULT_JSONL="$TRAIN_RESULT" QLORA_LOG_PATH="$TRAIN_LOG"
export QLORA_RESOURCE_JSONL="$TRAIN_RESOURCES" QLORA_STORAGE_PROFILE=ssd-wsl-ext4-c

bash "$ROOT/scripts/14_finetune_qlora.sh" --method "$METHOD" --steps 16 --max-seq-length 192 2>&1 | tee -a "$TRAIN_LOG"
cp "$TRAIN_RESULT" "$ROOT/results/raw/$(basename "$TRAIN_RESULT")"
cp "$TRAIN_RESOURCES" "$ROOT/results/raw/$(basename "$TRAIN_RESOURCES")"
cp "$TRAIN_LOG" "$ROOT/logs/$(basename "$TRAIN_LOG")"

ADAPTER_PATH="$("$PYTHON" - "$TRAIN_RESULT" <<'PY'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
if not rows or not rows[-1].get("success"):
    raise SystemExit("training did not produce a successful adapter")
print(rows[-1]["adapter_path"])
PY
)"
require_wsl_ext4_path "$ADAPTER_PATH" "adapter checkpoint"
require_wsl_ext4_path "$ADAPTER_PATH/adapter_model.safetensors" "adapter weights"

python3 "$ROOT/benchmark/resource_sampler.py" --output "$QUALITY_RESOURCES" --interval 1 &
SAMPLER_PID=$!
cleanup() { kill "$SAMPLER_PID" 2>/dev/null || true; wait "$SAMPLER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
"$PYTHON" "$ROOT/benchmark/qlora_quality.py" \
  --model-dir "$MODEL_DIR" --adapter "$ADAPTER_PATH" --dataset "$QUALITY_DATASET" \
  --output "$QUALITY_RESULT" --method "$METHOD" --repeats 3 --warmup 2>&1 | tee -a "$QUALITY_LOG"
cleanup
trap - EXIT INT TERM

cp "$QUALITY_RESULT" "$ROOT/results/raw/$(basename "$QUALITY_RESULT")"
cp "$QUALITY_RESOURCES" "$ROOT/results/raw/$(basename "$QUALITY_RESOURCES")"
cp "$QUALITY_LOG" "$ROOT/logs/$(basename "$QUALITY_LOG")"
"$PYTHON" "$ROOT/benchmark/summarize_qlora_quality.py" \
  --input "$QUALITY_RESULT" \
  --csv "$ROOT/results/csv/$METHOD-quality-heldout-$RUN_ID.csv" \
  --report "$ROOT/results/reports/$METHOD-quality-heldout-$RUN_ID.md"
echo "Results stored on the SSD run directory and copied into the source tree: $RUN_ID"
