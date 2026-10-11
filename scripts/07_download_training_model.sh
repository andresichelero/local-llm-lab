#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
MODEL_DIR="${MODEL_DIR:-$BENCH_STORAGE_ROOT/models}"
PROFILE="qwen25-coder-0.5b"
DRY_RUN=0
while (($#)); do
  case "$1" in
    --help) echo "Usage: MODEL_DIR=$BENCH_STORAGE_ROOT/models $0 [--profile qwen25-coder-0.5b|qwen25-coder-7b] [--dry-run]"; exit 0 ;;
    --profile) (($# >= 2)) || { echo "--profile needs a value" >&2; exit 2; }; PROFILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
ARGS=(--model-dir "$MODEL_DIR" --profile "$PROFILE")
DOWNLOAD_LOG="$BENCH_STORAGE_ROOT/results/raw/model-downloads-training.jsonl"
mkdir -p "$(dirname "$DOWNLOAD_LOG")"
((DRY_RUN)) && ARGS+=(--dry-run)
BENCH_STORAGE_ROOT="$BENCH_STORAGE_ROOT" MODEL_DOWNLOAD_LOG="$DOWNLOAD_LOG" python3 "$ROOT/benchmark/download_training_model.py" "${ARGS[@]}"
if ((DRY_RUN == 0)) && [[ -f "$DOWNLOAD_LOG" ]]; then cp "$DOWNLOAD_LOG" "$ROOT/results/raw/model-downloads-training.jsonl"; fi
