#!/usr/bin/env bash
set -euo pipefail

MODEL_NAME="Qwen2.5-Coder-7B-Instruct"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${DATA_HOME}/local-llm-lab}"
MODEL_SOURCE_DIR="${MODEL_SOURCE_DIR:-/mnt/e/local-llm-models/${MODEL_NAME}}"
TRAINING_SOURCE_DIR="${TRAINING_SOURCE_DIR:-/mnt/e/local-llm-envs/training}"
TRAINING_MODEL_DIR="${TRAINING_MODEL_DIR:-${BENCH_STORAGE_ROOT}/models/${MODEL_NAME}}"
TRAINING_ENV_DIR="${TRAINING_ENV_DIR:-${BENCH_STORAGE_ROOT}/envs/training}"
DRY_RUN=false

usage() {
  cat <<EOF
Usage: $0 [--dry-run] [--help]

Copy the pinned 7B model and isolated training environment from E: to the
WSL Linux filesystem (stored on C: for this machine). Copies are resumable
and never delete or modify the source directories.

Override paths with MODEL_SOURCE_DIR, TRAINING_SOURCE_DIR,
TRAINING_MODEL_DIR, TRAINING_ENV_DIR, and BENCH_STORAGE_ROOT.
EOF
}

while (($#)); do
  case "$1" in
    --help) usage; exit 0 ;;
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for tool in rsync df; do
  command -v "$tool" >/dev/null || { echo "Required command is missing: $tool" >&2; exit 1; }
done
[[ -f "${MODEL_SOURCE_DIR}/config.json" ]] || { echo "Model source is missing config.json: ${MODEL_SOURCE_DIR}" >&2; exit 1; }
[[ -f "${TRAINING_SOURCE_DIR}/pyvenv.cfg" && -x "${TRAINING_SOURCE_DIR}/bin/python" ]] || {
  echo "Training environment source is incomplete: ${TRAINING_SOURCE_DIR}" >&2
  exit 1
}

printf 'Model source:       %s\nModel on SSD:       %s\n' "$MODEL_SOURCE_DIR" "$TRAINING_MODEL_DIR"
printf 'Training source:    %s\nTraining env on SSD:%s\n' "$TRAINING_SOURCE_DIR" "$TRAINING_ENV_DIR"
df -h "$BENCH_STORAGE_ROOT" 2>/dev/null || df -h /
MODE=()
if [[ "$DRY_RUN" == true ]]; then MODE+=(--dry-run); fi

if [[ "$DRY_RUN" == false ]]; then
  mkdir -p "$TRAINING_MODEL_DIR" "$TRAINING_ENV_DIR"
fi
rsync -a --human-readable --info=progress2 --stats "${MODE[@]}" "${MODEL_SOURCE_DIR}/" "${TRAINING_MODEL_DIR}/"
rsync -a --human-readable --stats "${MODE[@]}" "${TRAINING_SOURCE_DIR}/" "${TRAINING_ENV_DIR}/"

if [[ "$DRY_RUN" == false ]]; then
  "$TRAINING_ENV_DIR/bin/python" -c \
    'import pathlib,sys; expected=pathlib.Path(sys.argv[1]).resolve(); actual=pathlib.Path(sys.prefix).resolve(); print(f"Python prefix: {actual}"); assert actual == expected, f"Copied venv is not relocatable: expected {expected}"' \
    "$TRAINING_ENV_DIR"
  printf '\nSSD staging complete. Use:\n'
  printf '  TRAINING_ENV_DIR=%q TRAINING_MODEL_DIR=%q TRAINING_MODEL_ID=%q TRAINING_MODEL_PARAMETERS=%q QLORA_OUTPUT_ROOT=%q bash scripts/14_finetune_qlora.sh\n' \
    "$TRAINING_ENV_DIR" "$TRAINING_MODEL_DIR" "Qwen/Qwen2.5-Coder-7B-Instruct" "7.62B" "${BENCH_STORAGE_ROOT}/results/qlora"
fi
