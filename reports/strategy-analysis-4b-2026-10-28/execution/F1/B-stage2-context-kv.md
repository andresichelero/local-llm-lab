# OpenCode baseline: stage 2, context and KV

Date: 29/10/2026. Author: Claude (orchestrator).

- Protocol: `bwrap-v6`, commit `417e96d`.
- Control: Q4_K_M, KV q4_0, 64K context, cache enabled, thinking disabled, 40 steps. These are the 24 `bwrap-v5` episodes.
- Each arm changes **one factor** and runs 1 time on the 12 tasks.

| Arm | Passes | Rate | Median s (successes) | Median TTFT ms | Device peak VRAM, MiB | Fraction of prompt from cache | Failures |
|---|---:|---:|---:|---:|---:|---:|---|
| **Control** (64K, q4_0) | 16/24 | 67% | 36 | 273 | 4.567 | 0,94 | 5 oracle, 1 phase 1, 1 timeout, 1 CLI |
| ctx 16K | **3/12** | **25%** | 28 | 437 | 3.858 | 0,87 | **9 context exceeded** |
| ctx 32K | 9/12 | 75% | 38 | 234 | 4.105 | 0,92 | 3 oracle |
| ctx 128K | 9/12 | 75% | 38 | 258 | 5.422 | 0,95 | 2 oracle, 1 timeout |
| KV q8_0 | 9/12 | 75% | 31 | 272 | 5.038 | 0,92 | 2 oracle, 1 CLI |
| KV f16 | 7/12 | 58% | 32 | 273 | 5.754 | 0,91 | 4 oracle, 1 timeout |

## Interpretation

1. **16K is insufficient for OpenCode on this corpus.** Nine episodes died with `exceeds the available context size (16384 tokens)`; one request reached 23.723 tokens. This is a harness capacity limit with this repository, not a model error.
2. **There is no detectable difference in pass rate from 32K to 128K** (75%, 67% and 75%). In the control, 4 tasks changed outcomes between repetitions, so differences of 1 to 2 episodes are noise.
3. **KV type does not detectably change the pass rate** (q4_0 67%, q8_0 75%, f16 58%). f16 scored lower, but within the noise. **KV q4_0 has no measurable quality cost** and is the cheapest.
4. **The cost of larger context and KV is small at this scale of real use.**
   - Peak VRAM: 4,1 GiB at 32K, 4,6 GiB at 64K and 5,4 GiB at 128K, all with q4_0; 5,8 GiB with f16 at 64K.
   - TTFT was between 230 and 280 ms in all arms from 32K upwards. The cache covers more than 91% of the prompt.
   - Since the agent does not fill the window, the 85 s cold prefill cost measured in the needle at 128K does not appear here.

## Recommended usage configuration

- **Context: 32K is the minimum, 64K is a comfortable margin.** 128K works and fits in the GPU (5,4 GiB), but did not improve results on this corpus.
- **KV: q4_0.**
- The control for subsequent stages remains **64K with q4_0**.
