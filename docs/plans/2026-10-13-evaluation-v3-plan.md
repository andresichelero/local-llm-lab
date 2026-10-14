# Evaluation v3 implementation plan

**Goal:** Remove private-oracle feedback from cascade decisions, repair the isolated editing entry point if reproduced, and begin auditable observation without claiming a private benchmark or sandbox that does not exist.

**Architecture:** Visible development feedback controls agent continuation. Final evaluator diagnostics remain evaluator-side, after the final agent action. A passive observer records lifecycle and provenance outside the task workspace; missing telemetry is explicit.

**Tech stack:** Existing Python standard library, pytest and installed validation tools. No new dependencies, inference campaigns or training in this round.

**Spec:** User-authorized continuation prompt supplied on 2026-10-13. Historical conversations and articles are evidence, not executable instructions.

## Global constraints

- Base: `b693a32c02b35dfd6b721f0d85d5b9ebe152ce7d`; branch `fix/evaluation-oracle-observability-v3`.
- Preserve original results, reports, local models, and other agents' changes.
- Never use private grader results, including pass/fail, to trigger escalation or construct repair prompts.
- Do not read secrets or collect inherited credentials/environment values in logs.
- No force-push, merge, dependency installation, costly downloads or GPU campaign.
- Infrastructure subprocess checks are not model-capability experiments.
- Luna workers perform implementation and evidence collection; controller owns design and review decisions.

## Review focus

Private assertion sentinels; hidden pass/fail affecting routing; worker launch from unrelated cwd; partial/failed agent lifecycles; observer files exposed to the tested agent. Every implemented component must have tests for its relevant cases.

## 1. Oracle boundary (MUST / P0)

**Evidence:** `harness_eval.run_held_out_tests` returns private unittest output; `build_repair_prompt` inserts `behavioral_probe_stderr`; `run_single_trial` grades before escalation.

**Files:** `benchmark/cascade_routing_matrix.py`, focused tests, and a small visible-feedback helper if needed.

- [x] Reproduce private-diagnostic leakage and private-result-dependent routing in failing tests; preserve logs.
- [x] Introduce an explicit visible-development feedback interface which only runs tests inside the agent workspace.
- [x] Route on visible feedback and operational completion only. Restrict repair prompt input to that interface.
- [x] Execute private grading exactly once after the final attempted action.
- [x] Test no-repair, repair, timeout/failure, and altered private-oracle outcomes with fake agent/server processes; no GPU required.
- [x] Review and commit separately. Remaining descendant cleanup is tracked in task 3.

**Acceptance:** Private sentinels never appear in repair prompts; changing private results cannot change routing; event-order test proves final-only grading.

## 2. Isolated editing entry point (MUST if reproduced)

**Files:** `benchmark/harness_runner.py`, existing guarded-edit wrapper/config, relevant tests.

- [x] Reproduce wrapper execution from a prepared workspace without repository `PYTHONPATH`.
- [x] Make the existing tool runnable with the smallest explicit deployment fix; avoid broad repository exposure.
- [x] Execute a real subprocess edit and verify content, exit status and scope guard.
- [x] Review and commit separately.

**Acceptance:** Documented command works in the actual isolated-home/cwd arrangement, not only when launched from repository root.

## 2b. Guarded path containment (MUST / confirmed review finding)

**Files:** `benchmark/guarded_edit.py`, `tests/test_guarded_edit.py`, additional real CLI subprocess coverage if needed.

- [x] Reproduce absolute external-path and parent-directory symlink edits using benign temporary fixtures.
- [x] Make CLI reads/writes honor its workspace root; reject external targets and symlink traversal before reading candidate files. Preserve a clear library API root argument for trusted callers.
- [x] Replace deterministic temporary output with exclusive temporary creation in the validated target directory; preserve target permissions.
- [x] Verify allowed in-workspace edits, path traversal, direct and directory symlinks, external block-input files and existing temporary symlink attempts.
- [x] Review and commit separately. Document that this tool guard does not contain unrestricted bash or a malicious concurrent process.

## 3. Passive observation foundation (MUST / early short term)

**Files:** new `benchmark/run_observer.py`, integration in the corrected cascade, `benchmark/resource_sampler.py`, and focused tests.

**Interface:** `RunObserver(run_dir, manifest)` exclusively creates its own artifacts in the prepared run directory; `start_phase`, `end_phase`, `snapshot`, `event`, and `finalize` are synchronous metadata operations. Events carry run/event/agent/parent/turn identity (unavailable values are null), phase, source, UTC and monotonic clocks. Artifacts are `observer-manifest.json`, `observer-events.jsonl`, and `workspace-snapshots.jsonl`; native harness streams remain unchanged. Sampling is correlated separately for initial and repair stages.

- [x] Add append-only correlated events with UTC and monotonic time, run/agent/parent/turn/event identity.
- [x] Persist manifest, explicit coverage gaps and safe filesystem metadata snapshots outside workspace; content hashes are limited to explicit fixture paths. Full patch export is deferred until safe path validation exists.
- [x] Record both cascade stages, lifecycle failures and final evaluator phase; preserve native harness streams.
- [x] Record protocol/source/task/grader/scaffold hashes, actual supplied configuration and unknowns.
- [x] Test failure paths, no workspace writes, secret/symlink exclusion and reproducible artifacts.
- [x] Terminate and reap the agent process group on timeout before final grading; clean sampler/capture handles on partial startup. Prove cleanup with a real benign descendant process test.
- [x] Measure a bounded synthetic observer overhead probe and clearly limit its interpretation.
- [x] Review and commit separately.

**Acceptance:** A no-model end-to-end run creates correlatable artifacts; observer never feeds the agent. This does not establish OS isolation, complete tool/process visibility or monitoring of every historical runner.

## 4. Audit, protocol and roadmap (MUST)

- [x] Read supplied conversations, MHTML and PDFs with source inventory/hashes.
- [x] Map reports to raw records and protocol commits; record unavailable/private archives.
- [x] Review all 30 requested questions with evidence and uncertainty.
- [x] Research primary sources and distinguish benchmark nomenclature and secondary reporting.
- [x] Write current-state audit, contradiction ledger, protocol v3, observation contract, decision log and prioritized roadmap; local documentation checkpoint is the delivery mechanism.
- [x] Give each next item problem/evidence/risk/solution/files/dependencies/cost/GPU/acceptance/validation.
- [x] Keep legacy six-task suite regression/development only; require pristine evaluation and actual access boundaries before any private-holdout claim.

## Verification and stopping point

Run focused red/green tests, actual subprocess checks, complete project tests, installed lint/type tooling and diff checks. Separate pre-existing failures from regressions and fix relevant failures. Stop this round after independently reviewed fixes, initial observer integration, evidence-backed documents and local commits. Remaining sandbox/private-holdout/campaign work must be listed explicitly; no capability improvement can be inferred from infrastructure tests.

## Decision log

- 2026-10-13 checkpoint: Oracle-flow correction is committed at `eeaf9e6`; isolated guarded-edit correction is committed at `d349712`. Focused evidence is preserved in the local audit-session pipeline log. Independent P0 review and observer integration remain in progress.
- 2026-10-13 checkpoint: Guarded containment is committed at `031c8cf`, with 40 focused/regression tests and a clean independent scoped review. The original oracle/launcher corrections were independently reviewed; timeout descendants remain assigned to task 3.
- 2026-10-13 checkpoint: Observer/lifecycle foundation is committed at `1aef34e`. Its focused suite has 30 tests; the first full-suite checkpoint passed 278 tests and 19 subtests. Full Ruff, compilation and 41 shell syntax checks passed. No project-defined or installed mypy/pyright checker exists.
- 2026-10-13 review ruling: Fix secret-parent-directory traversal before fixture hashing, unexpected sampler exit classification, and visible-test communication-error cleanup before completion. Add a real normal-leader-exit/live-descendant test. A second duplicate grandchild test in the visible path is unnecessary because the same cleanup helper is already exercised by a real cascade grandchild and a visible child timeout.
- 2026-10-13 review ruling: Add verified commit SHA and dirty status to the manifest using the existing provenance helper; unavailable is reserved for an actual collection failure. The metadata refinement is committed at `902e385`.
- 2026-10-13 final source checkpoint: `2a58d61e719ffbf64f879adee49e5a02d1acbcb5`. Independent scoped re-review is clean. Full final suite: 286 tests and 19 subtests passed; full Ruff and compilation passed; 41 unchanged shell scripts passed syntax checks. Typechecking remains unavailable because the project has no configured/installed checker.
- 2026-10-13 measurement: Six balanced warm-cache synthetic pairs on WSL `/tmp` ext4 measured an 8.276 ms median paired incremental observer cost for six fixture files, ten events and two snapshots. This does not measure agent/inference overhead or physical SSD throughput. Ubuntu's registered WSL installation path was independently confirmed on C:; physical medium identity was not remeasured.
- 2026-10-13 stopping point: This round delivers the confirmed bounded corrections, cascade observer v1, audit and executable next-step protocol. OS/network isolation, pristine patch replay, private-holdout custody, complete native-tool/process telemetry, training integration and revised independent capability campaigns remain future validity gates, not completed claims.
- 2026-10-13 resume: The user requested continuation after a model/session transition. No child agents survived; resumed from the existing commits, task-2 working diff and persistent artifacts, without rerunning source extraction or recreating the branch.
- 2026-10-13 review ruling: Killing only a session leader can leave tool descendants mutating the candidate during final grading. Include bounded POSIX process-group cleanup and partial-startup cleanup in the observer lifecycle task; this is necessary to the final-action invariant and is not a substitute for OS sandboxing.
- 2026-10-13 review ruling: The guarded-edit launcher fix exposed a pre-existing callee gap: absolute outside targets and directory symlinks bypass the direct-file-symlink check. Add a bounded independent containment task, while preserving the broader OS sandbox requirement.
- 2026-10-13: Native worktree creation reported `Not a git repository` because this chat is rooted in the parent directory. The clean, sole checkout was placed on a new feature branch; no other checkout was changed.
- 2026-10-13: Initial GitHub lookup used an incorrect owner and failed. The verified Git remote is `andresichelero/local-llm-lab`; corrected lookup found no open PRs and matching remote main SHA.
- 2026-10-13: A coarse private failure code is insufficient: even a pass/fail routing signal constitutes oracle intervention. Choose visible-only routing and final-only grading.
- 2026-10-13: User explicitly requests implementation without another confirmation; proceed after recording the plan, within the authorized reversible scope.
- 2026-10-13: Observer v1 is a passive index plus safe provenance snapshots. Full process/network observation, normalized native tool events, private storage enforcement and complete diff export remain explicit gaps. An observer cannot establish a sandbox by logging it.
