#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
DOWNLOAD_LOG="$BENCH_STORAGE_ROOT/results/raw/model-downloads-qwen35.jsonl"
mkdir -p "$(dirname "$DOWNLOAD_LOG")"
ARGS=(--model-dir "${MODEL_DIR:-$BENCH_STORAGE_ROOT/models}" --record "$DOWNLOAD_LOG")
case "${1:-}" in
  --dry-run) ARGS+=(--dry-run) ;;
  "") ;;
  --help) echo "Usage: MODEL_DIR=$BENCH_STORAGE_ROOT/models $0 [--dry-run]"; exit 0 ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac
BENCH_STORAGE_ROOT="$BENCH_STORAGE_ROOT" python3 "$ROOT/benchmark/download_qwen35_gguf.py" "${ARGS[@]}"
if [[ "${1:-}" != "--dry-run" && -f "$DOWNLOAD_LOG" ]]; then cp "$DOWNLOAD_LOG" "$ROOT/results/raw/model-downloads-qwen35.jsonl"; fi
