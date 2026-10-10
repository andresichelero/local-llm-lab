#!/usr/bin/env bash
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib_env.sh"

usage() {
  cat <<'EOF'
Show reclaimable package-cache and lab artifact sizes without deleting anything.

Usage: cleanup.sh [--help]

This script is intentionally read-only. It never deletes models, datasets,
results, environments, package caches, or user files.
EOF
}

if [[ "${1:-}" == "--help" ]]; then usage; exit 0; fi
if [[ $# -gt 0 ]]; then usage >&2; exit 2; fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
printf 'WSL filesystem availability:\n'
df -h / "$repo_root" "$MODEL_DIR" 2>/dev/null || df -h / "$repo_root"
for path in /var/cache/apt/archives "$repo_root/tools" "$repo_root/logs" "$repo_root/results" "$MODEL_DIR"; do
  if [[ -e "$path" ]]; then du -sh "$path"; fi
done
printf '\nNo files were changed. Review sizes and remove only items you explicitly choose.\n'
