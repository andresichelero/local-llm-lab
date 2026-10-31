# Stage 5: weights, tools and cascades

Date: 29/10/2026, 10h47 to 13h23. Runner `benchmark/baseline_stage5.py` at commit `31a1d4b`. Protocol `qwen-4b-opencode-stage5-v2`. Results in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-stage5-v2`.

The design is 8 arms × 12 tasks × 1 repetition, totaling **96 episodes**. There were **zero infrastructure failures**, after the classification fixes in `31a1d4b`.

Each arm changes one factor relative to the stage 4 control:
- Q4_K_M bartowski with KV q4_0;
- 64K context and cache enabled;
- thinking disabled, temperature 0 and 40 steps.

## First-attempt results

Counting follows the same rule as previous stages: the first attempt counts, and the second replaces the first only when the first failed due to infrastructure.

The combined Q4_K_M control (B0 from v5 plus C4-q4 from v7) scored **41/60 = 68%**, with 95% CI from 56% to 79%.

| Arm | Passed | 95% CI (Wilson) | s/episode (median) | Prompt tokens | Tool failures |
|---|---|---|---:|---:|---:|
| Q5-Q6KL (bartowski Q6_K_L) | 10/12 | 55–95% | 56.1 | 5.86 M | 4 |
| Q5-UDQ6XL (unsloth UD-Q6_K_XL) | 10/12 | 55–95% | 40.1 | 3.32 M | 6 |
| T5-lsp-tool (LSP + `lsp` tool) | 10/12 | 55–95% | 37.8 | 5.24 M | 3 |
| Q5-UDQ4XL (unsloth UD-Q4_K_XL) | 9/12 | 47–91% | 34.2 | 3.90 M | 3 |
| T5-lsp (Pyright diagnostics) | 9/12 | 47–91% | 67.0 | 6.13 M | 7 |
| X-9b, 1st attempt (= control) | 8/12 | 39–86% | 37.3 | 4.38 M | 7 |
| X-think, 1st attempt (= control) | 7/12 | 32–81% | 44.4 | 6.02 M | 6 |
| **T5-rtk (RTK plugin)** | **6/12** | 25–75% | 44.2 | 6.55 M | 7 |

The first attempt in the X arms runs exactly the control configuration. Combined, they score **15/24 = 62%**, consistent with the 68% stage 4 control: the control is stable across campaigns.

With 12 episodes per arm, **no difference from the control is statistically significant**. All intervals overlap.

## Cascades

Cascades escalate only on a visible failure or an identified model failure. A private oracle failure alone does not escalate, because the agent cannot see it.

| Cascade | 1st attempt | Escalations | Final | Total time | Extra escalation time |
|---|---|---:|---|---:|---:|
| X-think (2nd with reasoning enabled, sampling 0.6/0.95/20) | 7/12 | 4 | **11/12** | 1.518 s | 465 s |
| X-9b (2nd with Qwen3.5-9B Q4_K_M) | 8/12 | 3 | 9/12 | 2.083 s | 813 s |

Key points:
- **X-think rescued 4 of 4 escalations.** It cost about 116 s more per rescue and requires no model switch.
- 9B rescued 1 of 3 escalations, at higher cost (271 s per escalation, with model unloading and reloading).
- In this sample, the 4B → 4B cascade with thinking is better and cheaper than 4B → 9B.

One caveat: with 4 events, the X-think rescue is strong evidence of direction, but not a precise estimate.

## By task

Key: `ok` = passed; `oracle` = passed the visible test and failed the private one; `timeout` = timed out; `phase1` = phase 1 incomplete; `cli` = CLI failure.

| Task | Control (5 runs) | Q6KL | UDQ4XL | UDQ6XL | lsp | lsp-tool | rtk | 9b (1st) | think (1st) |
|---|---|---|---|---|---|---|---|---|---|
| cont_path | 4/5 | ok | ok | ok | ok | ok | oracle | ok | ok |
| cont_quote | 4/5 | ok | ok | ok | phase1 | ok | ok | ok | ok |
| js_plural | 5/5 | ok | ok | ok | ok | ok | oracle | ok | ok |
| js_sign | 3/5 | ok | ok | ok | ok | ok | ok | oracle | oracle |
| mcp_header | 5/5 | ok | ok | ok | ok | ok | ok | ok | ok |
| mcp_params | 5/5 | ok | ok | ok | ok | ok | ok | ok | ok |
| py_query | 3/5 | ok | ok | ok | cli | ok | ok | ok | oracle |
| py_range | **0/5** | oracle | oracle | oracle | **ok** | oracle | oracle | oracle | oracle |
| recover_date | 4/5 | ok | oracle | ok | ok | oracle | oracle | ok | ok |
| recover_decode | 5/5 | ok | ok | ok | ok | ok | ok | ok | ok |
| tests_query | 1/5 | ok | oracle | ok | ok | ok | oracle | timeout | timeout |
| tests_range | 2/5 | timeout | ok | timeout | timeout | ok | timeout | oracle | oracle |

Interpretation:
- **`py_range` remains the hardest task.** Only the LSP arm passed. The control never passed it (0/5), and one pass cannot separate an LSP effect from luck.
- **`tests_query` and `tests_range` are near the time limit.** The Q6 and LSP arms exceed wall time on `tests_range`.

## Tools: what was actually used

- **LSP.** Pyright started in every episode of both LSP arms. Diagnostics appear in OpenCode events.
- **`lsp` tool.** In T5-lsp-tool, **the model never called the tool**: `lsp_tool_calls = 0` in all 12 episodes. The difference between T5-lsp and T5-lsp-tool therefore cannot be attributed to the tool. It is variation across runs of the same effect, automatic diagnostics.
- **RTK.** The plugin rewrote commands as expected in 10 of 12 episodes. The most common were:
  - `rtk pytest test/ -v 2>&1 | head -100` (70 times);
  - `rtk pytest <arquivo> -v` (60 times);
  - `rtk grep -n` (44 times).

  There are also `rtk recall <id>` calls, where the model must request the output summarized by RTK again.

### Hypothesis for RTK degradation (unverified)

RTK had the worst result (6/12) and largest prompt volume (6.55 M tokens, with 292 model calls). The most likely explanation is that RTK summarizes pytest output, and the 4B loses error details such as asserts and tracebacks. The model then spends more turns and fails more often at the private oracle; 4 of the 6 failures were `oracle`.

This contradicts RTK's goal of saving context. Confirmation would require comparing summarized output with the originals.

## Weights

- **Q6_K_L and UD-Q6_K_XL (10/12 each)** repeat the stage 4 trend: Q6 slightly above Q4, without significance. UD-Q6_K_XL was faster and used less prompt than Q6_K_L.
- **UD-Q4_K_XL (9/12)** tied the control and was the fastest arm.
- None of the three alone justifies changing the control.

## Recommendation

1. **Adopt the X-think cascade** (4B without thinking, escalating to 4B with thinking on visible failure) as the recommended worker configuration. It is the only intervention in this stage with a large, direct effect (7 → 11/12), and keeps a single model in VRAM.
2. **Do not adopt RTK** for this model. If retested, leave pytest outside the filter.
3. **LSP** is neutral to slightly positive and costs time (T5-lsp had the highest median). Do not prioritize the `lsp` tool, which the model does not use spontaneously.
4. **Weights:** keep Q4_K_M as the control. UD-Q6_K_XL is the candidate if VRAM permits.
5. **Next:** replicate X-think and T5-rtk with 3 repetitions to confirm the two strong directions before documenting them as a conclusion.

## Files

- `scratchpad/stage5_detail.py`: per-task matrix, Wilson CI and costs.
- `scratchpad/stage5-detail.txt`: analysis output.
- `units/<braço>/summary.json`: first-attempt and final rates, and cascade times.
- `units/<braço>/<tarefa>-r1/cascade.json` and `model-switches.json`: decisions and model switches.
