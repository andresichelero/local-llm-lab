#!/usr/bin/env bash
set -euo pipefail

ENV_DIR="${EXLLAMA_ENV_DIR:-/mnt/e/local-llm-envs/exllamav3}"
CACHE_DIR="${UV_CACHE_DIR:-/mnt/e/local-llm-cache}"
PYTHON="${EXLLAMA_PYTHON:-python3.12}"
WHEEL_URL="https://github.com/turboderp-org/exllamav3/releases/download/v1.6.0/exllamav3-1.6.0+cu128.torch2.10.0-cp312-cp312-linux_x86_64.whl"
WHEEL_SHA256="201a1c1c611cf96a9ebdfa1ae0a9d165a30399026160ca963970765a03f0dfbe"

usage() {
  echo "Usage: $0 [--dry-run]"
  echo "Set EXLLAMA_ENV_DIR and UV_CACHE_DIR to place the isolated environment/cache."
}

DRY_RUN=0
while (($#)); do
  case "$1" in
    --help) usage; exit 0 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v uv >/dev/null || { echo "uv is required; run scripts/01_install_base.sh first." >&2; exit 1; }
command -v "$PYTHON" >/dev/null || { echo "Python 3.12 is required." >&2; exit 1; }
mkdir -p "$(dirname "$ENV_DIR")" "$CACHE_DIR"
FREE_BYTES=$(df -PB1 "$(dirname "$ENV_DIR")" | awk 'NR==2 {print $4}')
MIN_FREE_BYTES=$((8 * 1024 * 1024 * 1024))
printf 'env=%s\ncache=%s\nfree_bytes=%s\nminimum_free_bytes=%s\nwheel=%s\nwheel_sha256=%s\n' \
  "$ENV_DIR" "$CACHE_DIR" "$FREE_BYTES" "$MIN_FREE_BYTES" "$WHEEL_URL" "$WHEEL_SHA256"
if ((FREE_BYTES < MIN_FREE_BYTES)); then
  echo "At least 8 GiB free space is required on the environment filesystem." >&2
  exit 1
fi
if ((DRY_RUN)); then exit 0; fi

export UV_CACHE_DIR="$CACHE_DIR"
if [[ ! -x "$ENV_DIR/bin/python" ]]; then
  uv venv "$ENV_DIR" --python "$PYTHON"
fi
uv pip install --python "$ENV_DIR/bin/python" torch==2.10.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python "$ENV_DIR/bin/python" \
  'tokenizers>=0.21.1' 'numpy>=2.1.0' rich typing_extensions 'safetensors>=0.3.2' \
  ninja pillow pyyaml marisa_trie pydantic 'llguidance>=1.7.0'
WHEEL_PATH="$CACHE_DIR/$(basename "$WHEEL_URL")"
WHEEL_SHA256="$WHEEL_SHA256" "$ENV_DIR/bin/python" - "$WHEEL_PATH" "$WHEEL_URL" <<'PY'
import hashlib, os, pathlib, sys, urllib.request

target = pathlib.Path(sys.argv[1])
url = sys.argv[2]
expected = os.environ["WHEEL_SHA256"]
if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
    print(f"Using verified wheel cache: {target}")
else:
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "local-llm-lab/0.1"})
    with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as output:
        while chunk := response.read(8 * 1024 * 1024):
            output.write(chunk)
    actual = hashlib.sha256(partial.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"Wheel SHA-256 mismatch: expected {expected}, got {actual}; partial preserved at {partial}")
    partial.replace(target)
    print(f"Downloaded and verified wheel: {target}")
PY
uv pip install --python "$ENV_DIR/bin/python" --no-deps "$WHEEL_PATH"
"$ENV_DIR/bin/python" - <<PY
import hashlib, urllib.request
import torch, exllamav3
from importlib.metadata import version

assert torch.__version__.startswith("2.10.0+cu128"), torch.__version__
assert torch.cuda.is_available(), "PyTorch cannot see CUDA"
print(f"torch={torch.__version__}; cuda={torch.version.cuda}; gpu={torch.cuda.get_device_name(0)}")
print(f"exllamav3={version('exllamav3')}")
PY
