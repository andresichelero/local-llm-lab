#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARGS=(--model-dir "${MODEL_DIR:-/mnt/e/local-llm-models}")
case "${1:-}" in
  --dry-run) ARGS+=(--dry-run) ;;
  "") ;;
  --help) echo "Usage: MODEL_DIR=/mnt/e/local-llm-models $0 [--dry-run]"; exit 0 ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
python3 "$ROOT/benchmark/download_qwen35_gguf.py" "${ARGS[@]}"
