# Corpus v2 — design

The corpus has 36 tasks: 10 python_fix, 5 javascript_fix, 6 continuation, 5 mcp, 5 tool_recovery and 5 authored_tests. The 12 originals remain intact. The table covers the 24 new tasks. Bug lines count original lines changed; `1→2` replaces one line with two. In authored_tests there is no bug patch: the model writes a suite, which the oracle runs on the reference and two distinct mutants.

| ID | Class | Area | Bug lines | Cause → symptom | Visible | Oracle only |
|---|---|---|---:|---|---|---|
| py_route | python_fix | route filters | 1 | filter conversion → route parameter | positive integer | negative, zero and invalid input |
| py_template | python_fix | variable precedence | 1 | render → template result | keyword over dictionary | multiple dictionaries and escape/raw |
| py_cookie | python_fix | signed cookies | 1 | cookie reading → result by name | different name | signature, wrong and missing secret |
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
| cont_cache | continuation | HTTP cache | 2 | comparisons → file status | equal date and distinct ETag | earlier/later date, invalid and exact ETag |
| mcp_render | mcp | HTML interpolation | 2 | process_inline → template | default escape | raw interpolation and escape |
| mcp_import | mcp | object loading | 2 | load → object or expression | literal with capitals | mixed-case class name |
| mcp_groups | mcp | regular expression groups | 2 | _re_flatten → converted pattern | ordinary group | named group and escaped parentheses |
| recover_hvalue | tool_recovery | header value | 2 | normalization → returned value | preserved spaces | LF, CR and NUL controls |
| recover_httpdate | tool_recovery | HTTP date formatting | 2 | formatting → header value | epoch in GMT | following day and preserved string |
| recover_cookieformat | tool_recovery | cookie format detection | 1→2 | detection → recognition | prefix and separator | leading space and missing marker |
| tests_escape | authored_tests | HTML escaping | — | written suite → escape regressions | suite passes on reference | ampersand and quote mutants |
| tests_list | authored_tests | list normalization | — | written suite → value conversion | suite passes on reference | collection and false scalar mutants |
| tests_compare | authored_tests | string comparison | — | written suite → equality | suite passes on reference | content and length mutants |

The stubs are deterministic. They provide local external evidence. They do not measure real MCP transport. Cases of two or more lines and the two phases increase the need to investigate. Average difficulty is a hypothesis until calibration. The eight batch 1 python_fix tasks change one line in the same function as the symptom; they may saturate.

In `py_range`, the objective mentions explicit endpoints but does not describe the suffix case also tested by the oracle. This gap is a hypothesis for the observed difficulty, not a proven cause.

## Manifest and history

Prefixes and manifest were regenerated for the expanded corpus. Historical results remain valid for the 12-task corpus, with its original hashes and prefixes; they must not be mixed with new runs. `benchmark/configs/qwen-4b-prefix-cache.json` lists the 12 old IDs. T3b now selects by config IDs and rejects missing IDs, but a campaign resumed with an old manifest must retain its original snapshot. T3b prefix campaigns and the OpenCode baseline, combined, stage5, stage5-rep3 and long-tasks runners record or check corpus hashes in the output manifest. Their old configs and existing results are not converted to v2; a new run requires a new protocol and directory.

## Next step

Calibrate on GPU without escalation: Q4_K_M control, KV q4_0, 64K, cache and zero temperature; compare the recommended configuration with MTP n-max 2 and checkpoints, thinking disabled. Run two repetitions on the 24 new tasks. Retain tasks with pass rate approximately between 20% and 80%. No calibration was run in this change.

## Review fixes

The oracles verify registered route converters, the mandatory cookie separator and alternate WSGI text encoding in `decode` and `getunicode`. Authored tests include mutants for double quotes, true scalars and true equality, with automated counterexamples for partial solutions. The default validator requires the frozen distribution of 36 tasks (10/5/6/5/5/5); flexibility remains limited to explicit development mode.
