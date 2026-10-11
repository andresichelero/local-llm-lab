#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
DRY_RUN=0
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --help) echo "Usage: MODEL_DIR=$BENCH_STORAGE_ROOT/models/exllama $0 [--dry-run]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
PYTHON="${EXLLAMA_ENV_DIR:-$BENCH_STORAGE_ROOT/envs/exllamav3}/bin/python"
[[ -x "$PYTHON" ]] || { echo "ExLlama venv not found; run scripts/04_install_exllamav3.sh first." >&2; exit 1; }
ARGS=(--model-dir "${MODEL_DIR:-$BENCH_STORAGE_ROOT/models/exllama}")
DOWNLOAD_LOG="$BENCH_STORAGE_ROOT/results/raw/model-downloads-exl3.jsonl"
mkdir -p "$(dirname "$DOWNLOAD_LOG")"
((DRY_RUN)) && ARGS+=(--dry-run)
HF_HOME="${HF_HOME:-$BENCH_STORAGE_ROOT/cache/huggingface}" BENCH_STORAGE_ROOT="$BENCH_STORAGE_ROOT" MODEL_DOWNLOAD_LOG="$DOWNLOAD_LOG" "$PYTHON" "$ROOT/benchmark/download_exl3_model.py" "${ARGS[@]}"
if ((DRY_RUN == 0)) && [[ -f "$DOWNLOAD_LOG" ]]; then cp "$DOWNLOAD_LOG" "$ROOT/results/raw/model-downloads-exl3.jsonl"; fi
