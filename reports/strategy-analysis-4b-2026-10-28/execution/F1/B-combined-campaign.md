# Combined campaign: MTP, checkpoints and escalation with thinking, Q4 and Q6

Date: 30/10/2026, from 01h37 to 03h38. Ran with runner `benchmark/baseline_stage5.py --config benchmark/configs/qwen-4b-opencode-combined.json`, on branch `bench/combined-config`, commit `1b908ac`. The protocol is `qwen-4b-opencode-combined-v2`, and results are in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-combined-v2`.

Design: 2 arms × 12 tasks × 3 repetitions, totaling **72 episodes**, with no infrastructure failures. Both arms use:
- KV q4_0, 64K context, prompt cache and temperature 0;
- MTP with `--spec-draft-n-max 2`;
- context checkpoints (`--ctx-checkpoints 64 --checkpoint-min-step 1024`);
- `--cache-ram 2048`;
- escalation with thinking when visible verification fails.

| Arm | Model |
|---|---|
| R-q4 | Q4_K_M (bartowski) |
| R-q6 | Q6_K_L (bartowski) |

The comparison is with the X-think arm of the `stage5-rep3-v2` replication. It uses the same escalation, without MTP or checkpoints, with RAM cache at the 8 GiB default.

## v1 interruption

v1 stopped at the 8th episode, when WSL Linux killed `llama-server` for lack of memory (RSS of 6.9 GB). The llama.cpp RAM prompt cache defaults to 8 GiB, the same size as total WSL RAM. With MTP and checkpoints, each cache entry reached 1.2 GiB. v2 limits that cache to 2 GiB. This differs from the comparison arm.

## Result

| Arm | 1st attempt | Final | Escalations (rescues) | Median time per episode | Total time | Peak VRAM |
|---|---|---|---|---:|---:|---:|
| X-think (replication) | 22/36 = 61% | **30/36 = 83%** | 10 (8) | 53.8 s | 77 min | 4,546 MiB |
| R-q4 | **27/36 = 75%** | 29/36 = 81% | 3 (2) | 40.3 s | 72 min | 5,800 MiB |
| R-q6 | 23/36 = 64% | 28/36 = 78% | 7 (5) | 38.0 s | 59 min | 6,618 MiB |

Paired comparisons by task and repetition (exact McNemar):

| Comparison | Only the 1st passed | Only the 2nd passed | p |
|---|---:|---:|---:|
| R-q4 versus X-think, 1st attempt | 3 | 8 | 0.23 |
| R-q4 versus X-think, final | 2 | 1 | 1.00 |
| R-q6 versus X-think, final | 4 | 2 | 0.69 |
| R-q4 versus R-q6, 1st attempt | 7 | 3 | 0.34 |
| R-q4 versus R-q6, final | 3 | 2 | 1.00 |

## Interpretation

- **Final pass rate holds.** R-q4 scores 81% and X-think 83%. The difference is 1 episode, without significance. MTP and checkpoints do not harm quality.
- **The 1st attempt improved with R-q4 (61% to 75%), but without significance.** Escalation was therefore used less (3 versus 10), and median time per episode fell from 54 s to 40 s. It is still unclear whether MTP, checkpoints, smaller cache or variation caused this. A campaign with one factor at a time would be needed to separate them.
- **Successful 1st attempts did not become faster.** The median was 35.5 s for R-q4 versus 28.4 s for X-think. The MTP decode gain, about +55% in stage 4, does not appear in episode time. The hypothesis is that prefill, tools and the number of turns dominate the time.
- **Q6 is not worthwhile.** It used 0.8 GB more VRAM and did not improve the pass rate (78% versus 81%). It was faster overall (59 min), but with more escalations. Choose Q4.
- **The VRAM cost of MTP and checkpoints** is about 1.25 GB more at peak: 5.8 GB versus 4.5 GB. It still fits comfortably on an 8 GB card.
- `py_range` remains at 0 in every arm. `recover_date` fell in R-q4 (0/3 versus 2/3 in X-think).

## Recommendation

The usage configuration is **Q4_K_M + KV q4_0 + 64K + cache + `--cache-ram 2048` + MTP n-max 2 + checkpoints + temperature 0**, with thinking disabled on the 1st attempt and enabled on escalation. It has the same final pass rate as escalation without MTP, uses escalation less frequently and fits in 5.8 GB.

Files:
- aggregate in `results/3070-benchmark/combined-summary.txt`;
- script in `scratchpad/combined_compare.py`.
