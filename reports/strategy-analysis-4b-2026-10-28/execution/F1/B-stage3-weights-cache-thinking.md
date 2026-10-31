# OpenCode baseline: stage 3 (weights, cache and thinking)

Date: 29/10/2026. Author: Claude (orchestrator).

- Protocol: `bwrap-v6`.
- Control: the 24 `bwrap-v5` episodes, with Q4_K_M (bartowski), KV q4_0, 64K context, cache enabled, thinking disabled, temperature 0 and 40 steps.
- Each arm changes one factor and runs the 12 tasks once.

| Arm | Passes | Rate | Median time for successes (s) | Median TTFT (ms) | Peak VRAM (MiB) | Failures |
|---|---:|---:|---:|---:|---:|---|
| **Control** | 16/24 | 67% | 36 | 273 | 4.567 | 5 oracle, 1 phase 1, 1 timeout, 1 CLI |
| Q6_K (unsloth) | 10/12 | 83% | 34 | 290 | 5.162 | 1 oracle, 1 CLI |
| Q8_0 (unsloth) | 8/12 | 67% | 32 | 320 | 6.033 | 4 oracle |
| Cache disabled | 9/12 | 75% | **82** | **7.704** | 4.521 | 1 timeout, 1 oracle, 1 CLI |
| **Thinking enabled** (temperature 0,6, top_p 0,95, top_k 20) | **11/12** | **92%** | **109** | 200 | 4.535 | 1 oracle |

## Interpretation

1. **Thinking enabled had the highest rate so far: 11 out of 12.** It solved difficult tasks where the control failed. The cost is about **3× the time per task** (109 s versus 36 s). With 12 episodes, the difference is not yet statistically firm, but it is the strongest signal in the matrix. Stage 4 therefore added the **C4-think arm with 2 repetitions** to confirm it.
2. **Q6_K with 10/12 and Q8_0 with 8/12.** More bits did not produce a monotonic gain. Q6_K remains promising, but this could be noise or a quantizer effect. Stage 4 runs 3 repetitions of Q6_K and a Q4_K_M from the same quantizer (unsloth) to separate the two effects.
3. **Cache does not change the pass rate, but is essential for latency.** Without cache, median TTFT rises from 0.27 s to 7.7 s and time per task more than doubles (82 s versus 36 s).
4. No infrastructure failures.

## Consolidated stages 1–3

The provisional usage configuration, to be confirmed in stage 4, is: **Q4_K_M or Q6_K, KV q4_0, 32–64K context, cache enabled**. For thinking:
- **enabled** when quality matters more than time;
- **disabled** for quick responses.

16K context is unsuitable for OpenCode.
