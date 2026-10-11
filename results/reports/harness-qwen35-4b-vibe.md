# Harness evaluation summary

Sources: `results/raw/qwen35-4b-vibe-harness-20261011.jsonl`. Warm-up runs, invalid runs, and rows without a Git revision are excluded; raw entries remain preserved.
Rows are grouped by harness, model, runtime, quantization, context, KV cache, and storage profile. Token counts come from each harness's own usage records, including cached input where exposed.
Success requires clean harness exit, passing unit tests, passing behavior probe, and scoped edits.

| Model | Harness | Version | Runs | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | RAM peak MB median | VRAM peak MB median |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.5-4B-Q4_K_M | vibe | 2.26.1 | 5 | 0/5 (0%) | 20.02 (20.41 ± 0.58) | 8088.0 | 54225.0 | 6.0 | 1913.0 | 4105.0 |

These measurements cover one fixed coding task and the exact model/harness configurations shown above. They do not establish broad coding quality or long-context, compaction, subagent, or MCP performance.
Vibe first-prompt counts are read from journal usage events; llama.cpp prompt-evaluation work is stored separately and can be smaller when server prefix caching is active.
See the raw JSONL for per-run quality details, tool errors, timing, resource samples, and excluded setup attempts.
