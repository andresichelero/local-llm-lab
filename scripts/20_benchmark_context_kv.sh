#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_PATH="${MODEL_PATH:-/home/foxtrot/local-llm-benchmark/models/gguf/Qwen3.5-9B-Q4_K_M.gguf}"
MODEL_REVISION="${MODEL_REVISION:-3885219b6810b007914f3a7950a8d1b469d598a5}"
LLAMA_SERVER="${LLAMA_SERVER:-/home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server}"
LLAMA_CPP_SOURCE="${LLAMA_CPP_SOURCE:-$ROOT/tools/llama.cpp}"
LLAMA_LIBRARY_DIR="${LLAMA_LIBRARY_DIR:-/home/foxtrot/local-llm-benchmark/tools/llama-bin}"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
BENCH_LOG_DIR="${BENCH_LOG_DIR:-$BENCH_STORAGE_ROOT/logs}"
CONTEXTS="${CONTEXTS:-16384,32768}"
KV_CONTEXT="${KV_CONTEXT:-16384}"
KV_TYPES="${KV_TYPES:-q8_0,f16}"
PROMPT_PERCENT="${PROMPT_PERCENT:-8750}"
REPETITIONS="${REPETITIONS:-3}"
WARMUPS="${WARMUPS:-1}"
PORT_BASE="${PORT_BASE:-18200}"
MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-64}"
MODEL_ID="${MODEL_ID:-Qwen3.5-9B-Q4_K_M}"
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage: scripts/20_benchmark_context_kv.sh [options]

Run Qwen3.5-9B Q4_K_M context and KV-cache experiments sequentially using
the C:-hosted WSL ext4 model/runtime. The Q4_0 context sweep includes the
baseline KV format; KV_TYPES compares alternatives at KV_CONTEXT.

Options:
  --contexts LIST    Comma-separated context sizes (default: 16384,32768)
  --kv-context N     Context used for alternative KV formats (default: 16384)
  --kv-types LIST    Comma-separated alternatives (default: q8_0,f16)
  --repeat N         Measured repetitions (default: 3)
  --dry-run          Print every planned server configuration without running
  --help             Show this help

Environment overrides: MODEL_PATH, MODEL_REVISION, LLAMA_SERVER,
LLAMA_CPP_SOURCE, LLAMA_LIBRARY_DIR, BENCH_STORAGE_ROOT, BENCH_LOG_DIR,
PROMPT_PERCENT (basis points; default 8750), REPETITIONS, WARMUPS, PORT_BASE,
MAX_NEW_TOKENS, MODEL_ID, STORAGE_PROFILE, RUNTIME_STORAGE_PROFILE,
OUTPUT_PREFIX. Active JSONL, resource samples, and server logs are written to
BENCH_STORAGE_ROOT on the SSD. Completed JSONL files are copied into the Git
checkout after all configurations finish.
EOF
}

while (($#)); do
  case "$1" in
    --contexts)
      (($# >= 2)) || { echo "--contexts needs a comma-separated list" >&2; exit 2; }
      CONTEXTS="$2"; shift 2 ;;
    --kv-context)
      (($# >= 2)) || { echo "--kv-context needs a value" >&2; exit 2; }
      KV_CONTEXT="$2"; shift 2 ;;
    --kv-types)
      (($# >= 2)) || { echo "--kv-types needs a comma-separated list" >&2; exit 2; }
      KV_TYPES="$2"; shift 2 ;;
    --repeat)
      (($# >= 2)) || { echo "--repeat needs a value" >&2; exit 2; }
      REPETITIONS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$REPETITIONS" =~ ^[1-9][0-9]*$ ]] || { echo "REPETITIONS must be a positive integer" >&2; exit 2; }
[[ "$WARMUPS" =~ ^[0-9]+$ ]] || { echo "WARMUPS must be a non-negative integer" >&2; exit 2; }
[[ "$PORT_BASE" =~ ^[0-9]+$ ]] && ((PORT_BASE >= 1024 && PORT_BASE <= 65520)) || {
  echo "PORT_BASE must be between 1024 and 65520" >&2; exit 2;
}
[[ "$PROMPT_PERCENT" =~ ^[0-9]+$ ]] && ((PROMPT_PERCENT > 0 && PROMPT_PERCENT < 10000)) || {
  echo "PROMPT_PERCENT must be basis points between 1 and 9999" >&2; exit 2;
}
[[ "$KV_CONTEXT" =~ ^[0-9]+$ ]] && ((KV_CONTEXT >= 256 && KV_CONTEXT % 256 == 0)) || {
  echo "KV_CONTEXT must be a positive multiple of 256" >&2; exit 2;
}

IFS=',' read -r -a CONTEXT_LIST <<<"$CONTEXTS"
IFS=',' read -r -a KV_LIST <<<"$KV_TYPES"
(( ${#CONTEXT_LIST[@]} > 0 && ${#KV_LIST[@]} > 0 )) || { echo "At least one context and KV type are required" >&2; exit 2; }

OUTPUT_PREFIX="${OUTPUT_PREFIX:-$BENCH_STORAGE_ROOT/results/raw/qwen35-ssd}"
STORAGE_PROFILE="${STORAGE_PROFILE:-ssd-wsl-ext4-c}"
RUNTIME_STORAGE_PROFILE="${RUNTIME_STORAGE_PROFILE:-ssd-wsl-ext4-c}"
PORT="$PORT_BASE"
ARCHIVE_OUTPUTS=()

run_config() {
  local context="$1" kv_type="$2" phase="$3" prompt_tokens experiment output resource_output
  [[ "$context" =~ ^[0-9]+$ ]] && ((context >= 256 && context % 256 == 0)) || {
    echo "Context sizes must be positive multiples of 256: $context" >&2; return 2;
  }
  [[ "$kv_type" =~ ^(f16|bf16|q8_0|q4_0)$ ]] || {
    echo "Unsupported KV cache type: $kv_type" >&2; return 2;
  }
  prompt_tokens=$((context * PROMPT_PERCENT / 10000))
  ((prompt_tokens + MAX_NEW_TOKENS < context)) || {
    echo "Prompt target plus generation does not fit context $context" >&2; return 2;
  }
  experiment="llama-cpp-qwen35-ssd-${phase}-${context}-${kv_type}-kv"
  output="${OUTPUT_PREFIX}-${phase}-${context}-${kv_type}.jsonl"
  resource_output="${OUTPUT_PREFIX}-${phase}-${context}-${kv_type}-resources.jsonl"
  printf 'experiment=%s context=%s input_target=%s kv=%s warmups=%s repeats=%s port=%s\n' \
    "$experiment" "$context" "$prompt_tokens" "$kv_type" "$WARMUPS" "$REPETITIONS" "$PORT"
  if [[ "$DRY_RUN" == true ]]; then
    printf 'model=%s\nruntime=%s\noutput=%s\nresources=%s\n' \
      "$MODEL_PATH" "$LLAMA_SERVER" "$output" "$resource_output"
  else
    mkdir -p "$(dirname "$output")" "$(dirname "$resource_output")" "$BENCH_LOG_DIR"
    ARCHIVE_OUTPUTS+=("$output" "$resource_output")
    MODEL_PATH="$MODEL_PATH" MODEL_REVISION="$MODEL_REVISION" STORAGE_PROFILE="$STORAGE_PROFILE" \
    LLAMA_SERVER="$LLAMA_SERVER" LLAMA_CPP_SOURCE="$LLAMA_CPP_SOURCE" \
    LD_LIBRARY_PATH="$LLAMA_LIBRARY_DIR" LOG_PATH="$BENCH_LOG_DIR/llama-server-$PORT.log" \
    RUNTIME_STORAGE_PROFILE="$RUNTIME_STORAGE_PROFILE" \
    PORT="$PORT" OUTPUT="$output" RESOURCE_OUTPUT="$resource_output" \
    EXPERIMENT="$experiment" MODEL_ID="$MODEL_ID" CTX_SIZE="$context" \
    GPU_LAYERS=99 BATCH_SIZE=256 UBATCH_SIZE=128 FLASH_ATTN=on \
    KV_TYPE_K="$kv_type" KV_TYPE_V="$kv_type" REASONING=off CACHE_PROMPT=off \
    REPETITIONS="$REPETITIONS" WARMUPS="$WARMUPS" MAX_NEW_TOKENS="$MAX_NEW_TOKENS" \
    INPUT_TOKENS="$prompt_tokens" bash "$ROOT/scripts/09_benchmark_inference.sh"
  fi
  PORT=$((PORT + 1))
}

for context in "${CONTEXT_LIST[@]}"; do
  run_config "$context" q4_0 context
done
for kv_type in "${KV_LIST[@]}"; do
  run_config "$KV_CONTEXT" "$kv_type" kv
done

if [[ "$DRY_RUN" == false ]]; then
  for source in "${ARCHIVE_OUTPUTS[@]}"; do
    [[ -s "$source" ]] || { echo "Expected benchmark output is missing or empty: $source" >&2; exit 1; }
    cp -- "$source" "$ROOT/results/raw/$(basename "$source")"
  done
  echo "Completed JSONL and resource samples were copied to $ROOT/results/raw; SSD-side originals remain under $BENCH_STORAGE_ROOT."
fi
