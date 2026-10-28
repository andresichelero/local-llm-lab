#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TASK_ROOT"
exec bash "$TASK_ROOT/scripts/daily-run.sh" \
  /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python \
  -m benchmark.practical_selection --execute "$@"
