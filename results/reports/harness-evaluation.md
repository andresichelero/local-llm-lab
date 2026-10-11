# Harness evaluation summary

Source: `/mnt/d/Usuario/Downloads/LLM/local-llm-lab/results/raw/harness-run-summary.jsonl`. Warm-up runs and records marked `benchmark_valid: false` are excluded; raw entries remain preserved.
All measured runs used the same deterministic coding fixture, Qwen3.5-9B Q4_K_M, llama.cpp, a local endpoint, 16K context, and Q4_0 KV cache. Token counts come from each harness's own usage records, including cached input where exposed.
Success requires clean harness exit, passing unit tests, passing behavior probe, and scoped edits.

| Harness | Version | Runs | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | RAM peak MB median | VRAM peak MB median |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| opencode | 1.19.0 | 3 | 3/3 (100%) | 23.14 (23.14 ± 0.05) | 7550.0 | 50549.0 | 6.0 | 4508.0 | 6359.0 |
| pi | 1.1.0 | 3 | 3/3 (100%) | 14.71 (14.38 ± 0.58) | 1709.0 | 11189.0 | 6.0 | 2763.0 | 6385.0 |
| vibe | 2.26.1 | 3 | 3/3 (100%) | 23.03 (22.36 ± 2.18) | 8088.0 | 53495.0 | 6.0 | 2751.0 | 6394.0 |

On this single coding task, all three harnesses passed 3/3 valid measurements. Pi had lower measured context overhead and wall time; this result does not test long-context compaction, subagents, MCP, or broader task success.
Vibe first-prompt counts are read from journal usage events; llama.cpp prompt-evaluation work is stored separately and can be smaller when server prefix caching is active.
See the raw JSONL for per-run quality details, tool errors, timing, resource samples, and excluded setup attempts.
