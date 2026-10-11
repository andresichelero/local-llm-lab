# Harness evaluation summary

Sources: `results/raw/qwen35-4b-whitespace-harness-20261011.jsonl`. Warm-up runs, invalid runs, and rows without a Git revision are excluded; raw entries remain preserved.
Rows are grouped by task, harness, model, runtime, quantization, context, KV cache, and storage profile. Token counts come from each harness's own usage records, including cached input where exposed.
Success requires clean harness exit, passing unit tests, passing behavior probe, and scoped edits.

| Task | Model | Harness | Version | Runs | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | RAM peak MB median | Swap peak MB median | VRAM peak MB median |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| whitespace_normalization | Qwen3.5-4B-Q4_K_M | opencode | 1.19.0 | 5 | 5/5 (100%) | 16.99 (17.37 ± 0.96) | 7642.0 | 49504.0 | 6.0 | 7334.0 | 1168.0 | 4109.0 |
| whitespace_normalization | Qwen3.5-4B-Q4_K_M | pi | 1.1.0 | 5 | 5/5 (100%) | 14.76 (28.36 ± 33.99) | 1759.0 | 16536.0 | 6.0 | 4222.0 | 0.0 | 4108.0 |
| whitespace_normalization | Qwen3.5-4B-Q4_K_M | vibe | 2.26.1 | 5 | 5/5 (100%) | 14.76 (15.17 ± 0.59) | 8139.0 | 43624.0 | 5.0 | 7349.0 | 2094.0 | 4110.0 |

These measurements cover one fixed coding task and the exact model/harness configurations shown above. They do not establish broad coding quality or long-context, compaction, subagent, or MCP performance.
Vibe first-prompt counts are read from journal usage events; llama.cpp prompt-evaluation work is stored separately and can be smaller when server prefix caching is active.
See the raw JSONL for per-run quality details, tool errors, timing, resource samples, and excluded setup attempts.
