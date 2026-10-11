#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
UNSLOTH_ENV_DIR="${UNSLOTH_ENV_DIR:-$BENCH_STORAGE_ROOT/envs/unsloth}"
PYTHON="${UNSLOTH_PYTHON_BIN:-$UNSLOTH_ENV_DIR/bin/python}"
MODEL_DIR="${TRAINING_MODEL_DIR:-$BENCH_STORAGE_ROOT/models/Qwen2.5-Coder-0.5B-Instruct}"
DATASET="$BENCH_STORAGE_ROOT/data/qlora-smoke.jsonl"
RUNNER="$BENCH_STORAGE_ROOT/scripts/unsloth_smoke.py"
RESULT="${UNSLOTH_RESULT_JSONL:-$BENCH_STORAGE_ROOT/results/raw/unsloth-smoke.jsonl}"
OUTPUT_ROOT="${UNSLOTH_OUTPUT_ROOT:-$BENCH_STORAGE_ROOT/results/unsloth}"
RESOURCE_ROOT="${UNSLOTH_RESOURCE_ROOT:-$BENCH_STORAGE_ROOT/results/raw/unsloth-resources}"
LOG_ROOT="${UNSLOTH_LOG_ROOT:-$BENCH_STORAGE_ROOT/logs/unsloth}"
STEPS="${UNSLOTH_STEPS:-8}"
MAX_SEQ_LENGTH="${UNSLOTH_MAX_SEQ_LENGTH:-192}"
LORA_DROPOUT="${UNSLOTH_LORA_DROPOUT:-0.05}"
RUN_PREFIX="${UNSLOTH_RUN_PREFIX:-unsloth}"
WARMUPS="${UNSLOTH_WARMUPS:-1}"
REPETITIONS="${UNSLOTH_REPETITIONS:-3}"
DRY_RUN=false
SAMPLER_PID=""

usage() {
  echo "Usage: $0 [--dry-run] [--help]"
  echo "Run one warm-up and repeated identical SSD-only Unsloth QLoRA smokes."
}

while (($#)); do
  case "$1" in
    --help) usage; exit 0 ;;
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for tool in cp date; do
  command -v "$tool" >/dev/null || { echo "Required command missing: $tool" >&2; exit 1; }
done
[[ "$RUN_PREFIX" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || { echo "UNSLOTH_RUN_PREFIX must be a simple filename prefix (1-64 safe characters)." >&2; exit 2; }
[[ -x "$PYTHON" ]] || { echo "Unsloth Python missing: $PYTHON" >&2; exit 1; }
[[ -f "$MODEL_DIR/model.safetensors" && -f "$DATASET" ]] || { echo "Pinned SSD model or dataset missing; run scripts/23_stage_qlora_model_to_ssd.sh first." >&2; exit 1; }

mkdir -p "$BENCH_STORAGE_ROOT/scripts" "$OUTPUT_ROOT" "$LOG_ROOT" "$(dirname "$RESULT")" "$RESOURCE_ROOT"
cp -- "$ROOT/benchmark/unsloth_smoke.py" "$RUNNER"
SCRIPT_SHA="$(sha256sum "$ROOT/benchmark/unsloth_smoke.py" | cut -d ' ' -f1)"
COPIED_SHA="$(sha256sum "$RUNNER" | cut -d ' ' -f1)"
[[ "$SCRIPT_SHA" == "$COPIED_SHA" ]] || { echo "SSD runner copy checksum mismatch." >&2; exit 1; }
export BENCH_STORAGE_ROOT
export LAB_REPOSITORY_ROOT="$ROOT"
export QLORA_STORAGE_PROFILE=ssd-wsl-ext4-c
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$BENCH_STORAGE_ROOT/cache/pycache/unsloth}"
export HF_HOME="${HF_HOME:-$BENCH_STORAGE_ROOT/cache/huggingface}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

printf 'runtime=%s\nrunner=%s\nrunner_sha256=%s\nmodel=%s\ndataset=%s\nsteps=%s\nsequence=%s\nlora_dropout=%s\nrun_prefix=%s\nwarmups=%s\nrepetitions=%s\n' \
  "$PYTHON" "$RUNNER" "$SCRIPT_SHA" "$MODEL_DIR" "$DATASET" "$STEPS" "$MAX_SEQ_LENGTH" "$LORA_DROPOUT" "$RUN_PREFIX" "$WARMUPS" "$REPETITIONS"
df -h "$BENCH_STORAGE_ROOT"
if [[ "$DRY_RUN" == true ]]; then
  "$PYTHON" "$RUNNER" --model-dir "$MODEL_DIR" --dataset "$DATASET" --output-root "$OUTPUT_ROOT" --result-jsonl "$RESULT" --steps "$STEPS" --max-seq-length "$MAX_SEQ_LENGTH" --lora-dropout "$LORA_DROPOUT" --dry-run
  exit 0
fi

finish() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$SAMPLER_PID" ]]; then kill "$SAMPLER_PID" 2>/dev/null || true; wait "$SAMPLER_PID" 2>/dev/null || true; fi
  [[ ! -f "$RESULT" ]] || cp -- "$RESULT" "$ROOT/results/raw/$(basename "$RESULT")"
  for file in "$RESOURCE_ROOT"/*.jsonl; do [[ ! -f "$file" ]] || cp -- "$file" "$ROOT/results/raw/$(basename "$file")"; done
  for file in "$LOG_ROOT"/*.log; do [[ ! -f "$file" ]] || cp -- "$file" "$ROOT/logs/$(basename "$file")"; done
  exit "$status"
}
trap finish EXIT INT TERM

run_one() {
  local label="$1"
  shift
  local resource_file="$RESOURCE_ROOT/$RUN_PREFIX-$label-resources.jsonl"
  local log_file="$LOG_ROOT/$RUN_PREFIX-$label.log"
  python3 "$ROOT/benchmark/resource_sampler.py" --output "$resource_file" --interval 1 &
  SAMPLER_PID=$!
  set +e
  "$PYTHON" "$RUNNER" --model-dir "$MODEL_DIR" --dataset "$DATASET" --output-root "$OUTPUT_ROOT" \
    --result-jsonl "$RESULT" --steps "$STEPS" --max-seq-length "$MAX_SEQ_LENGTH" --lora-dropout "$LORA_DROPOUT" "$@" 2>&1 | tee "$log_file"
  local status=${PIPESTATUS[0]}
  set -e
  kill "$SAMPLER_PID" 2>/dev/null || true
  wait "$SAMPLER_PID" 2>/dev/null || true
  SAMPLER_PID=""
  return "$status"
}

for ((run=1; run<=WARMUPS; run++)); do run_one "warmup-$run" --warmup; done
for ((run=1; run<=REPETITIONS; run++)); do run_one "rep-$run"; done
