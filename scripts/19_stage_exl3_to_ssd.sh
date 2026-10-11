#!/usr/bin/env bash
set -euo pipefail

BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL_SOURCE_DIR="${MODEL_SOURCE_DIR:-/mnt/e/local-llm-models/exllama/Qwen3.5-9B-exl3-2.5bpw}"
MODEL_DEST_DIR="${MODEL_DEST_DIR:-$BENCH_STORAGE_ROOT/models/exllama/Qwen3.5-9B-exl3-2.5bpw}"
MODEL_PART_DIR="${MODEL_DEST_DIR}.partial"
WEIGHT_NAME="model.safetensors"
EXPECTED_SIZE_BYTES=5889564052
EXPECTED_SHA256="19e38d592d439a19205469aba6f477355aaa17d81f1f516b222a2abc7ba76d23"
DRY_RUN=false

usage() {
  cat <<EOF
Usage: $0 [--dry-run] [--help]

Stage the pinned EXL3 model from its E: archive to WSL ext4 on C: for tests.
The archive is never modified. A mismatched or partial destination is preserved
and causes an error instead of being overwritten.

Overrides: BENCH_STORAGE_ROOT, MODEL_SOURCE_DIR, MODEL_DEST_DIR.
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
[[ -f "$MODEL_SOURCE_DIR/$WEIGHT_NAME" ]] || { echo "Pinned model archive is missing: $MODEL_SOURCE_DIR/$WEIGHT_NAME" >&2; exit 1; }
SOURCE_SIZE="$(stat -c '%s' "$MODEL_SOURCE_DIR/$WEIGHT_NAME")"
[[ "$SOURCE_SIZE" == "$EXPECTED_SIZE_BYTES" ]] || {
  echo "Unexpected archive size: $SOURCE_SIZE (expected $EXPECTED_SIZE_BYTES)" >&2
  exit 1
}

printf 'Model archive: %s\nSSD destination: %s\nExpected weight size: %s bytes\nExpected SHA-256: %s\n' \
  "$MODEL_SOURCE_DIR" "$MODEL_DEST_DIR" "$EXPECTED_SIZE_BYTES" "$EXPECTED_SHA256"
df -h "$BENCH_STORAGE_ROOT"

if [[ -e "$MODEL_DEST_DIR" ]]; then
  [[ -f "$MODEL_DEST_DIR/$WEIGHT_NAME" ]] || { echo "Destination exists without model weights; refusing to overwrite: $MODEL_DEST_DIR" >&2; exit 1; }
  ACTUAL_SHA256="$(sha256sum "$MODEL_DEST_DIR/$WEIGHT_NAME" | awk '{print $1}')"
  [[ "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] || { echo "Destination checksum mismatch; refusing to overwrite: $MODEL_DEST_DIR" >&2; exit 1; }
  echo "Pinned model is already staged and verified."
  exit 0
fi
[[ ! -e "$MODEL_PART_DIR" ]] || { echo "Partial destination already exists; inspect it before retrying: $MODEL_PART_DIR" >&2; exit 1; }

AVAILABLE_BYTES="$(df --output=avail -B1 "$BENCH_STORAGE_ROOT" | tail -n 1 | tr -d ' ')"
REQUIRED_BYTES=$((EXPECTED_SIZE_BYTES + 536870912))
printf 'Available space: %s bytes; required with 512 MiB margin: %s bytes\n' "$AVAILABLE_BYTES" "$REQUIRED_BYTES"
[[ "$AVAILABLE_BYTES" -ge "$REQUIRED_BYTES" ]] || { echo "Insufficient C: SSD space for staging." >&2; exit 1; }
if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run: no files copied."
  exit 0
fi

mkdir -p "$(dirname "$MODEL_DEST_DIR")"
mkdir "$MODEL_PART_DIR"
rsync -a --partial --human-readable --info=progress2 "$MODEL_SOURCE_DIR/" "$MODEL_PART_DIR/"
ACTUAL_SIZE="$(stat -c '%s' "$MODEL_PART_DIR/$WEIGHT_NAME")"
ACTUAL_SHA256="$(sha256sum "$MODEL_PART_DIR/$WEIGHT_NAME" | awk '{print $1}')"
[[ "$ACTUAL_SIZE" == "$EXPECTED_SIZE_BYTES" && "$ACTUAL_SHA256" == "$EXPECTED_SHA256" ]] || {
  echo "Staged weight verification failed; partial files retained for inspection." >&2
  exit 1
}
mv -n -- "$MODEL_PART_DIR" "$MODEL_DEST_DIR"
[[ -f "$MODEL_DEST_DIR/$WEIGHT_NAME" ]] || { echo "Could not finalize staged model: $MODEL_DEST_DIR" >&2; exit 1; }
printf 'Verified SSD model: %s/%s\n' "$MODEL_DEST_DIR" "$WEIGHT_NAME"
