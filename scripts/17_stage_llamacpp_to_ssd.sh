#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-/home/foxtrot/local-llm-benchmark}"
SOURCE_DIR="${LLAMA_CPP_BIN_SOURCE:-$ROOT/tools/llama.cpp/build/bin}"
DEST_DIR="${LLAMA_CPP_BIN_DIR:-$BENCH_STORAGE_ROOT/tools/llama-bin}"
DRY_RUN=false

usage() {
  cat <<EOF
Usage: $0 [--dry-run] [--help]

Copy the built llama.cpp runtime and its shared libraries to the WSL-native
benchmark filesystem. The source is left untouched and destination files are
never deleted.

Overrides: LLAMA_CPP_BIN_SOURCE, LLAMA_CPP_BIN_DIR, BENCH_STORAGE_ROOT.
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

command -v rsync >/dev/null || { echo "Required command is missing: rsync" >&2; exit 1; }
[[ -x "$SOURCE_DIR/llama-server" ]] || { echo "llama-server is missing: $SOURCE_DIR" >&2; exit 1; }

printf 'Runtime source: %s\nRuntime on SSD: %s\n' "$SOURCE_DIR" "$DEST_DIR"
du -sh "$SOURCE_DIR"
if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run: no files copied."
  printf 'After staging, use LLAMA_SERVER=%q LD_LIBRARY_PATH=%q RUNTIME_STORAGE_PROFILE=ssd-wsl-ext4-c\n' \
    "$DEST_DIR/llama-server" "$DEST_DIR"
  exit 0
fi

mkdir -p "$DEST_DIR"
rsync -a --human-readable --info=progress2 --stats "$SOURCE_DIR/" "$DEST_DIR/"

SOURCE_VERSION="$("$SOURCE_DIR/llama-server" --version 2>&1)"
DEST_VERSION="$(LD_LIBRARY_PATH="$DEST_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$DEST_DIR/llama-server" --version 2>&1)"
[[ "$SOURCE_VERSION" == "$DEST_VERSION" ]] || {
  echo "Runtime version mismatch after copy." >&2
  printf 'source: %s\ndestination: %s\n' "$SOURCE_VERSION" "$DEST_VERSION" >&2
  exit 1
}

DIFFERENCES="$(rsync -acni --out-format='%n' "$SOURCE_DIR/" "$DEST_DIR/")"
[[ -z "$DIFFERENCES" ]] || {
  echo "Runtime files differ after copy:" >&2
  printf '%s\n' "$DIFFERENCES" >&2
  exit 1
}
if LD_LIBRARY_PATH="$DEST_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ldd "$DEST_DIR/llama-server" | grep -F "$SOURCE_DIR/" >/dev/null; then
  echo "A llama.cpp library still resolves from the source HDD path." >&2
  exit 1
fi

printf 'Verified runtime:\n%s\n' "$DEST_VERSION"
printf 'Use LLAMA_SERVER=%q LD_LIBRARY_PATH=%q RUNTIME_STORAGE_PROFILE=ssd-wsl-ext4-c\n' \
  "$DEST_DIR/llama-server" "$DEST_DIR"
