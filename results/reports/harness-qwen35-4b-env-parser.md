# Harness evaluation summary

Sources: `results/raw/qwen35-4b-env-parser-harness-20261011.jsonl`. Warm-up runs, invalid runs, and rows without a Git revision are excluded; raw entries remain preserved.
Rows are grouped by task, harness, model, runtime, quantization, context, KV cache, and storage profile. Token counts come from each harness's own usage records, including cached input where exposed.
Success requires clean harness exit, passing unit tests, passing behavior probe, and scoped edits.

| Task | Model | Harness | Version | Runs | Success | Wall s median (mean ± sd) | First prompt tokens median | Prompt tokens median | Tool calls median | RAM peak MB median | Swap peak MB median | VRAM peak MB median |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| dotenv_line_parser | Qwen3.5-4B-Q4_K_M | opencode | 1.19.0 | 5 | 5/5 (100%) | 38.88 (38.71 ± 0.88) | 7664.0 | 59961.0 | 7.0 | 4699.0 | 0.0 | 4119.0 |
| dotenv_line_parser | Qwen3.5-4B-Q4_K_M | pi | 1.1.0 | 5 | 3/5 (60%) | 41.98 (58.81 ± 43.23) | 1780.0 | 40738.0 | 12.0 | 2758.0 | 0.0 | 4115.0 |
| dotenv_line_parser | Qwen3.5-4B-Q4_K_M | vibe | 2.26.1 | 5 | 4/5 (80%) | 54.35 (53.48 ± 8.43) | 8159.0 | 92562.0 | 9.0 | 5110.0 | 0.0 | 4107.0 |

These measurements cover one fixed coding task and the exact model/harness configurations shown above. They do not establish broad coding quality or long-context, compaction, subagent, or MCP performance.
Vibe first-prompt counts are read from journal usage events; llama.cpp prompt-evaluation work is stored separately and can be smaller when server prefix caching is active.
See the raw JSONL for per-run quality details, tool errors, timing, resource samples, and excluded setup attempts.

Strict task result: 12/15 measurements passed—Pi 3/5, OpenCode 5/5, and Mistral Vibe 4/5. The three failures still passed all unit tests and the independent behavior probe but wrote additional test files outside the allowed scope (`test_config_parser.py`, `src/test_config_parser.py`, or `test_manual.py`). Pi also recorded 11 failed tool calls across its five runs. Thus the failures indicate edit-scope/tool-retry issues on this task, not incorrect parser behavior.

All measurements used Qwen3.5-4B Q4_K_M revision `4168f45a16a1290d65a4ec0fa312ae917a4c15d6`, llama.cpp commit `d81235049384534c167caea52b85a694f6103d14`, a 16K context, Q4_0 K/V, and 99 GPU layers on the RTX 3070. Active benchmark files stayed on the C-backed WSL ext4 SSD. Sampled RAM peaked at 5,178 MiB, swap stayed at zero, VRAM peaked at 4,120 MiB, and GPU temperature reached 72 C. Times and harness token counts are specific to this task and setup.