# OpenCode baseline report

First attempt per unit, except explicit infrastructure failures; units without an eligible attempt are excluded. Directories are analyzed separately.
Pairs use identical task and repetition; an unpaired repetition is excluded. Token rates and TTFT are medians of per-episode medians; empty fields indicate unavailable data.

## By arm

| source | arm | n | successes | success_rate | wilson_low | wilson_high | seconds_mean | seconds_median | ttft_ms_median | prefill_tok_s_median | decode_tok_s_median | peak_vram_mib_median | processed_tokens_total | cache_tokens_total | wasted_prompt_tokens | wasted_completion_tokens | wasted_seconds | taxonomy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | 24 | 16 | 0.6667 | 0.4671 | 0.8203 | 97.8391 | 42.2508 | 295.8651 | 713.8766 | 71.2449 | 4535.5000 |  |  | 6722306 | 85053 | 1528.6387 | {} |

## By task and arm

| source | arm | task | n | successes | outcomes | stability |
| --- | --- | --- | --- | --- | --- | --- |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | cont_path | 2 | 1 | 10 | mixed |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | cont_quote | 2 | 2 | 11 | consistent |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | js_plural | 2 | 2 | 11 | consistent |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | js_sign | 2 | 1 | 10 | mixed |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | mcp_header | 2 | 2 | 11 | consistent |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | mcp_params | 2 | 2 | 11 | consistent |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | py_query | 2 | 2 | 11 | consistent |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | py_range | 2 | 0 | 00 | consistent |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | recover_date | 2 | 1 | 01 | mixed |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | recover_decode | 2 | 2 | 11 | consistent |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | tests_query | 2 | 0 | 00 | consistent |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | tests_range | 2 | 1 | 01 | mixed |

## Comparison between arms by task and directory

| source | task | arms |
| --- | --- | --- |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | cont_path | {"B0": {"n": 2, "successes": 1}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | cont_quote | {"B0": {"n": 2, "successes": 2}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | js_plural | {"B0": {"n": 2, "successes": 2}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | js_sign | {"B0": {"n": 2, "successes": 1}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | mcp_header | {"B0": {"n": 2, "successes": 2}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | mcp_params | {"B0": {"n": 2, "successes": 2}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | py_query | {"B0": {"n": 2, "successes": 2}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | py_range | {"B0": {"n": 2, "successes": 0}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | recover_date | {"B0": {"n": 2, "successes": 1}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | recover_decode | {"B0": {"n": 2, "successes": 2}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | tests_query | {"B0": {"n": 2, "successes": 0}} |
| /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v5 | tests_range | {"B0": {"n": 2, "successes": 1}} |

## Paired comparisons: exact McNemar

No data.
