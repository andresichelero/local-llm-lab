#!/usr/bin/env bash
set -euo pipefail

BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL_SOURCE="${MODEL_SOURCE:-/mnt/e/local-llm-models/Qwen3.5-9B-GGUF/Qwen3.5-9B-Q4_K_M.gguf}"
MODEL_DEST_DIR="${MODEL_DEST_DIR:-$BENCH_STORAGE_ROOT/models/gguf}"
MODEL_DEST="$MODEL_DEST_DIR/Qwen3.5-9B-Q4_K_M.gguf"
MODEL_PART="$MODEL_DEST.part"
EXPECTED_SIZE_BYTES=5680522464
EXPECTED_SHA256="03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8"
DRY_RUN=false

usage() {
  cat <<EOF
Usage: $0 [--dry-run] [--help]

Stage the pinned Qwen3.5-9B GGUF from its E: archive to WSL ext4 on the SSD.
The source is never modified. A mismatched existing destination is preserved
and causes an error rather than being overwritten.

Overrides: BENCH_STORAGE_ROOT, MODEL_SOURCE, MODEL_DEST_DIR.
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

for tool in df rsync sha256sum stat; do
  command -v "$tool" >/dev/null || { echo "Required command is missing: $tool" >&2; exit 1; }
done
[[ -f "$MODEL_SOURCE" ]] || { echo "Pinned model archive is missing: $MODEL_SOURCE" >&2; exit 1; }
SOURCE_SIZE="$(stat -c '%s' "$MODEL_SOURCE")"
[[ "$SOURCE_SIZE" == "$EXPECTED_SIZE_BYTES" ]] || {
  echo "Unexpected source size: $SOURCE_SIZE (expected $EXPECTED_SIZE_BYTES)" >&2
  exit 1
}

printf 'Model source: %s\nModel destination: %s\nExpected size: %s bytes\nExpected SHA-256: %s\n' \
  "$MODEL_SOURCE" "$MODEL_DEST" "$EXPECTED_SIZE_BYTES" "$EXPECTED_SHA256"
df -h "$BENCH_STORAGE_ROOT"
if [[ ! -e "$MODEL_DEST" ]]; then
  AVAILABLE_BYTES="$(df --output=avail -B1 "$BENCH_STORAGE_ROOT" | tail -n 1 | tr -d ' ')"
  printf 'Available space: %s bytes\n' "$AVAILABLE_BYTES"
  [[ "$AVAILABLE_BYTES" -ge "$EXPECTED_SIZE_BYTES" ]] || {
    echo "Insufficient space: need $EXPECTED_SIZE_BYTES bytes, have $AVAILABLE_BYTES" >&2
    exit 1
  }
fi
if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run: no files copied."
  exit 0
fi

if [[ -e "$MODEL_DEST" ]]; then
  ACTUAL_SHA256="$(sha256sum "$MODEL_DEST" | awk '{print $1}')"
  [[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] || {
    echo "Destination exists with a different checksum; refusing to overwrite: $MODEL_DEST" >&2
    exit 1
  }
  echo "Pinned model is already staged and verified."
  exit 0
fi

mkdir -p "$MODEL_DEST_DIR"
rsync -a --partial --human-readable --info=progress2 "$MODEL_SOURCE" "$MODEL_PART"
ACTUAL_SHA256="$(sha256sum "$MODEL_PART" | awk '{print $1}')"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] || {
  echo "SHA-256 mismatch; retained the copied file for inspection: $MODEL_PART" >&2
  exit 1
}
mv -n -- "$MODEL_PART" "$MODEL_DEST"
[[ -f "$MODEL_DEST" ]] || { echo "Could not finalize staged model: $MODEL_DEST" >&2; exit 1; }
ACTUAL_SHA256="$(sha256sum "$MODEL_DEST" | awk '{print $1}')"
[[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] || {
  echo "Final destination failed checksum verification: $MODEL_DEST" >&2
  exit 1
}
printf 'Verified staged model: %s\n' "$MODEL_DEST"
printf 'Use MODEL_PATH=%q MODEL_REVISION=%q STORAGE_PROFILE=ssd-wsl-ext4-c\n' \
  "$MODEL_DEST" "3885219b6810b007914f3a7950a8d1b469d598a5"
