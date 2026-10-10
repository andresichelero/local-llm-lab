#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib_env.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGS=(--model-dir "$MODEL_DIR")
case "${1:-}" in
  --dry-run) ARGS+=(--dry-run) ;;
  "") ;;
  --help) echo "Usage: MODEL_DIR=<dir> $0 [--dry-run]"; exit 0 ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
python3 "$ROOT/benchmark/download_qwen35_gguf.py" "${ARGS[@]}"
