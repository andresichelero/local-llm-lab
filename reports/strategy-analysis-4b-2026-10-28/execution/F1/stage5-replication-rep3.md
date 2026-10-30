# Stage 5: replication of X-think and T5-rtk (3 repetitions)

Date: 29/10/2026, from 19h04 to 21h39. Runner `benchmark/baseline_stage5.py --config benchmark/configs/qwen-4b-opencode-stage5-rep3.json`, branch `bench/stage5-replication`, commit `956f489`. Protocol `qwen-4b-opencode-stage5-rep3-v2`, with results in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-stage5-rep3-v2`.

The design has 2 arms × 12 tasks × 3 repetitions, or **72 episodes**. No episode ended in infrastructure failure. The first X-think attempt runs the control (Q4_K_M, KV q4_0, 64K, cache, thinking disabled, temperature 0) and serves as the pair for T5-rtk on the same task and repetition.

## Interruptions

- **v1:** stopped at episode 34. A model timeout left a `ConnectionResetError` in the proxy, and the priority rule in PR #45 turned this into `server_http_error`. The rule was fixed in `956f489`: after a timeout, a client disconnect does not count as a server failure. v1 was discarded, and v2 restarted from scratch.
- **v2:** stopped at episode 56, when the orchestrator session restarted. The incomplete episode (`T5-rtk/recover_date-r2`) was archived in `stage5-rep3-v2-interrupted`. The campaign resumed with the same manifest, reran that episode from scratch and skipped the 55 already completed.

## Result

| Arm | 1st attempt | 95% CI | Final | 95% CI |
|---|---|---|---|---|
| X-think (control + escalation with thinking) | 22/36 = 61% | 45–75% | **30/36 = 83%** | 68–92% |
| T5-rtk | 17/36 = 47% | 32–63% | 17/36 = 47% | 32–63% |

By repetition:
- X-think, 1st attempt → final: 8 → 10, 7 → 10 and 7 → 10.
- T5-rtk: 5, 7 and 5.

## Cascade with thinking: confirmed

- **10 escalations, 8 rescues and no losses.** The exact McNemar test comparing the 1st attempt and final result gives p = 0,008.
- Rescues occurred in:
  - `cont_quote`: 3/3;
  - `py_query`: 2/3;
  - `tests_query`: 1/3;
  - `tests_range`: 2/3.
- Combined with the original stage 5 (7 → 11/12), the total is **29/48 → 41/48 (60% → 85%)**, with 12 rescues in 14 escalations.
- `py_range` remains at 0 in every repetition, with and without thinking.

## RTK: negative trend, without significance

| Paired comparison (same task and repetition) | Count |
|---|---:|
| Only the control passed | 8 |
| Only RTK passed | 3 |
| Both passed or both failed | 25 |

- The exact McNemar test gives p = 0,23. The drop from 61% to 47% repeats the direction of stage 5 (6/12), but is not significant.
- RTK consistently loses on `recover_date`, `js_sign` and `cont_path`, and wins on `cont_quote`.
- The hypothesis remains unverified: summarized pytest output may hide the model error.

## By task

Key: `1` passed on the 1st attempt; `F` passed only after escalation; `0` failed. The order is r1, r2, r3.

| Task | X-think | T5-rtk |
|---|---|---|
| cont_path | 111 | 010 |
| cont_quote | FFF | 110 |
| js_plural | 111 | 111 |
| js_sign | 111 | 001 |
| mcp_header | 111 | 111 |
| mcp_params | 111 | 111 |
| py_query | 1FF | 000 |
| py_range | 000 | 000 |
| recover_date | 110 | 000 |
| recover_decode | 111 | 111 |
| tests_query | 0F1 | 000 |
| tests_range | F0F | 010 |

## Conclusion

1. **Adopt the 4B → 4B cascade with thinking** as the worker configuration. It is the only statistically confirmed effect so far.
2. **Keep RTK out.** Retest only with pytest outside the filter, if still of interest.

Aggregate: `results/3070-benchmark/stage5-rep3-summary.txt`. Script: `scratchpad/rep3_summary.py`.
