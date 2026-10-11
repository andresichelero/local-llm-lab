# Harness evaluation summary

Source: `/mnt/d/Usuario/Downloads/LLM/local-llm-lab/results/raw/harness-run-summary.jsonl`. Warm-up runs, invalid runs, and legacy rows without a Git revision are excluded; raw entries remain preserved.
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
