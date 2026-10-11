#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="${MODEL_DIR:-/mnt/e/local-llm-models}"
PROFILE="qwen25-coder-0.5b"
DRY_RUN=0
while (($#)); do
  case "$1" in
    --help) echo "Usage: MODEL_DIR=/mnt/e/local-llm-models $0 [--profile qwen25-coder-0.5b|qwen25-coder-7b] [--dry-run]"; exit 0 ;;
    --profile) (($# >= 2)) || { echo "--profile needs a value" >&2; exit 2; }; PROFILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
ARGS=(--model-dir "$MODEL_DIR" --profile "$PROFILE")
((DRY_RUN)) && ARGS+=(--dry-run)
python3 "$ROOT/benchmark/download_training_model.py" "${ARGS[@]}"
