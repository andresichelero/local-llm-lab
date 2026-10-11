#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL_PATH="${MODEL_PATH:-$BENCH_STORAGE_ROOT/models/gguf/Qwen3.5-9B-Q4_K_M.gguf}"
RUNTIME_DIR="${RUNTIME_DIR:-$BENCH_STORAGE_ROOT/tools/llama-bin}"
LLAMA_SERVER="${LLAMA_SERVER:-$RUNTIME_DIR/llama-server}"
REPETITIONS="${REPETITIONS:-5}"
WARMUPS="${WARMUPS:-1}"
PORT_BASE="${PORT_BASE:-18230}"
STAMP="${STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"

usage() {
  cat <<'EOF'
Run repeated Qwen3.5-9B JSON and tool-round-trip quality probes on WSL ext4 SSD.

Environment: BENCH_STORAGE_ROOT, MODEL_PATH, RUNTIME_DIR, LLAMA_SERVER,
REPETITIONS (default 5), WARMUPS (default 1), PORT_BASE (default 18230), STAMP.
Use --dry-run to verify paths and show planned repetitions without starting inference.
EOF
}

case "${1:-}" in
  --help) usage; exit 0 ;;
  --dry-run) DRY_RUN=true ;;
  "") DRY_RUN=false ;;
  *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

[[ "$REPETITIONS" =~ ^[1-9][0-9]*$ ]] || { echo "REPETITIONS must be a positive integer" >&2; exit 2; }
[[ "$WARMUPS" =~ ^[0-9]+$ ]] || { echo "WARMUPS must be a non-negative integer" >&2; exit 2; }
[[ "$PORT_BASE" =~ ^[0-9]+$ ]] || { echo "PORT_BASE must be an integer" >&2; exit 2; }
[[ -f "$MODEL_PATH" ]] || { echo "SSD model missing: $MODEL_PATH" >&2; exit 1; }
[[ -x "$LLAMA_SERVER" ]] || { echo "SSD llama-server missing: $LLAMA_SERVER" >&2; exit 1; }
[[ "$(findmnt -n -o FSTYPE -T "$MODEL_PATH")" == ext4 ]] || { echo "Model must be on WSL ext4 SSD: $MODEL_PATH" >&2; exit 1; }
[[ "$(findmnt -n -o FSTYPE -T "$LLAMA_SERVER")" == ext4 ]] || { echo "Runtime must be on WSL ext4 SSD: $LLAMA_SERVER" >&2; exit 1; }
[[ "$(findmnt -n -o FSTYPE -T "$BENCH_STORAGE_ROOT")" == ext4 ]] || { echo "Benchmark storage must be on WSL ext4 SSD: $BENCH_STORAGE_ROOT" >&2; exit 1; }

RESOLVED_LIBS="$(LD_LIBRARY_PATH="$RUNTIME_DIR" ldd "$LLAMA_SERVER")"
if grep -E '/mnt/[de]/|not found' <<<"$RESOLVED_LIBS"; then
  echo "llama-server has unresolved or HDD-backed dependencies; refusing to benchmark." >&2
  exit 1
fi
while IFS= read -r library; do
  [[ -z "$library" ]] && continue
  [[ "$library" == "$RUNTIME_DIR"/* ]] || {
    echo "llama.cpp library is outside the SSD runtime bundle: $library" >&2
    exit 1
  }
done < <(awk '$1 ~ /^lib(llama|ggml|mtmd)/ && $2 == "=>" {print $3}' <<<"$RESOLVED_LIBS")

echo "model=$MODEL_PATH"
echo "runtime=$LLAMA_SERVER"
echo "runtime_libraries=$RUNTIME_DIR"
echo "storage=$BENCH_STORAGE_ROOT"
echo "warmups=$WARMUPS repetitions=$REPETITIONS"
echo "experiment_stamp=$STAMP"
[[ "$DRY_RUN" == true ]] && exit 0

run_one() {
  local label="$1" port="$2"
  BENCH_STORAGE_ROOT="$BENCH_STORAGE_ROOT" \
  MODEL_PATH="$MODEL_PATH" \
  LLAMA_SERVER="$LLAMA_SERVER" \
  LD_LIBRARY_PATH="$RUNTIME_DIR" \
  PORT="$port" \
  MODEL_ID="Qwen3.5-9B-Q4_K_M" \
  CTX_SIZE=2048 GPU_LAYERS=99 KV_CACHE_K=f16 KV_CACHE_V=f16 REASONING=off \
  OUTPUT="$BENCH_STORAGE_ROOT/results/raw/qwen35-quality-${STAMP}-${label}.jsonl" \
  RESOURCE_OUTPUT="$BENCH_STORAGE_ROOT/results/raw/qwen35-quality-${STAMP}-${label}-resources.jsonl" \
  LOG_PATH="$BENCH_STORAGE_ROOT/logs/qwen35-quality-${STAMP}-${label}.log" \
    bash "$ROOT/scripts/10_quality_smoke.sh"
}

for ((i=1; i<=WARMUPS; i++)); do
  run_one "warmup-$i" "$((PORT_BASE + i - 1))"
done
for ((i=1; i<=REPETITIONS; i++)); do
  run_one "rep-$i" "$((PORT_BASE + WARMUPS + i - 1))"
done
