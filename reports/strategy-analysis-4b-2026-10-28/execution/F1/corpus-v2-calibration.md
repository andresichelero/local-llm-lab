# Corpus v2 calibration

The 24 new tasks ran with the recommended server profile, thinking off and no retry: Q4_K_M, KV q4_0, 64K, prompt cache, MTP, context checkpoints and `--cache-ram 2048`. Two repetitions gave 48 episodes in 37 minutes, with no infrastructure failures.

- Config: `benchmark/configs/qwen-4b-opencode-calibration.json`.
- Aggregate: [calibration-v1-summary.txt](../../../../results/3070-benchmark/calibration-v1-summary.txt).

## Result

30 of 48 episodes passed (62.5%). Failures: 17 oracle, 1 CLI. Median episode time was 30.4 s and peak VRAM 5,546 MiB.

| Group | Tasks | Count |
| --- | --- | --- |
| Passed once of two | `cont_forms`, `cont_plugins`, `py_config`, `py_cookie`, `py_urlbuild`, `tests_list` | 6 |
| Passed both | `cont_cache`, `cont_redirect`, `mcp_import`, `py_auth`, `py_headers`, `py_multi`, `py_route`, `py_template`, `recover_cookieformat`, `recover_hvalue`, `tests_compare`, `tests_escape` | 12 |
| Passed neither | `js_decimal`, `js_invalid`, `js_units`, `mcp_groups`, `mcp_render`, `recover_httpdate` | 6 |

## Tasks that never passed

Both repetitions of each task produced the same diff, so these two runs count as one observation.

| Task | Visible test | Diff lines | Reading |
| --- | --- | --- | --- |
| `js_decimal` | Passed | 11 | The fix covers the visible case and misses the oracle cases |
| `js_invalid` | Passed | 18 | Same |
| `js_units` | Passed | 11 | Same |
| `recover_httpdate` | Passed | 11 | Same |
| `mcp_groups` | Failed | 11 | Failed its visible test, so a cascade would retry it |
| `mcp_render` | Failed | 0 | Made no edit, so a cascade would retry it |

The oracle output stored in `result.json` holds only pass or fail, so the failing assertions were not inspected.

## Selection

Two repetitions cannot place a task between 20% and 80%. They separate tasks that varied from tasks that did not.

- **Keep as discriminating:** the 6 tasks that passed once.
- **Keep for now as hard:** the 6 tasks that never passed. They failed in a reproducible way, the reference solutions pass the validator, and a better setup could still solve them.
- **Hold back as saturated:** the 12 tasks that passed twice. They stay in the corpus but should not count toward comparisons until a harder setting or a third repetition shows variation.

The design predicted that the one-line Python tasks might saturate. Five of the eight did; the other three varied.

The calibration corpus for the next comparison is therefore the 12 kept tasks, optionally added to the pilot tasks that vary.

## Limits

- Two repetitions per task. At temperature 0 they are not independent when the diff repeats.
- The PC resource monitor was tested and adjusted during the run, adding a small unmeasured CPU load. It does not change the model's output at this level of analysis, but timings are approximate.
- The private tests for the new tasks were written with their references, and the corpus remains a development set.
