# Archived benchmark records

`exllama-qwen35-9b-pre-ssd.jsonl` and its paired resource trace preserve the ExLlamaV3 data present in Git before the C:-SSD-only rerun on 2026-10-11. Those older rows do not encode enough storage-path provenance to count as SSD measurements. They are retained for history and excluded from the active `scripts/15_generate_report.sh` summary; use the top-level ExLlama JSONL for the SSD-only runs documented in `results/reports/exllama-ssd.md`.
