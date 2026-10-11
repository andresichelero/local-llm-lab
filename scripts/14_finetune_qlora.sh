#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAINING_ENV_DIR="${TRAINING_ENV_DIR:-/mnt/e/local-llm-envs/training}"
PYTHON="${TRAINING_PYTHON_BIN:-$TRAINING_ENV_DIR/bin/python}"
MODEL_DIR="${TRAINING_MODEL_DIR:-${MODEL_DIR:-/mnt/e/local-llm-models}/Qwen2.5-Coder-0.5B-Instruct}"
MODEL_ID="${TRAINING_MODEL_ID:-Qwen/Qwen2.5-Coder-0.5B-Instruct}"
MODEL_PARAMETERS="${TRAINING_MODEL_PARAMETERS:-0.49B}"
OUTPUT_ROOT="${QLORA_OUTPUT_ROOT:-/mnt/e/local-llm-results/qlora}"
RESULT_JSONL="${QLORA_RESULT_JSONL:-$ROOT/results/raw/qlora-smoke.jsonl}"
RESOURCE_JSONL="${QLORA_RESOURCE_JSONL:-$ROOT/results/raw/qlora-smoke-resources.jsonl}"
LOG_PATH="${QLORA_LOG_PATH:-$ROOT/logs/qlora-smoke-$(date -u +%Y%m%dT%H%M%SZ).log}"
STEPS="${QLORA_STEPS:-8}"
MAX_SEQ_LENGTH="${QLORA_MAX_SEQ_LENGTH:-192}"
METHOD="${TRAINING_METHOD:-qlora}"
DRY_RUN=0
while (($#)); do
  case "$1" in
    --help) "$PYTHON" "$ROOT/benchmark/qlora_smoke.py" --help; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --steps) (($# >= 2)) || { echo "--steps needs a value" >&2; exit 2; }; STEPS="$2"; shift 2 ;;
    --max-seq-length) (($# >= 2)) || { echo "--max-seq-length needs a value" >&2; exit 2; }; MAX_SEQ_LENGTH="$2"; shift 2 ;;
    --method) (($# >= 2)) || { echo "--method needs lora or qlora" >&2; exit 2; }; METHOD="$2"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
ARGS=(--model-dir "$MODEL_DIR" --model-id "$MODEL_ID" --model-parameters "$MODEL_PARAMETERS" --method "$METHOD" --output-root "$OUTPUT_ROOT" --result-jsonl "$RESULT_JSONL" --steps "$STEPS" --max-seq-length "$MAX_SEQ_LENGTH")
if ((DRY_RUN)); then
  "$PYTHON" "$ROOT/benchmark/qlora_smoke.py" "${ARGS[@]}" --dry-run
  exit 0
fi
[[ -x "$PYTHON" ]] || { echo "Training Python not found: $PYTHON" >&2; exit 1; }
[[ -f "$MODEL_DIR/model.safetensors" || -f "$MODEL_DIR/model.safetensors.index.json" ]] || { echo "Pinned training model is missing; run scripts/07_download_training_model.sh first." >&2; exit 1; }
mkdir -p "$(dirname "$LOG_PATH")"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/tmp/local-llm-training-pycache}"
export HF_HOME="${HF_HOME:-/mnt/e/local-llm-cache/huggingface}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
python3 "$ROOT/benchmark/resource_sampler.py" --output "$RESOURCE_JSONL" --interval 1 &
SAMPLER_PID=$!
cleanup() { kill "$SAMPLER_PID" 2>/dev/null || true; wait "$SAMPLER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
"$PYTHON" "$ROOT/benchmark/qlora_smoke.py" "${ARGS[@]}" 2>&1 | tee -a "$LOG_PATH"
