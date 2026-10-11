#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL_PATH="${MODEL_PATH:-$BENCH_STORAGE_ROOT/models/gguf/Qwen3.5-9B-Q4_K_M.gguf}"
MODEL_REVISION="${MODEL_REVISION:-3885219b6810b007914f3a7950a8d1b469d598a5}"
LLAMA_SERVER="${LLAMA_SERVER:-$BENCH_STORAGE_ROOT/tools/llama-bin/llama-server}"
LLAMA_CPP_SOURCE="${LLAMA_CPP_SOURCE:-$BENCH_STORAGE_ROOT/tools/llama.cpp}"
LLAMA_LIBRARY_DIR="${LLAMA_LIBRARY_DIR:-$BENCH_STORAGE_ROOT/tools/llama-bin}"
LOG_DIR="${LOG_DIR:-$BENCH_STORAGE_ROOT/logs}"
OUTPUT_PREFIX="${OUTPUT_PREFIX:-$BENCH_STORAGE_ROOT/results/raw/qwen35-ssd-recall-16k}"
KV_TYPES="${KV_TYPES:-q4_0,q8_0,f16}"
REPETITIONS="${REPETITIONS:-3}"
WARMUPS="${WARMUPS:-1}"
TARGET_TOKENS="${TARGET_TOKENS:-14000}"
PORT_BASE="${PORT_BASE:-18300}"
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage: scripts/21_benchmark_context_recall.sh [--kv-types LIST] [--repeat N] [--dry-run] [--help]

Run a deterministic long-context exact-recall probe for Qwen3.5-9B on the SSD.
The same invented fact is placed once near the middle of a tokenizer-sized prompt.

Environment overrides: MODEL_PATH, MODEL_REVISION, LLAMA_SERVER, LLAMA_CPP_SOURCE,
LLAMA_LIBRARY_DIR, BENCH_STORAGE_ROOT, LOG_DIR, OUTPUT_PREFIX, KV_TYPES,
REPETITIONS, WARMUPS, TARGET_TOKENS, PORT_BASE.
EOF
}

while (($#)); do
  case "$1" in
    --kv-types) (($# >= 2)) || { echo "--kv-types needs a list" >&2; exit 2; }; KV_TYPES="$2"; shift 2 ;;
    --repeat) (($# >= 2)) || { echo "--repeat needs a value" >&2; exit 2; }; REPETITIONS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$REPETITIONS" =~ ^[1-9][0-9]*$ ]] || { echo "REPETITIONS must be positive" >&2; exit 2; }
[[ "$WARMUPS" =~ ^[0-9]+$ ]] || { echo "WARMUPS must be non-negative" >&2; exit 2; }
[[ "$TARGET_TOKENS" =~ ^[0-9]+$ ]] && ((TARGET_TOKENS > 0 && TARGET_TOKENS < 16384)) || { echo "TARGET_TOKENS must be between 1 and 16383" >&2; exit 2; }
[[ "$PORT_BASE" =~ ^[0-9]+$ ]] && ((PORT_BASE >= 1024 && PORT_BASE <= 65520)) || { echo "PORT_BASE must be between 1024 and 65520" >&2; exit 2; }
IFS=',' read -r -a KV_LIST <<<"$KV_TYPES"
(( ${#KV_LIST[@]} > 0 )) || { echo "At least one KV type is required" >&2; exit 2; }

OUTPUTS=()
PORT="$PORT_BASE"
RESULT=0
for kv_type in "${KV_LIST[@]}"; do
  [[ "$kv_type" =~ ^(q4_0|q8_0|f16)$ ]] || { echo "Unsupported KV type: $kv_type" >&2; exit 2; }
  experiment="llama-cpp-qwen35-ssd-context-recall-16384-${kv_type}"
  output="${OUTPUT_PREFIX}-${kv_type}.jsonl"
  resources="${OUTPUT_PREFIX}-${kv_type}-resources.jsonl"
  archive_output="$ROOT/results/raw/$(basename "$output")"
  archive_resources="$ROOT/results/raw/$(basename "$resources")"
  printf 'experiment=%s context=16384 target_tokens=%s kv=%s warmups=%s repeats=%s port=%s\n' \
    "$experiment" "$TARGET_TOKENS" "$kv_type" "$WARMUPS" "$REPETITIONS" "$PORT"
  printf 'model=%s\nruntime=%s\noutput=%s\nresources=%s\n' "$MODEL_PATH" "$LLAMA_SERVER" "$output" "$resources"
  if [[ "$DRY_RUN" == true ]]; then
    PORT=$((PORT + 1))
    continue
  fi
  for path in "$output" "$resources" "$archive_output" "$archive_resources"; do
    [[ ! -e "$path" ]] || { echo "Refusing to overwrite existing output: $path" >&2; exit 1; }
  done
  mkdir -p "$(dirname "$output")" "$(dirname "$resources")" "$LOG_DIR"
  OUTPUTS+=("$output" "$resources")
  RESOURCE_OUTPUT="$resources" python3 "$ROOT/benchmark/resource_sampler.py" --output "$resources" --interval 1 &
  sampler_pid=$!
  server_pid=""
  cleanup() {
    if [[ -n "$server_pid" ]]; then kill "$server_pid" 2>/dev/null || true; wait "$server_pid" 2>/dev/null || true; fi
    kill "$sampler_pid" 2>/dev/null || true; wait "$sampler_pid" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "Port $PORT already has a healthy server; refusing unknown process." >&2
    exit 1
  fi
  LD_LIBRARY_PATH="$LLAMA_LIBRARY_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$LLAMA_SERVER" --model "$MODEL_PATH" --host 127.0.0.1 --port "$PORT" \
    --ctx-size 16384 --n-gpu-layers 99 --batch-size 256 --ubatch-size 128 \
    --flash-attn on --cache-type-k "$kv_type" --cache-type-v "$kv_type" \
    --reasoning off --no-cache-prompt >"$LOG_DIR/context-recall-$PORT.log" 2>&1 &
  server_pid=$!
  ready=0
  for _ in $(seq 1 90); do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then ready=1; break; fi
    if ! kill -0 "$server_pid" 2>/dev/null; then break; fi
    sleep 1
  done
  if ((ready == 0)); then tail -100 "$LOG_DIR/context-recall-$PORT.log" >&2; exit 1; fi
  if ! python3 "$ROOT/benchmark/context_recall.py" --url "http://127.0.0.1:$PORT" \
    --model-revision "$MODEL_REVISION" --runtime-source "$LLAMA_CPP_SOURCE" \
    --context 16384 --target-tokens "$TARGET_TOKENS" --kv-type "$kv_type" \
    --repetitions "$REPETITIONS" --warmups "$WARMUPS" --experiment "$experiment" \
    --output "$output"; then RESULT=1; fi
  cleanup
  trap - EXIT INT TERM
  server_pid=""
  PORT=$((PORT + 1))
done

if [[ "$DRY_RUN" == false ]]; then
  for source in "${OUTPUTS[@]}"; do
    [[ -s "$source" ]] || { echo "Missing or empty output: $source" >&2; RESULT=1; continue; }
    cp -- "$source" "$ROOT/results/raw/$(basename "$source")"
  done
  echo "Completed quality outputs are archived in $ROOT/results/raw; SSD originals remain under $BENCH_STORAGE_ROOT."
fi
exit "$RESULT"
