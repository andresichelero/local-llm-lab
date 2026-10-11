#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH_ROOT="${BENCHMARK_ROOT:-/home/foxtrot/local-llm-benchmark}"
MODEL="${MODEL_PATH:-$BENCH_ROOT/models/gguf/Qwen3.5-9B-Q4_K_M.gguf}"
SERVER="${LLAMA_SERVER:-$BENCH_ROOT/tools/llama-bin/llama-server}"
VIBE="${VIBE_BIN:-$BENCH_ROOT/envs/mistral-vibe/bin/vibe}"
PORT="${PORT:-8080}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$BENCH_ROOT/results/vibe-context-stress/$RUN_ID"
WORKSPACE="$RUN_DIR/workspace"
HOME_DIR="$RUN_DIR/home"
LOG_DIR="$BENCH_ROOT/logs"
SERVER_LOG="$LOG_DIR/vibe-context-stress-server-$RUN_ID.log"

usage() {
  cat <<'EOF'
Usage: scripts/28_benchmark_vibe_context_stress.sh [--help] [--dry-run]
Run two local Vibe prompts against a 32-file synthetic workspace and test continuation after compaction.
All active model, workspace, logs, session state, and outputs must be on WSL ext4.
Environment: BENCHMARK_ROOT, MODEL_PATH, LLAMA_SERVER, VIBE_BIN, PORT.
EOF
}
case "${1:-}" in
  --help|-h) usage; exit 0 ;;
  --dry-run)
    printf 'model=%s\nserver=%s\nvibe=%s\nrun_dir=%s\n' "$MODEL" "$SERVER" "$VIBE" "$RUN_DIR"
    exit 0
    ;;
  "") ;;
  *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
esac

for path in "$ROOT" "$BENCH_ROOT" "$MODEL" "$SERVER" "$VIBE" "$LOG_DIR"; do
  [[ -e "$path" ]] || { echo "Required path does not exist: $path" >&2; exit 1; }
  filesystem="$(findmnt -n -o FSTYPE -T "$path")"
  [[ "$filesystem" == ext4 ]] || { echo "SSD-only preflight: $path is on $filesystem, expected WSL ext4" >&2; exit 1; }
done
if curl --silent --fail "http://127.0.0.1:$PORT/health" >/dev/null; then
  echo "Port $PORT already has a server; refusing to reuse an unowned process." >&2
  exit 1
fi

mkdir -p "$WORKSPACE" "$HOME_DIR" "$RUN_DIR/output-phase-1" "$RUN_DIR/output-phase-2" "$LOG_DIR"
python3 - "$WORKSPACE" <<'PY'
import hashlib
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
words = ["amber", "birch", "cobalt", "delta", "ember", "frost", "granite", "harbor", "indigo", "juniper"]
for i in range(1, 33):
    lines = []
    for j in range(28):
        a, b = words[(i + j) % len(words)], words[(i * 3 + j * 2) % len(words)]
        lines.append(f"Record {i}-{j}: {a} {b} {a}-{j} is a synthetic benchmark record used only to create deterministic repository context. Its value has no operational meaning. Verify indexes before using it.")
    fingerprint = hashlib.sha256(f"pi-context-stress-2026|archive-{i:02d}".encode()).hexdigest()[:12].upper()
    lines.append(f"ARCHIVE FINGERPRINT: {fingerprint}. Record this exact value in the manifest.")
    if i == 7:
        lines.append("ARCHIVE RECOVERY KEY: GLACIER-47-MAPLE. Preserve this exact value for final verification.")
    (workspace / f"archive-{i:02d}.md").write_text(f"# Archive {i}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
(workspace / "README.md").write_text("# Vibe context stress fixture\n\nSynthetic files for local context-continuity testing.\n", encoding="utf-8")
(workspace / "test_result.py").write_text("""from pathlib import Path
import hashlib
import unittest

class ResultTests(unittest.TestCase):
    def test_summary_exists(self):
        text = Path(__file__).with_name("summary.md").read_text()
        self.assertIn("archive_count: 32", text)
        self.assertIn("recovery_key: GLACIER-47-MAPLE", text)
    def test_manifest_has_every_fingerprint(self):
        expected = [f"archive-{i:02d}=" + hashlib.sha256(f"pi-context-stress-2026|archive-{i:02d}".encode()).hexdigest()[:12].upper() for i in range(1, 33)]
        self.assertEqual(Path(__file__).with_name("archive_manifest.txt").read_text().splitlines(), expected)

if __name__ == "__main__":
    unittest.main()
""", encoding="utf-8")
PY
git -C "$WORKSPACE" init --quiet
git -C "$WORKSPACE" add .
git -C "$WORKSPACE" -c user.name='Local LLM Lab' -c user.email='lab@example.invalid' commit --quiet -m 'fixture baseline'

cat >"$RUN_DIR/phase-1.md" <<'EOF'
Inspect every file archive-01.md through archive-32.md using your tools. For each file, copy its exact ARCHIVE FINGERPRINT to archive_manifest.txt as one line archive-NN=FINGERPRINT, in numeric order. Find the exact ARCHIVE RECOVERY KEY in archive-07.md and preserve it in summary.md as recovery_key: <exact value>. Include exactly archive_count: 32 and a short description. Run python3 test_result.py and fix every mismatch by inspecting the relevant archive. Do not create recovery.txt yet; a second user task will ask you to recover the key after the context has compacted. Do not claim completion unless the tests pass.
EOF
cat >"$RUN_DIR/phase-2.md" <<'EOF'
This is a new continuation task after archive inspection and automatic context compaction. Using only the key preserved in summary.md or the continued task state, write exactly that key to recovery.txt. Do not reopen any archive file. Run python3 test_result.py and report the recovered key and whether compaction occurred.
EOF

cp "$ROOT/benchmark/configs/harnesses/vibe.config.toml" "$HOME_DIR/config.toml"
python3 - "$HOME_DIR/config.toml" "$PORT" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
s = p.read_text(encoding="utf-8")
s = s.replace('api_base = "http://127.0.0.1:8080/v1"', f'api_base = "http://127.0.0.1:{sys.argv[2]}/v1"')
p.write_text(s, encoding="utf-8")
PY

LD_LIBRARY_PATH="$BENCH_ROOT/tools/llama-bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$SERVER" --model "$MODEL" --host 127.0.0.1 --port "$PORT" --ctx-size 16384 \
  --n-gpu-layers 99 --batch-size 256 --ubatch-size 128 --flash-attn on \
  --cache-type-k q4_0 --cache-type-v q4_0 --reasoning off >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
SAMPLER_PID=""
cleanup() {
  if [[ -n "$SAMPLER_PID" ]] && kill -0 "$SAMPLER_PID" 2>/dev/null; then kill "$SAMPLER_PID"; wait "$SAMPLER_PID" || true; fi
  if kill -0 "$SERVER_PID" 2>/dev/null; then kill "$SERVER_PID"; wait "$SERVER_PID" || true; fi
}
trap cleanup EXIT INT TERM
ready=0
for _ in $(seq 1 180); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then tail -100 "$SERVER_LOG" >&2; exit 1; fi
  if curl --silent --fail "http://127.0.0.1:$PORT/health" >/dev/null; then ready=1; break; fi
  sleep 1
done
(( ready == 1 )) || { echo "llama-server failed readiness check" >&2; tail -100 "$SERVER_LOG" >&2; exit 1; }

export HOME="$HOME_DIR" VIBE_HOME="$HOME_DIR" XDG_CONFIG_HOME="$HOME_DIR/.config"
export XDG_DATA_HOME="$HOME_DIR/.local/share" XDG_CACHE_HOME="$HOME_DIR/.cache"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib"
python3 "$ROOT/benchmark/resource_sampler.py" --output "$RUN_DIR/resources.jsonl" --interval 1 >/dev/null 2>&1 &
SAMPLER_PID=$!
set +e
"$VIBE" --prompt-file "$RUN_DIR/phase-1.md" --workdir "$WORKSPACE" --trust --auto-approve --max-turns 40 --max-tokens 250000 --time-limit 240 --output json --output-dir "$RUN_DIR/output-phase-1" >"$RUN_DIR/stdout-phase-1.json" 2>"$RUN_DIR/stderr-phase-1.log"
phase1_status=$?
SESSION_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8")).get("session_id", ""))' "$RUN_DIR/output-phase-1/export.json")"
if [[ -z "$SESSION_ID" ]]; then
  echo "Vibe did not export a session ID; cannot run the continuation phase." >&2
  phase2_status=4
else
  "$VIBE" --resume "$SESSION_ID" --prompt-file "$RUN_DIR/phase-2.md" --workdir "$WORKSPACE" --trust --auto-approve --max-turns 20 --max-tokens 350000 --time-limit 240 --output json --output-dir "$RUN_DIR/output-phase-2" >"$RUN_DIR/stdout-phase-2.json" 2>"$RUN_DIR/stderr-phase-2.log"
  phase2_status=$?
fi
set -e
printf 'run_dir=%s\nserver_log=%s\nphase1_exit=%s\nphase2_exit=%s\n' "$RUN_DIR" "$SERVER_LOG" "$phase1_status" "$phase2_status"
exit 0
