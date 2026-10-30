# OpenCode baseline: stage 1, B0 control

Date: 29/10/2026. Author: Claude (orchestrator).

- Runner: `benchmark/opencode_baseline.py`, branch `feat/4b-worker-v2`.
- Control: Qwen3.5-4B Q4_K_M, KV q4_0/q4_0, 64K context, prompt cache enabled, thinking disabled, temperature 0.
- Environment: OpenCode 1.19.5 isolated in bubblewrap, llama.cpp v0.8.0, 12 corpus tasks with 2 repetitions each.

## Two rounds, with one different harness variable

| Protocol | OpenCode step limit | Episodes | Successes | Rate |
|---|---:|---:|---:|---:|
| bwrap-v4 | 20 | 23 (the 24th did not run because of an evaluator error) | 15 | 65% |
| bwrap-v5 | 40 | 24 | **16** (the runner recorded 17; see correction below) | **67%** |

**Corrections applied to the data:**

1. **v4, `tests_query` r2:** the evaluator aborted because `CORPUS_SUPPORT` was missing from the oracle environment. This episode is excluded from the count. Fixed in `f3a895d`.
2. **v5, `cont_path` r2:** phase 1 exhausted 40 steps and the runner classified this as "infrastructure". With that classification the episode received a 2nd attempt, which passed. **The 1st attempt counts, and it is a model failure.** The classification bug was fixed in `417e96d`, which is the v6 protocol, used from stage 2 onwards.

## By task (v5, after correction)

| Task | r1 | r2 | Note |
|---|---|---|---|
| js_plural, mcp_header, mcp_params, recover_decode, cont_quote | ✅ | ✅ | stable |
| py_query | ✅ | ✅ | r2 took 36 steps and 106 s |
| js_sign | ✅ | ❌ | r2 exhausted 40 steps |
| recover_date | ❌ | ✅ | r1 exhausted 40 steps |
| cont_path | ✅ | ❌ | r2 stopped in phase 1 at the step limit |
| tests_range | ❌ (CLI failure) | ✅ | |
| py_range | ❌ | ❌ | 0/4 across v4 and v5: the hardest task in the corpus |
| tests_query | ❌ | ❌ (timeout, 505 s) | 0/3 evaluable across v4 and v5 |

## Operational cost (v5)

- Median successful episode: **33 s**. Median TTFT of 200–450 ms per request.
- **93,5%** of prompt tokens came from the cache.
- Device VRAM peak in smoke tests: ~5,3 GiB.

## Interpretation

- **The 4B solves most corpus tasks** with a mature harness and a sensible runtime configuration. This contrasts with 0/17 in the custom harness in F1, but the tasks and harnesses differ in the two cases.
- **The 20 or 40 step limit did not change the rate detectably** (65% versus 67%, within the noise). Variation between repetitions is high: 4 tasks changed outcomes between r1 and r2. To claim differences in stages 2 and 3, consider the magnitude and do not treat 1 or 2 episodes as an effect.
- v5 (40 steps) is the control for subsequent stages.
