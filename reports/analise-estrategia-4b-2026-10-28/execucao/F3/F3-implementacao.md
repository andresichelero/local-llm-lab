# F3 — worker contract, applicator and runner

Date: 2026-10-28. Offline work in worktree `<workspace>`, branch `feat/4b-worker-f3`, base `a459b11`. Commit `f2970caab86e541210541ffb896c9977828b17f8`. No push, merge, GPU, real llama-server or inference. Files reserved for F1 were not modified.

## Architecture and files

- `corpus/validate_corpus.py`: Node resolution in the order `CORPUS_NODE`, PATH and numeric versions of `~/.nvm/versions/node/*/bin/node`, selecting the latest. Invalid overrides and absence produce a clear message. `--node` remains available.
- `benchmark/guarded_edit.py`: retains `apply_guarded_edit` and its old fallback; adds `apply_edit_batch` with a mandatory allowlist, expected SHA-256, exact match, validation before any write, temporary files and rollback. The per-file receipt includes relative path, hashes, unified diff and each search/replace block. Rejections are typed; the result retains the original output. Python uses AST; JavaScript uses `node --check` offline. Failure to locate/run the checker is classified as infrastructure by the runner.
- Existing upstream tests and oracles are protected. The exception for `authored_tests` tasks is an explicitly allowed test file, absent at the start of the attempt: it can be created and repaired in that attempt. This is necessary for `tests_query` and `tests_range` in the corpus.
- `benchmark/worker_contract.py`: dataclasses and closed JSON schemas for metadata and result; separate Markdown body. The builder reads `task.json` and the visible test, accepts only exact excerpts from relevant workspace files and, for tasks with a stub, adds the local stub JSON output. It does not read oracles or reference patches to build the package. The WL prefix must be the frozen file for the respective host; `prefix_id` is its SHA-256.
- `benchmark/worker_runner.py`: minimal injectable HTTP client, runner and JSONL journal. Each runner has a UUID; each record contains ID, state and, where applicable, generation number, original output or receipts. Tokenization calls `/apply-template` and `/tokenize` with `add_special=true` and `parse_special=true`, aligned with local llama.cpp v0.8.0 code; generation uses cache, zero temperature, fixed seed and thinking disabled. These interfaces were checked in local code/documentation and with a fake client, not against a running server.

## Response grammar

The patch response is the concatenation of one or more blocks, without prose or Markdown fences. Markers must occupy complete lines ending in LF:

```text
FILE: caminho/relativo
<<<<<<< SEARCH
<texto exato a localizar, inclusive suas quebras de linha>
=======
<texto substituto, inclusive suas quebras de linha>
>>>>>>> REPLACE
```

The search must occur exactly once in the state resulting from previous blocks. An empty search only creates a missing file on the allowlist; empty searches in existing files are rejected. Reserved markers inside content, fences, text outside blocks or a marker embedded in a line are rejected without silent repair. A block is a line `BLOCKED: <motivo>`, with `insufficient_context`, `conflicting_requirements` or `cannot_safely_edit`.

## States, verification and budgets

`prepared → generating → candidate → verifying → accepted | rejected | blocked | infrastructure_error`. A failed visible check can return to `generating` once, only with a nonempty diagnostic not already in the package. The private callback is called only after a passing visible check in the final phase; the boolean return is recorded as a note and does not enter the prompt. It is not called in the first continuation phase; follow-up is created only by the runner that accepted that first submission. `accepted` with `oracle_passed=false` is possible and represents incorrect visible acceptance, a metric required for F4.

Finalization is idempotent. W16 sends the package; WL first sends the system message with a prefix identical by hash, then the package. Both use `cache_prompt=true`. The default budget reserves 14.336 input tokens and 2.048 output tokens for a 16.384 window; WL requires an input budget adjusted to the window chosen in F2. The wall-clock limit is at most 300 s per package and there is at most one repair. On WSL/POSIX the timer uses `SIGALRM` on the main thread and refuses an already occupied timer.

## Verification performed

The suite includes the five previous F0 files (64 tests at that point) and new contract/runner, Node and batch tests. It covers states, blocking, malformed output, input limit, timeout, double finalization, repair with/without a new diagnostic, non-propagation of private diagnostics, token counting, prefix stability across tasks, continuation gating, exclusion of oracles and references in the 12 task packages, tool stub, edit rejections, JS syntax checking, receipts and rollback after failure and interruption immediately after rename.

Actual command, in WSL:

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -p no:cacheprovider -q tests/test_corpus_validate.py tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py tests/test_worker_contract.py tests/test_worker_runner.py
........................................................................ [ 75%]
........................                                                 [100%]
96 passed in 19.50s
```

```text
/home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/worker_contract.py benchmark/worker_runner.py corpus/validate_corpus.py tests/test_guarded_edit.py tests/test_worker_contract.py tests/test_worker_runner.py tests/test_corpus_validate.py
All checks passed!
```

The full validator also ran without `--node`, with `PYTHONDONTWRITEBYTECODE=1`; all 12 tasks returned `PASS bug/oracle/visible/original=(1, 0, 0, 0)` and output ended with `RESULT: PASS (12 tasks)`. On the first attempt at this check, the manifest detected three `.pyc` files generated by test runs; these three cache files were removed individually and the check repeated with bytecode disabled. No typecheck is configured in this project.

Independent static review by Sol 6.1 High: no actionable findings remained after prefix, token and rollback fixes; the reviewer did not run tests or a server. The rollback regression on interruption after rename was reproduced failing and then passed.

## Limitations and outstanding items for F4

- The worktree and path checks are not an operating-system sandbox. The executor must isolate the workspace and keep candidate code from accessing oracles, references, credentials or external resources. The allowlist does not protect against hostile concurrent path replacement.
- The batch validates before writing and attempts to undo failures, including interruptions; multiple `rename`s do not constitute a filesystem transaction against power/process failure or rollback failure. If rollback fails, temporary backups are preserved and the failure is propagated. Use a disposable exclusive workspace.
- The runner receives visible and private verification callbacks: their trusted implementation/orchestration and preparation of corpus workspaces for F4 episodes still need to be connected and tested end to end. Tests do not prove isolation against callbacks that violate this contract. W16 packages need useful excerpts chosen by the coordinator; the builder does not select them automatically. Stubs run locally as part of building, not as a real MCP session.
- The timer depends on POSIX/main thread and is not an OS resource limit, nor does it guarantee termination of arbitrary subprocesses started by callbacks. Counting uses the local llama.cpp contract, without confirmation by a real server at this stage.
- Before F4: complete F1/F2 and the project review gate; freeze packages and account for coordinator preparation; select WL window/budget, warm and measure cache/TTFT and VRAM; implement metric collection and adapters for verifiers and serial orchestration; validate W16/WL/AG/C with the same state/oracle; obtain explicit authorization for any inference/GPU. No actual quality, performance or cache result is claimed here.

## Post-review fixes

The adversarial review `F3-revisao-sol.md` rejected commit `f2970ca`; the earlier statement of no findings refers only to the earlier review and does not supersede that verdict. The fixes below are in commit `b296ad6` on the same branch. This section records implementation and checks without claiming that Sol has already reassessed or approved the new commit.

1. **Finalization and journal:** before persisting the terminal record, the runner blocks `SIGALRM`, disarms the timer and checks the deadline and pending signal with a nonblocking wait. An already recorded finalization is recovered from JSONL and returns a consistent result without another terminal record. The `prepared` record is also protected by timeout handling. The deadline check occurs before terminal persistence starts: if a write started before the deadline is slow, it completes without timer interruption and the result agrees with the record.
2. **Oracle timeout:** the handler retains the expiration flag even when the callback catches `TimeoutError`; after `private_oracle()` the runner checks the flag and clock before interpreting the return. Expiration ends as `infrastructure_error`/`TimeoutError`, with `oracle_passed=null`.
3. **Overlapping search:** after the first position, another is sought starting at `primeira + 1`; a second occurrence, including an overlap, results in `multiple_occurrences` without writing.
4. **Compilable Python:** the batch uses `compile(content, path, "exec", dont_inherit=True)` in memory before writing; `return` and `break` out of context return `invalid_syntax`.

**I/O error policy:** a terminal write with a complete JSONL line already present is recovered; no second terminal record is written. If writing fails without a complete terminal record or leaves a partial/malformed line, the runner raises `JournalPersistenceError`, marks the attempt as a persistence failure and does not attempt another append. In that case there is no guarantee of a durable terminal record: there may be zero complete terminal records, and the consumer must treat the journal as inconclusive and preserve it for investigation. The implementation does not promise durability against power or process failure.

**Private fragments:** tests now scan nontrivial lines from the oracles corresponding to the 12 packages and check oracle excerpts and a sentinel emitted on private stderr against the repair prompt. Some oracle lines are literally identical to assertions already published in visible tests (for example in `mcp_params`); these shared public lines are excluded from the comparison of exclusive excerpts. This does not certify isolation of future process adapters.

**RED → GREEN regressions:** before the fixes, tests reproducing the four findings exactly produced `5 failed` (overlapping search, `return`, `break`, interrupted finalization and oracle swallowing timeout). After the fixes, the same selection produced `5 passed in 4.17s`. An additional review identified and motivated tests for timeout after `prepared`, valid JSON record without LF and I/O policy before/after append; the pending-signal wait became nonblocking. These additional cases were fixed before final verification.

**Actual final checks**, in WSL with bytecode disabled:

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -p no:cacheprovider -q tests/test_corpus_validate.py tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py tests/test_worker_contract.py tests/test_worker_runner.py
........................................................................ [ 66%]
....................................                                     [100%]
108 passed in 22.07s
```

```text
/home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/worker_contract.py benchmark/worker_runner.py corpus/validate_corpus.py tests/test_guarded_edit.py tests/test_worker_contract.py tests/test_worker_runner.py tests/test_corpus_validate.py
All checks passed!
```

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -u corpus/validate_corpus.py
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

The suite above is the requested F3 suite (the previous 96 tests and the new ones), not a claim that the other repository test files were run. The isolation, callback and F4 integration limitations recorded above still apply. No GPU, real llama-server, inference, push, merge, reset, stash or rebase.

- Re-review of b296ad6: commit 1e9a81c replaces the circular list of public lines with frozen visible files and adds a negative builder contamination test (failed before and passed afterward); pytest: 109 passed in 25.54s; Ruff: All checks passed!; corpus: RESULT: PASS (12 tasks).
