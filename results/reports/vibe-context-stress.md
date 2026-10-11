# Vibe local context-compaction stress

The same local Qwen3.5-9B Q4_K_M endpoint and synthetic 32-file workspace were used in two Vibe prompts. The second prompt resumed the exact first session ID. The runtime, model, scratch workspaces, server logs, and resource samples were on C:-backed WSL ext4; no HDD performance I/O or paid endpoint was used.

A full pass requires both phases to exit cleanly, at least one automatic compaction, tool-call evidence for all 32 archive files, an exact fingerprint manifest, the recovery key preserved and recovered, passing workspace tests, and only expected output files changed.

| Started (UTC) | Wall (s) | Tokens in/out | Compactions | Tools | Files read | Reopened | Manifest | Continuity | Tests | Mode flips | Result |
|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|
| 2026-10-11T14:12:58.378964Z | 113.84 | 105496/1950 | 2 | 6 | 32/32 | 0 | pass | fail | fail | 34 | FAIL |
| 2026-10-11T14:16:10.964780Z | 217.632 | 459840/6470 | 4 | 78 | 32/32 | 2 | pass | pass | pass | 34 | FAIL |
| 2026-10-11T14:21:24.497259Z | 148.44 | 278870/4683 | 2 | 187 | 32/32 | 0 | pass | pass | pass | 34 | FAIL |

Strict full-task passes: 0/3.

All three sessions referenced 32 archives and recorded automatic compactions. The second and third runs produced the exact manifest and key, and the independent workspace tests passed. The second run nevertheless reopened archive-01 and archive-07 during its continuation; the final run made no archive references after continuation. Git marked all 34 tracked fixture files as executable-bit changes (100644 to 100755) in every run; the final diff showed no content changes to those files, but the mode changes are outside the allowed output scope. Therefore none is a strict full-task pass. The first attempt also hit its artificial token cap and could not resume without an explicit session ID; the second resumed successfully but its first phase still hit the cap. The final run had no token cap and both phases exited cleanly, yet still failed the file-scope gate.

Usage totals are the harness-reported sum across model calls, not the peak context size. Vibe's journal records compaction IDs and requests, but this run does not expose a reliable token count for the history removed; no token compression ratio is claimed. Resource samples are one-second observations and the RTX 3070 is shared with the Windows desktop.

Session journals, workspaces, stdout/stderr, and server logs are archived on E: after measurement with a SHA-256 manifest. Re-run with `scripts/28_benchmark_vibe_context_stress.sh`; regenerate the consolidated table with `python3 benchmark/summarize_vibe_context_stress.py --runs-root /mnt/e/LocalLLMLabArchive/2026-10-11/vibe-context-stress --git-sha <benchmark_git_sha> --raw results/raw/vibe-context-stress.jsonl --csv results/csv/vibe-context-stress.csv --report results/reports/vibe-context-stress.md`.
