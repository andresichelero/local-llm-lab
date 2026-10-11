#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL_SOURCE_DIR="${MODEL_SOURCE_DIR:-/mnt/e/local-llm-models/Qwen2.5-Coder-7B-Instruct}"
MODEL_DEST_DIR="${MODEL_DEST_DIR:-$BENCH_STORAGE_ROOT/models/Qwen2.5-Coder-7B-Instruct}"
WEIGHT_BYTES=15231271864
RESERVE_BYTES=536870912
DRY_RUN=false

usage() {
  echo "Usage: $0 [--dry-run] [--help]"
  echo "Stage the pinned Qwen2.5-Coder-7B model from the E: archive to SSD-backed WSL ext4."
  echo "Overrides: BENCH_STORAGE_ROOT, MODEL_SOURCE_DIR, MODEL_DEST_DIR."
}

while (($#)); do
  case "$1" in
    --help) usage; exit 0 ;;
    --dry-run) DRY_RUN=true ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for tool in cp df mv rsync sha256sum stat; do
  command -v "$tool" >/dev/null || { echo "Required command missing: $tool" >&2; exit 1; }
done

declare -A expected_sizes=(
  [model-00001-of-00004.safetensors]=4877660776
  [model-00002-of-00004.safetensors]=4932751008
  [model-00003-of-00004.safetensors]=4330865200
  [model-00004-of-00004.safetensors]=1089994880
)
declare -A expected_hashes=(
  [model-00001-of-00004.safetensors]=0b6f069918b07c064cbba8ae4f00f529aa9bbf84b7cdfcb7fc2694a40f6aa8ef
  [model-00002-of-00004.safetensors]=c3d46733e7aa054ea7b063fbccd0a5a08446e7bd1814bef26936c5aa1331da62
  [model-00003-of-00004.safetensors]=9fe45dacee087385b3d2d6dd27a7413a8a56d95f145772facc148fa86fc73446
  [model-00004-of-00004.safetensors]=5aa6e5cbe642377fd441fb4e60e83cca96b2bcd9820e245b9ea06d94653f17f2
)

for file in "${!expected_sizes[@]}"; do
  [[ -f "$MODEL_SOURCE_DIR/$file" ]] || { echo "Pinned archive shard missing: $MODEL_SOURCE_DIR/$file" >&2; exit 1; }
  [[ "$(stat -c '%s' "$MODEL_SOURCE_DIR/$file")" == "${expected_sizes[$file]}" ]] || { echo "Pinned archive shard has wrong size: $file" >&2; exit 1; }
done
for file in config.json tokenizer.json tokenizer_config.json model.safetensors.index.json; do
  [[ -f "$MODEL_SOURCE_DIR/$file" ]] || { echo "Required model metadata missing: $MODEL_SOURCE_DIR/$file" >&2; exit 1; }
done

printf 'Archive: %s\nSSD destination: %s\nPinned weight bytes: %s\n' "$MODEL_SOURCE_DIR" "$MODEL_DEST_DIR" "$WEIGHT_BYTES"
df -h "$BENCH_STORAGE_ROOT" /mnt/e

if [[ -e "$MODEL_DEST_DIR" ]]; then
  for file in "${!expected_sizes[@]}"; do
    [[ "$(stat -c '%s' "$MODEL_DEST_DIR/$file" 2>/dev/null || true)" == "${expected_sizes[$file]}" ]] || { echo "Existing SSD shard missing or has wrong size; refusing: $file" >&2; exit 1; }
    actual="$(sha256sum "$MODEL_DEST_DIR/$file")"
    [[ "${actual%% *}" == "${expected_hashes[$file]}" ]] || { echo "Existing SSD shard checksum mismatch; refusing: $file" >&2; exit 1; }
  done
  echo "Pinned model is already staged and verified on SSD."
  exit 0
fi

MODEL_PART="${MODEL_DEST_DIR}.partial"
[[ ! -e "$MODEL_PART" ]] || { echo "Partial SSD destination exists; inspect before retry: $MODEL_PART" >&2; exit 1; }
AVAILABLE_BYTES="$(df --output=avail -B1 "$BENCH_STORAGE_ROOT" | tail -n 1 | tr -d ' ')"
REQUIRED_BYTES=$((WEIGHT_BYTES + RESERVE_BYTES))
[[ "$AVAILABLE_BYTES" -ge "$REQUIRED_BYTES" ]] || { echo "Insufficient SSD space: need $REQUIRED_BYTES bytes including reserve; have $AVAILABLE_BYTES." >&2; exit 1; }
if [[ "$DRY_RUN" == true ]]; then echo "Dry run: destination has room; copy and verify four pinned shards on SSD."; exit 0; fi

mkdir -p "$(dirname "$MODEL_DEST_DIR")"
mkdir "$MODEL_PART"
rsync -a --partial "$MODEL_SOURCE_DIR/" "$MODEL_PART/"
for file in "${!expected_sizes[@]}"; do
  [[ "$(stat -c '%s' "$MODEL_PART/$file")" == "${expected_sizes[$file]}" ]] || { echo "Staged shard size mismatch; partial retained: $file" >&2; exit 1; }
  actual="$(sha256sum "$MODEL_PART/$file")"
  [[ "${actual%% *}" == "${expected_hashes[$file]}" ]] || { echo "Staged shard checksum mismatch; partial retained: $file" >&2; exit 1; }
done
for file in config.json tokenizer.json tokenizer_config.json model.safetensors.index.json; do
  [[ -f "$MODEL_PART/$file" ]] || { echo "Staged metadata missing; partial retained: $file" >&2; exit 1; }
done
mv -n -- "$MODEL_PART" "$MODEL_DEST_DIR"
echo "Pinned Qwen2.5-Coder-7B model staged and SHA-256 verified on SSD."
