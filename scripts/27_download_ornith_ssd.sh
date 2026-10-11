#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
MODEL_DIR="${MODEL_DIR:-$BENCH_STORAGE_ROOT/models/gguf/ornith-1.0-9b}"
MODEL_PATH="$MODEL_DIR/ornith-1.0-9b-Q4_K_M.gguf"
REPO="ornith-ai/Ornith-1.0-9B-GGUF"
REVISION="3296bc7a404871a72ac3f1903f561459c09b5c17"
EXPECTED_SIZE=5629108704
EXPECTED_SHA256=5720d1f671b4996481274fffe01868c3c36e87c135cc8538471cc7bd6087b106
MIN_FREE_BYTES=$((EXPECTED_SIZE + 1073741824))

usage() {
  cat <<'EOF'
Download the pinned official Ornith-1.0-9B Q4_K_M GGUF to WSL ext4 SSD and verify it.

Environment: BENCH_STORAGE_ROOT (default $HOME/local-llm-benchmark), MODEL_DIR.
Use --dry-run to check filesystem and free space without downloading.
An existing file is accepted only if its exact expected size and SHA-256 match.
EOF
}

case "${1:-}" in
  --help) usage; exit 0 ;;
  --dry-run) DRY_RUN=true ;;
  "") DRY_RUN=false ;;
  *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

[[ -d "$BENCH_STORAGE_ROOT" ]] || { echo "SSD benchmark root does not exist: $BENCH_STORAGE_ROOT" >&2; exit 1; }
[[ "$(findmnt -n -o FSTYPE -T "$BENCH_STORAGE_ROOT")" == ext4 ]] || {
  echo "Benchmark root must be on WSL ext4 SSD: $BENCH_STORAGE_ROOT" >&2
  exit 1
}

if [[ -e "$MODEL_PATH" ]]; then
  actual_size="$(stat -c %s "$MODEL_PATH")"
  actual_sha="$(sha256sum "$MODEL_PATH" | awk '{print $1}')"
  [[ "$actual_size" == "$EXPECTED_SIZE" && "$actual_sha" == "$EXPECTED_SHA256" ]] || {
    echo "Existing model differs from the pinned artifact; preserving it at: $MODEL_PATH" >&2
    exit 1
  }
  echo "Pinned model already verified: $MODEL_PATH"
  exit 0
fi

available_bytes="$(df -B1 --output=avail "$BENCH_STORAGE_ROOT" | tail -n 1 | tr -d '[:space:]')"
printf 'repo=%s\nrevision=%s\nfile=%s\nsize_bytes=%s\nsha256=%s\ndestination=%s\nfilesystem=ext4\navailable_bytes=%s\nminimum_required_bytes=%s\n' \
  "$REPO" "$REVISION" "$(basename "$MODEL_PATH")" "$EXPECTED_SIZE" "$EXPECTED_SHA256" "$MODEL_PATH" "$available_bytes" "$MIN_FREE_BYTES"
((available_bytes >= MIN_FREE_BYTES)) || {
  echo "Insufficient SSD space; need artifact size plus a 1 GiB safety margin." >&2
  exit 1
}
command -v hf >/dev/null || { echo "Hugging Face CLI 'hf' is required in WSL." >&2; exit 1; }
[[ "$DRY_RUN" == true ]] && { echo "Dry-run complete; no files downloaded or created."; exit 0; }

mkdir -p "$MODEL_DIR"
hf download "$REPO" "$(basename "$MODEL_PATH")" --revision "$REVISION" --local-dir "$MODEL_DIR"
actual_size="$(stat -c %s "$MODEL_PATH")"
actual_sha="$(sha256sum "$MODEL_PATH" | awk '{print $1}')"
[[ "$actual_size" == "$EXPECTED_SIZE" && "$actual_sha" == "$EXPECTED_SHA256" ]] || {
  echo "Downloaded file does not match the pinned artifact; preserving it for inspection: $MODEL_PATH" >&2
  exit 1
}
printf 'Verified model size=%s sha256=%s path=%s\n' "$actual_size" "$actual_sha" "$MODEL_PATH"
