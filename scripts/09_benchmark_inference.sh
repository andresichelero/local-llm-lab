#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${MODEL_PATH:-${MODEL_DIR:-/mnt/e/local-llm-models}/granite-4.1-3b-Q4_K_M.gguf}"
SERVER="${LLAMA_SERVER:-$ROOT/tools/llama.cpp/build/bin/llama-server}"
RUNTIME_SOURCE="${LLAMA_CPP_SOURCE:-$ROOT/tools/llama.cpp}"
PORT="${PORT:-18180}"
OUTPUT="${OUTPUT:-$ROOT/results/raw/tier0.jsonl}"
RESOURCE_OUTPUT="${RESOURCE_OUTPUT:-${OUTPUT%.jsonl}-resources.jsonl}"
EXPERIMENT="${EXPERIMENT:-tier0_streaming_smoke}"
MODEL_ID="${MODEL_ID:-granite-4.1-3b}"
CTX_SIZE="${CTX_SIZE:-2048}"
GPU_LAYERS="${GPU_LAYERS:-99}"
BATCH_SIZE="${BATCH_SIZE:-256}"
UBATCH_SIZE="${UBATCH_SIZE:-128}"
FLASH_ATTN="${FLASH_ATTN:-on}"
REASONING="${REASONING:-auto}"
KV_TYPE_K="${KV_TYPE_K:-f16}"
KV_TYPE_V="${KV_TYPE_V:-f16}"
REPETITIONS="${REPETITIONS:-3}"
WARMUPS="${WARMUPS:-1}"
if [[ "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Run one local llama.cpp inference series (one warm-up, then repeated prompts).
Environment: MODEL_PATH, PORT, OUTPUT, RESOURCE_OUTPUT, EXPERIMENT, CTX_SIZE,
GPU_LAYERS, BATCH_SIZE, UBATCH_SIZE, FLASH_ATTN=on|off, KV_TYPE_K/V,
REASONING=auto|on|off, REPETITIONS, WARMUPS, LLAMA_SERVER.
KV types: f16, bf16, q8_0, q4_0. Build-time support varies by backend.
EOF
  exit 0
fi
if [[ "${1:-}" == "--dry-run" ]]; then
  printf 'model=%s\nserver=%s\nport=%s\ncontext=%s\ngpu_layers=%s\nflash_attention=%s\nkv_k=%s\nkv_v=%s\noutput=%s\n' "$MODEL" "$SERVER" "$PORT" "$CTX_SIZE" "$GPU_LAYERS" "$FLASH_ATTN" "$KV_TYPE_K" "$KV_TYPE_V" "$OUTPUT"
  exit 0
fi
if [[ ! -x "$SERVER" ]]; then echo "llama-server missing: $SERVER" >&2; exit 1; fi
if [[ ! -f "$MODEL" ]]; then echo "Model file not found: $MODEL" >&2; exit 1; fi
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then echo "Port $PORT already has a healthy server; refusing to benchmark an unknown process." >&2; exit 1; fi
SHA="$(git -C "$ROOT" rev-parse HEAD)"
if ! git -C "$ROOT" diff --quiet HEAD -- . ':(exclude)results/**'; then SOURCE_DIRTY=true; else SOURCE_DIRTY=false; fi
RUNTIME_COMMIT="$(git -C "$RUNTIME_SOURCE" rev-parse HEAD 2>/dev/null || echo unknown)"
LOG="$ROOT/logs/llama-server-$PORT.log"
python3 "$ROOT/benchmark/resource_sampler.py" --output "$RESOURCE_OUTPUT" --interval 1 &
SAMPLER_PID=$!
"$SERVER" --model "$MODEL" --host 127.0.0.1 --port "$PORT" --ctx-size "$CTX_SIZE" --n-gpu-layers "$GPU_LAYERS" --batch-size "$BATCH_SIZE" --ubatch-size "$UBATCH_SIZE" --flash-attn "$FLASH_ATTN" --cache-type-k "$KV_TYPE_K" --cache-type-v "$KV_TYPE_V" --reasoning "$REASONING" >"$LOG" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; kill "$SAMPLER_PID" 2>/dev/null || true; wait "$SAMPLER_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
READY=0
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then READY=1; break; fi
  if ! kill -0 "$PID" 2>/dev/null; then break; fi
  sleep 1
done
if ((READY == 0)); then tail -100 "$LOG" >&2; exit 1; fi
LAB_GIT_SHA="$SHA" LAB_SOURCE_DIRTY="$SOURCE_DIRTY" LAB_RUNTIME_COMMIT="$RUNTIME_COMMIT" LAB_EXPERIMENT="$EXPERIMENT" LAB_CTX_SIZE="$CTX_SIZE" LAB_KV_TYPE_K="$KV_TYPE_K" LAB_KV_TYPE_V="$KV_TYPE_V" LAB_GPU_LAYERS="$GPU_LAYERS" LAB_BATCH_SIZE="$BATCH_SIZE" LAB_UBATCH_SIZE="$UBATCH_SIZE" LAB_FLASH_ATTN="$FLASH_ATTN" LAB_REASONING="$REASONING" python3 "$ROOT/benchmark/llama_cpp_bench.py" --url "http://127.0.0.1:$PORT" --model "$MODEL_ID" --repetitions "$REPETITIONS" --warmups "$WARMUPS" --output "$OUTPUT" --experiment "$EXPERIMENT"
