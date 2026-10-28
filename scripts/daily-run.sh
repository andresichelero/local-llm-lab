#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if (($# == 0)); then
  echo "Usage: scripts/daily-run.sh COMMAND [ARG ...]" >&2
  exit 2
fi

bash "$ROOT/scripts/00_update_runtime.sh"
exec "$@"
