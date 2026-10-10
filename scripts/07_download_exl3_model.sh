#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib_env.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=0
while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --help) echo "Usage: MODEL_DIR=<dir>/exllama $0 [--dry-run]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
PYTHON="$EXLLAMA_ENV_DIR/bin/python"
[[ -x "$PYTHON" ]] || { echo "ExLlama venv not found; run scripts/04_install_exllamav3.sh first." >&2; exit 1; }
ARGS=(--model-dir "$MODEL_DIR/exllama")
((DRY_RUN)) && ARGS+=(--dry-run)
"$PYTHON" "$ROOT/benchmark/download_exl3_model.py" "${ARGS[@]}"
