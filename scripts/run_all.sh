#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --help) echo "Usage: $0 [--dry-run] — run the current Tier 0 pipeline; model download is explicit."; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
MODEL="${MODEL_PATH:-${MODEL_DIR:-/mnt/e/local-llm-models}/granite-4.1-3b-Q4_K_M.gguf}"
if [[ ! -f "$MODEL" ]]; then echo "Pinned Tier 0 model is missing: $MODEL; run scripts/07_download_models.sh --tier small explicitly." >&2; exit 1; fi
if ((DRY_RUN)); then
  printf 'Would audit system, build llama.cpp CUDA, smoke-test %s, and run benchmark.\n' "$MODEL"
  exit 0
fi
bash "$ROOT/scripts/00_audit_system.sh"
if [[ ! -x "${CUDA_HOME:-/usr/local/cuda}/bin/nvcc" ]]; then
  echo "CUDA compiler is missing. Install with scripts/02_install_cuda_runtime.sh as root, then rerun." >&2
  exit 1
fi
bash "$ROOT/scripts/03_build_llamacpp.sh"
bash "$ROOT/scripts/08_smoke_test.sh"
bash "$ROOT/scripts/09_benchmark_inference.sh"
bash "$ROOT/scripts/15_generate_report.sh"
