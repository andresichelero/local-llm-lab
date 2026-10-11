#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL_SOURCE_DIR="${MODEL_SOURCE_DIR:-/mnt/e/local-llm-models/Qwen2.5-Coder-0.5B-Instruct}"
MODEL_DEST_DIR="${MODEL_DEST_DIR:-$BENCH_STORAGE_ROOT/models/Qwen2.5-Coder-0.5B-Instruct}"
DATASET_SOURCE="${DATASET_SOURCE:-$ROOT/benchmark/data/qlora-smoke.jsonl}"
DATASET_DEST="${DATASET_DEST:-$BENCH_STORAGE_ROOT/data/qlora-smoke.jsonl}"
EXPECTED_SIZE=988097824
EXPECTED_SHA256=f9523886352217ded3aeeef552b381af79d568c6d49a4b9e423288cea56b0a44
DRY_RUN=false

usage() {
  echo "Usage: $0 [--dry-run] [--help]"
  echo "Copy the pinned 0.5B training model and tiny dataset from archives/repo to SSD-backed WSL ext4."
  echo "Overrides: BENCH_STORAGE_ROOT, MODEL_SOURCE_DIR, MODEL_DEST_DIR, DATASET_SOURCE, DATASET_DEST."
}

while (($#)); do
  case "$1" in
    --help) usage; exit 0 ;;
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for tool in cmp cp df rsync sha256sum stat; do
  command -v "$tool" >/dev/null || { echo "Required command missing: $tool" >&2; exit 1; }
done
[[ -f "$MODEL_SOURCE_DIR/model.safetensors" ]] || { echo "Archive model is missing." >&2; exit 1; }
[[ "$(stat -c '%s' "$MODEL_SOURCE_DIR/model.safetensors")" == "$EXPECTED_SIZE" ]] || { echo "Archive model size mismatch." >&2; exit 1; }
SOURCE_HASH="$(sha256sum "$MODEL_SOURCE_DIR/model.safetensors")"
[[ "${SOURCE_HASH%% *}" == "$EXPECTED_SHA256" ]] || { echo "Archive model checksum mismatch." >&2; exit 1; }
[[ -f "$DATASET_SOURCE" ]] || { echo "Dataset source is missing: $DATASET_SOURCE" >&2; exit 1; }

printf 'Archive source: %s\nSSD model: %s\nModel size: %s bytes\nModel SHA-256: %s\nDataset source: %s\nSSD dataset: %s\n' \
  "$MODEL_SOURCE_DIR" "$MODEL_DEST_DIR" "$EXPECTED_SIZE" "$EXPECTED_SHA256" "$DATASET_SOURCE" "$DATASET_DEST"
df -h "$BENCH_STORAGE_ROOT" /mnt/e

if [[ -e "$MODEL_DEST_DIR" ]]; then
  [[ -f "$MODEL_DEST_DIR/model.safetensors" ]] || { echo "SSD destination exists without model weights; refusing." >&2; exit 1; }
  [[ "$(stat -c '%s' "$MODEL_DEST_DIR/model.safetensors")" == "$EXPECTED_SIZE" ]] || { echo "SSD model size mismatch; refusing." >&2; exit 1; }
  DEST_HASH="$(sha256sum "$MODEL_DEST_DIR/model.safetensors")"
  [[ "${DEST_HASH%% *}" == "$EXPECTED_SHA256" ]] || { echo "SSD model checksum mismatch; refusing." >&2; exit 1; }
else
  MODEL_PART="${MODEL_DEST_DIR}.partial"
  [[ ! -e "$MODEL_PART" ]] || { echo "Partial SSD destination exists; inspect before retry: $MODEL_PART" >&2; exit 1; }
  REQUIRED_BYTES=$((EXPECTED_SIZE + 536870912))
  AVAILABLE_BYTES="$(df --output=avail -B1 "$BENCH_STORAGE_ROOT" | tail -n 1 | tr -d ' ')"
  [[ "$AVAILABLE_BYTES" -ge "$REQUIRED_BYTES" ]] || { echo "Insufficient SSD free space." >&2; exit 1; }
  if [[ "$DRY_RUN" == true ]]; then echo "Dry run: model copy would be verified before use."; exit 0; fi
  mkdir -p "$(dirname "$MODEL_DEST_DIR")"
  mkdir "$MODEL_PART"
  rsync -a --partial "$MODEL_SOURCE_DIR/" "$MODEL_PART/"
  [[ "$(stat -c '%s' "$MODEL_PART/model.safetensors")" == "$EXPECTED_SIZE" ]] || { echo "Staged model size mismatch; partial retained." >&2; exit 1; }
  DEST_HASH="$(sha256sum "$MODEL_PART/model.safetensors")"
  [[ "${DEST_HASH%% *}" == "$EXPECTED_SHA256" ]] || { echo "Staged model checksum mismatch; partial retained." >&2; exit 1; }
  mv -n -- "$MODEL_PART" "$MODEL_DEST_DIR"
fi

if [[ -e "$DATASET_DEST" ]]; then
  cmp -s "$DATASET_SOURCE" "$DATASET_DEST" || { echo "Existing SSD dataset differs from the source; refusing overwrite." >&2; exit 1; }
else
  if [[ "$DRY_RUN" == true ]]; then echo "Dry run: dataset copy would be staged on the SSD."; exit 0; fi
  mkdir -p "$(dirname "$DATASET_DEST")"
  cp -- "$DATASET_SOURCE" "$DATASET_DEST"
fi
[[ "$(sha256sum "$MODEL_DEST_DIR/model.safetensors" | cut -d ' ' -f1)" == "$EXPECTED_SHA256" ]]
cmp -s "$DATASET_SOURCE" "$DATASET_DEST"
echo "Pinned model and dataset are staged and verified on SSD."
