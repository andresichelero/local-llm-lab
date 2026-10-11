#!/usr/bin/env bash
set -euo pipefail

SOURCE_MODEL="${SOURCE_MODEL:-/home/foxtrot/local-llm-benchmark/models/hybrid/qwen2.5-coder-14b-instruct-q4_k_m.gguf}"
ARCHIVE_MODEL="${ARCHIVE_MODEL:-/mnt/e/local-llm-models/hybrid/qwen2.5-coder-14b-instruct-q4_k_m.gguf}"
ARCHIVE_FILESYSTEM="${ARCHIVE_FILESYSTEM:-/mnt/e}"
EXPECTED_SIZE=8988110272
EXPECTED_SHA256=c1e659736d89ac1065fb495330fb824d94001974a4bfa78e7270e43476a8d940
DRY_RUN=false

usage() {
  echo "Usage: $0 [--dry-run] [--help]"
  echo "Verify the tested Qwen 14B model, archive it on E:, then remove its SSD working copy."
}

while (($#)); do
  case "$1" in
    --help) usage; exit 0 ;;
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for tool in cp df sha256sum stat; do
  command -v "$tool" >/dev/null || { echo "Required command missing: $tool" >&2; exit 1; }
done
[[ -f "$SOURCE_MODEL" ]] || { echo "SSD model missing: $SOURCE_MODEL" >&2; exit 1; }
[[ "$(stat -c '%s' "$SOURCE_MODEL")" == "$EXPECTED_SIZE" ]] || { echo "Unexpected SSD model size; refusing archive." >&2; exit 1; }
SOURCE_SHA="$(sha256sum "$SOURCE_MODEL")"
[[ "${SOURCE_SHA%% *}" == "$EXPECTED_SHA256" ]] || { echo "SSD model checksum mismatch; refusing archive." >&2; exit 1; }

printf 'SSD source: %s\nE: archive: %s\nsize: %s bytes\nsha256: %s\n' \
  "$SOURCE_MODEL" "$ARCHIVE_MODEL" "$EXPECTED_SIZE" "$EXPECTED_SHA256"
df -h "$(dirname "$SOURCE_MODEL")" "$ARCHIVE_FILESYSTEM"

if [[ -e "$ARCHIVE_MODEL" ]]; then
  [[ -f "$ARCHIVE_MODEL" ]] || { echo "Archive destination is not a regular file; refusing." >&2; exit 1; }
  [[ "$(stat -c '%s' "$ARCHIVE_MODEL")" == "$EXPECTED_SIZE" ]] || { echo "Existing archive size mismatch; refusing to overwrite." >&2; exit 1; }
  ARCHIVE_SHA="$(sha256sum "$ARCHIVE_MODEL")"
  [[ "${ARCHIVE_SHA%% *}" == "$EXPECTED_SHA256" ]] || { echo "Existing archive checksum mismatch; refusing to overwrite." >&2; exit 1; }
  echo "Existing archive matches pinned size and checksum."
else
  if [[ "$DRY_RUN" == true ]]; then echo "Dry run: would copy, verify, then remove only the SSD source file."; exit 0; fi
  mkdir -p "$(dirname "$ARCHIVE_MODEL")"
  cp -- "$SOURCE_MODEL" "$ARCHIVE_MODEL"
  [[ "$(stat -c '%s' "$ARCHIVE_MODEL")" == "$EXPECTED_SIZE" ]] || { echo "Archive size mismatch; SSD source retained." >&2; exit 1; }
  ARCHIVE_SHA="$(sha256sum "$ARCHIVE_MODEL")"
  [[ "${ARCHIVE_SHA%% *}" == "$EXPECTED_SHA256" ]] || { echo "Archive checksum mismatch; SSD source retained." >&2; exit 1; }
fi

if [[ "$DRY_RUN" == true ]]; then echo "Dry run: archive verified; SSD source would be removed."; exit 0; fi
rm -- "$SOURCE_MODEL"
[[ ! -e "$SOURCE_MODEL" ]] || { echo "SSD source still exists after removal." >&2; exit 1; }
echo "Archive verified; SSD working copy removed."
