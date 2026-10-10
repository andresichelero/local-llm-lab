#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/tools"
SRC="$TOOLS/llama.cpp"
BUILD="$SRC/build"
TAG="${LLAMA_CPP_TAG:-v0.6.0}"
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --help) echo "Usage: $0 [--dry-run] (LLAMA_CPP_TAG defaults to v0.6.0)"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
if [[ ! -x "$CUDA_HOME/bin/nvcc" ]]; then echo "nvcc is missing. Run scripts/02_install_cuda_runtime.sh first." >&2; exit 1; fi
export CUDA_HOME
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
if ((DRY_RUN)); then printf 'Would clone/build %s at %s with CUDA into %s\n' https://github.com/ggml-org/llama.cpp "$TAG" "$BUILD"; exit; fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
exec > >(tee "$ROOT/logs/llamacpp-build-$STAMP.log") 2>&1
mkdir -p "$TOOLS"
if [[ ! -d "$SRC/.git" ]]; then git clone --filter=blob:none --no-checkout https://github.com/ggml-org/llama.cpp "$SRC"; fi
git -C "$SRC" fetch --tags --depth=1 origin "$TAG"
git -C "$SRC" checkout --detach "$TAG"
CUDA_HOST=()
if [[ -x /usr/bin/g++-12 ]]; then CUDA_HOST=(-DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12); fi
cmake -S "$SRC" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=ON "${CUDA_HOST[@]}"
cmake --build "$BUILD" --config Release --target llama-cli llama-server --parallel "${BUILD_JOBS:-2}"
"$BUILD/bin/llama-cli" --version
"$BUILD/bin/llama-server" --version
git -C "$SRC" rev-parse HEAD | tee "$ROOT/results/system-audit/llama-cpp-commit.txt"
