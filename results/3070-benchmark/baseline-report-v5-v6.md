# OpenCode baseline report

First attempt per unit, except explicit infrastructure failures; units without an eligible attempt are excluded. Directories are analyzed separately.
Pairs use identical task and repetition; an unpaired repetition is excluded. Token rates and TTFT are medians of per-episode medians; empty fields indicate unavailable data.

## By arm

| source | arm | n | successes | success_rate | wilson_low | wilson_high | seconds_mean | seconds_median | ttft_ms_median | prefill_tok_s_median | decode_tok_s_median | peak_vram_mib_median | processed_tokens_total | cache_tokens_total | wasted_prompt_tokens | wasted_completion_tokens | wasted_seconds | taxonomy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | 24 | 16 | 0.6667 | 0.4671 | 0.8203 | 97.8391 | 42.2508 | 295.8651 | 713.8766 | 71.2449 | 4535.5000 |  |  | 6722306 | 85053 | 1528.6387 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | 12 | 9 | 0.7500 | 0.4677 | 0.9111 | 106.9651 | 58.1511 | 294.0819 | 830.0840 | 75.7587 | 5422.0000 |  |  | 2089982 | 40724 | 775.5263 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | 12 | 3 | 0.2500 | 0.0889 | 0.5323 | 27.0657 | 16.4075 | 448.2864 | 1403.2359 | 80.5841 | 3847.0000 |  |  | 508607 | 10130 | 236.6481 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | 12 | 9 | 0.7500 | 0.4677 | 0.9111 | 57.7708 | 46.0784 | 235.4497 | 737.3398 | 82.7438 | 4074.0000 | 299405 | 3575410 | 1276127 | 10281 | 198.1701 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | 12 | 7 | 0.5833 | 0.3195 | 0.8067 | 109.9293 | 34.6288 | 306.3277 | 983.7959 | 77.7435 | 5747.0000 |  |  | 1712760 | 51523 | 962.7857 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | 12 | 9 | 0.7500 | 0.4677 | 0.9111 | 71.4528 | 39.0061 | 265.2191 | 849.6479 | 76.7672 | 5036.0000 |  |  | 1984968 | 25008 | 448.8020 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | 12 | 9 | 0.7500 | 0.4677 | 0.9111 | 194.8139 | 115.4770 | 7497.8899 | 3433.4743 | 75.5348 | 4509.0000 |  |  | 1910877 | 25707 | 979.1332 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | 12 | 10 | 0.8333 | 0.5520 | 0.9530 | 105.4676 | 37.0389 | 301.2438 | 857.5961 | 65.4072 | 5116.0000 |  |  | 1465326 | 36252 | 639.3098 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | 12 | 8 | 0.6667 | 0.3906 | 0.8619 | 54.3222 | 38.5133 | 316.9142 | 758.1371 | 59.0274 | 6033.0000 | 316622 | 5383176 | 3330224 | 14923 | 364.7615 | {} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | 12 | 11 | 0.9167 | 0.6461 | 0.9851 | 122.5981 | 110.1327 | 214.3930 | 1112.9678 | 78.4802 | 4528.0000 | 258757 | 4975323 | 570250 | 10376 | 177.7484 | {} |

## By task and arm

| source | arm | task | n | successes | outcomes | stability |
| --- | --- | --- | --- | --- | --- | --- |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | cont_path | 2 | 1 | 10 | mixed |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | cont_quote | 2 | 2 | 11 | consistent |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | js_plural | 2 | 2 | 11 | consistent |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | js_sign | 2 | 1 | 10 | mixed |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | mcp_header | 2 | 2 | 11 | consistent |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | mcp_params | 2 | 2 | 11 | consistent |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | py_query | 2 | 2 | 11 | consistent |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | py_range | 2 | 0 | 00 | consistent |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | recover_date | 2 | 1 | 01 | mixed |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | recover_decode | 2 | 2 | 11 | consistent |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | tests_query | 2 | 0 | 00 | consistent |
| results/qwen-4b-opencode-baseline-bwrap-v5 | B0 | tests_range | 2 | 1 | 01 | mixed |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | cont_path | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | cont_quote | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | mcp_header | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | py_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | py_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | recover_date | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | recover_decode | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | tests_query | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | tests_range | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | cont_path | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | cont_quote | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | mcp_header | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | py_query | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | py_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | recover_date | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | recover_decode | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | tests_query | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | tests_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | cont_path | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | cont_quote | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | mcp_header | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | py_query | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | py_range | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | recover_date | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | recover_decode | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | tests_query | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | tests_range | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | cont_path | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | cont_quote | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | mcp_header | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | py_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | py_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | recover_date | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | recover_decode | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | tests_query | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | tests_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | cont_path | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | cont_quote | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | mcp_header | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | py_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | py_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | recover_date | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | recover_decode | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | tests_query | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | tests_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | cont_path | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | cont_quote | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | mcp_header | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | py_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | py_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | recover_date | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | recover_decode | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | tests_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | tests_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | cont_path | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | cont_quote | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | mcp_header | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | py_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | py_range | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | recover_date | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | recover_decode | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | tests_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | tests_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | cont_path | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | cont_quote | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | mcp_header | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | py_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | py_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | recover_date | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | recover_decode | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | tests_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | tests_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | cont_path | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | cont_quote | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | js_plural | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | js_sign | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | mcp_header | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | mcp_params | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | py_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | py_range | 1 | 0 | 0 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | recover_date | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | recover_decode | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | tests_query | 1 | 1 | 1 | insufficient |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | tests_range | 1 | 1 | 1 | insufficient |

## Comparison between arms by task and directory

| source | task | arms |
| --- | --- | --- |
| results/qwen-4b-opencode-baseline-bwrap-v5 | cont_path | {"B0": {"n": 2, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | cont_quote | {"B0": {"n": 2, "successes": 2}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | js_plural | {"B0": {"n": 2, "successes": 2}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | js_sign | {"B0": {"n": 2, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | mcp_header | {"B0": {"n": 2, "successes": 2}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | mcp_params | {"B0": {"n": 2, "successes": 2}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | py_query | {"B0": {"n": 2, "successes": 2}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | py_range | {"B0": {"n": 2, "successes": 0}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | recover_date | {"B0": {"n": 2, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | recover_decode | {"B0": {"n": 2, "successes": 2}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | tests_query | {"B0": {"n": 2, "successes": 0}} |
| results/qwen-4b-opencode-baseline-bwrap-v5 | tests_range | {"B0": {"n": 2, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | cont_path | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 0}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 0}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 0}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | cont_quote | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 0}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 1}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | js_plural | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 1}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 1}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 1}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | js_sign | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 1}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 1}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 1}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | mcp_header | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 1}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 1}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | mcp_params | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 1}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 1}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 1}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | py_query | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 0}, "B-kv16": {"n": 1, "successes": 1}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 1}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | py_range | {"B-ctx128": {"n": 1, "successes": 0}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 0}, "B-kv8": {"n": 1, "successes": 0}, "B-nocache": {"n": 1, "successes": 0}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 0}, "B-think": {"n": 1, "successes": 0}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | recover_date | {"B-ctx128": {"n": 1, "successes": 0}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 0}, "B-kv16": {"n": 1, "successes": 1}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 0}, "B-q8": {"n": 1, "successes": 0}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | recover_decode | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 1}, "B-kv8": {"n": 1, "successes": 1}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 1}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | tests_query | {"B-ctx128": {"n": 1, "successes": 0}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 0}, "B-kv16": {"n": 1, "successes": 0}, "B-kv8": {"n": 1, "successes": 0}, "B-nocache": {"n": 1, "successes": 1}, "B-q6": {"n": 1, "successes": 1}, "B-q8": {"n": 1, "successes": 1}, "B-think": {"n": 1, "successes": 1}} |
| results/qwen-4b-opencode-baseline-bwrap-v6 | tests_range | {"B-ctx128": {"n": 1, "successes": 1}, "B-ctx16": {"n": 1, "successes": 0}, "B-ctx32": {"n": 1, "successes": 1}, "B-kv16": {"n": 1, "successes": 0}, "B-kv8": {"n": 1, "successes": 0}, "B-nocache": {"n": 1, "successes": 0}, "B-q6": {"n": 1, "successes": 0}, "B-q8": {"n": 1, "successes": 0}, "B-think": {"n": 1, "successes": 1}} |

## Paired comparisons: exact McNemar

| source | arm | control | control_source | pairs | wins | losses | ties | mcnemar_p |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx128 | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 1 | 0 | 11 | 1.0000 |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx16 | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 0 | 5 | 7 | 0.0625 |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-ctx32 | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 2 | 1 | 9 | 1.0000 |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv16 | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 1 | 2 | 9 | 1.0000 |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-kv8 | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 1 | 0 | 11 | 1.0000 |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-nocache | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 2 | 1 | 9 | 1.0000 |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q6 | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 2 | 0 | 10 | 0.5000 |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-q8 | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 1 | 1 | 10 | 1.0000 |
| results/qwen-4b-opencode-baseline-bwrap-v6 | B-think | B0 | results/qwen-4b-opencode-baseline-bwrap-v5 | 12 | 3 | 0 | 9 | 0.2500 |
