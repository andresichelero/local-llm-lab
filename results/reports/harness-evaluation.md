# Harness evaluation summary

Source: `/mnt/d/Usuario/Downloads/LLM/local-llm-lab/results/raw/harness-run-summary.jsonl`. Warm-up runs, invalid runs, and legacy rows without a Git revision are excluded; raw entries remain preserved.
The table selects one-based JSONL lines 21–29, three per harness, at `git_sha=ddeef10e4f4ee697baf76514114e65e26d98dac3`, with `source_tree_dirty=false`, `run_kind=measurement`, and `success=true`. This historical successful triplet is not a denominator for broader reliability; new comparisons must retain valid failed measurements too. Re-audited on 2026-10-11.
All measured runs used the same deterministic coding fixture, Qwen3.5-9B Q4_K_M, llama.cpp, a local endpoint, 16K context, and Q4_0 KV cache. Token counts come from each harness's own usage records, including cached input where exposed.
Success requires clean harness exit, passing unit tests, passing behavior probe, and scoped edits.

| Harness | Version | Runs | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | RAM peak MB median | VRAM peak MB median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| opencode | 1.19.0 | 3 | 3/3 (100%) | 46.13 (47.15 ± 1.8) | 7550.0 | 50580.0 | 7.0 | 2913.0 | 6154.0 |
| pi | 1.1.0 | 3 | 3/3 (100%) | 19.92 (19.57 ± 2.65) | 1709.0 | 13875.0 | 6.0 | 2458.0 | 6145.0 |
| vibe | 2.26.1 | 3 | 3/3 (100%) | 45.02 (45.0 ± 0.03) | 8088.0 | 53490.0 | 6.0 | 2709.0 | 6145.0 |

On this single coding task, all three harnesses passed 3/3 valid measurements. Pi had lower measured context overhead and wall time; this result does not test long-context compaction, subagents, MCP, or broader task success.
Vibe first-prompt counts are read from journal usage events; llama.cpp prompt-evaluation work is stored separately and can be smaller when server prefix caching is active.
See the raw JSONL for per-run quality details, tool errors, timing, resource samples, and excluded setup attempts.

## Pi model follow-up: Qwen3.5 vs Ornith-1.0 — SSD only

Pi 1.1.0 was rerun on the same deterministic coding fixture with the pinned Ornith-1.0-9B Q4_K_M GGUF (revision `3296bc7a404871a72ac3f1903f561459c09b5c17`). The runtime remained llama.cpp `d81235049384534c167caea52b85a694f6103d14`, with 16K context, Q4_0 K/V, 99 GPU layers, Flash Attention on, reasoning off, and prompt caching off. The model, runtime, task workspaces, logs, and resource samples stayed on the C:-backed WSL ext4 SSD; E: was not used for performance I/O.

| Model | Measured runs | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | Tool failures | VRAM peak MB median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.5-9B Q4_K_M | 3 | 3/3 | 19.92 (19.57 ± 2.65) | 1,709 | 13,875 | 6 | 0 | 6,145 |
| Ornith-1.0-9B Q4_K_M | 3 | 3/3 | 25.13 (24.45 ± 3.19) | 1,709 | 14,343 | 6 | 0 | 6,164 |

All six measured coding runs passed the independent behavior probe and five unit tests, and changed only the two files permitted by the fixture. On these runs, Ornith took about 26% longer at the median; both models had the same observed task success and Pi's initial harness context was identical. This small, single-task sample does not establish a general model ranking. The resource sampler reports system-wide WSL/GPU snapshots, so its RAM values are not directly comparable across sessions.

Ornith raw metrics are in `results/raw/harness-ornith-pi.jsonl`; per-run agent events and resource samples are in the adjacent `harness-ornith-pi-*.jsonl` files, with the aggregate table in `results/csv/harness-ornith-pi.csv`. The runner now accepts model, revision, GGUF path, endpoint, context, server log, and output path arguments while retaining the Qwen defaults. Reproduce on WSL ext4 with the pinned model staged on the C: SSD, the llama.cpp server started with the settings above and alias `ornith-ai/Ornith-1.0-9B-GGUF`, then run one `--warmup` and `--repeat 3` using `benchmark/harness_runner.py --harness pi --model ornith-ai/Ornith-1.0-9B-GGUF --model-revision 3296bc7a404871a72ac3f1903f561459c09b5c17 --model-path "$HOME/local-llm-benchmark/models/gguf/ornith-1.0-9b/ornith-1.0-9b-Q4_K_M.gguf" --context 16384 --server-url http://127.0.0.1:8080 --benchmark-root "$HOME/local-llm-benchmark"`. The runner checks the source checkout, benchmark root, model, server log, and result destination for WSL ext4 before it starts a run; the downloader applies the same SSD check to `MODEL_DIR` and uses that destination's filesystem for its free-space check.

After testing, the model and full run directories were copied to `E:\LocalLLMLabArchive\2026-10-11\ornith-pi-harness`; the archived model's SHA-256 was verified before removing its temporary SSD copy. E: served only as post-run archive storage, never as a benchmark source.

## Ornith harness matrix — SSD only

The same pinned Ornith model and fixed task were also run through OpenCode 1.19.0 and Mistral Vibe 2.26.1, one warm-up plus three measurements each. The Pi measurements above are the third harness in this matrix. Every measured run passed the independent behavior check, the five unit tests, and the two-file scope check; each harness had zero failed tool calls.

| Harness | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | VRAM peak MB median |
|---|---:|---:|---:|---:|---:|---:|
| Pi 1.1.0 | 3/3 | 25.129 (24.446 ± 3.189) | 1,709 | 14,343 | 6 | 6,164 |
| OpenCode 1.19.0 | 3/3 | 48.254 (49.597 ± 3.339) | 7,605 | 50,935 | 7 | 6,172 |
| Mistral Vibe 2.26.1 | 3/3 | 45.024 (46.108 ± 2.791) | 8,088 | 44,698 | 6 | 6,170 |

This extends the earlier Qwen-only harness comparison: Pi again had the lowest prompt usage and wall time for this task, while Vibe and OpenCode were close in time. Token totals come from each harness's own counters, including cached input where exposed, so they are approximate context-overhead measures rather than a normalized tokenization comparison. This is one repository task and does not measure subagents, MCP, long-context compaction, or broad coding quality.

The measured rows and all warm-ups are in `results/raw/harness-ornith-matrix.jsonl`; agent events and one-second resource traces are in the adjacent `harness-ornith-matrix-*.jsonl` files. Per-run CSV: `results/csv/harness-ornith-matrix-runs.csv`. To reproduce aggregate comparisons across the Qwen baseline and both Ornith series, run `python3 benchmark/summarize_harness_results.py --input results/raw/harness-run-summary.jsonl --input results/raw/harness-ornith-pi.jsonl --input results/raw/harness-ornith-matrix.jsonl --csv results/csv/harness-multi-model-summary.csv --markdown results/reports/harness-multi-model-summary.md`. All model, runtime, task, session, log, and result I/O remained on WSL ext4 backed by C:. After testing, the model remained in the verified archive at `E:\\LocalLLMLabArchive\\2026-10-11\\ornith-pi-harness\\model`, and the matrix run directories, logs, raw records, and a verified SHA-256 manifest were archived at `E:\\LocalLLMLabArchive\\2026-10-11\\ornith-harness-matrix`. The temporary SSD model copy and scratch directories were removed afterward.

## Qwen3.5-4B local-worker follow-up — Pi, SSD only

Pi 1.1.0 was run on the same fixed coding task using Qwen3.5-4B Q4_K_M, llama.cpp `d81235049384534c167caea52b85a694f6103d14`, 16K context, Q4_0 KV, 99 GPU layers, and Flash Attention. All model, task, log, and result I/O used the C:-backed WSL ext4 SSD. One warm-up preceded five measured runs.

Three of five runs met the strict task grader (60%). All five exited cleanly, passed unit tests and the independent behavior probe, changed only the two allowed files, and had no tool-call failures. The two strict failures used test identifiers that differed from the exact names required by the fixture, despite correct behavior. This exposes a spec-following weakness, not an arithmetic or test failure.

| Model | Runs | Strict success | Wall s median | Prompt tokens median | Tool calls median | VRAM peak median |
|---|---:|---:|---:|---:|---:|---:|
| Qwen3.5-4B Q4_K_M | 5 | 3/5 | 16.82 | 13,542 | 6 | 4,108 MB |
| Qwen3.5-9B Q4_K_M | 3 | 3/3 | 19.92 | 13,875 | 6 | 6,145 MB |

The 4B sample was faster and used less VRAM, but its strict success rate was lower; sample sizes differ and this single task cannot establish a general ranking. Per-run records and summary are in `results/raw/qwen35-4b-pi-harness-20261011.jsonl`, `results/csv/harness-qwen35-4b-pi.csv`, and `results/reports/harness-qwen35-4b-pi.md`. The post-run historical archive is `E:\\LocalLLMLabArchive\\2026-10-11\\qwen35-4b-pi-harness-20261011`; E: was not used for benchmark I/O.

## Qwen3.5-4B local-worker follow-up — OpenCode, SSD only

OpenCode 1.19.0 ran the same fixed coding task, model revision, local llama.cpp endpoint, and settings as the Pi follow-up: Qwen3.5-4B Q4_K_M, 16K context, Q4_0 KV, 99 GPU layers, and Flash Attention. All benchmark I/O stayed on C:-backed WSL ext4 SSD. One warm-up preceded five measured runs. All five met the strict grader, passed unit tests and the independent behavior probe, changed only the two allowed files, and had zero tool-call failures.

| Harness | Runs | Strict success | Wall s median | First prompt tokens median | Prompt tokens median | Tool calls median | VRAM peak median |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pi 1.1.0 | 5 | 3/5 | 16.82 | 1,709 | 13,542 | 6 | 4,108 MB |
| OpenCode 1.19.0 | 5 | 5/5 | 19.98 | 7,592 | 59,495 | 7 | 4,103 MB |

On this single task, Pi used substantially fewer harness-reported prompt tokens and finished about 16% sooner, while OpenCode followed the exact test-name specification on all five runs. Each harness has different token accounting and schemas, so token totals are directional overhead indicators, not a normalized tokenizer comparison. The result does not cover broader coding tasks, compaction, subagents, or MCP. OpenCode raw records, CSV, and report are in `results/raw/qwen35-4b-opencode-harness-20261011.jsonl`, `results/csv/harness-qwen35-4b-opencode.csv`, and `results/reports/harness-qwen35-4b-opencode.md`; E: is reserved for a checksum-verified post-run archive.

## Qwen3.5-4B local-worker follow-up — Mistral Vibe, SSD only

Mistral Vibe 2.26.1 used the same fixed coding task, Qwen3.5-4B Q4_K_M revision, local llama.cpp server, and settings as the Pi and OpenCode runs. All benchmark I/O stayed on C:-backed WSL ext4 SSD. One warm-up preceded five measured runs. All five exited cleanly, passed unit tests and the independent behavior probe, changed only the two allowed files, and had zero tool failures. None met the strict grader because the generated test names did not match the exact required identifiers.

| Harness | Runs | Strict success | Wall s median | First prompt tokens median | Prompt tokens median | Tool calls median | VRAM peak median |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pi 1.1.0 | 5 | 3/5 | 16.82 | 1,709 | 13,542 | 6 | 4,108 MB |
| OpenCode 1.19.0 | 5 | 5/5 | 19.98 | 7,592 | 59,495 | 7 | 4,103 MB |
| Mistral Vibe 2.26.1 | 5 | 0/5 | 20.02 | 8,088 | 54,225 | 6 | 4,105 MB |

In this single-task sample, OpenCode was the only harness to follow the exact test-name requirement in all runs; Pi and Vibe still produced passing behavior and unit tests but missed that strict spec detail. Pi had lower reported prompt overhead and was faster. Vibe used fewer reported tokens than OpenCode but completed at a similar wall time. Harness counters and schemas differ, so token totals are directional rather than normalized. This does not establish general quality or measure compaction, subagents, or MCP. Vibe raw data, CSV, and report are in `results/raw/qwen35-4b-vibe-harness-20261011.jsonl`, `results/csv/harness-qwen35-4b-vibe.csv`, and `results/reports/harness-qwen35-4b-vibe.md`; its post-run archive is checksum-verified on E:.

## Qwen3.5-4B matched harness follow-up — whitespace normalization task, SSD only

The harness runner now supports a second deterministic task, `whitespace_normalization`, with a separate fixture and independent grader. Pi 1.1.0, OpenCode 1.19.0, and Mistral Vibe 2.26.1 used the pinned Qwen3.5-4B Q4_K_M, llama.cpp `d81235049384534c167caea52b85a694f6103d14`, 16K context, Q4_0 K/V, 99 GPU layers, and Flash Attention. Each harness had one warm-up followed by five measurements, all on C-backed WSL ext4.

| Harness | Strict success | Wall s median (mean ± sd) | Prompt tokens median | Tool failures total | WSL RAM peak median | WSL swap peak median |
|---|---:|---:|---:|---:|---:|---:|
| Pi | 5/5 | 14.76 (28.36 ± 33.99) | 16,536 | 2 | 4,222 MB | 0 MB |
| OpenCode | 5/5 | 16.99 (17.37 ± 0.96) | 49,504 | 0 | 7,334 MB | 1,168 MB |
| Mistral Vibe | 5/5 | 14.76 (15.17 ± 0.59) | 43,624 | 0 | 7,349 MB | 2,094 MB |

All 15 measured runs passed the exact test-name grader, the independent behavior probe, unit tests, preservation of `word_count`, and the two-file scope check. Pi had one 89.035 s outlier with 30 tool calls and two failed calls; it still completed the task correctly. Across this task and the earlier division task, strict success was Pi 8/10, OpenCode 10/10, and Vibe 5/10. The contrast shows the earlier test-name failures were task-specific and should not be treated as general harness failure rates.

The WSL resource sampler reached 7,610 MiB RAM and 2,447 MiB swap during the full series, close to the configured memory ceiling; there was no OOM. Memory pressure makes small timing differences provisional. Harness-reported prompt tokens are not normalized across tools. The comparison covers only these two small tasks and does not test long-context compaction, subagents, or MCP. The task-level report, combined report, CSV, and raw JSONL are `results/reports/harness-qwen35-4b-whitespace.md`, `results/reports/harness-qwen35-4b-multitask.md`, `results/csv/harness-qwen35-4b-whitespace.csv`, `results/csv/harness-qwen35-4b-multitask.csv`, and `results/raw/qwen35-4b-whitespace-harness-20261011.jsonl`.
