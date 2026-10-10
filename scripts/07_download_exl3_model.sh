#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=0
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --help) echo "Usage: MODEL_DIR=/mnt/e/local-llm-models/exllama $0 [--dry-run]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
PYTHON="${EXLLAMA_ENV_DIR:-/mnt/e/local-llm-envs/exllamav3}/bin/python"
[[ -x "$PYTHON" ]] || { echo "ExLlama venv not found; run scripts/04_install_exllamav3.sh first." >&2; exit 1; }
ARGS=(--model-dir "${MODEL_DIR:-/mnt/e/local-llm-models/exllama}")
((DRY_RUN)) && ARGS+=(--dry-run)
HF_HOME="${HF_HOME:-/mnt/e/local-llm-cache/huggingface}" "$PYTHON" "$ROOT/benchmark/download_exl3_model.py" "${ARGS[@]}"
