# PR 45 review fixes

## Changes

- The proxy emits only `text/event-stream` or `application/json`.
- The baseline runs the visible test and oracle in separate bubblewrap sandboxes without network access. The workspace is writable; scripts and oracle are read-only. HOME and temporary files are isolated. Without bubblewrap, the result is infrastructure failure. T2 uses the same evaluator.
- In T3b, Landlock grants the visible test only copies of the necessary scripts. The oracle has its own private copy. The workspace and a dedicated temporary directory are writable; the journal is protected.
- Import and syntax errors from the workspace during collection are model failures. Evaluator unavailability remains infrastructure. A confirmed visible rejection is not erased by a subsequent oracle failure.
- The worker wall-clock budget has its own reason. A timeout does not overwrite an already identified server failure. The follow-up receives the remaining first-phase repair budget.
- The v3 aggregate contains a summary, manifest and 36 units. VRAM labels and documentation counts were corrected.

## Revalidation without GPU

Raw data were only read. Workspaces were copied to temporary directories before evaluation. There was no inference. Per-evaluation evidence is in [pr45-regrade.jsonl](../../../../results/3070-benchmark/pr45-regrade.jsonl).

**425 workspaces** were reevaluated in **453 private evaluations**: 170 stage 4 attempts, 103 stage 5 attempts, 36 applicable private objectives from the 8 T2 workspaces, 108 T3b v2 units and 36 T3b v3 units. No new evaluation returned infrastructure failure. Available private scores for stage 4 (170), stage 5 (103) and T2 (36) matched those published. In T2, phases without a private oracle and objectives not started were not compared.

In T3b, 9 of 102 comparable scores in v2 and 5 of 35 in v3 changed from fail to pass. The other 7 units had no comparable private score. The 14 discrepancies have a historical Node/OpenSSL error in the oracle. All submissions ended rejected; the regrade does not reconstruct the interaction that would have occurred with a healthy verifier.

The historical oracle recorded a JavaScript infrastructure error in 18 v2 units and 6 v3 units. Four were `P-W16/js_sign`: three v2 repetitions and one v3 repetition. They were rejected because no new visible diagnostic followed the environmental error, with no proven model failure. Excluding that task, P-W16's task rate changes from **2/12 to 2/11**, in both v2 and v3. README and RESULTS present this correction alongside historical counts. The other 20 units with this error also recorded edit or output rejection. Even so, the environmental error may have influenced repairs; the counterfactual result cannot be reconstructed.

The last preserved visible diagnostics contained an OpenSSL error in 12 v2 and 6 v3 units. In 14 of them, the only verification event was followed by new generation: the diagnostic was returned to the model. In the other four, there was more than one verification and the journal does not retain the intermediate text. It is impossible to prove which text was returned. The T3b quality comparison remains inconclusive.

### Other review points

- **Import and collection:** zero units classified as infrastructure with candidate import or syntax errors in the artifacts searched. The search covered preserved logs and journals; it cannot prove events that were not recorded.
- **Oracle or patch leakage:** zero matches for private paths or exact fragments of at least 30 characters in preserved visible diagnostics: 199 records from stage 4, 119 from stage 5, 44 from T2, 48 from v2 and 18 from v3. Smaller or paraphrased fragments were not ruled out. Not all intermediate T3b diagnostics were preserved.
- **Wall-clock budget:** zero `wall_budget` records classified as infrastructure in the T3b v2/v3 journals and outputs searched.
- **Code 124 and server:** 11 attempts from stages 4 and 5 ended in timeout and recorded `ConnectionResetError` on the last request. Literal application of the new priority would classify four final stage 4 results, five final stage 5 results and two intermediate cascade attempts as infrastructure. There is no per-request timestamp to determine whether the reset preceded timeout or resulted from cancellation. No HTTP 500, `server_exited` or connection refused was found in these logs. Tables retain historical classifications, with this caveat.

## Code verification

Tests cover mounts, missing bubblewrap, real isolation, import and syntax errors, evaluator failure, journal protection, repair budget and failure priority. Ruff passed on the changed Python files. The project defines no typecheck command; no typechecker was available on PATH. The full suite passed: **326 tests and 47 subtests**, with the requested Python, `PYTHONDONTWRITEBYTECODE=1` and `pytest -p no:cacheprovider`.

**Restriction deviation:** the suite includes two parametrized cases that start real OpenCode with `debug config`. They were run by mistake during the suite, despite the prohibition on starting real OpenCode. There was no real server execution, inference or GPU use in these cases. A new run excluding those two cases passed with **324 tests and 47 subtests**, with 2 cases deselected.
