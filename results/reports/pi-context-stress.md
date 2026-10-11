# Pi local context-compaction stress

This is a functional stress probe, not a throughput ranking. It ran Pi SDK 1.1.0 with Qwen3.5-9B Q4_K_M through llama.cpp on the RTX 3070, using a 16,384-token context. Auto-compaction was enabled with a 2,048-token reserve and 4,096 recent-token retention. Scratch workspaces, sessions, model, server, and raw run files were on the C:-hosted WSL2 SSD; no HDD benchmark I/O was used.

Success requires: at least one automatic compaction, all 32 archive files evidenced in actual Pi tool-call transcripts, an exact 32-line fingerprint manifest, the exact recovery key in the summary and continuation file, a passing workspace test, and clean source provenance.

| Run (UTC) | Time (s) | Compactions | Tools | Archive files read | Summary / key | Manifest | Continuation | Test | Result |
|---|---:|---:|---:|---:|---|---|---|---:|---|
| 2026-10-11T10:38:21.971Z | 115.0 | 5 | 34 | 32/32 | fail | fail | fail | 0 | FAIL |
| 2026-10-11T10:40:40.395Z | 80.1 | 3 | 24 | 20/32 | pass | fail | fail | 0 | FAIL |
| 2026-10-11T10:42:39.808Z | 53.5 | 2 | 15 | 7/32 | pass | fail | pass | 0 | FAIL |
| 2026-10-11T10:46:22.180Z | 133.9 | 5 | 25 | 15/32 | fail | fail | fail | 1 | FAIL |
| 2026-10-11T13:58:24.923Z | 225.7 | 9 | 31 | 31/32 | fail | fail | fail | 1 | FAIL |

Full quality passes: 0/5. Earlier attempts remain in the raw data and are not omitted from this assessment.

The first run read all 32 files and passed the summary test, but failed recovery and then exposed a cleanup API error. Later runs preserved parts of the state but failed the full contract; transcript inspection rejected an apparent pass that had read only 7/32 archives. The fourth run read 15/32 files, overflowed the configured context and produced neither summary nor manifest. The fifth run lasted 225.7 seconds, made 31 read-tool calls and covered 31/32 archive files, but produced no summary or manifest; its workspace tests failed. Pi reported 16,828 tokens after phase 1 and 16,906 after phase 2 against a 16,384-token context (102.7% and 103.2%). It emitted nine compaction start events, yet context remained over limit and no continuation key was recovered.

This machine-specific sample shows that compaction events alone do not establish task continuity. Across five runs, none passed the full independent quality contract. The existing records include context estimates, pre-compaction context counts and summary character lengths, but they do not measure the tokenized content removed by each compaction, so a token compression ratio cannot be calculated reliably. Treat Pi as a low-overhead option for bounded tasks, not as validated for long-context continuation with this model and workload. The fifth run's over-limit context is part of its failure, not a valid performance result.

The early attempts are retained in `results/raw/pi-context-stress-exploratory-invalid.jsonl`; the pre-audit apparent pass is retained in `results/raw/pi-context-stress.jsonl`. The fifth trial's session, workspace, and server log were copied to `E:\LocalLLMLabArchive\2026-10-11\pi-context-stress\20261011T135433Z` after measurement and checksum verification; C:-backed WSL ext4 was used for all benchmark execution. Recreate with `scripts/22_benchmark_pi_context_stress.sh`; regenerate this table with `python3 benchmark/summarize_pi_context_stress.py --raw results/raw/pi-context-stress.jsonl --raw results/raw/pi-context-stress-exploratory-invalid.jsonl --csv results/csv/pi-context-stress.csv --report results/reports/pi-context-stress.md`.
