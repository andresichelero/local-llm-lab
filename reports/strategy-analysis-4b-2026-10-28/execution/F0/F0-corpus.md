# F0 — pilot corpus

Status: **12 tasks implemented and validated offline**, without inference, GPU or llama-server. Branch `feat/4b-worker-v2`. Commits: `ce7d44a` (preliminary Ruff), `c6c8ff6` (snapshots) and `a459b11` (corpus, validator and preservation of the bytes of a snapshot file).

## Hosts and provenance

- **Bottle 0.13.2**, MIT, https://github.com/bottlepy/bottle, tag `0.13.2`, commit `ab49e0c22491f8acfcb02e4a7b8c648843268233`. It is a real single-module framework, with its own tests runnable without native dependencies. SHA-256 of the uncompressed file produced by `git archive --format=tar HEAD`: `6cb77dbe442edec538ebc9af0b4cb3d9c22fb3b8e262d4ecfb0e064a2e28ea44`. Its `LICENSE` and tests are in the snapshot. The original tests in the initial snapshot produced **355 passed**.
- **ms 2.1.3**, MIT, https://github.com/vercel/ms, tag `2.1.3`, commit `1c6264b795492e8fdecbc82cb8802fcfbfc08d26`. It has no runtime dependencies and hosts the two JavaScript tasks. SHA-256 of `git archive --format=tar HEAD`: `8320d0029c9cd17cb89f5f5d2509a14373d3e2efc6f4824907237f63475d882b`. The original tests run by the `node:test` adapter, without changing the upstream test file, produced **49 passed**. The adapter replaces the three assertion forms used by those tests; it is not a run of the original Mocha.
- Production code estimate: `bottle.py` has **180.178 Unicode characters** and `index.js` has **3.024**, totaling **183.202 / 3.5 = 52.343 estimated tokens**. Method: UTF-8 reading, character count, excluding tests/documentation; this is not model tokenization. Bottle alone: approximately 51,479 tokens. The Bottle prefix with reference lines hidden has 179.962 characters, approximately 51,418 tokens.
- Git metadata from the clones and generated tar files were preserved locally in `corpus/provenance/`, ignored by Git; tracked snapshots do not contain `.git`. The manifest records SHA-256 for each file in the snapshots, tasks, oracles, stubs, support and prefixes. The 325 corpus files in the index were compared byte by byte with the worktree using Git object hashes, without differences.

## Tasks

The difficulty below is an estimate, not a model measurement. The two authored-test oracles run the reference tests on correct Bottle and two distinct mutants. MCP/recovery tasks use deterministic local stubs and edit Bottle; they do not simulate the complete MCP protocol.

| ID | Class | Editable file | Difficulty | What it discriminates |
|---|---|---|---|---|
| py_range | python_fix | bottle.py | medium | inclusive end, boundaries and invalid ranges |
| py_query | python_fix | bottle.py | medium | spaces, escapes and repetition in query strings |
| js_sign | javascript_fix | index.js | medium | negative durations, fractions and units |
| js_plural | javascript_fix | index.js | medium | plural threshold and negative numbers |
| tests_query | authored_tests | test/test_tests_query.py | medium | detects decoding and order mutants |
| tests_range | authored_tests | test/test_tests_range.py | medium | detects boundary and suffix mutants |
| cont_quote | continuation | bottle.py | medium | HTML character and control escaping after follow-up |
| cont_path | continuation | bottle.py | medium | shifts in both directions and trailing slash |
| mcp_header | mcp | bottle.py | medium | stub output and header name normalization |
| mcp_params | mcp | bottle.py | medium | stub output and parameter normalization |
| recover_date | tool_recovery | bottle.py | medium | stub diagnosis and time zone conversion |
| recover_decode | tool_recovery | bottle.py | medium | stub diagnosis and Unicode error policy |

## Actual validation

The validator ran twice, sequentially, with `python -u corpus/validate_corpus.py --node /home/foxtrot/.nvm/versions/node/v25.5.0/bin/node`, with `PYTHONDONTWRITEBYTECODE=1` and Python `/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python`. The two outputs were compared with `cmp` and were identical. Each tuple represents bug/oracle, reference/oracle, visible test and original tests respectively: the bug must fail by assertion (1) and the others must pass (0). The validator also checks the manifest, write scope, prefixes, two runs of each stub, stub samples on the bug and solution, and the two mutants per authored task.

```text
cont_path: PASS bug/oracle/visible/original=(1, 0, 0, 0)
cont_quote: PASS bug/oracle/visible/original=(1, 0, 0, 0)
js_plural: PASS bug/oracle/visible/original=(1, 0, 0, 0)
js_sign: PASS bug/oracle/visible/original=(1, 0, 0, 0)
mcp_header: PASS bug/oracle/visible/original=(1, 0, 0, 0)
mcp_params: PASS bug/oracle/visible/original=(1, 0, 0, 0)
py_query: PASS bug/oracle/visible/original=(1, 0, 0, 0)
py_range: PASS bug/oracle/visible/original=(1, 0, 0, 0)
recover_date: PASS bug/oracle/visible/original=(1, 0, 0, 0)
recover_decode: PASS bug/oracle/visible/original=(1, 0, 0, 0)
tests_query: PASS bug/oracle/visible/original=(1, 0, 0, 0)
tests_range: PASS bug/oracle/visible/original=(1, 0, 0, 0)
RESULT: PASS (12 tasks)
```

`DETERMINISM: identical output in both runs`

- Focused pytest: `tests/test_corpus_validate.py`, `tests/test_guarded_edit.py`, `tests/test_qwen_engines.py`, `tests/test_qwen_workloads.py` and `tests/test_prefix_cache_paired.py`: **64 passed in 13.35s**. In the separate preliminary stage, the four indicated existing tests produced **43 passed in 9.74s**.
- Ruff 0.17.3: `All checks passed!` on the modules fixed in the preliminary stage and, separately, on `corpus/validate_corpus.py`, `corpus/oracles`, `corpus/tasks`, `corpus/stubs`, `corpus/support/*.py` and `tests/test_corpus_validate.py`. Vendored upstream code was not reformatted.
- No typecheck is configured for this project, according to the F3 plan; no typecheck result is claimed.

## Risks and outstanding items for later phases

- Reference changes are small and some tasks may be easy or saturated; difficulty was not calibrated with inference. Some tasks share functions or concepts. The corpus is a pilot and not an independent confirmation.
- The Bottle prefix hides the modified original lines, but neighboring code and upstream tests may still reveal behavior. The intact snapshot, bug/reference patches, generator and oracles must not be delivered to the worker. File separation alone does not enforce this isolation: the F3 runner must enforce and test it.
- Continuation phases have separate materials, but the initial state already satisfies the first-phase test; the runner must release the follow-up only after the first submission. No real sequence with a model was evaluated.
- Stubs demonstrate deterministic execution and consistency of examples, but do not measure discovery, call history, retries or idempotence of a real MCP server.
- The small JavaScript host prefix alone has fewer than 40 thousand tokens; the WL comparison for these two tasks requires an explicit context decision. Selecting one task per class for F1 and running GPU phases remain outside this delivery and require the corresponding planning/authorization.
