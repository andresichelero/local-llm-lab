# Frozen offline pilot corpus

This corpus is for pilot development, not a held-out confirmation set. All
episodes for a task must begin from the same snapshot with its `bug.patch`
applied. The `reference.patch`, `bug.patch`, `oracles/`, `manifest.json`,
`reference_phase1.patch`, `validate_corpus.py` and supervisor fixture builder must never be given to a
worker. A coordinator may provide the task metadata, the relevant stub, the
visible check and the prepared host workspace. For continuation, give only
`task.json`, `verify_phase1.py` and `visible_phase1.py` at first; release
`followup.json`, `verify.py` and `visible.py` only after the first delivery.
The runner for F3 must enforce
that boundary; merely storing files separately does not enforce isolation.

Bottle 0.13.2: <https://github.com/bottlepy/bottle>, tag `0.13.2`, commit
`ab49e0c22491f8acfcb02e4a7b8c648843268233`, MIT. The SHA-256 of the
uncompressed `git archive --format=tar HEAD` is
`6cb77dbe442edec538ebc9af0b4cb3d9c22fb3b8e262d4ecfb0e064a2e28ea44`.
The production source `bottle.py` has 180,178 Unicode characters (UTF-8
decoded), or 51,479 estimated tokens at characters/3.5. This is not a model
token count, and excludes tests and documentation. The two production sources
together have 183,202 characters, about 52,343 tokens by the same estimate.

Never use the unmodified snapshot as the cached worker prefix: it contains the
reference lines. `prefixes/` contains stable versions with every original line
removed by a bug patch replaced by a marker. The manifest covers these files,
and validation regenerates and compares them. The coordinator provides the
buggy task-specific source separately. This reduces direct answer leakage,
but does not guarantee that neighboring code or upstream tests cannot reveal
the behavior. The small JavaScript host alone does not meet the large-prefix
size; its tasks need an explicitly designed context comparison in F4.

ms 2.1.3: <https://github.com/vercel/ms>, tag `2.1.3`, commit
`1c6264b795492e8fdecbc82cb8802fcfbfc08d26`, MIT. The SHA-256 of the
uncompressed `git archive --format=tar HEAD` is
`8320d0029c9cd17cb89f5f5d2509a14373d3e2efc6f4824907237f63475d882b`.
The upstream tests use Mocha and expect.js. `support/ms_original.test.cjs`
runs the original test file unchanged with `node:test` and a minimal adapter
for its three assertion forms; this is an adaptation, not Mocha execution.

The `mcp` and `tool_recovery` tasks use deterministic local stub outputs as
external evidence needed to repair Bottle, rather than claiming to exercise
an MCP transport or a real remote service. They do not measure protocol-level
discovery, call traces, idempotency or retries. The validator runs each stub
twice and checks its sample against both the buggy and corrected code.
Continuation tasks provide separate phase-one and follow-up material; a future
runner must actually sequence them.
For newer continuation tasks, the validator also checks that phase one fails
initially, applies the private `reference_phase1.patch`, checks the follow-up
oracle fails, and confirms the final reference still satisfies phase one.

Run from the repository root with the approved validation environment:

```sh
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python \
  corpus/validate_corpus.py --node /home/foxtrot/.nvm/versions/node/v25.5.0/bin/node
```

The validator checks the manifest, applies patches to disposable copies and
requires an assertion failure for the bug, success for the reference, visible
check and upstream tests. The authored-test private oracles additionally run
the reference suite against the correct code and two distinct mutants.
`--task ID` selects one task while retaining the complete manifest check.
Before freezing a changed corpus, `--task ID --skip-manifest-for-development`
validates one task without checking the manifest or generated prefixes. This
development-only option does not establish corpus integrity.
`--write-manifest` is for deliberate corpus freezing, never routine checks.

## Corpus v2

The corpus has 36 tasks: 10 python_fix, 5 javascript_fix, 6 continuation, 5 mcp, 5 tool_recovery and 5 authored_tests. The original 12 remain intact. The table covers the 24 new tasks. Bug lines count changed original lines; `1→2` replaces one line with two. In authored_tests there is no bug patch: the model writes a suite, which the oracle runs against the reference and two distinct mutants.

| ID | Class | Area | Bug lines | Cause → symptom | Visible | Oracle only |
|---|---|---|---:|---|---|---|
| py_route | python_fix | route filters | 1 | filter conversion → route parameter | positive integer | negative, zero and invalid input |
| py_template | python_fix | variable precedence | 1 | render → template result | keyword over dictionary | multiple dictionaries and escape/raw |
| py_cookie | python_fix | signed cookies | 1 | cookie reading → result by name | different name | signature, wrong secret and missing value |
| py_config | python_fix | ConfigDict | 1 | namespace loading → created keys | simple nested key | prefix and multiple branches |
| py_multi | python_fix | MultiDict | 1 | indexed lookup → returned value | first value | missing index, conversion and default |
| py_headers | python_fix | HeaderDict | 1 | lookup normalization → returned header | lowercase name | mixed case, index and default |
| py_auth | python_fix | Basic auth | 1 | credential splitting → password | password with colon | empty password, invalid input and scheme |
| py_urlbuild | python_fix | URL construction | 1 | assembly → URL and query | value and space | conversion, parameters and positional route |
| js_units | javascript_fix | units and formatting | 4 | constants and limits → ms API | year | weeks, decimals and long/short limits |
| js_decimal | javascript_fix | decimal parsing | 2 | parser → ms API | positive decimal | negative, spaces and implicit unit |
| js_invalid | javascript_fix | invalid inputs | 2 | dispatch → return/error | infinity and spaces | other types, NaN and valid inputs |
| cont_forms | continuation | FormsDict and encoding | 2 | _fix → getunicode/decode | accented character and decode | multiple values, fallback and latin1 |
| cont_redirect | continuation | redirection | 2 | status and URL → response | relative in HTTP/1.1 | HTTP/1.0, absolute and explicit status |
| cont_plugins | continuation | plugin precedence | 2 | all_plugins → route callback | precedence and exclusion by type | exclusion by name, global and all |
| cont_cache | continuation | HTTP cache | 2 | comparisons → file status | equal date and different ETag | earlier/later date, invalid date and exact ETag |
| mcp_render | mcp | HTML interpolation | 2 | process_inline → template | default escape | raw interpolation and escape |
| mcp_import | mcp | object loading | 2 | load → object or expression | uppercase literal | class with mixed-case name |
| mcp_groups | mcp | regular expression groups | 2 | _re_flatten → converted pattern | ordinary group | named group and escaped parentheses |
| recover_hvalue | tool_recovery | header value | 2 | normalization → returned value | preserved spaces | LF, CR and NUL controls |
| recover_httpdate | tool_recovery | HTTP date formatting | 2 | formatting → header value | epoch in GMT | next day and preserved string |
| recover_cookieformat | tool_recovery | cookie format detection | 1→2 | detection → recognition | prefix and separator | leading space and missing marker |
| tests_escape | authored_tests | HTML escape | — | written suite → escape regressions | suite passes on reference | ampersand and quote mutants |
| tests_list | authored_tests | list normalization | — | written suite → value conversion | suite passes on reference | collection and false scalar mutants |
| tests_compare | authored_tests | string comparison | — | written suite → equality | suite passes on reference | content and length mutants |

The stubs are deterministic. They provide local external evidence. They do not measure real MCP transport. Cases with two or more lines and the two phases increase the need for investigation. Medium difficulty is a hypothesis until calibration. The eight python_fix tasks in batch 1 change one line in the same function as the symptom; they may saturate.

In `py_range`, the objective mentions explicit endpoints but does not describe the suffix case that the oracle also tests. This gap is a hypothesis for the observed difficulty, not a proven cause.

## Manifest and history

The prefixes and manifest were regenerated for the expanded corpus. Historical results remain valid for the 12-task corpus, with their original hashes and prefixes; they must not be mixed with new runs. `benchmark/configs/qwen-4b-prefix-cache.json` lists the 12 old IDs. T3b now selects by config IDs and rejects missing IDs, but a campaign resumed with an old manifest must retain its original snapshot. The T3b prefix campaigns and OpenCode baseline, combined, stage5, stage5-rep3 and long-tasks runners record or check corpus hashes in the output manifest. Their old configs and existing results are not converted to v2; a new run requires a new protocol and directory.

## Next step

Calibrate on the GPU, without escalation: Q4_K_M control, KV q4_0, 64K, cache and zero temperature; compare the recommended configuration with MTP n-max 2 and checkpoints, thinking off. Run two repetitions on the 24 new tasks. Keep tasks with a pass rate of approximately 20% to 80%. No calibration was performed in this change.
