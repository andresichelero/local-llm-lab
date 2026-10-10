#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${MODEL_PATH:-${MODEL_DIR:-/mnt/e/local-llm-models}/granite-4.1-3b-Q4_K_M.gguf}"
CLI="${LLAMA_CLI:-$ROOT/tools/llama.cpp/build/bin/llama-cli}"
if [[ ! -x "$CLI" ]]; then echo "llama-cli not found or not executable: $CLI" >&2; exit 1; fi
if [[ ! -f "$MODEL" ]]; then echo "Model file not found: $MODEL" >&2; exit 1; fi
"$CLI" --model "$MODEL" --n-gpu-layers 99 --ctx-size 2048 --batch-size 256 --ubatch-size 128 --predict 64 --seed 1234 --temp 0 --prompt "Reply with exactly the word READY." 2>&1 | tee "$ROOT/logs/tier0-smoke.log"
