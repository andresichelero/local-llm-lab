#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
TRAINING_ENV_DIR="${TRAINING_ENV_DIR:-$BENCH_STORAGE_ROOT/envs/training}"
PYTHON="${TRAINING_PYTHON_BIN:-$TRAINING_ENV_DIR/bin/python}"
MODEL_DIR="${TRAINING_MODEL_DIR:-$BENCH_STORAGE_ROOT/models/Qwen2.5-Coder-0.5B-Instruct}"
DATASET="$ROOT/benchmark/data/qlora-smoke.jsonl"
QUALITY_DATASET="$ROOT/benchmark/data/qlora-quality-heldout.jsonl"
RANKS="8,16,32"
STEPS=16
MAX_SEQ_LENGTH=192
WARMUP=1
REPEATS=3
DRY_RUN=0

usage() {
  echo "Usage: $0 [--ranks 8,16,32] [--steps N] [--dry-run]"
  echo "Runs sequential SSD-only QLoRA rank comparisons with one warm-up and three measured runs per rank, then held-out evaluation."
}

while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --ranks) (($# >= 2)) || { echo "--ranks needs a comma-separated value" >&2; exit 2; }; RANKS="$2"; shift 2 ;;
    --steps) (($# >= 2)) || { echo "--steps needs a value" >&2; exit 2; }; STEPS="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

IFS=, read -r -a RANK_LIST <<<"$RANKS"
((${#RANK_LIST[@]} > 0)) || { echo "No ranks selected" >&2; exit 2; }
for rank in "${RANK_LIST[@]}"; do [[ "$rank" =~ ^[1-9][0-9]*$ ]] || { echo "Invalid rank: $rank" >&2; exit 2; }; done

source "$ROOT/scripts/lib/ssd_preflight.sh"
for path in "$ROOT" "$BENCH_STORAGE_ROOT" "$TRAINING_ENV_DIR" "$PYTHON" "$MODEL_DIR" "$DATASET" "$QUALITY_DATASET"; do
  require_wsl_ext4_path "$path" "QLoRA rank experiment input or runtime path"
done
[[ -x "$PYTHON" ]] || { echo "Training Python not found: $PYTHON" >&2; exit 1; }
[[ -f "$MODEL_DIR/model.safetensors" ]] || { echo "Pinned 0.5B model weights missing: $MODEL_DIR" >&2; exit 1; }

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RAW_DIR="$BENCH_STORAGE_ROOT/results/raw/qlora-rank-$RUN_ID"
LOG_DIR="$BENCH_STORAGE_ROOT/logs/qlora-rank-$RUN_ID"
mkdir -p "$RAW_DIR" "$LOG_DIR"
require_wsl_ext4_path "$RAW_DIR" "rank results"
require_wsl_ext4_path "$LOG_DIR" "rank logs"
printf 'storage=WSL ext4 on C: only\nmodel=%s\nranks=%s\nsteps=%s\nsequence_length=%s\nwarmups=%s\nrepetitions=%s\nrun_id=%s\n' \
  "$MODEL_DIR" "$RANKS" "$STEPS" "$MAX_SEQ_LENGTH" "$WARMUP" "$REPEATS" "$RUN_ID"

if ((DRY_RUN)); then
  for rank in "${RANK_LIST[@]}"; do
    QLORA_RUN_ID="$RUN_ID-r${rank}-dryrun" TRAINING_MODEL_DIR="$MODEL_DIR" \
      QLORA_OUTPUT_ROOT="$BENCH_STORAGE_ROOT/results/qlora-rank-dryrun" \
      QLORA_RESULT_JSONL="$RAW_DIR/dryrun-r${rank}.jsonl" \
      bash "$ROOT/scripts/14_finetune_qlora.sh" --method qlora --optimizer adamw32 \
      --steps "$STEPS" --max-seq-length "$MAX_SEQ_LENGTH" --rank "$rank" \
      --alpha "$((rank * 2))" --dry-run
  done
  exit 0
fi

for rank in "${RANK_LIST[@]}"; do
  alpha=$((rank * 2))
  adapter=""
  for label in warmup rep-1 rep-2 rep-3; do
    run_tag="$RUN_ID-r${rank}-$label"
    record="$RAW_DIR/train-r${rank}-$label.jsonl"
    echo "training rank=$rank alpha=$alpha run=$label"
    QLORA_RUN_ID="$run_tag" QLORA_COPY_RESULTS_TO_REPO=0 QLORA_OUTPUT_ROOT="$BENCH_STORAGE_ROOT/results/qlora-rank-$RUN_ID/adapters" \
      QLORA_RESULT_JSONL="$record" QLORA_RESOURCE_JSONL="$RAW_DIR/resources-r${rank}-$label.jsonl" \
      QLORA_LOG_PATH="$LOG_DIR/train-r${rank}-$label.log" TRAINING_MODEL_DIR="$MODEL_DIR" \
      TRAINING_MODEL_ID=Qwen/Qwen2.5-Coder-0.5B-Instruct TRAINING_MODEL_PARAMETERS=0.49B \
      TRAINING_METHOD=qlora TRAINING_OPTIMIZER=adamw32 \
      bash "$ROOT/scripts/14_finetune_qlora.sh" --method qlora --optimizer adamw32 \
      --steps "$STEPS" --max-seq-length "$MAX_SEQ_LENGTH" --rank "$rank" --alpha "$alpha"
    adapter="$("$PYTHON" -c 'import json,sys; print(json.loads(open(sys.argv[1],encoding="utf-8").read().splitlines()[-1])["adapter_path"])' "$record")"
  done
  echo "held-out evaluation rank=$rank adapter=$adapter"
  QLORA_QUALITY_RESULT_JSONL="$RAW_DIR/quality-r${rank}.jsonl" \
    "$PYTHON" "$ROOT/benchmark/qlora_quality.py" --model-dir "$MODEL_DIR" --adapter "$adapter" \
    --dataset "$QUALITY_DATASET" --output "$RAW_DIR/quality-r${rank}.jsonl" --method qlora \
    --adapter-training-backend transformers-peft --adapter-training-optimizer adamw32 \
    --adapter-training-rank "$rank" --adapter-training-alpha "$alpha" --repeats "$REPEATS" --warmup \
    >"$LOG_DIR/quality-r${rank}.jsonl" 2>"$LOG_DIR/quality-r${rank}.stderr.log"
done

REPO_RAW_DIR="$ROOT/results/raw/qlora-rank-sweep-$RUN_ID"
mkdir -p "$REPO_RAW_DIR"
cp "$RAW_DIR"/*.jsonl "$REPO_RAW_DIR/"
REPO_LOG_DIR="$ROOT/logs/qlora-rank-sweep-$RUN_ID"
mkdir -p "$REPO_LOG_DIR"
cp "$LOG_DIR"/* "$REPO_LOG_DIR/"
echo "Completed SSD-only rank series in $RAW_DIR; adapter artifacts remain under $BENCH_STORAGE_ROOT/results/qlora-rank-$RUN_ID/adapters"
