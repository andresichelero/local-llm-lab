#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL="${MODEL_PATH:-$BENCH_STORAGE_ROOT/models/gguf/Qwen3.5-9B-Q4_K_M.gguf}"
SERVER="${LLAMA_SERVER:-$BENCH_STORAGE_ROOT/tools/llama-bin/llama-server}"
NODE="${NODE:-$BENCH_STORAGE_ROOT/runtimes/node-v22.23.3-linux-x64/bin/node}"
PI_PACKAGE="${PI_PACKAGE:-$BENCH_STORAGE_ROOT/envs/node-harnesses/pi/node_modules/@earendil-works/pi-coding-agent}"
PORT="${PORT:-8080}"
OUT_ROOT="${PI_STRESS_OUT_ROOT:-$BENCH_STORAGE_ROOT/results/pi-context-stress}"
LOG_ROOT="${PI_STRESS_LOG_ROOT:-$BENCH_STORAGE_ROOT/logs}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$OUT_ROOT/$RUN_ID"
AGENT_DIR="$RUN_DIR/agent"
WORKSPACE="$RUN_DIR/workspace"
RAW="$BENCH_STORAGE_ROOT/results/raw/pi-context-stress.jsonl"
INVALID="$BENCH_STORAGE_ROOT/results/pi-context-stress/exploratory-invalid.jsonl"
SERVER_LOG="$LOG_ROOT/pi-context-stress-server-$RUN_ID.log"
RECORD="$RUN_DIR/result.jsonl"

usage() {
  cat <<'EOF'
Usage: scripts/22_benchmark_pi_context_stress.sh [--help] [--dry-run]
Run an isolated Pi SDK compaction stress workload against the local llama.cpp server.
All model, scratch workspace, session, logs, and results default to the WSL SSD benchmark root.
Environment: BENCH_STORAGE_ROOT, MODEL_PATH, LLAMA_SERVER, NODE, PI_PACKAGE, PORT,
             PI_STRESS_OUT_ROOT, PI_STRESS_LOG_ROOT.
EOF
}
case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --dry-run)
    printf 'model=%s\nserver=%s\nnode=%s\npi_package=%s\noutput=%s\n' "$MODEL" "$SERVER" "$NODE" "$PI_PACKAGE" "$RUN_DIR"
    exit 0 ;;
  "") ;;
  *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac

for path in "$MODEL" "$SERVER" "$NODE" "$PI_PACKAGE/dist/index.js" "$ROOT/benchmark/configs/harnesses/pi.models.json"; do
  [[ -e "$path" ]] || { echo "Required path does not exist: $path" >&2; exit 1; }
done
mkdir -p "$AGENT_DIR" "$WORKSPACE" "$LOG_ROOT" "$(dirname "$RAW")"
if curl --silent --fail "http://127.0.0.1:$PORT/health" >/dev/null; then
  echo "Port $PORT already has a server; refusing to reuse an unowned process." >&2
  exit 1
fi

LD_LIBRARY_PATH="$BENCH_STORAGE_ROOT/tools/llama-bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$SERVER" --model "$MODEL" --host 127.0.0.1 --port "$PORT" --ctx-size 16384 \
  --n-gpu-layers 99 --batch-size 256 --ubatch-size 128 --flash-attn on \
  --cache-type-k q4_0 --cache-type-v q4_0 --reasoning off >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
cleanup() {
  if kill -0 "$SERVER_PID" 2>/dev/null; then kill "$SERVER_PID"; wait "$SERVER_PID" || true; fi
}
trap cleanup EXIT INT TERM

ready=0
for _ in $(seq 1 180); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then tail -100 "$SERVER_LOG" >&2; exit 1; fi
  if curl --silent --fail "http://127.0.0.1:$PORT/health" >/dev/null; then ready=1; break; fi
  sleep 1
done
if (( ready == 0 )); then echo "llama-server failed readiness check" >&2; tail -100 "$SERVER_LOG" >&2; exit 1; fi

export PI_PACKAGE PI_AGENT_DIR="$AGENT_DIR" PI_WORKSPACE="$WORKSPACE"
export PI_MODELS_JSON="$ROOT/benchmark/configs/harnesses/pi.models.json"
export PI_REPO_ROOT="$ROOT"
export PI_OUTPUT_JSONL="$RECORD"
export PATH="$(dirname "$NODE"):/usr/bin:/bin"
set +e
"$NODE" "$ROOT/benchmark/pi_context_stress.mjs" | tee "$RUN_DIR/stdout.json"
status=${PIPESTATUS[0]}
set -e
if (( status == 0 )); then
  cat "$RECORD" >> "$RAW"
else
  cat "$RECORD" >> "$INVALID"
fi
printf 'run_dir=%s\nrecord=%s\nserver_log=%s\nexit_code=%s\n' "$RUN_DIR" "$RECORD" "$SERVER_LOG" "$status"
exit "$status"
