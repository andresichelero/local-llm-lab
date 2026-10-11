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
    --help) echo "Usage: MODEL_DIR=$BENCH_STORAGE_ROOT/models $0 --tier small [--dry-run]"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if [[ "$TIER" != small ]]; then echo "Only researched small tier is enabled; other tiers need pinned files and a separate space review." >&2; exit 2; fi
ARGS=(--model-dir "${MODEL_DIR:-$BENCH_STORAGE_ROOT/models}")
((DRY_RUN)) && ARGS+=(--dry-run)
python3 "$ROOT/benchmark/download_model.py" "${ARGS[@]}"
