#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib_env.sh"

ENV_DIR="$TRAINING_ENV_DIR"
CACHE_DIR="$UV_CACHE_DIR"
PYTHON="${TRAINING_PYTHON:-python3.12}"
DRY_RUN=0
while (($#)); do
  case "$1" in
    --help) echo "Usage: $0 [--dry-run]; TRAINING_ENV_DIR and UV_CACHE_DIR may relocate the isolated install."; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v uv >/dev/null || { echo "uv is required; run scripts/01_install_base.sh first." >&2; exit 1; }
command -v "$PYTHON" >/dev/null || { echo "Python 3.12 is required." >&2; exit 1; }
PARENT="$(dirname "$ENV_DIR")"
mkdir -p "$PARENT"
FREE_BYTES="$(df -PB1 "$PARENT" | awk 'NR==2 {print $4}')"
MIN_FREE_BYTES=$((20 * 1024 * 1024 * 1024))
printf 'env=%s\ncache=%s\npython=%s\nfree_bytes=%s\nminimum_free_bytes=%s\ntorch=2.10.0+cu128\ntransformers=5.19.0\npeft=0.21.2\nbitsandbytes=0.50.2\naccelerate=1.15.0\ntrl=1.14.1\n' \
  "$ENV_DIR" "$CACHE_DIR" "$PYTHON" "$FREE_BYTES" "$MIN_FREE_BYTES"
if ((FREE_BYTES < MIN_FREE_BYTES)); then echo "At least 20 GiB free space is required on the environment filesystem." >&2; exit 1; fi
if ((DRY_RUN)); then exit 0; fi

mkdir -p "$CACHE_DIR"
export UV_CACHE_DIR="$CACHE_DIR"
if [[ ! -x "$ENV_DIR/bin/python" ]]; then uv venv "$ENV_DIR" --python "$PYTHON"; fi
uv pip install --python "$ENV_DIR/bin/python" torch==2.10.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python "$ENV_DIR/bin/python" \
  transformers==5.19.0 peft==0.21.2 bitsandbytes==0.50.2 \
  accelerate==1.15.0 trl==1.14.1
uv pip check --python "$ENV_DIR/bin/python"
"$ENV_DIR/bin/python" - <<'PY'
import torch
import transformers, peft, bitsandbytes, accelerate, trl
assert torch.__version__.startswith("2.10.0+cu128"), torch.__version__
assert torch.cuda.is_available(), "PyTorch cannot see CUDA"
device = torch.cuda.get_device_name(0)
assert "RTX 3070" in device, device
print(f"torch={torch.__version__}; cuda={torch.version.cuda}; gpu={device}")
print(f"transformers={transformers.__version__}; peft={peft.__version__}; bitsandbytes={bitsandbytes.__version__}; accelerate={accelerate.__version__}; trl={trl.__version__}")
PY
