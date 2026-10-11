# Vibe local context-compaction stress

The same local Qwen3.5-9B Q4_K_M endpoint and synthetic 32-file workspace were used in two Vibe prompts. The second prompt resumed the exact first session ID. The runtime, model, scratch workspaces, server logs, and resource samples were on C:-backed WSL ext4; no HDD performance I/O or paid endpoint was used.

A full pass requires both phases to exit cleanly, at least one automatic compaction, tool-call evidence for all 32 archive files, an exact fingerprint manifest, the recovery key preserved and recovered, passing workspace tests, and only expected output files changed.

| Started (UTC) | Wall (s) | Tokens in/out | Compactions | Tools | Successful reads | Reopened | Manifest | Continuity | Tests | Mode flips | Result |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|
| 2026-10-11T14:12:58.378964Z | 113.84 | 105496/1950 | 2 | 6 | 32/32 | 0 | pass | fail | fail | 34 | FAIL |
| 2026-10-11T14:16:10.964780Z | 217.632 | 459840/6470 | 4 | 78 | 32/32 | 2 | pass | pass | pass | 34 | FAIL |
| 2026-10-11T14:21:24.497259Z | 148.44 | 278870/4683 | 2 | 187 | 32/32 | 0 | pass | pass | pass | 34 | FAIL |
| 2026-10-11T14:49:55.448802Z | 157.319 | 323847/5076 | 3 | 20 | 32/32 | 0 | pass | pass | pass | 0 | PASS |

Strict full-task passes: 1/4.

Correlating archive paths with successful file-read tool results gives 32/32, 32/32, 32/32, 32/32 successful reads in run order. The earlier summary used intent-only matching; the updated journal audit confirms each reported read through a successful read result or successful shell output containing the deterministic archive fingerprints. Workspace mode-change counts in run order were 34, 34, 34, 0; mode changes remain a strict-scope failure even when file contents are unchanged. Reopened archives after continuation: run 2: [1, 7]. The latest run completed both phases, preserved all required artifacts, passed workspace tests, and made no out-of-scope workspace changes. Strict full-task passes: 1/4.

Usage totals are the harness-reported sum across model calls, not the peak context size. Vibe's journal records compaction IDs and requests, but this run does not expose a reliable token count for the history removed; no token compression ratio is claimed. Resource samples are one-second observations and the RTX 3070 is shared with the Windows desktop.

Session journals, workspaces, stdout/stderr, and server logs are archived on E: after measurement in a SHA-256-verified tarball. The latest workspace was graded from its original C:-backed WSL ext4 run directory before archival; do not run the workspace-mode quality gate directly from the mounted E: copy. To reproduce the comparison, restore all archived run folders onto WSL ext4, then run `python3 benchmark/summarize_vibe_context_stress.py --runs-root $BENCH_ROOT/results/vibe-context-stress --git-sha <fallback_git_sha> --raw results/raw/vibe-context-stress.jsonl --csv results/csv/vibe-context-stress.csv --report results/reports/vibe-context-stress.md`. The checked-in JSONL/CSV retain the exact per-run provenance and results.
