# Evaluation protocol v3 (draft)

**Protocol ID:** evaluation-v3-draft
**State:** Design contract; observer v1 is integrated for the cascade runner at source checkpoint `2a58d61e719ffbf64f879adee49e5a02d1acbcb5`. Full test/quality checks and scoped review passed for this implementation round; broader access, holdout, and observability gates remain open.
**Audit base:** b693a32c02b35dfd6b721f0d85d5b9ebe152ce7d
**Purpose:** Measure a local coding-agent system without confusing model behavior, scaffold behavior, verifier quality, task exposure, or operational failures. This protocol does not claim an existing private holdout or OS sandbox.

The supporting source and artifact metadata is in the [portable evidence index](../../results/reports/evaluation-v3-evidence-index-20261013.json). Baseline code findings refer to the audit base above; current source hashes and selected synthetic E2E evidence are anchored to `2a58d61`. The bundle has no model and supports no performance inference.

## 1. Evaluation units and suite roles

The primary statistical unit is the **task**. Repeated runs on a task estimate run-to-run variability inside that task; they are not new task samples.

- **regression:** The six repeatedly used lab tasks and prior fixtures. Use for code, harness, grader, runtime, and infrastructure regression only.
- **dev:** Public tasks used to tune prompts, scaffold, permissions, timeouts, routing, and edit interface. Do not report dev results as confirmatory capability.
- **diagnostic/adversarial:** Purpose-built tasks for testing specific failure modes such as scope violations, oracle leakage, path traversal, timeout behavior, or context loss. Report these separately.
- **private_holdout:** A separately controlled task set whose tests, grader internals, reference patches, mutation suite, and future Git refs are inaccessible to agent and tuning authors until the protocol is frozen. Keep it outside the agent-visible repository and mounts. “Private from the current agent” does not mean unseen during model training; public benchmarks can only be described as exposure-reduced, not training-unseen.

Use a distinct identifier and immutable revision for each suite and task. The same task may move to regression after exposure, but must not silently retain a confirmatory label.

## 2. Versioning and run manifest

Every run receives a unique run ID and immutable manifest. Hash bytes rather than display names. Record unknown values as null with a reason; never backfill by inference.

Minimum manifest:

- Protocol: evaluation_protocol_version, protocol hash, schema version, suite, task ID and task_version.
- Task inputs: visible task prompt hash, fixture/scaffold hash, dependency lock/image digest, allowed-file contract, visible test revision.
- Evaluator: grader_version/hash, private-suite hash stored only evaluator-side, mutation-suite hash, reference-patch hash, static-analysis and quality-tool versions.
- Agent system: harness/scaffold version/hash, model and quantization, model file SHA-256 and upstream revision, agent/tool versions, edit backend and format, permission profile, retry/routing policy.
- Runtime: inference engine build/commit, endpoint type, context and output limits, temperature, seed, reasoning mode, cache/MTP settings, parallelism, GPU offload and all effective runtime flags.
- Environment: OS/kernel/container/image digest, Python/Node versions, working directory identity, mounts, user ID, process and network policy, dependency cache state, GPU/CPU/memory/storage identifiers.
- Budget and timing: wall/task/round limits, step/tool/token budgets, retry limits, load/unload policy, queue and setup time, monotonic and UTC start/end timestamps.
- Provenance: source Git commit and dirty state, hashes for relevant source files, task/prompt/grader/scaffold/config, raw artifact locations and SHA-256, archive retention class, and a reproducibility status.

Do not publish model credentials or inherited secrets in manifests. Record only a safe presence/policy summary when needed, never secret values.

## 3. Execution and oracle boundary

The agent phase receives only the task, visible source/tests, permitted tools, and declared network. The runner must enforce and record the actual filesystem, process, and network boundary. A tool permission or isolated cwd is not itself a sandbox.

The verifier owns private tests, reference patches, mutation tests, and final grade. It must run after the agent’s last action against a fresh pristine fixture with the candidate diff applied. The agent cannot read or modify the verifier, future Git refs, observer output, or grade.

Development feedback and final grading are separate channels:

1. Visible development tests may inform agent repairs if that is the declared intervention.
2. Private tests, private pass/fail, private stderr, hidden assertion names, and evaluator diagnostics never inform the agent, repair prompt, routing, or escalation.
3. Final private grading occurs once after the final candidate action. Its outputs are evaluator-only.
4. Routing may use only predeclared, visible operational signals (for example process failure or a visible test result). Any change in routing trigger is a protocol change.

If the task requires network access, declare an allowlist and test it. Otherwise deny network at the OS/container layer and retain evidence of the enforcement. Public tasks may remain model-contaminated even when the sandbox blocks retrieval.

Timeouts are lifecycle boundaries. Before any later visible test, routing step, or private grade, terminate and reap every process descended from a timed-out agent or test runner; killing only the leader is insufficient. The runner now cleans up its owned process group; full-suite and focused safety checks passed, and scoped independent review was clean. A normal-exit descendant path was tested. No separate grandchild test is claimed. Escaped/new-session descendants remain an OS sandbox gap, and process-tree telemetry is unavailable.

Every edit target must be proven inside the resolved task workspace before it is read or written. Reject absolute/outside paths, parent traversal, and symlinked path components. Create temporary edit files with unique exclusive creation and no symlink following. The correction is present at `031c8cf`; guarded-scope and final scoped reviews found no actionable defects, and focused safety/full-suite checks passed. This is a runner safeguard, not an OS sandbox.

## 4. Result dimensions

Emit a separate state for each dimension: pass, fail, not_run, invalid, or unknown. Include reason and evaluator version. Do not coerce not_run/invalid/unknown to a model failure.

Required dimensions:

- **functional_pass:** behavior verified by independent task contract and tests.
- **regression_pass:** required preexisting behavior remains intact.
- **integrity_pass:** workspace and protected artifacts are unmodified except permitted patch paths.
- **scope_pass:** final diff obeys explicit file/behavior constraints.
- **workflow_pass:** required visible workflow and completion steps occurred.
- **tool_reliability:** launch, tool, parser, and infrastructure operations succeeded.
- **test_quality:** candidate tests exercise specified cases; naming/style is scored separately from behavior.
- **code_quality:** before/after deltas for maintainability and static checks.
- **agent_completion:** the agent produced a final candidate/status before budget expiry.
- **resource_efficiency:** latency, token counters with source, tool calls, memory, VRAM, power/energy, and load/unload accounting.

Distinguish **model capability** (model under a fixed interface), **agent-system capability** (model plus scaffold/tools), and **operational reliability** (launch/runtime/environment). A composite strict pass may be shown only as a derived policy gate after every dimension and denominator is reported. Never use it as a synonym for model functional correctness.

## 5. Controls and causal attribution

Each task protocol should define a no-op candidate, a known-good reference patch, and a small mutation suite. The no-op must fail required behavior; the reference patch must pass all relevant dimensions; each necessary mutation must be detected. Store those control outcomes and artifacts.

When attributing failures, use a multi-label taxonomy with one primary_cause when evidence supports it and contributing_causes[] for other causes. Allowed examples:

- MODEL_REASONING, MODEL_SPEC_FOLLOWING, MODEL_TOOL_USE, MODEL_CONTEXT_MANAGEMENT
- SCAFFOLD_PROMPT, SCAFFOLD_FEEDBACK, SCAFFOLD_TOOL_INTERFACE, EDIT_BACKEND
- TASK_UNDERSPECIFIED, TASK_CONTRADICTORY
- GRADER_FALSE_NEGATIVE, GRADER_FALSE_POSITIVE, ORACLE_LEAKAGE
- ENVIRONMENT_FAILURE, TIMEOUT, INFRA_FAILURE, BENCHMARK_CONTAMINATION

Keep causal unit an identified run/event with its task, protocol, raw trace, and adjudication evidence. Unknown is a valid category. Do not force exclusive labels or infer causes from aggregate percentages. Use counterfactuals where feasible: regrade the same patch, alter only the prompt/interface, compare model under a fixed harness, or compare harness under a fixed model.

## 6. Repeats, uncertainty, and latency

- Report task count, per-task results, attempted runs, pass@1, success probability, and all failure/invalid/timeout counts.
- Pair comparisons by task and protocol. Repeats are nested within task. For uncertainty, resample tasks (or use an explicitly justified hierarchical model); never treat runs of the same task as independent tasks.
- With a very small task set, show raw task outcomes and avoid strong ranking claims.
- Report P50/P90 latency with task/run count, successful-run latency, all-attempt latency, timeouts, and censoring. Do not omit failed or timed-out attempts.
- Define wall-time boundaries. Separate model/runtime load, warm task execution, escalation/swap, unload, and queue/setup time. Include phases only in metrics whose names state that boundary.
- Keep cache, MTP, prompt, context, seed, quantization, inference runtime, edit backend, and harness fixed for a model comparison; if varied, declare a paired/blocked experimental factor and new protocol version.
- Token counters differ across harnesses. Record counter name/source, cached-token handling, and tokenizer where known. Do not compare totals across harnesses as equivalent tokens without a normalization experiment.

## 7. Code quality before and after

Compare pristine fixture with final candidate diff using task-relevant checks: tests and coverage, lint, type checking, security/static analysis, duplication, diff size, large functions, nesting, and maintainability. Report failures and missing tools explicitly.

Cognitive Complexity is a relative estimate of understandability based on breaks in linear flow and nesting. Use it to compare before/after code where the language/tooling supports a meaningful comparison; it is not a universal quality score, and no single metric replaces review or correctness tests. The supplied Cognitive Complexity whitepaper is the source for that metric definition.

## 8. Resource measurement and observation

Retain raw resource samples and label each metric’s scope: process, process tree, GPU device, WSL/system, or host. Include sampling interval and collection source. One-second samples are coarse observations and cannot guarantee sub-second peak capture. Do not describe a sampled maximum as a physical peak.

If reporting power or energy, capture a matched idle baseline and state integration method, sampling interval, device scope, and background load. Report absolute and idle-adjusted values separately.

Observer events should carry run ID, event ID, phase, source, UTC timestamp, monotonic timestamp, and agent/parent/turn IDs where available. Export to evaluator-owned storage inaccessible to the agent. Keep the observer passive; if it affects behavior or supplies feedback, treat that as an experimental intervention. State instrumentation overhead and missing event coverage.

Implement and validate this passive observer early, after the validity-blocking P0s and before a new capability campaign. Version 1 is integrated at checkpoint `1aef34e`, its selected source is anchored at `2a58d61`, and it applies only to the cascade runner. A seven-file synthetic no-model E2E bundle completed in 7.54 seconds with an expected timeout outcome and complete artifacts; it is not a model result. The bounded I/O probe measured only a warm-cache synthetic filesystem workload. Explicit gaps remain: process-tree telemetry, normalized tool events, network observation/enforcement, isolated OS/sandbox evidence, pristine verifier replay, a separately controlled private holdout, and training-data integrations. The observer does not provide total orchestration observability: the parent/controller for this audit used a GPT-6-family model and delegated Luna xhigh workers, with up to three concurrently, and platform-managed workers may not expose full inference parameters, model-file hashes, runtime/KV settings, or host resource attribution. Record known worker identity and prompt/brief hashes where available, and label unavailable fields as unknown. Do not claim complete transcript access beyond the supplied CHATS.md.

## 9. Quality and promotion gates

**MUST before capability claims:** verified verifier controls; no private-oracle feedback; complete run manifests/raw records; separate metric dimensions; task-level reporting; confirmatory task access policy; explicit timeout and environment status.

**SHOULD before a new comparison campaign:** paired task schedule, frozen model/harness/edit configuration, resource scope labels, load/unload metrics, idle energy baseline if energy is reported, and code-quality before/after checks.

**Fine-tuning gate:** Do not start QLoRA for a prior roadmap item alone. Require a recurring error across multiple tasks that survives prompt, harness, and edit-backend ablations; suitable training data; and an uncontaminated holdout. Otherwise fix the system.

**Routing gate:** Compare fixed 4B, fixed 9B, and cascade under the same task/protocol; report success, escalation rate, successful/unnecessary/missed escalation, latency, load/swap, tools, tokens, VRAM, and resource scope. The trigger must not use hidden grader output.

**Self-created tools:** Experimental only. Require code proposal review, static/security checks, isolated execution, temporary registration, evaluator-owned logs, and cleanup. Dynamic tool code never gets unrestricted host access.

## 10. Current status and references

This document records a design contract and current code state, not proof that all controls exist. At baseline `b693a32`, oracle-feedback leakage, isolated-launch failure, path-scope weaknesses, and timeout cleanup gaps were present. Corrections are present through source checkpoint `2a58d61`; the full suite, Ruff, compileall, shell syntax checks, focused safety subset, post-commit synthetic E2E, and scoped independent review passed as described in the linked audit and evidence index. The six-pair overhead microprobe measured a 7.540 ms baseline median, 15.734 ms observer median, and 8.276 ms paired increment median on WSL `/tmp` ext4; this does not establish agent/inference or production overhead or physical SSD throughput. No verified isolated OS/network boundary, pristine verifier replay, or private holdout is established. Same-user observer-file access, process-tree telemetry, normalized tool events, and training-data integrations remain open.

- [Methodology audit and 30-check matrix](../../results/reports/methodology-audit-v3-20261013.md)
- [Research ledger](../../research/evaluation-v3-sources-20261013.md)
- [Implementation plan](../plans/2026-10-13-evaluation-v3-plan.md)
- External extraction/source hashes: D:/Usuario/Downloads/LLM/audit-session-20261013/evidence/evidence-manifest.json

## 2026-10-14: pristine grading diagnostic checkpoint

`pristine-workspace-v1` replays allowlisted candidate source into a fingerprinted fixture and does not execute candidate-authored tests as the trusted suite. Its 29 expected control cases are useful ordinary behavior and structure checks. The runner-forgery proof nevertheless demonstrated a wrong implementation passing all five gates and aggregate `success` after candidate code patched `unittest`; runtime result authentication remains open. Keep `runtime_result_authenticated=false`, `aggregate_is_security_proof=false`, `private_holdout=false`, and `capability_evidence_eligible=false`. This checkpoint is not a capability result and is not comparable with historical direct-workspace grades.

At source commit `489c0d57ca5f58ca742117759f4abf99fc4b7a6a`, the full suite passed (298 tests and 19 subtests), as did Ruff 0.15.17, Python 3.12.3 compileall, and `bash -n` on 41 files in a Git-aware WSL ext4 clone. The 29-control matrix passed with zero assertion failures after correcting one stale field name in a copied external driver; the initial schema-mismatch run remains preserved and is not reclassified. These checks do not close the runner-forgery finding. See the [pristine grading protocol](pristine-grading-protocol.md), [validation report](../../results/reports/pristine-grading-validation-20261013.md), and [metadata-only evidence index](../../results/reports/pristine-grading-validation-evidence-index-20261014.json).
