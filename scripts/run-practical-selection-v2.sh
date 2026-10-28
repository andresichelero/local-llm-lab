#!/usr/bin/env bash
set -euo pipefail

TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAB_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
OUTPUT="$LAB_ROOT/results/practical-selection-v2-tool-review-v1"
previous=""
READ_ONLY=1
for argument in "$@"; do
  if [[ "$previous" == "--output" ]]; then OUTPUT="$argument"; fi
  case "$argument" in --output=*) OUTPUT="${argument#--output=}" ;; esac
  case "$argument" in --execute) READ_ONLY=0 ;; esac
  case "$argument" in
    --validate-only|--regrade-run|--regrade-run=*|--help|-h) READ_ONLY=1 ;;
  esac
  previous="$argument"
done
cd "$TASK_ROOT"
# A campaign already owns its versions. Resuming must not update underneath it.
FROZEN=0
if [[ -f "$OUTPUT/manifest.json" ]]; then
  FROZEN="$(/usr/bin/python3 -c 'import json,sys; print(int(bool(json.load(open(sys.argv[1])).get("runtime_versions"))))' "$OUTPUT/manifest.json")"
elif [[ -f "$OUTPUT/protocol.json" ]]; then
  FROZEN=1
fi
if [[ "$READ_ONLY" == 0 && "$FROZEN" == 0 ]]; then
  bash "$TASK_ROOT/scripts/00_update_runtime.sh"
fi
exec "$LAB_ROOT/envs/lab-validation/bin/python" -m benchmark.practical_campaign_v2 \
  "$@" --output "$OUTPUT"
