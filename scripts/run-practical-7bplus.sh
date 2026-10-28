#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAB="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
cd "$ROOT"
CATALOGUE="$ROOT/benchmark/configs/practical-7bplus-v1.json"
OUTPUT=""
READ_ONLY=1
previous=""
for argument in "$@"; do
  case "$previous" in --catalogue) CATALOGUE="$argument" ;; --output) OUTPUT="$argument" ;; esac
  case "$argument" in
    --execute) READ_ONLY=0 ;;
    --catalogue=*) CATALOGUE="${argument#--catalogue=}" ;;
    --output=*) OUTPUT="${argument#--output=}" ;;
    --validate-only|--help|-h) READ_ONLY=1 ;;
  esac
  previous="$argument"
done
if [[ -z "$OUTPUT" && "$READ_ONLY" == 0 ]]; then
  OUTPUT="$(/usr/bin/python3 - "$CATALOGUE" "$LAB" <<'PY'
import json
import sys
from pathlib import Path
value = json.loads(Path(sys.argv[1]).read_text())
print(value.get('output') or str(Path(sys.argv[2]) / 'results' / value['protocol_id']))
PY
)"
fi
# The marker makes this a no-op after the first successful update of the day.
# Frozen runs never update their dependencies on resume.
FROZEN=0
if [[ "$READ_ONLY" == 0 && -f "$OUTPUT/manifest.json" ]]; then
  FROZEN="$(/usr/bin/python3 -c 'import json,sys; print(int(bool(json.load(open(sys.argv[1])).get("runtime_versions"))))' "$OUTPUT/manifest.json")"
fi
if [[ "$READ_ONLY" == 0 && "$FROZEN" == 0 ]]; then
  bash scripts/00_update_runtime.sh
fi
exec "$LAB/envs/lab-validation/bin/python" -m benchmark.practical_queue "$@"
