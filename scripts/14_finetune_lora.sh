#!/usr/bin/env bash
# LoRA/QLoRA fine-tuning wrapper. Arguments are passed to benchmark/finetune_lora.py.
# Interpreter selection: TRAINING_PYTHON overrides TRAINING_ENV_DIR (default: the isolated WSL training venv).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib_env.sh"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: scripts/14_finetune_lora.sh [--dry-run] [finetune_lora.py options]

Examples:
  scripts/14_finetune_lora.sh --dry-run --tiny-random
  TRAINING_PYTHON=/path/to/venv/bin/python scripts/14_finetune_lora.sh --tiny-random --output results/raw/finetune-lora-tiny.jsonl
  scripts/14_finetune_lora.sh --model-dir "$MODEL_DIR/<model>" --model-id <id> --model-revision <rev> --qlora

--tiny-random is a CPU code-path smoke test with random weights, not a quality or GPU measurement.
Real-model runs refuse to start when CUDA is unavailable.
USAGE
  exit 0
fi

PYTHON="${TRAINING_PYTHON:-$TRAINING_ENV_DIR/bin/python}"
[[ -x "$PYTHON" ]] || { echo "Training interpreter not found: $PYTHON (set TRAINING_PYTHON or run scripts/05_install_training_stack.sh)." >&2; exit 1; }
mkdir -p "$ROOT/results/raw" "$ROOT/logs"
"$PYTHON" "$ROOT/benchmark/finetune_lora.py" "$@" 2>&1 | tee -a "$ROOT/logs/finetune-lora.log"
