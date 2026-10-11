#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="${MODEL_DIR:-/mnt/e/local-llm-models}"
DRY_RUN=0
while (($#)); do
  case "$1" in
    --help) echo "Usage: MODEL_DIR=/mnt/e/local-llm-models $0 [--dry-run]"; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
ARGS=(--model-dir "$MODEL_DIR")
((DRY_RUN)) && ARGS+=(--dry-run)
python3 "$ROOT/benchmark/download_training_model.py" "${ARGS[@]}"
