#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${EXLLAMA_ENV_DIR:-/mnt/e/local-llm-envs/exllamav3}/bin/python"
[[ -x "$PYTHON" ]] || { echo "ExLlama venv not found; run scripts/04_install_exllamav3.sh first." >&2; exit 1; }
exec "$PYTHON" "$ROOT/benchmark/exllama_bench.py" "$@"
