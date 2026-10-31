# T2: long-task results with three repetitions (v3)

This campaign repeated the long-task comparison from [T2 v2](T2-long-task-results.md), which had one repetition per arm, and confirmed for the first time whether each compaction finished. Each marathon chains objectives in one workspace, and each unit counts the private oracles that pass at the end.

The design is 4 arms × 2 marathons × 3 repetitions, 24 units and 108 oracle results. Every repetition ran each arm on both marathons. Arms are the same as in v2: Qwen3.5-4B Q4_K_M, KV q4_0, prompt cache, no thinking and no MTP.

- Config: `benchmark/configs/qwen-4b-long-tasks.json`, protocol `qwen-4b-opencode-long-tasks-v3`.
- Aggregate: [t2-long-tasks-v3-summary.txt](../../../../results/3070-benchmark/t2-long-tasks-v3-summary.txt).

## Result

The v2 ranking did not hold. `L-compact`, last but one in v2, passed the most oracles. `L-bigctx`, which passed 9 of 9 in v2, passed 18 of 27.

| Arm | Context | Oracles passed | Marathons complete | Median unit | Peak VRAM | Compactions finished |
| --- | --- | --- | --- | --- | --- | --- |
| `L-compact` | 32K, OpenCode compaction | 23/27 | 2/6 | 151 s | 4,101 MiB | 10 of 10 |
| `L-bigctx` | 128K | 18/27 | 1/6 | 170 s | 5,435 MiB | 2 of 2 |
| `L-reset` | 32K, new session per objective | 17/27 | 0/6 | 176 s | 4,099 MiB | 35 of 116 |
| `L-headroom` | 32K, Headroom proxy | 14/27 | 0/6 | 207 s | 4,099 MiB | 13 of 13 |

McNemar exact on oracle results, paired by marathon, repetition and objective. Oracles inside one marathon are not independent, so these p values are generous.

| Pair | First only | Second only | p |
| --- | --- | --- | --- |
| `L-compact`, `L-headroom` | 9 | 0 | 0.004 |
| `L-compact`, `L-reset` | 7 | 1 | 0.070 |
| `L-compact`, `L-bigctx` | 7 | 2 | 0.180 |
| `L-bigctx`, `L-headroom` | 6 | 2 | 0.289 |
| `L-bigctx`, `L-reset` | 2 | 1 | 1.000 |

No unit showed a regression, where an oracle that had passed later failed. No unit ran out of memory.

## Passes by objective

Out of three repetitions.

| Marathon | Objective | bigctx | compact | headroom | reset |
| --- | --- | --- | --- | --- | --- |
| M1 | `py_query` | 3 | 3 | 3 | 3 |
| M1 | `py_range` | 1 | 0 | 0 | 0 |
| M1 | `cont_quote:2` | 3 | 3 | 3 | 3 |
| M1 | `recover_decode` | 3 | 3 | 3 | 3 |
| M2 | `mcp_header` | 3 | 3 | 3 | 3 |
| M2 | `mcp_params` | 0 | 3 | 2 | 0 |
| M2 | `recover_date` | 0 | 3 | 0 | 0 |
| M2 | `cont_path:2` | 3 | 2 | 0 | 3 |
| M2 | `tests_range` | 2 | 3 | 0 | 2 |

M1 separates nothing except `py_range`, the hardest objective. All of the gap comes from M2, and from two or three objectives, so the ranking may depend on those tasks.

## Compaction

The runner used to count requests. It now also counts assistant summaries that OpenCode stored with `finish: stop` and no error.

Compaction finished every time in `L-compact`, `L-headroom` and `L-bigctx`. `L-bigctx` compacted only in `M2-r3`, which also hit the wall budget at 1,716 s.

`L-reset-M2-r3` recorded 87 requests and 6 finished summaries, which accounts for the low total in that arm. The other `L-reset` units finished every request. Every `L-reset` unit also ended in `model_cli_failure` with a context overflow in its taxonomy, so a fresh session per objective does not avoid the limit on this setup.

Recounting the saved v2 units gives 1 of 2 finished in `L-headroom-M1` and every request finished in the others.

## Interruptions

The campaign ran in two parts. It stopped at `L-headroom-M2-r1`, because an earlier cleanup had removed the Python runtime under the Headroom environment. The runtime was reinstalled at the same path and the unit ran again. The Distill evaluation ran between the two parts, and no code changed. The first four units ran about four hours before the rest.

## Limits

- Six units per arm is still few, and the ranking changed between v2 and v3.
- M2 decides the result through three objectives.
- The Headroom gap of 9 against 0 is the only clear difference, and it should not be read as a verdict on Headroom in general. Its `cont_path:2` and `tests_range` failures need a look before any conclusion about the tool.

## Decision

Stop recommending a large context for long tasks. Use 32K with OpenCode compaction: it passed the most oracles and needs about 1.3 GB less VRAM. This replaces the v2 recommendation, which rested on one repetition.
