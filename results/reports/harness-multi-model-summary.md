# Harness evaluation summary

Sources: `results/raw/harness-run-summary.jsonl`, `results/raw/harness-ornith-pi.jsonl`, `results/raw/harness-ornith-matrix.jsonl`. Warm-up runs, invalid runs, and rows without a Git revision are excluded; raw entries remain preserved.
Rows are grouped by harness, model, runtime, quantization, context, KV cache, and storage profile. Token counts come from each harness's own usage records, including cached input where exposed.
Success requires clean harness exit, passing unit tests, passing behavior probe, and scoped edits.

| Model | Harness | Version | Runs | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | RAM peak MB median | VRAM peak MB median |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.5-9B-Q4_K_M | opencode | 1.19.0 | 3 | 3/3 (100%) | 46.13 (47.15 ± 1.8) | 7550.0 | 50580.0 | 7.0 | 2913.0 | 6154.0 |
| ornith-ai/Ornith-1.0-9B-GGUF | opencode | 1.19.0 | 3 | 3/3 (100%) | 48.25 (49.6 ± 3.34) | 7605.0 | 50935.0 | 7.0 | 2599.0 | 6172.0 |
| Qwen3.5-9B-Q4_K_M | pi | 1.1.0 | 3 | 3/3 (100%) | 19.92 (19.57 ± 2.65) | 1709.0 | 13875.0 | 6.0 | 2458.0 | 6145.0 |
| ornith-ai/Ornith-1.0-9B-GGUF | pi | 1.1.0 | 3 | 3/3 (100%) | 25.13 (24.45 ± 3.19) | 1709.0 | 14343.0 | 6.0 | 1504.0 | 6164.0 |
| Qwen3.5-9B-Q4_K_M | vibe | 2.26.1 | 3 | 3/3 (100%) | 45.02 (45.0 ± 0.03) | 8088.0 | 53490.0 | 6.0 | 2709.0 | 6145.0 |
| ornith-ai/Ornith-1.0-9B-GGUF | vibe | 2.26.1 | 3 | 3/3 (100%) | 45.02 (46.11 ± 2.79) | 8088.0 | 44698.0 | 6.0 | 2746.0 | 6170.0 |

These measurements cover one fixed coding task and the exact model/harness configurations shown above. They do not establish broad coding quality or long-context, compaction, subagent, or MCP performance.
Vibe first-prompt counts are read from journal usage events; llama.cpp prompt-evaluation work is stored separately and can be smaller when server prefix caching is active.
See the raw JSONL for per-run quality details, tool errors, timing, resource samples, and excluded setup attempts.
