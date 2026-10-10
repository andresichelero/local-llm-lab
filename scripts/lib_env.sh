# Sourced by the wrappers. Loads optional machine-specific overrides from config/local.env
# (gitignored; copy config/local.env.example) and sets repository-relative defaults.
# shellcheck shell=bash
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
if [[ -f "$ROOT/config/local.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/config/local.env"
  set +a
fi
export MODEL_DIR="${MODEL_DIR:-$ROOT/models}"
export HF_HOME="${HF_HOME:-$ROOT/cache/huggingface}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/cache/uv}"
export EXLLAMA_ENV_DIR="${EXLLAMA_ENV_DIR:-$ROOT/envs/exllamav3}"
export TRAINING_ENV_DIR="${TRAINING_ENV_DIR:-$ROOT/envs/training}"
