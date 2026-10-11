#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
EXLLAMA_ENV_DIR="${EXLLAMA_ENV_DIR:-$BENCH_STORAGE_ROOT/envs/exllamav3}"
RUN_RESULTS="$BENCH_STORAGE_ROOT/results/raw"
RUN_LOGS="$BENCH_STORAGE_ROOT/logs"
PYTHON="$EXLLAMA_ENV_DIR/bin/python"
[[ -x "$PYTHON" ]] || { echo "ExLlama venv not found; run scripts/04_install_exllamav3.sh first." >&2; exit 1; }
mkdir -p "$RUN_LOGS" "$RUN_RESULTS"
python3 "$ROOT/benchmark/resource_sampler.py" --output "$RUN_RESULTS/exllama-qwen35-9b-resources.jsonl" --interval 1 &
SAMPLER_PID=$!
cleanup() {
  kill -TERM "$SAMPLER_PID" 2>/dev/null || true
  wait "$SAMPLER_PID" 2>/dev/null || true
}
trap cleanup EXIT
"$PYTHON" "$ROOT/benchmark/exllama_bench.py" --model-dir "${MODEL_DIR:-$BENCH_STORAGE_ROOT/models/exllama/Qwen3.5-9B-exl3-2.5bpw}" --output "$RUN_RESULTS/exllama-qwen35-9b.jsonl" "$@" 2>&1 | tee -a "$RUN_LOGS/exllama-benchmark.log"
cleanup
cp "$RUN_RESULTS/exllama-qwen35-9b.jsonl" "$ROOT/results/raw/exllama-qwen35-9b.jsonl"
cp "$RUN_RESULTS/exllama-qwen35-9b-resources.jsonl" "$ROOT/results/raw/exllama-qwen35-9b-resources.jsonl"
