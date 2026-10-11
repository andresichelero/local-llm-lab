#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
MODEL="${MODEL_PATH:-${MODEL_DIR:-$BENCH_STORAGE_ROOT/models}/granite-4.1-3b-Q4_K_M.gguf}"
SERVER="${LLAMA_SERVER:-$BENCH_STORAGE_ROOT/tools/llama-bin/llama-server}"
LLAMA_LIBRARY_DIR="${LLAMA_LIBRARY_DIR:-$BENCH_STORAGE_ROOT/tools/llama-bin}"
PORT="${PORT:-18181}"
OUTPUT="${OUTPUT:-$BENCH_STORAGE_ROOT/results/raw/tier0-quality.jsonl}"
MODEL_ID="${MODEL_ID:-granite-4.1-3b}"
RESOURCE_OUTPUT="${RESOURCE_OUTPUT:-$BENCH_STORAGE_ROOT/results/raw/tier0-quality-resources.jsonl}"
SERVER_LOG="${LOG_PATH:-$BENCH_STORAGE_ROOT/logs/llama-server-quality-$PORT.log}"
REASONING="${REASONING:-off}"
CTX_SIZE="${CTX_SIZE:-2048}"
GPU_LAYERS="${GPU_LAYERS:-99}"
KV_CACHE_K="${KV_CACHE_K:-f16}"
KV_CACHE_V="${KV_CACHE_V:-f16}"
if [[ "${1:-}" == "--help" ]]; then echo "Usage: $0 [--dry-run]; validates JSON output and a single local tool round trip. Set REASONING, CTX_SIZE, GPU_LAYERS, KV_CACHE_K, KV_CACHE_V to configure the run."; exit 0; fi
case "$REASONING" in on|off|auto) ;; *) echo "REASONING must be on, off, or auto" >&2; exit 2 ;; esac
[[ "$CTX_SIZE" =~ ^[1-9][0-9]*$ ]] || { echo "CTX_SIZE must be a positive integer" >&2; exit 2; }
[[ "$GPU_LAYERS" =~ ^[0-9]+$ ]] || { echo "GPU_LAYERS must be a non-negative integer" >&2; exit 2; }
[[ -x "$SERVER" ]] || { echo "llama-server missing: $SERVER" >&2; exit 1; }
[[ -f "$MODEL" ]] || { echo "Model file missing: $MODEL" >&2; exit 1; }
mkdir -p "$(dirname "$OUTPUT")" "$(dirname "$RESOURCE_OUTPUT")" "$(dirname "$SERVER_LOG")"
source "$ROOT/scripts/lib/ssd_preflight.sh"
require_wsl_ext4_path "$BENCH_STORAGE_ROOT" "benchmark storage root"
require_wsl_ext4_path "$MODEL" "model"
require_llama_cpp_ssd_bundle "$SERVER" "$LLAMA_LIBRARY_DIR"
for output_dir in "$(dirname "$OUTPUT")" "$(dirname "$RESOURCE_OUTPUT")" "$(dirname "$SERVER_LOG")"; do
  require_wsl_ext4_path "$output_dir" "benchmark output directory"
done
if [[ "${1:-}" == "--dry-run" ]]; then
  printf 'model=%s server=%s libraries=%s port=%s reasoning=%s context=%s gpu_layers=%s kv_k=%s kv_v=%s output=%s\nSSD preflight passed.\n' "$MODEL" "$SERVER" "$LLAMA_LIBRARY_DIR" "$PORT" "$REASONING" "$CTX_SIZE" "$GPU_LAYERS" "$KV_CACHE_K" "$KV_CACHE_V" "$OUTPUT"
  exit 0
fi
if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then echo "Port $PORT already has a healthy server; refusing to use an unknown process." >&2; exit 1; fi
SHA="$(git -C "$ROOT" rev-parse HEAD)"
if ! git -C "$ROOT" diff --quiet HEAD -- . ':(exclude)results/**'; then SOURCE_DIRTY=true; else SOURCE_DIRTY=false; fi
RUNTIME_COMMIT="$(git -C "$ROOT/tools/llama.cpp" rev-parse HEAD 2>/dev/null || echo unknown)"
python3 "$ROOT/benchmark/resource_sampler.py" --output "$RESOURCE_OUTPUT" --interval 1 &
SAMPLER_PID=$!
LD_LIBRARY_PATH="$LLAMA_LIBRARY_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$SERVER" --model "$MODEL" --host 127.0.0.1 --port "$PORT" --ctx-size "$CTX_SIZE" --n-gpu-layers "$GPU_LAYERS" --batch-size 256 --ubatch-size 128 --flash-attn on --cache-type-k "$KV_CACHE_K" --cache-type-v "$KV_CACHE_V" --reasoning "$REASONING" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
cleanup() { kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; kill "$SAMPLER_PID" 2>/dev/null || true; wait "$SAMPLER_PID" 2>/dev/null || true; }
finish() {
  local status=$?
  trap - EXIT INT TERM
  cleanup
  [[ -f "$OUTPUT" ]] && cp "$OUTPUT" "$ROOT/results/raw/$(basename "$OUTPUT")"
  [[ -f "$RESOURCE_OUTPUT" ]] && cp "$RESOURCE_OUTPUT" "$ROOT/results/raw/$(basename "$RESOURCE_OUTPUT")"
  [[ -f "$SERVER_LOG" ]] && cp "$SERVER_LOG" "$ROOT/logs/$(basename "$SERVER_LOG")"
  exit "$status"
}
trap finish EXIT INT TERM
READY=0
for _ in $(seq 1 90); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then READY=1; break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
  sleep 1
done
if ((READY == 0)); then tail -100 "$SERVER_LOG" >&2; exit 1; fi
LAB_GIT_SHA="$SHA" LAB_SOURCE_DIRTY="$SOURCE_DIRTY" LAB_RUNTIME_COMMIT="$RUNTIME_COMMIT" LAB_REASONING="$REASONING" LAB_CONTEXT_TOKENS="$CTX_SIZE" LAB_GPU_LAYERS="$GPU_LAYERS" LAB_KV_CACHE_K="$KV_CACHE_K" LAB_KV_CACHE_V="$KV_CACHE_V" python3 "$ROOT/benchmark/quality_smoke.py" --url "http://127.0.0.1:$PORT" --model "$MODEL_ID" --output "$OUTPUT"
