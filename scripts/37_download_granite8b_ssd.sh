#!/usr/bin/env bash
set -euo pipefail

BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL_DIR="${MODEL_DIR:-$BENCH_STORAGE_ROOT/models/gguf/granite-4.1-8b}"
HF_CLI="${HF_CLI:-/home/foxtrot/.local/bin/hf}"
REPO="ibm-granite/granite-4.1-8b-GGUF"
REVISION="865b82c2e7970d82e3731278c88c57ae7138359c"
FILE="granite-4.1-8b-Q4_K_M.gguf"
SIZE_BYTES=5347914400
SHA256="ed902ac9eb6adce5a90c6a08c8ea201b50e23fdc5976d1cd0362006afac5309e"
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage: scripts/37_download_granite8b_ssd.sh [--model-dir PATH] [--dry-run] [--help]

Download official IBM Granite 4.1 8B Q4_K_M GGUF to the WSL SSD and verify
its expected byte size and SHA-256. Existing files are never overwritten.

Environment overrides: BENCH_STORAGE_ROOT, MODEL_DIR, HF_CLI.
EOF
}

while (($#)); do
  case "$1" in
    --model-dir) (($# >= 2)) || { echo "--model-dir needs a path" >&2; exit 2; }; MODEL_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

TARGET="$MODEL_DIR/$FILE"
PARENT="$(dirname "$MODEL_DIR")"
SPACE_PATH="$PARENT"
[[ -d "$SPACE_PATH" ]] || SPACE_PATH="$BENCH_STORAGE_ROOT"
AVAILABLE_BYTES="$(df -PB1 "$SPACE_PATH" | awk 'NR == 2 {print $4}')"
printf 'repo=%s\nrevision=%s\nfile=%s\nsize_bytes=%s\nsha256=%s\npath=%s\navailable_bytes=%s\n' \
  "$REPO" "$REVISION" "$FILE" "$SIZE_BYTES" "$SHA256" "$TARGET" "$AVAILABLE_BYTES"

if [[ "$DRY_RUN" == true ]]; then
  ((AVAILABLE_BYTES >= SIZE_BYTES + 8589934592)) || { echo "Insufficient SSD free space for model plus 8 GiB working margin" >&2; exit 1; }
  exit 0
fi

if [[ -e "$TARGET" ]]; then
  [[ -f "$TARGET" ]] || { echo "Refusing to overwrite non-file target: $TARGET" >&2; exit 1; }
  ACTUAL_SIZE="$(stat -c '%s' "$TARGET")"
  ACTUAL_SHA="$(sha256sum "$TARGET" | awk '{print $1}')"
  [[ "$ACTUAL_SIZE" == "$SIZE_BYTES" && "$ACTUAL_SHA" == "$SHA256" ]] || {
    echo "Existing file does not match pinned size/SHA-256; refusing to overwrite: $TARGET" >&2; exit 1;
  }
  echo "Already present and verified: $TARGET"
  exit 0
fi

((AVAILABLE_BYTES >= SIZE_BYTES + 8589934592)) || { echo "Insufficient SSD free space for model plus 8 GiB working margin" >&2; exit 1; }
[[ -x "$HF_CLI" ]] || { echo "Hugging Face CLI not found or not executable: $HF_CLI" >&2; exit 1; }
mkdir -p "$MODEL_DIR"
"$HF_CLI" download "$REPO" "$FILE" --revision "$REVISION" --local-dir "$MODEL_DIR"
ACTUAL_SIZE="$(stat -c '%s' "$TARGET")"
ACTUAL_SHA="$(sha256sum "$TARGET" | awk '{print $1}')"
[[ "$ACTUAL_SIZE" == "$SIZE_BYTES" ]] || { echo "Downloaded file size mismatch: $ACTUAL_SIZE" >&2; exit 1; }
[[ "$ACTUAL_SHA" == "$SHA256" ]] || { echo "Downloaded file SHA-256 mismatch: $ACTUAL_SHA" >&2; exit 1; }
echo "Downloaded and verified: $TARGET"
