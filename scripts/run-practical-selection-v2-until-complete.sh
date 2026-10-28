#!/usr/bin/env bash
set -euo pipefail

TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAB_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
OUTPUT="$LAB_ROOT/results/practical-selection-v2-r3"
GPU_FREE_FLOOR_MIB=7000
MAX_INFRA_RESTARTS=8
WAIT_PID=""

while (($#)); do
  case "$1" in
    --wait-pid)
      WAIT_PID="${2:?--wait-pid requires a PID}"
      shift 2
      ;;
    --max-infra-restarts)
      MAX_INFRA_RESTARTS="${2:?--max-infra-restarts requires a number}"
      shift 2
      ;;
    --help|-h)
      cat <<'EOF'
Wait for an active practical-selection-v2 campaign, then resume it from saved
evidence until complete. Only infrastructure-exhaustion blocks are restarted.

Options:
  --wait-pid PID              Existing campaign process to wait for first
  --max-infra-restarts COUNT  Maximum operator resumes after infrastructure blocks (default: 8)
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

[[ "$MAX_INFRA_RESTARTS" =~ ^[0-9]+$ ]] || { echo "Invalid restart count" >&2; exit 2; }
if [[ -n "$WAIT_PID" ]]; then
  [[ "$WAIT_PID" =~ ^[0-9]+$ ]] || { echo "Invalid PID" >&2; exit 2; }
fi

LOCK_DIR="/tmp/practical-selection-v2-supervisor.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "A practical-selection-v2 supervisor already holds $LOCK_DIR" >&2
  exit 3
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

mkdir -p "$OUTPUT"
LOG="$OUTPUT/supervisor.log"
log() { printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG"; }

if [[ -n "$WAIT_PID" ]]; then
  current_cmd="$(ps -p "$WAIT_PID" -o args= 2>/dev/null || true)"
  if [[ -n "$current_cmd" && "$current_cmd" != *practical_campaign_v2* ]]; then
    echo "PID $WAIT_PID is not the practical campaign process" >&2
    exit 2
  fi
  if [[ -n "$current_cmd" ]]; then
    log "Waiting for current campaign PID $WAIT_PID to finish before supervising resumes."
    while kill -0 "$WAIT_PID" 2>/dev/null; do sleep 10; done
  fi
fi

read_manifest_state() {
  /usr/bin/python3 - "$OUTPUT/manifest.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    manifest = json.load(stream)
print("\t".join(str(manifest.get(key) or "").replace("\t", " ").replace("\n", " ")
                 for key in ("status", "failure", "error")))
PY
}

restarts=0
while :; do
  if [[ ! -f "$OUTPUT/manifest.json" ]]; then
    log "Manifest is missing; refusing to start a new campaign implicitly."
    exit 4
  fi

  IFS=$'\t' read -r status failure error < <(read_manifest_state)
  if [[ "$status" == "complete" ]]; then
    log "Campaign completed."
    exit 0
  fi

  if [[ "$status" == "blocked" ]]; then
    if [[ "$error" != *"infrastructure retry exhausted"* ]]; then
      log "Stopped on non-retryable block: failure=$failure error=$error"
      exit 5
    fi
    if ((restarts >= MAX_INFRA_RESTARTS)); then
      log "Stopped after $restarts infrastructure resumes; latest error: $error"
      exit 6
    fi
    ((restarts += 1))
    log "Resuming saved campaign after infrastructure block (resume $restarts/$MAX_INFRA_RESTARTS)."
  elif [[ "$status" == "running" || "$status" == "interrupted" ]]; then
    log "Resuming campaign from its saved $status state."
  else
    log "Stopped on unexpected campaign state: status=$status failure=$failure error=$error"
    exit 5
  fi

  set +e
  bash "$TASK_ROOT/scripts/run-practical-selection-v2.sh" \
    --retry-blocked --gpu-free-floor-mib "$GPU_FREE_FLOOR_MIB"
  runner_rc=$?
  set -e
  log "Campaign invocation exited with code $runner_rc."
done
