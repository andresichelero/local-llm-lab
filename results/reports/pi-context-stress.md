# Pi local context-compaction stress

This is a functional stress probe, not a throughput ranking. It ran Pi SDK 1.1.0 with Qwen3.5-9B Q4_K_M through llama.cpp on the RTX 3070, using a 16,384-token context. Auto-compaction was enabled with a 2,048-token reserve and 4,096 recent-token retention. Scratch workspaces, sessions, model, server, and raw run files were on the C:-hosted WSL2 SSD; no HDD benchmark I/O was used.

Success requires: at least one automatic compaction, all 32 archive files evidenced in actual Pi tool-call transcripts, an exact 32-line fingerprint manifest, the exact recovery key in the summary and continuation file, a passing workspace test, and clean source provenance.

| Run (UTC) | Time (s) | Compactions | Tools | Archive files read | Summary / key | Manifest | Continuation | Test | Result |
|---|---:|---:|---:|---:|---|---|---|---:|---|
| 2026-10-11T10:38:21.971Z | 115.0 | 5 | 34 | 32/32 | fail | fail | fail | 0 | FAIL |
| 2026-10-11T10:40:40.395Z | 80.1 | 3 | 24 | 20/32 | pass | fail | fail | 0 | FAIL |
| 2026-10-11T10:42:39.808Z | 53.5 | 2 | 15 | 7/32 | pass | fail | pass | 0 | FAIL |
| 2026-10-11T10:46:22.180Z | 133.9 | 5 | 25 | 15/32 | fail | fail | fail | 1 | FAIL |

Full quality passes: 0/4. Earlier attempts remain in the raw data and are not omitted from this assessment.

The first run read all 32 files and passed the summary test, but failed recovery and then exposed a cleanup API error. A subsequent run preserved the key in `summary.md` and passed its then-current test, but its transcript showed only 7/32 files read; this apparent pass is rejected by the independent read audit. The stricter run read 20/32 files, preserved the key, and passed its summary-only test, yet still failed continuation. The final strict run reached 15/32 files after five compaction events, left context usage above the configured 16K window, and produced neither summary nor manifest; its deterministic test failed.

This machine-specific sample shows that compaction events alone do not establish task continuity. Under this 9B local model and tool-heavy 16K workload, Pi's compaction summary and the new continuation prompt were unreliable: the harness sometimes repeated the earlier summary task, skipped files, or overflowed before producing artifacts. The exact key was recovered in one run, but no run passed the full independent quality contract. Treat Pi as a promising low-overhead harness for bounded tasks, not yet as validated for long-context continuation on this model. The final record's context estimate reached 16,879 tokens (103.0% of the configured window); that overrun is part of the observed failure, not a valid performance measurement.

The early attempts are retained in `results/raw/pi-context-stress-exploratory-invalid.jsonl`; the pre-audit apparent pass is retained in `results/raw/pi-context-stress.jsonl`. Session transcripts remain on the SSD run directories referenced by each JSONL record. Recreate with `scripts/22_benchmark_pi_context_stress.sh`; regenerate this table with `python3 benchmark/summarize_pi_context_stress.py --raw results/raw/pi-context-stress.jsonl --raw results/raw/pi-context-stress-exploratory-invalid.jsonl --csv results/csv/pi-context-stress.csv --report results/reports/pi-context-stress.md`.
