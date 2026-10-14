# Pristine final grading implementation plan

**Goal:** Close the reproduced bytecode false-positive and prevent candidate tests or Git state from selecting the authoritative evaluation environment.

**Base:** `fe528839a7659a0161f7e5c320cd4414b07f74ce`, branch `fix/evaluation-oracle-observability-v3`.

**Architecture:** A central `grade_workspace` entry point evaluates a safe source snapshot replayed into a fresh, trusted fixture. The direct historical grader remains explicitly available as a legacy API. Candidate-authored tests are parsed only for workflow evidence; trusted regression tests and external behavioral probes run against the replayed source, once at final evaluation. This does not establish OS/network isolation.

**Evidence:** Local read-only audits and controls in `audit-session-20261013/pristine/design-audit.md` and `controls-audit.md`. A timestamp-valid cached implementation passed while candidate source remained the TODO fixture; a missing baseline test directory also passed. Six existing reference/no-op/mutation controls are retained outside agent workspaces.

## Constraints and decisions

- Luna xhigh workers implement and validate; controller plans and orchestrates.
- No model/GPU campaign, installation, network benchmark, service/driver change, push or merge.
- Preserve prior results and evaluation protocol identities; new grades are not comparable with historical direct-workspace aggregates.
- Never read secrets, symlink/hardlink targets or arbitrary candidate additions. Validate structure before opening allowlisted content.
- Ordinary generated `__pycache__`/bytecode is excluded from replay, not automatically treated as misconduct; running visible tests normally creates caches.
- Ignore candidate Git metadata without trusting it. Record that Git metadata is not audited; do not claim comprehensive integrity from that exclusion.
- Task policies explicitly list allowed source and authored-test paths. A committed fixture fingerprint manifest detects substituted/missing baseline files. It is a provenance control, not protection against a hostile host process editing evaluator code.
- Retain independent `functional_pass`, `regression_pass`, `integrity_pass`, `scope_pass`, `workflow_pass`, with null/not-run reasons where appropriate. Lexical names never affect `functional_pass`.
- The compatibility `success` field remains a labeled aggregate across these gates. Static workflow checks do not prove authored-test quality; `test_quality` remains unmeasured.
- Keep `private_holdout=false`, `capability_evidence_eligible=false`, filesystem/network isolation unverified until the following gate is implemented.
- Keep `runtime_result_authenticated=false`: executing candidate source in the test interpreter allows result forgery or monkeypatching. `integrity_pass` covers static workspace structure and protected files only. The next gate must move assertion/result authority outside that interpreter; OS isolation alone does not close this boundary.

## Task 1 — central pristine grader (MUST / P0)

**Files:** new `benchmark/pristine_grading.py`, new committed fixture fingerprints under `benchmark/configs/grading/`, `benchmark/harness_eval.py`, focused grader tests.

**Interface:** `grade_pristine_workspace(workspace: Path, baseline: Path, task: str = "calculator_division", artifact_dir: Path | None = None) -> dict[str, Any]`. Existing `grade_workspace` delegates centrally; the former implementation is explicitly `grade_workspace_legacy` for trusted historical reproduction only.

- [x] Capture red tests for cached-bytecode false pass, candidate-test execution, absent/substituted baseline tests and unsafe paths.
- [x] Validate fixed task policy, baseline fingerprint and candidate structure before executing or reading unrelated candidate content. Reject symlinks, hardlinks and special entries; detect protected-file and mode changes.
- [x] Build a fresh fixture without candidate Git, caches, startup drop-ins or candidate tests; overlay only validated source bytes, including permitted new source files.
- [x] Execute fixture regression tests and the task probe once, using minimal environment and owned process-group cleanup. Fail closed on absent/empty tests and unsafe/failed cleanup; runtime result authority remains unverified as recorded below.
- [x] Report independent gates, static workflow metadata, explicit unknowns and a new grader protocol version. Keep aliases honest when a legacy field no longer represents candidate test execution.
- [x] Write replay manifest/source hashes and source-only patch when an evaluator artifact sink is supplied; preserve the original workspace and avoid artifact overwrite.
- [x] Verify all six reference/no-op/behavior-mutation controls plus normal cache presence, bytecode substitution, tests deleted/tampered, Git spoof, startup shadowing, modes, links and FIFO on WSL.
- [x] Review and commit source separately.

## Task 2 — active caller and provenance migration (MUST)

**Files:** `benchmark/model_quality_paired.py`, relevant result/protocol writers and focused caller tests.

- [x] Remove duplicate broad candidate-content reads in the paired pregrade path; use the shared safe inspection rather than reading secrets or unsafe links before the central grader.
- [x] Retain final-only oracle timing and visible-only routing in cascade and other callers.
- [x] Propagate `grader_protocol_version` and changed aggregate semantics in active records/protocols; do not rewrite historical rows.
- [x] Capture persistent no-model end-to-end replay evidence and demonstrate trusted tests remain unchanged while candidate tests are never imported.
- [x] Review and commit separately if the central migration can be independently accepted; otherwise one coherent source commit is acceptable.

## Task 3 — verification and next gate

- [x] Run focused red/green checks, complete project tests, full Ruff, compilation and relevant shell syntax checks. Typecheck remains unavailable unless an existing configured tool is found; do not install one.
- [x] Preserve raw logs, source SHA, replay artifacts and a derived control matrix in the external session folder; publish a metadata-only repository summary.
- [x] Update the protocol/decision record without retroactively changing the prior audit baseline.
- [x] Record existing rootless namespace feasibility for the following sandbox gate. Tool/primitive availability is not an enforced sandbox claim.

## Acceptance and stopping point

The captured source patch, not candidate bytecode/tests/Git state, determines replay behavior. All six ordinary reference controls must pass their expected dimensions; no-op and behavior mutations must fail functional checks. Unsafe structure and missing trusted tests are rejected before candidate execution. Candidate test names affect workflow only. New records identify this changed protocol. The reviewed implementation and full suite must pass before the local checkpoint.

**Revised acceptance after independent review:** this is a diagnostic replay checkpoint only. The adversarial runner-forgery proof passed all gates with a wrong implementation, so trusted result authority is an open P0. `success` cannot certify adversarial correctness. Authentication of result authority outside the candidate interpreter, OS/network isolation and true private holdout custody remain the next gate. Passing ordinary controls does not close this finding.

## Decision log

- The prior step's clean checkpoint and artifacts were rechecked before this plan; no source had changed.
- Rootless user/mount/PID/network namespaces and a private tmpfs probe are available in WSL without installation. Agent access to the host-local model endpoint from a network namespace still needs a reviewed transport; no sandbox enforcement is inferred.
- The cached-bytecode reproduction is a confirmed P0, so implementation proceeds immediately rather than extending the literature audit.
- Independent review on October 14 identified the remaining in-process result authority boundary and three provenance/retention inconsistencies. This step records that boundary explicitly and fixes the inconsistencies before acceptance; it does not establish adversarial evaluator security.

## Verified diagnostic checkpoint — 2026-10-14

Source checkpoint: `489c0d57ca5f58ca742117759f4abf99fc4b7a6a`. Independent validation on that revision passed 298 project tests and 19 subtests, Ruff, compileall, all 41 shell syntax checks, and 29 expected no-model controls. The final control run reported zero assertion failures and unchanged original Git state. Typecheck was not run because no configured existing tool was available. Raw failed staging/invocation/schema-check attempts are retained separately; their outcomes were not rewritten.

See [validation report](../../results/reports/pristine-grading-validation-20261013.md), [pristine protocol](../methodology/pristine-grading-protocol.md), and [evidence index](../../results/reports/pristine-grading-validation-evidence-index-20261014.json). The checked implementation items above mean diagnostic replay behavior only, under the revised acceptance boundary.

- [ ] **OPEN P0:** move assertion/result authority outside the candidate-controlled interpreter and authenticate results. The preserved wrong-division/runner-forgery proof still defeats current runtime grading.
- [ ] Enforce and independently validate OS/filesystem/network isolation and separate private holdout custody before capability campaigns.
