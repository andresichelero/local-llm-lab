# Calibrated comparison: MTP and checkpoints on corpus v2

This campaign measured what MTP and context checkpoints change for Qwen3.5-4B on the tasks the calibration kept. Both arms used Q4_K_M, KV q4_0, 64K, prompt cache, `--cache-ram 2048` and the thinking cascade. `CMP-rec` added `--spec-type draft-mtp --spec-draft-n-max 2 --ctx-checkpoints 64 --checkpoint-min-step 1024`.

Each arm ran 18 tasks three times, 54 units per arm. The tasks were the 12 kept by the [calibration](corpus-v2-calibration.md) and 6 pilot tasks that vary.

- Configs: `benchmark/configs/qwen-4b-opencode-calibrated-comparison.json` and `benchmark/configs/qwen-4b-opencode-calibrated-comparison-rec-resume.json`.
- Aggregate: [calibrated-comparison-v1-summary.txt](../../../../results/3070-benchmark/calibrated-comparison-v1-summary.txt).

## Result

`CMP-rec` was faster. The pass rate did not differ significantly, but the data cannot rule out a real loss.

| Measure | CMP-base | CMP-rec |
| --- | --- | --- |
| Passed first attempt | 21/54 | 22/54 |
| Passed after retry | 34/54 (63.0%, CI 49.6-74.6) | 30/54 (55.6%, CI 42.4-68.0) |
| Retries | 20 | 15 |
| Rescued by retry | 13 | 8 |
| Retry also failed | 7 | 7 |
| Failed oracle only, no retry | 13 | 17 |
| Decode speed | 72.7 tok/s | 107.1 tok/s |
| Median first attempt | 82.7 s | 60.1 s |
| Median unit | 124.6 s | 82.3 s |
| Arm total | 169 to 183 min | 126 min |
| Peak VRAM | 5,273 MiB | 5,282 MiB |

MTP was active in `CMP-rec`: 86,428 of 99,506 draft tokens were accepted (86.9%). No episode compacted. Peak VRAM rose by 9 MiB.

McNemar exact, paired by task and repetition:

| Metric | Base only | Rec only | p |
| --- | --- | --- | --- |
| First attempt | 8 | 9 | 1.000 |
| After retry | 7 | 3 | 0.344 |

The paired difference after retry is -7.4 points, with an approximate 95% interval of -18.7 to +3.9. A loss of up to about 19 points is still compatible with these runs. Repetitions of a task are not independent, so this interval is probably too narrow.

Per task, `CMP-rec` did better on 3, `CMP-base` on 3, and 12 tied.

## Where the gap comes from

First-attempt passes are level, 21 and 22. The gap comes from the retry: it rescued 13 units in `CMP-base` and 8 in `CMP-rec`. The cascade retries only after a visible failure, and `CMP-rec` more often passed the visible test and then failed the oracle (17 against 13). These units never reach the retry.

`py_cookie` shows this. Two `CMP-base` first attempts failed the visible test, were retried and passed. All three `CMP-rec` first attempts passed the visible test, failed the oracle and were not retried.

Few diffs match across arms: 12 of 54 first attempts are byte-identical for the same task and repetition. MTP should not change the output in principle, yet these runs took different paths. This campaign cannot say whether that comes from MTP, from checkpoints or from the variation already present inside each arm, where 9 of 18 `CMP-base` tasks gave three distinct diffs.

## Per task

Each cell gives the first attempt, then the final result, for repetitions 1 to 3. `P` is a pass and `x` a failure.

| Task | Group | CMP-base | CMP-rec |
| --- | --- | --- | --- |
| `cont_forms` | Varied | xxx > xPx | xxx > xPP |
| `cont_plugins` | Varied | PPP > PPP | xPx > xPx |
| `py_config` | Varied | PxP > PPP | xPx > PPP |
| `py_cookie` | Varied | xxP > PPP | xxx > xxx |
| `py_urlbuild` | Varied | PPx > PPP | PPP > PPP |
| `tests_list` | Varied | PxP > PPP | PPP > PPP |
| `js_decimal` | Hard | xxx > xxx | xxx > xxx |
| `js_invalid` | Hard | xxx > xxx | Pxx > Pxx |
| `js_units` | Hard | xxx > xxx | xxx > xxx |
| `mcp_groups` | Hard | xxx > xxx | xxx > xxx |
| `mcp_render` | Hard | xxx > PPP | PxP > PPP |
| `recover_httpdate` | Hard | xxx > xxx | xxx > xxx |
| `cont_path` | Pilot | PPP > PPP | PPP > PPP |
| `cont_quote` | Pilot | PxP > PPP | PPP > PPP |
| `py_query` | Pilot | xPP > PPP | xPP > PPP |
| `recover_date` | Pilot | PPx > PPx | xxx > xxx |
| `tests_query` | Pilot | PPx > PPP | PxP > PPP |
| `tests_range` | Pilot | xxx > xPx | xPx > xPP |

Final passes by group: varied 16/18 and 12/18 (p=0.219), hard 3/18 and 4/18 (p=1.000), pilot 15/18 and 14/18 (p=1.000).

## Interruption and rerun

The first run stopped at `CMP-rec` `cont_plugins-r2`. The model had rewritten `bottle.py` from 4,680 lines to 13, leaving an `IndentationError`. The oracle check recognized `SyntaxError` but not its subclasses, so this was filed as a grader failure and the retry aborted the run. This was the only `grader_infrastructure` result in the campaign. `candidate_collection_error` now also accepts `IndentationError` and `TabError`.

The manifest correctly refuses to resume a directory after a code change, so the original output was left untouched. The 19 finished `CMP-rec` units were copied to a new output directory, and the other 35 ran there with the fix. Copied units were run with the earlier code. The fix does not change how any of them was classified.

The rerun of `cont_plugins-r2` passed on its first attempt. Repeating only a failed unit favors that arm, so the result was checked three ways:

| Treatment of the unit | Final passes, rec | Base only | Rec only | p |
| --- | --- | --- | --- | --- |
| Rerun counted | 30/54 | 7 | 3 | 0.344 |
| Crashed run counted as failure | 29/54 | 8 | 3 | 0.227 |
| Unit dropped | 29/53 (base 33/53) | 7 | 3 | 0.344 |

The conclusion is the same in all three.

## Limits

- The arms ran one after the other, not interleaved, so anything that changed on the PC during the morning falls on one arm.
- The `CMP-base` total is a range because its two clocks disagree. Recorded unit time sums to 183 min and file timestamps span about 169 min, with every unit about 8% long. The clocks agree in `CMP-rec`. The base decode speed may be affected by the same amount, so the time saving is between 25% and 31% and the decode gain between about 36% and 47%.
- MTP and checkpoints were changed together, as a profile. This campaign cannot separate their effects.
- Pass rates were not compared with earlier pilot campaigns, since the task sets differ.
- 3 repetitions on 18 tasks cannot detect a difference of a few points.

## Decision

Keep MTP and checkpoints as the profile for speed, and do not claim that they preserve quality. The earlier 29/36 and 30/36 result came from the pilot tasks. On this set the question is still open, and the retry gap is the thing to examine next.
