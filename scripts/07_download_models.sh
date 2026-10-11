#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
TIER=""
DRY_RUN=0
while (($#)); do
  case "$1" in
    --tier) (($# >= 2)) || { echo "--tier needs a value" >&2; exit 2; }; TIER="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help) echo "Usage: MODEL_DIR=$BENCH_STORAGE_ROOT/models $0 --tier small|hybrid [--dry-run]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
MODEL_DIR="${MODEL_DIR:-}"
case "$TIER" in
  small)
    MODEL_DIR="${MODEL_DIR:-$BENCH_STORAGE_ROOT/models}"
    ARGS=(--model-dir "$MODEL_DIR")
    if ((DRY_RUN == 1)); then ARGS+=(--dry-run); fi
    python3 "$ROOT/benchmark/download_model.py" "${ARGS[@]}"
    ;;
  hybrid)
    MODEL_DIR="${MODEL_DIR:-$BENCH_STORAGE_ROOT/models/hybrid}"
    ARGS=(--model-dir "$MODEL_DIR")
    if ((DRY_RUN == 1)); then ARGS+=(--dry-run); fi
    python3 "$ROOT/benchmark/download_qwen25_coder14b_gguf.py" "${ARGS[@]}"
    ;;
  *) echo "Unsupported tier '$TIER'; currently available: small, hybrid." >&2; exit 2 ;;
esac
