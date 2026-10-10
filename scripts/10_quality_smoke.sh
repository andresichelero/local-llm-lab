#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib_env.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${MODEL_PATH:-$MODEL_DIR/granite-4.1-3b-Q4_K_M.gguf}"
SERVER="${LLAMA_SERVER:-$ROOT/tools/llama.cpp/build/bin/llama-server}"
PORT="${PORT:-18181}"
OUTPUT="${OUTPUT:-$ROOT/results/raw/tier0-quality.jsonl}"
MODEL_ID="${MODEL_ID:-granite-4.1-3b}"
RESOURCE_OUTPUT="${RESOURCE_OUTPUT:-$ROOT/results/raw/tier0-quality-resources.jsonl}"
if [[ "${1:-}" == "--help" ]]; then echo "Usage: $0 [--dry-run]; validates JSON output and a single local tool round trip."; exit 0; fi
if [[ "${1:-}" == "--dry-run" ]]; then printf 'model=%s server=%s port=%s output=%s\n' "$MODEL" "$SERVER" "$PORT" "$OUTPUT"; exit 0; fi
[[ -x "$SERVER" ]] || { echo "llama-server missing: $SERVER" >&2; exit 1; }
[[ -f "$MODEL" ]] || { echo "Model file missing: $MODEL" >&2; exit 1; }
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then echo "Port $PORT already has a healthy server; refusing to use an unknown process." >&2; exit 1; fi
SHA="$(git -C "$ROOT" rev-parse HEAD)"
if ! git -C "$ROOT" diff --quiet HEAD -- . ':(exclude)results/**'; then SOURCE_DIRTY=true; else SOURCE_DIRTY=false; fi
RUNTIME_COMMIT="$(git -C "$ROOT/tools/llama.cpp" rev-parse HEAD 2>/dev/null || echo unknown)"
python3 "$ROOT/benchmark/resource_sampler.py" --output "$RESOURCE_OUTPUT" --interval 1 &
SAMPLER_PID=$!
"$SERVER" --model "$MODEL" --host 127.0.0.1 --port "$PORT" --ctx-size 2048 --n-gpu-layers 99 --batch-size 256 --ubatch-size 128 --flash-attn on --cache-type-k f16 --cache-type-v f16 >"$ROOT/logs/llama-server-quality-$PORT.log" 2>&1 &
SERVER_PID=$!
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; kill "$SAMPLER_PID" 2>/dev/null || true; wait "$SAMPLER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
READY=0
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then READY=1; break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
  sleep 1
done
if ((READY == 0)); then tail -100 "$ROOT/logs/llama-server-quality-$PORT.log" >&2; exit 1; fi
LAB_GIT_SHA="$SHA" LAB_SOURCE_DIRTY="$SOURCE_DIRTY" LAB_RUNTIME_COMMIT="$RUNTIME_COMMIT" python3 "$ROOT/benchmark/quality_smoke.py" --url "http://127.0.0.1:$PORT" --model "$MODEL_ID" --output "$OUTPUT"
