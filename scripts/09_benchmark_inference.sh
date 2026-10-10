#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${MODEL_PATH:-${MODEL_DIR:-/mnt/e/local-llm-models}/granite-4.1-3b-Q4_K_M.gguf}"
SERVER="${LLAMA_SERVER:-$ROOT/tools/llama.cpp/build/bin/llama-server}"
PORT="${PORT:-18180}"
OUTPUT="${OUTPUT:-$ROOT/results/raw/tier0.jsonl}"
if [[ ! -x "$SERVER" ]]; then echo "llama-server missing: $SERVER" >&2; exit 1; fi
if [[ ! -f "$MODEL" ]]; then echo "Model file not found: $MODEL" >&2; exit 1; fi
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then echo "Port $PORT already has a healthy server; refusing to benchmark an unknown process." >&2; exit 1; fi
SHA="$(git -C "$ROOT" rev-parse HEAD)"
LOG="$ROOT/logs/llama-server-$PORT.log"
"$SERVER" --model "$MODEL" --host 127.0.0.1 --port "$PORT" --ctx-size 2048 --n-gpu-layers 99 --batch-size 256 --ubatch-size 128 --flash-attn on >"$LOG" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
READY=0
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then READY=1; break; fi
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
  sleep 1
done
if ((READY == 0)); then tail -100 "$LOG" >&2; exit 1; fi
LAB_GIT_SHA="$SHA" python3 "$ROOT/benchmark/llama_cpp_bench.py" --url "http://127.0.0.1:$PORT" --repetitions 3 --warmups 1 --output "$OUTPUT"
