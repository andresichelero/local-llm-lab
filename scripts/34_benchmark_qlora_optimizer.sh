#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
TRAINING_ENV_DIR="${TRAINING_ENV_DIR:-$BENCH_STORAGE_ROOT/envs/training}"
PYTHON="${TRAINING_PYTHON_BIN:-$TRAINING_ENV_DIR/bin/python}"
MODEL_DIR="${TRAINING_MODEL_DIR:-$BENCH_STORAGE_ROOT/models/Qwen2.5-Coder-7B-Instruct}"
DATASET="${QLORA_DATASET:-$ROOT/benchmark/data/qlora-smoke.jsonl}"
OPTIMIZER=adamw32
DRY_RUN=0

usage() {
  echo "Usage: $0 [--optimizer adamw32|adamw8bit] [--dry-run]"
  echo "Runs one warm-up and three measured 8-step QLoRA trainings of the pinned 7B model on WSL ext4."
}

while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --optimizer) (($# >= 2)) || { echo "--optimizer needs adamw32 or adamw8bit" >&2; exit 2; }; OPTIMIZER="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ "$OPTIMIZER" == adamw32 || "$OPTIMIZER" == adamw8bit ]] || { echo "--optimizer must be adamw32 or adamw8bit" >&2; exit 2; }

source "$ROOT/scripts/lib/ssd_preflight.sh"
for path in "$ROOT" "$BENCH_STORAGE_ROOT" "$TRAINING_ENV_DIR" "$PYTHON" "$MODEL_DIR" "$DATASET"; do
  require_wsl_ext4_path "$path" "optimizer benchmark input or runtime path"
done
[[ -x "$PYTHON" ]] || { echo "Training Python not found: $PYTHON" >&2; exit 1; }
[[ -f "$MODEL_DIR/model.safetensors.index.json" ]] || { echo "Pinned sharded 7B model index missing: $MODEL_DIR" >&2; exit 1; }

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
printf 'storage=WSL ext4 on C: only\nmodel=%s\noptimizer=%s\nsteps=8\nsequence_length=192\nwarmups=1\nrepetitions=3\nrun_id=%s\n' \
  "$MODEL_DIR" "$OPTIMIZER" "$RUN_ID"
if ((DRY_RUN)); then
  QLORA_RUN_ID="$RUN_ID-$OPTIMIZER-dryrun" TRAINING_MODEL_DIR="$MODEL_DIR" \
    TRAINING_MODEL_ID=Qwen/Qwen2.5-Coder-7B-Instruct TRAINING_MODEL_PARAMETERS=7.62B \
    TRAINING_OPTIMIZER="$OPTIMIZER" bash "$ROOT/scripts/14_finetune_qlora.sh" \
    --method qlora --optimizer "$OPTIMIZER" --steps 8 --max-seq-length 192 --dry-run
  exit 0
fi

for label in warmup rep-1 rep-2 rep-3; do
  run_tag="$RUN_ID-$OPTIMIZER-$label"
  echo "run=$label optimizer=$OPTIMIZER"
  QLORA_RUN_ID="$run_tag" \
    QLORA_RESULT_JSONL="$BENCH_STORAGE_ROOT/results/raw/qwen25-coder-7b-$run_tag.jsonl" \
    QLORA_RESOURCE_JSONL="$BENCH_STORAGE_ROOT/results/raw/qwen25-coder-7b-$run_tag-resources.jsonl" \
    QLORA_LOG_PATH="$BENCH_STORAGE_ROOT/logs/qwen25-coder-7b-$run_tag.log" \
    TRAINING_MODEL_DIR="$MODEL_DIR" \
    TRAINING_MODEL_ID=Qwen/Qwen2.5-Coder-7B-Instruct \
    TRAINING_MODEL_PARAMETERS=7.62B TRAINING_OPTIMIZER="$OPTIMIZER" \
    bash "$ROOT/scripts/14_finetune_qlora.sh" \
      --method qlora --optimizer "$OPTIMIZER" --steps 8 --max-seq-length 192
done
