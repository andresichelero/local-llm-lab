# F3 — adversarial review of f2970ca

Date: 2026-10-28. **Verdict: REJECT the commit as the F3 gate for F4 until the four findings are fixed and checks repeated.** There are two high-severity and two medium-severity findings; none critical confirmed. The green suite does not cover the cases reproduced below.

## Scope and execution

- Worktree: `<workspace>`, branch `feat/4b-worker-f3`, HEAD `f2970caab86e541210541ffb896c9977828b17f8`; comparison `git diff a459b11 f2970ca`.
- Read: F3/F4 section of `PLANO-ESTRATEGICO-v2.md`, `execucao/F3/F3-implementacao.md`, the four changed modules and associated tests. Additional reading of local llama.cpp to check the tokenization contract.
- Read-only code review. No installation, network, GPU, inference, commit, push or merge. Proofs executed via stdin with disposable files exclusively in WSL `/tmp` and bytecode disabled. This report is the only deliverable written; the worktree remained clean.
- Results below are offline reproductions. There is no claim that they have contaminated a scientific run or that any real server was validated.

## Findings, in severity order

### 1. HIGH — Finalization interruption writes two contradictory terminal records

**Location:** `benchmark/worker_runner.py:81`, `:82` e `:176`.

`finalize()` persists the terminal record through `_record()` before assigning `self.result`. SIGALRM remains armed during this operation. If the deadline expires after persisting `accepted` but before assigning the result, `_run()`'s `except Exception` calls another finalization, now `infrastructure_error`: `self.result` is still `None`.

**Input → reproduced incorrect output:** `py_range` package, 1-second limit, valid patch from `x = 1\n` to `x = 2\n`, passing visible check and `True` oracle. Persistence delay injected: `_record` calls its real implementation and sleeps 2 seconds only after recording `accepted`. The timer interrupts finalization. The actual journal contains:

```text
prepared → generating → candidate → verifying → accepted → infrastructure_error
```

The returned `RunResult` is `infrastructure_error`, with reason `TimeoutError`, for the same `attempt_id` that already has `accepted` persisted. The delay simulates slow finalization/I/O, not a modification of evaluation callbacks. An equivalent real window exists between persistence and result assignment even without this injection.

**Impact:** the history no longer represents a machine with a single terminal record. Consumers using the acceptance event and consumers using the last terminal record produce different counts. Simply repeating `finalize()` after a completed run is idempotent, but this interrupted transition is not.

**Suggested fix:** check the deadline before the terminal commit and protect its completion from the runner's SIGALRM delivery; stop the timer as part of that transition. Define an explicit persistence error policy and prevent outer handling from writing another terminal record after one has already been persisted. Merely reversing `self.result` and `_record()` exchanges the failure for another in case of I/O and does not solve the protocol alone.

**Test gap:** `tests/test_worker_runner.py:35` calls finalization again only after complete success. Add interruption between terminal recording and assignment, requiring one terminal record and agreement between journal and result.

### 2. HIGH — Expired private-oracle deadline can end as incorrect acceptance

**Location:** `benchmark/worker_runner.py:163` to `:169`.

There is a clock check after generation and after visible verification, but not after `private_oracle()`. SIGALRM delivers `TimeoutError` only once. An evaluation wrapper that catches `Exception` can swallow this signal and return a boolean; the runner accepts that return even after the deadline has expired.

**Input → reproduced incorrect output:** same valid package/patch, `wall_seconds=1`, passing visible verification and this private callback:

```python
def private_oracle():
    try:
        time.sleep(2)
        return True
    except Exception:
        return False
```

Result observed after approximately 1,01 s:

```json
{"state":"accepted","oracle_passed":false,"reason":""}
```

The exception caught by the callback was `TimeoutError`. The outcome should record expiration without assigning a private incorrectness score to the patch. The callback need not be hostile or know the timer mechanism: a generic exception catch in a test wrapper suffices. The already documented absence of a sandbox does not explain the missing deadline check that the runner itself performs at earlier stages.

**Impact:** an evaluation expiration becomes the scientific metric of “incorrectly accepted”. In F4, which requires zero incorrect acceptances, this can directly change the hypothesis gate.

**Suggested fix:** check the clock immediately after the private callback and before interpreting/persisting its return; propagate expiration through the timeout/infrastructure path without `oracle_passed=False`. Also consider a persistent expiration flag in the handler so it does not depend on the exception passing through all callbacks.

**Test gap:** `tests/test_worker_runner.py:131` exercises blocking in the visible verifier; `:144` tests a non-boolean type. Neither exercises a private deadline caught internally. Add the scenario above and require no `accepted` terminal record.

### 3. MEDIUM — Search with overlapping occurrences is accepted as unique

**Location:** `benchmark/guarded_edit.py:468` to `:472`.

`str.count(search)` counts non-overlapping occurrences. That does not demonstrate that exactly one valid position exists for applying SEARCH.

**Concrete input:** allowed file `a.py`, correct SHA-256 and content:

```python
a = 1
a = 1
a = 1
```

Model response:

```text
FILE: a.py
<<<<<<< SEARCH
a = 1
a = 1
=======
a = 2
>>>>>>> REPLACE
```

**Incorrect output observed:** `status=applied`, with content `a = 2\na = 1\n`. The search has two possible positions, offsets 0 and 6; the second was ignored by `count()`. The contract requires `multiple_occurrences` rejection and no write.

**Impact:** the applicator silently chooses the first of two possible edits. An ambiguous response enters verification as a valid candidate, contrary to the deterministic guard required by F3.

**Suggested fix:** locate the first occurrence and search for a second starting at `primeira + 1`, including overlap. Apply only when there is no second position.

**Test gap:** `tests/test_guarded_edit.py:537` covers disjoint repetitions. Add the two-line repetition in three identical lines and verify status and original bytes.

### 4. MEDIUM — Valid AST does not guarantee compilable Python; batch writes syntax error

**Location:** `benchmark/guarded_edit.py:479`.

The batch uses only `ast.parse()`. The parser builds AST for certain statements whose context is rejected during compilation; therefore this gate does not ensure the required executable syntax.

**Input → reproduced incorrect output:** allowed file `a.py` with `value = 1\n`, correct hash, exact SEARCH for that content and replacement `value = 2\nreturn\n`. The batch returns `applied` and writes the replacement. Then:

```python
compile(target.read_text(), str(target), 'exec')
# SyntaxError: 'return' outside function (a.py, line 2)
```

**Impact:** non-compilable code passes a rejection that should happen before any write and reaches verification, potentially consuming the only repair. If visible verification imports the module, it will probably detect the failure; there is no claim that the runner will necessarily accept this code. The demonstrated defect is acceptance and writing by the applicator as syntactically valid.

**Suggested fix:** compile the candidate in memory, for example with `compile(content, str(target), 'exec', dont_inherit=True)`, without executing it, before writing. Retain the other validations and return `invalid_syntax` for the exception.

**Test gap:** `tests/test_guarded_edit.py:540` uses an open parenthesis, already rejected by `ast.parse()`. Include `return` and `break` outside the allowed context, requiring the original file to remain intact.

## Checked without additional findings

- **Private boundary:** in the default flow inspected, the builder uses task metadata, visible test, public stub and exact snippets from allowed files. Loading `corpus/oracles` or `reference.patch` into package/prefix was not confirmed. The runner calls the private callback only after visible success and does not call it in the first continuation phase. The boolean value goes to the score; private exception text is not recorded, only its type. Private stderr was not observed entering the package, repair or runner-implemented journal.
- **Limit of this evidence:** real verifier execution adapters and process isolation remain pending according to the implementation report. Test `tests/test_worker_runner.py:35` does not run a real oracle or inject private stderr; its sentinel is stored in an external list. Private-content absence tests in `tests/test_worker_contract.py:8` and `:65` compare whole texts: alone they would not detect leakage of a fragment. The conclusion above also depends on reading the flow, not those assertions alone. It does not certify stdout/stderr isolation of the future F4 executor.
- **Parser and scope:** no approximate fallback found in batch mode. Fences/prose, embedded markers and incomplete output are rejected; original output remains in the result. Allowlist, old hash, protection of existing upstream tests and `oracles` paths, external traversal and symlink components have useful checks. The exception for new tests permits repairing them in the same attempt. Overlapping ambiguity is the confirmed exception in finding 3.
- **Batch and rollback:** validation precedes writing. Tests exercise failure on the second replacement, unexpected exception and interruption immediately after rename, with restoration. No new case of partially persisted batch was found for these ordinary failures. Atomicity against process/power failure, rollback failure itself and hostile concurrent path replacement is not demonstrated and is already an explicit limitation; it was not converted into a new finding.
- **Repair and continuation in the normal path:** builder limits `repairs` to 0 or 1; flow permits at most two generations. Repair requires a nonempty visible diagnostic absent from the initial package. Public follow-up release requires acceptance by the same runner and first-phase task; premature release was not demonstrated in this path. Simple double finalization is idempotent; finding 1 covers its asynchronous interruption.
- **Infrastructure in the normal path:** client exception and unavailable syntax checker do not become model syntax rejection. No generation timeout was observed directly converted into acceptance. Finding 2 is the different case in which the timer is swallowed inside private evaluation. No causal validation of future test adapters was claimed.
- **Prefix/tokenization:** prefix compared byte by byte with the frozen host file, identified by SHA-256, checked again by the runner and sent first in a system message. Tests across tasks check identical bytes. `/apply-template` and generation receive the same messages and `enable_thinking=false`; this client's generation does not send tools, and stub evidence is part of the counted body. No static discrepancy confirmed for this textual flow.
- **Local primary check:** root `/home/foxtrot/local-llm-benchmark/tools/llama.cpp-v0.8.0-8642541b2`. In `tools/server/server-context.cpp:5997` and `:6345`, chat completions and apply-template use `oaicompat_chat_params_parse`; `:5347` tokenizes generation with `true,true`, consistent with `add_special=true, parse_special=true` at `:6372`/`:6376`. In `tools/server/server-common.cpp:1448`, `add_generation_prompt` defaults to `true`, and `:1481`/`:1491` apply kwargs and thinking disablement. This is code evidence from the local version, without a real server, GPU, cache measurement or confirmation of another deployed configuration.
- **Node:** review of the resolver and its tests found no confirmed defect; precedence of override, PATH and numeric NVM versions exercised.

## Checks performed

Main commands, with cwd in the worktree, in WSL:

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -p no:cacheprovider -q tests/test_corpus_validate.py tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py tests/test_worker_contract.py tests/test_worker_runner.py
96 passed in 20.00s

PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/worker_contract.py benchmark/worker_runner.py corpus/validate_corpus.py tests/test_guarded_edit.py tests/test_worker_contract.py tests/test_worker_runner.py tests/test_corpus_validate.py
All checks passed!

PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python corpus/validate_corpus.py
RESULT: PASS (12 tasks)
```

The validator returned `PASS bug/oracle/visible/original=(1, 0, 0, 0)` for each task. `git diff --check a459b11 f2970ca` also passed. No typecheck gate is defined for this F3, according to the plan; none was invented. Reviewers' auxiliary runs repeated overlapping subsets, so they were not added to the total of 96 tests.

The four additional proofs produced:

```text
overlap: offsets=[0, 6], status=applied, actual='a = 2\na = 1\n'
compile: status=applied, actual='value = 2\nreturn\n', SyntaxError="'return' outside function"
oracle_deadline: state=accepted, oracle_passed=false, elapsed≈1.01s, captured=TimeoutError
finalize_deadline: result=infrastructure_error/TimeoutError, journal=[prepared,generating,candidate,verifying,accepted,infrastructure_error]
```

## Verdict and reassessment gate

**REJECT entry to F4 in this state.** Fix the four demonstrated scenarios and include regressions proving: one terminal per attempt; private expiration without acceptance/incorrectness score; overlapping search rejection; non-compilable Python rejection before writing. Rerun the same tests, ruff and corpus validator. The already stated isolation and F4 integration limitations remain separate from these defects and need their own validation before inference.
## Re-review of b296ad6

Date: 2026-10-28. **New verdict: APPROVE WITH FIXES**, with the privacy test fix described below required before using this coverage as the F4 gate. The four original scenarios were fixed. No new defect in the changed production flow was confirmed; a new false negative in the private-fragment test was confirmed. This verdict refers to `b296ad6`; the rejection above remains as history for `f2970ca`.

### Scope and preservation

Reviewed `git diff f2970ca b296ad6` in the same worktree and branch, with HEAD confirmed as `b296ad6e25cd2a52f77f84958a134e90d568d7dd`. Also read the persistence policy added to the implementation report. Code and tests remained intact; no installation, network, GPU, inference, Git change or commit. Proofs ran via stdin in WSL, with disposable files only in `/tmp` and `PYTHONDONTWRITEBYTECODE=1`. This section was appended to the report without replacing its earlier content.

### 1. Rerun of the four original proofs

Same inputs, budgets and injections as the earlier review. The compilation proof observer was only adapted to accept the possibility that the original file remains intact; it no longer assumes that recompiling the persisted file must produce `SyntaxError`.

**Original proof 1 — finalization interruption:** `py_range` package, patch `x = 1\n` → `x = 2\n`, budget of 1 s, visible and private checks passed; real `_record` followed by `sleep(2)` only for `accepted`. Actual output:

```json
{"proof":"finalize_deadline","result":{"attempt_id":"5da0354e67624c31ae94fa097b889112","state":"accepted","input_tokens":10,"oracle_passed":true,"reason":""},"elapsed":2.001397736996296,"states":["prepared","generating","candidate","verifying","accepted"]}
```

**Result:** the two-terminal defect is fixed. There is exactly one `accepted`, consistent with the returned result. The return in 2,00 s for a 1 s budget is real: the implementation disarms the timer before terminal persistence. The now-documented policy allows persistence started within the deadline to finish without interruption. This does not prove a hard end-to-end time limit; persistence time must be included in F4 cost/latency measurement. It was not treated as a new occurrence of the old defect because the decision and its single terminal record started within the deadline, and the extension occurs during protected persistence.

**Original proof 2 — private oracle swallows timeout:** same patch/budget, callback with `try: sleep(2); return True` and `except Exception: return False`. Actual output:

```json
{"proof":"oracle_deadline","result":{"attempt_id":"aa35fbb3b6614d15b4800de3db0868ae","state":"infrastructure_error","input_tokens":10,"oracle_passed":null,"reason":"TimeoutError"},"elapsed":1.0073366690048715,"oracle_errors":["TimeoutError"],"states":["prepared","generating","candidate","verifying","infrastructure_error"]}
```

**Result:** fixed. The expiration flag and check after `private_oracle()` prevent acceptance and a false private score even when the callback swallows the exception.

**Original proof 3 — overlapping search:** content `a = 1\na = 1\na = 1\n`, two-line search `a = 1\na = 1\n`, replacement `a = 2\n`, correct hash and allowed file. Actual output:

```json
{"proof":"overlap","offsets":[0,6],"status":"multiple_occurrences","actual":"a = 1\na = 1\na = 1\n","original_unchanged":true}
```

**Result:** fixed. Both positions are detected and no target byte changes.

**Original proof 4 — non-compilable Python:** content `value = 1\n`, replacement `value = 2\nreturn\n`, correct hash and allowed file. Actual output:

```json
{"proof":"compile","status":"invalid_syntax","actual":"value = 1\n","persisted_compiler_error":null,"rejection_error":"'return' outside function (a.py, line 2)"}
```

**Result:** fixed. Rejection comes from `compile()` before writing. `persisted_compiler_error=null` means the preserved original file remains compilable; it does not mean the replacement passed.

### 2. New finding — MEDIUM: circular public-line list masks visible-test contamination

**File:line:** `tests/test_worker_contract.py:101`, with exclusion applied at `:106`.

The test defines `public_lines` from `package.readonly_context['visible_test']`, that is, the builder output it should audit. If an assembly bug adds a private line to this field and to Markdown, the line automatically gains public status and is excluded from comparison. The global `checked > 0` remains satisfied by other lines/tasks.

**Concrete scenario reproduced, with in-memory mutation only:** temporarily replace the `build_package` symbol used by the test module with a wrapper that calls the original builder and, only for `py_range`, uses `dataclasses.replace` to add the line below to both `readonly_context['visible_test']` and `markdown`:

```python
assert list(bottle.parse_range_header('bytes=0-0,5-99,-2', 8)) == [(0, 1), (5, 8), (6, 8)]
```

The line was read from the private oracle and **does not exist** in `corpus/tasks/py_range/visible.py`. With this contaminated output, I ran the actual functions `test_packages_exclude_nontrivial_private_oracle_lines()` and `test_all_corpus_packages_exclude_private_files()`. Both passed. As a control, the same injection only into Markdown, without contaminating the field used as the public list, made the new test fail correctly.

Actual output of the main proof:

```text
fragment: assert list(bottle.parse_range_header('bytes=0-0,5-99,-2', 8)) == [(0, 1), (5, 8), (6, 8)]
fragment_in_frozen_visible: False
new_fragment_test_with_leak_in_visible_test_and_markdown: PASS (leak undetected)
old_full_content_test_with_same_leak: PASS (leak undetected)
control_fragment_test_with_leak_in_markdown_only: FAIL as expected
```

**Impact:** this test can be green precisely when the builder publishes a private fragment inside the context it calls visible. The older whole-file checks do not compensate for this gap. This is a test false negative demonstrated by mutation, not a claim that the current builder leaks that line. The diff does not alter the production builder, and that leak was not found in the current flow.

**Suggested fix:** build the public-line list directly from the task's frozen public file (`visible.py` or `visible_phase1.py`, depending on phase), independently of the produced package. Add a negative test where the builder result contaminates `visible_test` with an oracle-exclusive line: the audit must reject that output. Excluding a genuinely public line is legitimate; the circularity lies in using the audited output as the source of that decision.

### 3. SIGALRM, persistence and regressions investigated

In addition to the four proofs, I injected failures in the stream returned by `Path.open` exclusively during journal append. The original `_record` method continued executing, including its `except OSError`; this avoids the false comfort of testing only a mock that skips the real wrapper.

| I/O proof input | Actual output | Complete terminal records persisted |
|---|---|---|
| `OSError` before writing terminal bytes | `JournalPersistenceError: terminal append failed; no retry is safe` | none |
| Half the terminal line written, followed by `OSError` | `JournalPersistenceError: journal cannot be read unambiguously` | none |
| Complete terminal line, followed by `OSError` on close | `accepted`, `oracle_passed=true` | one `accepted` |
| Terminal write sleeps 1,2 s with a 1 s budget | `accepted`, `oracle_passed=true`, actual time 1,202796875993954 s | one `accepted` |

In all four proofs, upon return or exception propagation, the signal mask was empty and the timer returned `(0.0, 0.0)`. In the three `OSError` cases, `_journal_failed=true`; in the complete-line case, recovery returned the already persisted terminal record without another append. Existing tests also verify that the inconclusive attempt cannot be finalized again with an unsafe append.

The policy distinguishes recoverable completion from inconclusive persistence: partial failure/no terminal record can raise an exception and leave zero terminals, instead of fabricating `infrastructure_error` in the same journal. The F4 executor must preserve this case as inconclusive; it must not convert it into a model error or repeat the attempt on the already modified workspace. This requirement is explicit in the implementation report and no contradiction with observed execution was found.

No other defect was confirmed in changed SIGALRM, deadline, compilation or overlap handling. The pending-signal wait is nonblocking, the expiration flag survives the callback catching the exception and the timer is disarmed during terminal persistence. The previously stated limitations remain: POSIX/main thread, I/O outside the hard wall-clock limit during finalization, trusted callbacks and absence of an OS sandbox.

**Repair leakage:** the new test emitting a fragment on stderr proves that fragment does not enter the repair prompt in this flow; it also confirms its presence in pytest-captured stderr. This does not certify stderr isolation of the future executor or absence of leakage in an external journal mixing stdout/stderr. No leak into the runner-implemented JSONL was confirmed in this re-review.

### 4. Checks performed against b296ad6

In WSL, cwd in the worktree, without bytecode or pytest cache:

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -p no:cacheprovider -q tests/test_corpus_validate.py tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py tests/test_worker_contract.py tests/test_worker_runner.py
108 passed in 24.23s

PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/worker_contract.py benchmark/worker_runner.py corpus/validate_corpus.py tests/test_guarded_edit.py tests/test_worker_contract.py tests/test_worker_runner.py tests/test_corpus_validate.py
All checks passed!

PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python corpus/validate_corpus.py
RESULT: PASS (12 tasks)
```

All 12 tasks individually returned `PASS bug/oracle/visible/original=(1, 0, 0, 0)`. The selection of 108 is the requested F3 suite, not all repository test files. `git diff --check f2970ca b296ad6` passed; worktree clean and HEAD unchanged after checks. No typecheck gate is defined by the plan. Auxiliary subset runs were not added to the 108.

### 5. New verdict

**APPROVE WITH FIXES.** The four findings from `f2970ca` are closed for the concrete scenarios rerun. Fix the public-line list source and add the negative contamination proof before considering the fragment test a satisfied gate for F4. No new production leak is confirmed and no isolation, real server, GPU or inference is approved in this review.