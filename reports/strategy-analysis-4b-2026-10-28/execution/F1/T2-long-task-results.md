# T2: long-task results (v2)

Date: 29/10/2026, from 10h21 to 10h47. Runner `benchmark/long_tasks.py`, commit `31a1d4b`, protocol `qwen-4b-opencode-long-tasks-20261029-v2`. Results in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-long-tasks-20261029-v2/campaign`.

The design is 4 arms × 2 marathons × 1 repetition, totaling **8 units**. There were **zero infrastructure failures**: v1's `grader_infrastructure` was fixed with `candidate_exception_only`.

Each marathon chains objectives in the same workspace:
- M1: `py_query`, `py_range`, `cont_quote` (two phases) and `recover_decode`. There are 4 private oracles.
- M2: `mcp_header`, `mcp_params`, `recover_date`, `cont_path` (two phases) and `tests_range`. There are 5 private oracles.

The arms are:
- **L-bigctx:** large context, no compaction;
- **L-compact:** native OpenCode compaction;
- **L-headroom:** compression via Headroom;
- **L-reset:** new session per objective, with `PROGRESS.md` saved in the workspace.

## Result

"Final oracles" counts private oracles that pass at the end of the marathon.

| Arm | M1 (of 4) | M2 (of 5) | Total | Completed marathons | M1 / M2 time | Model calls | Prompt tokens | Peak VRAM |
|---|---|---|---|---|---|---:|---:|---:|
| **L-bigctx** | **4** | **5** | **9/9** | 2/2 | 503 s / 168 s | 187 | 7,87 M | 5.432 MiB |
| L-headroom | 2 | **5** | 7/9 | 1/2 | 125 s / 216 s | 161 | 2,41 M | 4.077 MiB |
| L-compact | 3 | 3 | 6/9 | 0/2 | 97 s / 108 s | 108 | 1,52 M | 4.103 MiB |
| L-reset | 3 | 2 | 5/9 | 0/2 | 133 s / 261 s | 164 | 2,01 M | 4.077 MiB |

No arm showed regression: no oracle that passed after an objective later failed again. There was no OOM either.

L-reset M2 recorded one context exceeded, two tool failures and ended in `model_cli_failure`.

## Interpretation

- **L-bigctx was the only arm to complete both marathons.** The cost was high: 3 to 5× more prompt tokens and 1,3 GB more VRAM, namely larger context with KV q4_0. In M1 it made 120 calls in 503 s.

  Almost all prompt tokens came from cache: 5,69 M of 5,80 M tokens in M1. Time therefore grew much less than volume.
- **L-headroom** completed M2 and failed M1, at `py_range` and `cont_quote:2`. The taxonomy recorded `step_cap` and a visible test failure in the middle.
- **L-compact and L-reset** lose objectives in the middle of the marathon. Failure on `py_range` is common to all three reduced-context arms, but `py_range` is also the hardest task in isolation (0/5 in the stage 4 control).

  Thus, part of the effect is task difficulty, not memory loss.
- **Observed order:** bigctx > headroom > compact > reset. With one repetition per marathon, this is an indication, not a conclusion. The only difference that appears robust is bigctx against the other three.

## Caveats

- The `compaction_observation` field says "SQLite compaction parts requested; completion not established". The runner sees the compaction request, but does not confirm completion.

  The `usage.compactions` counter remained 0 in every unit, while `compactions` (at unit level) ranged from 1 to 6. Compaction instrumentation is not yet reliable enough to establish how many compactions actually occurred.
- Phase 1 objectives (`cont_quote:1`, `cont_path:1`) have no private oracle of their own.

## Recommendation

1. For long tasks on the 3070, **large context with KV q4_0 and prompt cache** is the safest option while it fits in VRAM. The 5,4 GB peak leaves room in 8 GB.
2. Headroom is the best compromise when context must be limited.
3. **Next:** 3 repetitions of L-bigctx versus L-headroom, and fix compaction completion confirmation before comparing compact with reset.
