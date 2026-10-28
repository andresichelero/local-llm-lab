#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# New corrected rounds update once per day; resumes verify their frozen contract.
# This command cannot release inference until the source has complete coverage.
exec /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python \
    -m benchmark.practical_repair "$@"
