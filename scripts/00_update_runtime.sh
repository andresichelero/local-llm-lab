#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_STORAGE_ROOT="${BENCH_STORAGE_ROOT:-${HOME}/local-llm-benchmark}"
LLAMA_SOURCE="${LLAMA_CPP_SOURCE:-$BENCH_STORAGE_ROOT/tools/llama.cpp}"
NODE_RUNTIME="${NODE_RUNTIME:-$BENCH_STORAGE_ROOT/runtimes/node-v22.23.3-linux-x64}"
TODAY="$(TZ=America/Sao_Paulo date +%F)"
UPDATE_DIR="$BENCH_STORAGE_ROOT/state/runtime-updates"
MARKER="$UPDATE_DIR/daily-$TODAY.json"
DRY_RUN=0
FORCE=0

usage() {
  cat <<'EOF'
Usage: scripts/00_update_runtime.sh [--dry-run] [--force]

Update the local inference runtime and isolated coding-agent applications once
per Sao Paulo execution day. CUDA, NVIDIA drivers, and training libraries stay
pinned. A successful update writes a dated evidence record and preserves prior
llama.cpp binaries for rollback.
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --force) FORCE=1 ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ -f "$MARKER" && "$FORCE" == 0 ]]; then
  if python3 - "$MARKER" "$TODAY" <<'PY'
import json
import sys

try:
    value = json.load(open(sys.argv[1], encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(1)
raise SystemExit(0 if value.get("date") == sys.argv[2] and value.get("status") == "complete" else 1)
PY
  then
    printf 'Runtime update already completed for today (%s).\n' "$TODAY"
    exit 0
  fi
  echo "Today's update marker is invalid; the update will run again." >&2
fi

for command in git cmake rsync python3; do
  command -v "$command" >/dev/null 2>&1 || { echo "Required command is missing: $command" >&2; exit 1; }
done
[[ -x "$NODE_RUNTIME/bin/node" && -x "$NODE_RUNTIME/bin/npm" ]] || {
  echo "Pinned Node.js/npm runtime is missing: $NODE_RUNTIME" >&2
  exit 1
}
[[ -d "$(dirname "$LLAMA_SOURCE")" ]] || { echo "llama.cpp source parent is missing: $(dirname "$LLAMA_SOURCE")" >&2; exit 1; }

export PATH="$NODE_RUNTIME/bin:$PATH"
NPM="$NODE_RUNTIME/bin/npm"
LLAMA_SERVER_OLD="$BENCH_STORAGE_ROOT/tools/llama-bin/llama-server"
[[ -x "$LLAMA_SERVER_OLD" ]] || { echo "Current llama-server is missing: $LLAMA_SERVER_OLD" >&2; exit 1; }
CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
if ((DRY_RUN == 0)); then
  [[ -x "$CUDA_HOME/bin/nvcc" ]] || {
    echo "CUDA compiler is missing at $CUDA_HOME/bin/nvcc; no software was changed." >&2
    exit 1
  }
  export CUDA_HOME
  export PATH="$CUDA_HOME/bin:$PATH"
  export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
fi

if ! TAG_REFS="$(git ls-remote --tags --refs https://github.com/ggml-org/llama.cpp 'refs/tags/v[0-9]*')"; then
  echo "Could not query stable llama.cpp tags; no software was changed." >&2
  exit 1
fi
LATEST_ENTRY="$(printf '%s\n' "$TAG_REFS" \
  | awk -F'\t' '$2 ~ /^refs\/tags\/v[0-9]+\.[0-9]+\.[0-9]+$/ {sub(/^refs\/tags\//, "", $2); print $2 "\t" $1}' \
  | sort -t $'\t' -k1,1V | tail -n 1)"
LATEST_TAG="${LATEST_ENTRY%%$'\t'*}"
[[ "$LATEST_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Could not resolve latest stable llama.cpp tag." >&2; exit 1; }
TAG_OBJECT="refs/tags/$LATEST_TAG"
TAG_META="$(git ls-remote --tags https://github.com/ggml-org/llama.cpp "$TAG_OBJECT" "$TAG_OBJECT^{}")"
REMOTE_COMMIT="$(printf '%s\n' "$TAG_META" | awk -F'\t' -v tag="$TAG_OBJECT" '$2 == tag {normal=$1} $2 == tag "^{}" {peeled=$1} END {if (peeled != "") print peeled; else print normal}')"
[[ "$REMOTE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "Could not resolve the commit for $LATEST_TAG." >&2; exit 1; }

OPENCODE_VERSION="$("$NPM" view opencode-ai version)"
PI_VERSION="$("$NPM" view @earendil-works/pi-coding-agent version)"
TRUEFORGE_VERSION="$("$NPM" view @truefoundry/trueforge version)"
VIBE_INDEX_OUTPUT="$("$BENCH_STORAGE_ROOT/envs/mistral-vibe/bin/python" -m pip index versions mistral-vibe 2>/dev/null)"
VIBE_LATEST_LINE="${VIBE_INDEX_OUTPUT%%$'\n'*}"
VIBE_LATEST="$(printf '%s\n' "$VIBE_LATEST_LINE" | sed -E 's/.*\(([^)]+)\).*/\1/')"
[[ -n "$VIBE_LATEST" && "$VIBE_LATEST" != "$VIBE_LATEST_LINE" ]] || {
  echo "Could not resolve latest mistral-vibe version." >&2
  exit 1
}

printf 'Daily update date: %s\n' "$TODAY"
printf 'llama.cpp target: %s\n' "$LATEST_TAG"
printf 'OpenCode target: %s\nPi target: %s\nTrueForge target: %s\nMistral Vibe target: %s\n' \
  "$OPENCODE_VERSION" "$PI_VERSION" "$TRUEFORGE_VERSION" "$VIBE_LATEST"
if ((DRY_RUN)); then
  echo "Dry run: no packages, source trees, binaries, or marker files were changed."
  exit 0
fi

mkdir -p "$BENCH_STORAGE_ROOT/logs" "$UPDATE_DIR" "$BENCH_STORAGE_ROOT/tools"
LOG="$BENCH_STORAGE_ROOT/logs/runtime-update-$TODAY.log"
exec > >(tee -a "$LOG") 2>&1

SOURCE_PARENT="$(dirname "$LLAMA_SOURCE")"
VERSIONED_SOURCE="$SOURCE_PARENT/llama.cpp-$LATEST_TAG-${REMOTE_COMMIT:0:9}"
if [[ -d "$VERSIONED_SOURCE/.git" ]]; then
  TARGET_COMMIT="$(git -C "$VERSIONED_SOURCE" rev-parse HEAD)"
  if [[ "$TARGET_COMMIT" != "$REMOTE_COMMIT" || -n "$(git -C "$VERSIONED_SOURCE" status --porcelain=v1)" ]]; then
    echo "Existing versioned llama.cpp source differs from the stable tag; preserving it: $VERSIONED_SOURCE" >&2
    exit 1
  fi
else
  if [[ -e "$VERSIONED_SOURCE" ]]; then
    echo "Versioned llama.cpp source path exists but is not a Git checkout; preserving it: $VERSIONED_SOURCE" >&2
    exit 1
  fi
  SOURCE_STAGE="$SOURCE_PARENT/.llama.cpp-$LATEST_TAG-stage-$(date +%H%M%S)-$$"
  mkdir -p "$SOURCE_PARENT"
  git clone --depth=1 --branch "$LATEST_TAG" --single-branch \
    https://github.com/ggml-org/llama.cpp "$SOURCE_STAGE"
  TARGET_COMMIT="$(git -C "$SOURCE_STAGE" rev-parse HEAD)"
  if [[ "$TARGET_COMMIT" != "$REMOTE_COMMIT" ]]; then
    echo "Cloned llama.cpp commit does not match the stable tag metadata; preserving $SOURCE_STAGE." >&2
    exit 1
  fi
  mv "$SOURCE_STAGE" "$VERSIONED_SOURCE"
fi

BUILD_DIR="$VERSIONED_SOURCE/build"
if [[ ! -x "$BUILD_DIR/bin/llama-server" || ! -f "$BUILD_DIR/.runtime-commit" || \
      "$(cat "$BUILD_DIR/.runtime-commit" 2>/dev/null || true)" != "$TARGET_COMMIT" ]]; then
  if [[ -f "$BUILD_DIR/CMakeCache.txt" ]]; then
    CACHED_SOURCE="$(awk -F= '$1 == "CMAKE_HOME_DIRECTORY:INTERNAL" {print $2; exit}' "$BUILD_DIR/CMakeCache.txt")"
    if [[ -n "$CACHED_SOURCE" && "$(readlink -f "$CACHED_SOURCE")" != "$(readlink -f "$VERSIONED_SOURCE")" ]]; then
      PRESERVED_BUILD="$BUILD_DIR.preserved-$(date +%H%M%S)"
      mv "$BUILD_DIR" "$PRESERVED_BUILD"
      printf 'Preserved incomplete build with a different source tree at %s\n' "$PRESERVED_BUILD"
    fi
  fi
  CUDA_HOST=()
  if [[ -x /usr/bin/g++-12 ]]; then CUDA_HOST=(-DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12); fi
  cmake -S "$VERSIONED_SOURCE" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON \
    -DCMAKE_CUDA_COMPILER="$CUDA_HOME/bin/nvcc" \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=ON "${CUDA_HOST[@]}"
  cmake --build "$BUILD_DIR" --config Release --target llama-cli llama-server --parallel "${BUILD_JOBS:-2}"
  printf '%s\n' "$TARGET_COMMIT" > "$BUILD_DIR/.runtime-commit"
fi

BUILD_VERSION="$(LD_LIBRARY_PATH="$BUILD_DIR/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$BUILD_DIR/bin/llama-server" --version 2>&1)"
VERSIONED_DIR="$BENCH_STORAGE_ROOT/tools/llama-bin-$LATEST_TAG-${TARGET_COMMIT:0:9}"
if [[ ! -x "$VERSIONED_DIR/llama-server" ]]; then
  STAGE_DIR="$BENCH_STORAGE_ROOT/tools/.llama-bin-stage-$TARGET_COMMIT-$(date +%H%M%S)-$$"
  mkdir "$STAGE_DIR"
  rsync -a "$BUILD_DIR/bin/" "$STAGE_DIR/"
  printf '%s\n' "$TARGET_COMMIT" > "$STAGE_DIR/runtime-commit.txt"
  STAGED_VERSION="$(LD_LIBRARY_PATH="$STAGE_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$STAGE_DIR/llama-server" --version 2>&1)"
  [[ "$BUILD_VERSION" == "$STAGED_VERSION" ]] || {
    echo "llama.cpp version changed while staging; refusing activation." >&2
    exit 1
  }
  if LD_LIBRARY_PATH="$STAGE_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ldd "$STAGE_DIR/llama-server" \
      | grep -F "$BUILD_DIR/bin/" >/dev/null; then
    echo "Staged llama-server still loads libraries from the build directory." >&2
    exit 1
  fi
  mv "$STAGE_DIR" "$VERSIONED_DIR"
fi

CURRENT_DIR="$BENCH_STORAGE_ROOT/tools/llama-bin"
if [[ -e "$CURRENT_DIR" && ! -L "$CURRENT_DIR" ]]; then
  BACKUP_DIR="$CURRENT_DIR.preserved-$TODAY"
  if [[ -e "$BACKUP_DIR" ]]; then
    BACKUP_DIR="$BACKUP_DIR-$(date +%H%M%S)"
  fi
  mv "$CURRENT_DIR" "$BACKUP_DIR"
  printf 'Preserved previous llama.cpp runtime at %s\n' "$BACKUP_DIR"
fi
ln -sfn "$VERSIONED_DIR" "$CURRENT_DIR"
LLAMA_VERSION="$(LD_LIBRARY_PATH="$CURRENT_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$CURRENT_DIR/llama-server" --version 2>&1)"
[[ "$LLAMA_VERSION" == "$BUILD_VERSION" ]] || { echo "Activated llama.cpp version did not verify." >&2; exit 1; }
LD_LIBRARY_PATH="$CURRENT_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$CURRENT_DIR/llama-server" --help >/dev/null

install_npm_app() {
  local package="$1" install_dir="$2" version="$3"
  "$NPM" install --prefix "$install_dir" --save-exact "$package@$version"
  "$NPM" ls --prefix "$install_dir" --depth=0 "$package"
}

install_npm_app opencode-ai "$BENCH_STORAGE_ROOT/envs/node-harnesses/opencode" "$OPENCODE_VERSION"
install_npm_app @earendil-works/pi-coding-agent "$BENCH_STORAGE_ROOT/envs/node-harnesses/pi" "$PI_VERSION"
install_npm_app @truefoundry/trueforge "$BENCH_STORAGE_ROOT/envs/node-harnesses/trueforge" "$TRUEFORGE_VERSION"
"$BENCH_STORAGE_ROOT/envs/mistral-vibe/bin/python" -m pip install --upgrade "mistral-vibe==$VIBE_LATEST"

OPENCODE_BIN="$BENCH_STORAGE_ROOT/envs/node-harnesses/opencode/node_modules/opencode-linux-x64/bin/opencode"
PI_BIN="$BENCH_STORAGE_ROOT/envs/node-harnesses/pi/node_modules/.bin/pi"
TRUEFORGE_BIN="$BENCH_STORAGE_ROOT/envs/node-harnesses/trueforge/node_modules/.bin/trueforge"
OPENCODE_INSTALLED="$("$OPENCODE_BIN" --version)"
PI_INSTALLED="$("$PI_BIN" --version)"
TRUEFORGE_INSTALLED="$("$NODE_RUNTIME/bin/node" -p "require('$BENCH_STORAGE_ROOT/envs/node-harnesses/trueforge/node_modules/@truefoundry/trueforge/package.json').version")"
TRUEFORGE_HELP="$("$TRUEFORGE_BIN" --help)"
VIBE_INSTALLED="$("$BENCH_STORAGE_ROOT/envs/mistral-vibe/bin/python" -c 'from importlib.metadata import version; print(version("mistral-vibe"))')"

[[ "$OPENCODE_INSTALLED" == "$OPENCODE_VERSION" ]] || { echo "OpenCode version verification failed." >&2; exit 1; }
[[ "$PI_INSTALLED" == "$PI_VERSION" ]] || { echo "Pi version verification failed." >&2; exit 1; }
[[ "$TRUEFORGE_INSTALLED" == "$TRUEFORGE_VERSION" ]] || { echo "TrueForge version verification failed." >&2; exit 1; }
[[ "$TRUEFORGE_HELP" == *"TrueForge v$TRUEFORGE_VERSION"* ]] || { echo "TrueForge CLI smoke verification failed." >&2; exit 1; }
[[ "$VIBE_INSTALLED" == "$VIBE_LATEST" ]] || { echo "Mistral Vibe version verification failed." >&2; exit 1; }

EVIDENCE_RELATIVE="results/system-audit/runtime-updates/daily-$TODAY.json"
mkdir -p "$ROOT/results/system-audit/runtime-updates"
python3 - "$ROOT/versions.lock" "$ROOT/$EVIDENCE_RELATIVE" "$MARKER" "$TODAY" \
  "$LATEST_TAG" "$TARGET_COMMIT" "$LLAMA_VERSION" "$OPENCODE_INSTALLED" "$PI_INSTALLED" \
  "$TRUEFORGE_INSTALLED" "$VIBE_INSTALLED" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

lock_path, evidence_path, marker_path, day, tag, commit, llama, opencode, pi, trueforge, vibe = sys.argv[1:]
evidence = {
    "date": day,
    "status": "complete",
    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    "llama_cpp": {"tag": tag, "commit": commit, "server_version": llama},
    "applications": {"opencode": opencode, "pi": pi, "trueforge": trueforge, "mistral_vibe": vibe},
}
lock_path = Path(lock_path)
updates = {
    "runtime.llama_cpp": f"{tag}; llama-cli and llama-server built successfully; commit={commit}",
    "runtime.llama_cpp_target": f"{tag}; exact tag checkout={commit}",
    "harness.opencode": f"opencode-ai {opencode}; npm isolated under envs/node-harnesses/opencode",
    "harness.pi": f"@earendil-works/pi-coding-agent {pi}; npm isolated under envs/node-harnesses/pi",
    "harness.trueforge": f"@truefoundry/trueforge {trueforge}; npm isolated under envs/node-harnesses/trueforge",
    "harness.mistral_vibe": f"mistral-vibe {vibe}; isolated venv at envs/mistral-vibe",
    "audit.llama_cpp_ssd_bundle": f"/home/foxtrot/local-llm-benchmark/tools/llama-bin; verified {tag} commit {commit}; previous runtime preserved",
    "audit.daily_runtime_update": f"{evidence_path}; {day}; exact app versions recorded; no model inference",
}
lines = lock_path.read_text(encoding="utf-8").splitlines()
seen = set()
for index, line in enumerate(lines):
    key, separator, _ = line.partition(":")
    if separator and key in updates:
        lines[index] = f"{key}: {updates[key]}"
        seen.add(key)
lines.extend(f"{key}: {value}" for key, value in updates.items() if key not in seen)
lock_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
Path(evidence_path).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
Path(marker_path).parent.mkdir(parents=True, exist_ok=True)
Path(marker_path).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
PY

printf 'Runtime update completed and recorded: %s\n' "$ROOT/$EVIDENCE_RELATIVE"
printf 'llama.cpp: %s\nOpenCode: %s\nPi: %s\nTrueForge: %s\nMistral Vibe: %s\n' \
  "$LLAMA_VERSION" "$OPENCODE_INSTALLED" "$PI_INSTALLED" "$TRUEFORGE_INSTALLED" "$VIBE_INSTALLED"
