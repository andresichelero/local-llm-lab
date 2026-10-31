# Stage 4: finalist replication and server options

Date: 29/10/2026. Protocol `bwrap-v7` (40 steps), 168 episodes, from 04h59 to 09h24, no infrastructure failures. Results in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v7`. Counted by first attempt (only a real infrastructure failure would allow a second), as in stages 1 to 3.

Control: Q4_K_M bartowski, KV q4_0, 64K context, prompt cache enabled, thinking disabled, temperature 0, 40 steps. Each arm changes one factor.

## Results by arm

| Arm | Change | n | Success | Rate | Median s (successes) | Decode tok/s | Peak VRAM MiB |
|---|---|---|---|---|---|---|---|
| C4-q4 | control, 3 repetitions | 36 | 25 | 69% | 37.5 | 74 | 4584 |
| C4-q6 | Q6_K unsloth, 3 repetitions | 36 | 27 | 75% | 32.0 | 67 | 5127 |
| C4-think | thinking enabled, 2 repetitions | 24 | 16 | 67% | 123.0 | 74 | 4529 |
| S-ctx48 | 48K context | 12 | 11 | 92% | 45.4 | 76 | 4307 |
| S-steps80 | 80-step limit | 12 | 10 | 83% | 39.0 | 78 | 4531 |
| S-checkpoints | `--ctx-checkpoints 64 --checkpoint-min-step 1024` | 12 | 9 | 75% | 24.5 | 76 | 4531 |
| S-mtp | MTP, `--spec-draft-n-max 2` | 12 | 8 | 67% | 24.8 | **115** | 5129 |
| S-q4-unsloth | Q4_K_M from unsloth | 12 | 7 | 58% | 36.0 | 77 | 4379 |
| S-qwen-sampling | Qwen-recommended sampling | 12 | 6 | 50% | 36.7 | 72 | 4531 |

## Aggregate with previous stages

| Configuration | Episodes | Rate | 95% CI (Wilson) |
|---|---|---|---|
| Q4_K_M (B0 v5 + C4-q4) | 60 | 68% (41) | 56–79% |
| Q6_K (B-q6 + C4-q6) | 48 | 77% (37) | 63–87% |
| Thinking (B-think + C4-think) | 36 | 75% (27) | 59–86% |

## Conclusions

1. **Thinking did not hold up.** In stage 3 it scored 11/12 (92%); in replication, 16/24 (67%). Combined, it is 75%, within control noise, and each episode takes about 3.3 times longer (123 s versus 37 s) because the model generates an average of 8,200 tokens instead of 2.200. It is not worthwhile as the default. It remains a cascade candidate (try thinking only on failure), the X-think arm of stage 5.
2. **Q6_K is the best weight candidate, but the difference is not significant.** Paired by task and repetition, Q4 passed 4 cases Q6 failed, and Q6 passed 6 Q4 failed (McNemar, p ≈ 0.75). Q6 produces far fewer tokens per episode (median 780 versus 2.200), is 10% slower at decode and uses about 550 MiB more VRAM. It still fits comfortably on an 8 GB card.
3. **MTP is the best server option.** Decode rises from 74 to 115 tok/s (+55%) with 91% draft acceptance, and median successful episode time falls from 37.5 s to 24.8 s. The rate (8/12) is within the noise. At temperature 0, speculative decoding should theoretically leave output unchanged (in practice, numerical batch differences can change some tokens), so the pass-rate difference should be noise, not an effect. Cost: about 550 MiB more VRAM.
4. **Context checkpoints** give speed similar to MTP (24.5 s) and maintain the rate (9/12). The gain comes from reusing the hybrid-layer cache.
5. **ctx48 (11/12) and steps80 (10/12)** have only one repetition. Results are compatible with the control, and there is no indication that 64K or 40 steps limit the result.
6. **Worse:** Qwen-recommended sampling (50%) and unsloth Q4_K_M (58%). With 12 episodes the intervals overlap the control, but there is no reason to adopt either.
7. **Tasks:** `py_range` fails almost everywhere (only Q6 passed 2/3). `tests_query` and `tests_range` are near 50%. `recover_date` shows the largest divergence between arms: Q4 passed 3/3 and Q6 failed 3/3. The other eight tasks are saturated, near 100%. The corpus has little discriminatory power; expanding it is a priority (BACKLOG).

## Recommendation for the control in future campaigns

Keep Q4_K_M + KV q4_0 + 64K + cache + thinking disabled as a comparable control. The **recommended usage configuration** becomes the same **with MTP (n-max 2) and context checkpoints**: large measured speed gains, with no expected effect on pass rate. Q6_K is an alternative weight when VRAM permits. The next step is to measure MTP and checkpoints together and with Q6_K, in a campaign with at least 3 repetitions and a larger corpus.

Limitations: 12 episodes per arm detect differences above only about 25 percentage points. Noise between repetitions is large: 4 tasks changed outcomes between repetitions of the same arm.
