#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_PARENT="/home/foxtrot/local-llm-benchmark/tmp"
mkdir -p "$TMP_PARENT"
TMP_DIR="$(mktemp -d "$TMP_PARENT/vibe-runner-smoke.XXXXXX")"
cleanup() {
  python3 - "$TMP_DIR" "$TMP_PARENT" <<'PY'
import shutil
import sys
from pathlib import Path

target, parent = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
if target.parent != parent or not target.name.startswith("vibe-runner-smoke."):
    raise SystemExit(f"Refusing to clean unexpected path: {target}")
shutil.rmtree(target)
PY
}
trap cleanup EXIT
PORT="$(python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)"
mkdir -p "$TMP_DIR/tools" "$TMP_DIR/logs" "$TMP_DIR/models" "$TMP_DIR/envs"
: >"$TMP_DIR/models/fake.gguf"
cat >"$TMP_DIR/tools/server" <<'PY'
#!/usr/bin/python3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[sys.argv.index("--port") + 1])

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *_args):
        pass

HTTPServer(("127.0.0.1", port), Handler).serve_forever()
PY
cat >"$TMP_DIR/envs/vibe" <<'PY'
#!/usr/bin/python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
out = Path(args[args.index("--output-dir") + 1])
out.mkdir(parents=True, exist_ok=True)
resumed = "--resume" in args
(out / "ambient-token-visible.txt").write_text(str("GITHUB_TOKEN" in os.environ))
(out / "export.json").write_text(json.dumps({"session_id": "smoke-session"}))
sys.exit(0 if resumed else 9)
PY
chmod +x "$TMP_DIR/tools/server" "$TMP_DIR/envs/vibe"

set +e
GITHUB_TOKEN=must-not-leak BENCHMARK_ROOT="$TMP_DIR" \
  MODEL_PATH="$TMP_DIR/models/fake.gguf" LLAMA_SERVER="$TMP_DIR/tools/server" \
  VIBE_BIN="$TMP_DIR/envs/vibe" PORT="$PORT" \
  bash "$ROOT/scripts/28_benchmark_vibe_context_stress.sh"
status=$?
set -e
[[ "$status" -eq 1 ]] || { echo "Expected runner failure status 1, got $status" >&2; exit 1; }
RUN_DIR="$(find "$TMP_DIR/results/vibe-context-stress" -mindepth 1 -maxdepth 1 -type d -print -quit)"
[[ -n "$RUN_DIR" ]] || { echo "Runner did not preserve its result directory" >&2; exit 1; }
[[ "$(cat "$RUN_DIR/output-phase-1/ambient-token-visible.txt")" == False ]]
[[ "$(cat "$RUN_DIR/output-phase-2/ambient-token-visible.txt")" == False ]]
[[ "$(cat "$RUN_DIR/git_sha.txt")" == "$(git -C "$ROOT" rev-parse HEAD)" ]]
[[ -s "$RUN_DIR/source_git_status.txt" ]]
[[ "$(cat "$RUN_DIR/source_diff_sha256.txt")" =~ ^[0-9a-f]{64}$ ]]
grep -q '^enable_telemetry = false$' "$RUN_DIR/home/config.toml"
grep -q '^enable_update_checks = false$' "$RUN_DIR/home/config.toml"
echo "runner smoke passed: D:-source checkout accepted; failed phase returned nonzero; credentials were isolated; artifacts preserved"
