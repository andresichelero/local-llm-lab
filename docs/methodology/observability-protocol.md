# Evaluation observability protocol

**Status:** Observer v1 is integrated for the cascade runner at source checkpoint `2a58d61e719ffbf64f879adee49e5a02d1acbcb5`. The full suite, quality checks, focused safety subset, post-commit synthetic E2E, bounded overhead probe, and scoped final review are recorded in the evidence index. Passive observation remains a MUST early in the implementation sequence, after validity-blocking P0s and before a new capability campaign. Scope is the cascade runner only; this is not total observability.

The supporting source and artifact metadata is in the [portable evidence index](../../results/reports/evaluation-v3-evidence-index-20261013.json). The index contains hashes and references only, not source text or run-log contents.

## Purpose and limits

The observer records what ran and what evidence was collected without deciding whether an agent should continue, escalating a model, or changing a score. Visible development feedback may guide repair through the harness's explicit interface. The private/final grader runs exactly once, after the last agent action. Its diagnostics and hidden-test output never enter the repair prompt or observer records.

Keep benchmark outcome separate from evidence completeness. A pass with missing telemetry remains a pass with incomplete evidence; an observer failure after launch must preserve native output and the grader result. A missing terminal event means the record is interrupted or incomplete.

## Run artifacts and identity

Cascade creates a new run directory and never deletes or reuses one. RunObserver attaches to that existing directory and exclusively creates:

- observer-manifest.json: immutable run and provenance manifest, written before agent launch.
- observer-events.jsonl: append-only lifecycle and phase events, flushed as emitted.
- workspace-snapshots.jsonl: safe before/after workspace metadata and allowlisted fixture hashes.

The existing events.jsonl and stderr.log remain raw native harness captures. The observer does not parse or normalize them and does not claim complete tool-call coverage. Existing resources.jsonl gains correlated sampler fields.

Every event includes event_id, run_id, event_seq, phase_id, agent_id, parent_agent_id, turn_id, source, UTC wall time, and monotonic_ns. Identity fields are present even when their values are null. Use stable initial/repair agent IDs; leave parent or turn IDs null when the harness does not provide them. Event and phase types and detail keys are fixed allowlists; details are bounded scalar metadata, never prompts, replies, command lines, environment values, test output, or grader diagnostics.

The first-version phase sequence is setup, initial agent, visible development feedback, optional model transition, optional repair agent, final grading, and finalization. Mark skipped repair explicitly. Resource coverage is limited to initial-agent and repair-agent phases. Model transitions and grading are uncovered in v1.

Observer-owned files are outside the task workspace and are not passed through agent arguments or environment variables. Their location alone does not prove they are unreadable: with a same-user, non-sandboxed process, parent-directory traversal may remain possible. Unless an execution boundary blocks and tests that access, record observer-file isolation as unavailable.

## Provenance and versioning

The manifest records schema and protocol IDs; harness/source revision; task, fixture, grader, and scaffold identifiers; declared model/runtime/configuration; hardware identity when available; path hashes; and explicit unknowns. Hash only sorted, explicit allowlists with streaming SHA-256, recording relative path, size, digest, and category. Keep source, task/fixture, grader/held-out, scaffold/profile, and declared configuration distinct. Never recursively hash the repository or workspace, and never read a path merely because it appears in a snapshot.

Record whether each value is verified from the actual run, declared by configuration, or unavailable. Do not treat defaults as effective runtime settings. Model identity, artifact checksum, quantization, runtime/build, tokenizer or prompt template, context limit, decoding parameters, seed, tool permissions, and model endpoint are recorded only when actually supplied or verified. Do not load a large model solely to calculate its hash; mark its digest unavailable unless a known artifact can be hashed practically and safely. Do not serialize secrets or inherited environment variables.

Increment protocol_id whenever a result-affecting input or method changes: task/grader revision, prompt, scaffold or edit interface, model/runtime or effective generation settings, tool permissions, budget, network policy, snapshot/hash allowlist, or scoring rule. Keep each manifest and raw evidence immutable. A correction creates a new protocol/run record; it does not rewrite prior evidence. Preserve the source revision and manifest digest with any derived summary.

## Inference, training exposure, and task statistics

For inference, record the actual model/runtime and generation configuration, agent/scaffold version, tool interface and permissions, limits, hardware, concurrency, and the task-level outcome. Separate declared settings from verified effective settings. Missing fields remain explicitly unavailable.

For training exposure, record the task source and version, publication/release date when known, whether the task or solution is public, and the basis for any claimed private or held-out status. For the model, record provider disclosures of pretraining cutoff and any known fine-tuning or reinforcement-learning data, marking them declared or unavailable rather than verified by the local observer. Model training exposure is generally not observable from a local run. Public benchmark status, network denial, or a withheld task split does not prove that model weights never saw the content. Do not call a task training-unseen without independent evidence. Keep development/tuning tasks separate from confirmatory tasks and report task-level outcomes; repeated runs of one task are not independent tasks.

## Process, network, filesystem, and hardware coverage

| Dimension | v1 evidence | Explicit gap |
|---|---|---|
| Process | Agent phase lifecycle, raw native streams, and timeout cleanup in the runner | No process-tree telemetry, per-process CPU/memory, child-process inventory, command-line capture, or proof that a process was absent |
| Network | None | No connection/DNS/egress telemetry and no proof of network denial; policy settings are not observed traffic |
| Filesystem | Before/after workspace metadata via scandir and lstat; explicit original-fixture hashes only for regular non-symlink files | No general content diff; same-size/same-time edits outside the hash allowlist may be missed; snapshots do not establish OS isolation |
| Sandbox boundary | None | No demonstrated OS/container boundary, mount restriction, or adversarial filesystem-access test; observer-file location alone does not prove isolation |
| Private holdout | None verified | No separately controlled task/test custody or access boundary is established by observer v1 |
| Hardware/resources | System-wide CPU, memory, and available NVIDIA samples during initial and repair agent phases | No per-agent attribution; no samples during model transition or grading; missing readings need explicit reasons |
| Verifier | Final-grader identity/revision hash and one final outcome | No hidden diagnostics or tests in the observer; observer does not prove verifier isolation |

Filesystem snapshots never follow symlinks or recurse through symlink directories. They exclude .git, configured metadata directories, and secret-named files/directories before opening or descending, including .env variants, credential/token/secret names, and key/certificate suffixes. Emit no symlink target. Hash only the explicit original task-fixture file allowlist after lstat confirms ordinary regular files. Record other nonsecret entries as metadata without reading content. Report skipped paths coarsely, without printing sensitive names. Traversal errors and exclusions make completeness explicit. A general diff is deferred; do not run unrestricted git diff or recursively read the workspace.

Future process or network instrumentation requires a separately reviewed, read-only collection design. Process telemetry must not collect command lines or environment values. Network controls and network observations are separate evidence: a configured deny rule is not a connection log, and a connection log does not establish that training data was unseen. Any claimed isolation must identify the enforced boundary and its validation. Observer v1 is not a sandbox, does not enforce or prove network denial, and does not create a private holdout. Its files are not proven inaccessible to a same-user, non-sandboxed process.

Code corrections for Task 2b guarded-edit confinement and Task 3 owned process-group cleanup are present by checkpoint `2a58d61` (path-scope change `031c8cf`, process-group change `1aef34e`). Guarded-scope and final scoped reviews report no actionable defects; focused safety and full-suite checks passed. Escaped/new-session descendants remain an OS sandbox gap; process-tree telemetry is unavailable. These are runner safeguards, not observer capabilities. They do not establish an isolated OS boundary or prove observer files are inaccessible to a same-user process.

## Resource sampling and observer overhead

Resource rows carry run_id, phase_id, sample_seq, UTC time, monotonic_ns, source, and associated stage identity. For each metric distinguish measured value, unavailable-with-reason, and collection error; missing /proc or nvidia-smi data is never a measured zero. Samples are system-wide and must not be attributed to one agent.

The selected seven-file synthetic no-model E2E bundle completed in 7.54 seconds with an expected timeout result, `evidence_status=complete`, a stub grader, and no performance claim. It validates an integration path only. A separate bounded warm-cache filesystem microprobe used six balanced pairs (12 runs) on WSL `/tmp` verified as ext4: baseline median 7.540 ms, observer median 15.734 ms, paired increment median 8.276 ms. Each observer run produced 10 lifecycle/event records and two complete snapshots. This supports only an I/O microprobe observation, not agent/inference or production-run overhead, physical SSD throughput, or peak resource fidelity. Ubuntu 24.04 is registered under `C:\Users\Andre\AppData\Local\wsl`, but physical media identity and SSD throughput were not measured. Any later agent-level overhead study needs its own matched protocol and authorization.

## Validation gates before claiming coverage

The 32-test focused safety subset plus Ruff and the full suite passed; final scoped review was clean. Available lifecycle tests include a normal-exit descendant path; no separate grandchild test is claimed. Keep the remaining gate list explicit: sampler unexpected/forced-kill evidence is incomplete; verify all relevant observer write/snapshot failure paths, duplicate run-path refusal, skipped/missing terminal events, symlink and secret-path exclusion, native-stream preservation, and exactly one final-grade call after the last agent action. Confirm failures mark evidence incomplete without silently rewriting benchmark outcome, then validate artifact correlation and immutable hashes. Do not claim process/network isolation, complete tool-call observation, same-user observer-storage isolation, or production overhead.

## 2026-10-14: pristine grader result authority

The pristine replay checkpoint keeps candidate source separate from trusted fixture tests, but the candidate source and trusted test runner still share a Python interpreter. An independent proof patched `unittest` during candidate import and made an incorrect implementation report every gate as passing without trusted test methods running. The observer and static workspace integrity checks do not authenticate this runtime result. Keep `runtime_result_authenticated=false`, `adversarial_evaluation_validated=false`, `aggregate_is_security_proof=false`, `capability_evidence_eligible=false`, and `private_holdout=false`. OS/network isolation remains unverified. The next gate is to place assertion/result authority outside the candidate-controlled interpreter and authenticate its output. See the [validation report](../../results/reports/pristine-grading-validation-20261013.md) and [evidence index](../../results/reports/pristine-grading-validation-evidence-index-20261014.json).
