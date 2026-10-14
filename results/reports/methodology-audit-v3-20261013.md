# Evaluation methodology audit v3

**Audit snapshot:** 2026-10-13; baseline commit b693a32c02b35dfd6b721f0d85d5b9ebe152ce7d.
**Status:** Baseline findings are preserved below. The oracle boundary, launcher, guarded-edit scope, timeout lifecycle, and cascade observer v1 corrections are present at source checkpoint `2a58d61e719ffbf64f879adee49e5a02d1acbcb5`. Full test/quality checks and scoped independent review passed; the synthetic E2E and bounded overhead probe are indexed. This closes only the tested implementation round, not the broader evaluation gates.
**Scope:** Supplied local documents, historical reports, available run records, and the 30 checks in the governing prompt. No source code was edited by this evidence audit.

**Evidence index:** [Portable metadata-only source and artifact inventory](evaluation-v3-evidence-index-20261013.json). The source checkpoint is `2a58d61e719ffbf64f879adee49e5a02d1acbcb5` on `fix/evaluation-oracle-observability-v3`. Code citations in the 30-check matrix remain anchored to baseline `b693a32`; current status is separately recorded below.

## Evidence labels and refresh boundary

Code citations in this report were checked against baseline commit `b693a32c02b35dfd6b721f0d85d5b9ebe152ce7d`. **Code inspection** establishes what that revision contains; it does not establish that a behavior was executed. **Reproduced** refers to the recorded child-process investigation in the local `pipeline/audit-log.md`; that reproduction was not rerun during this documentary continuation. **Raw record** means a retained run artifact, whose Git-tracked or local-only status is listed in the evidence index; a record can support a reported observation without making the experiment publicly reproducible. **Report-only** means no machine-readable underlying result was located in the checked scope. **Unverified** means no direct test or complete artifact established the property; it is not a pass.

## Finding

The reported **70.6% (24/34)** attribution is not a reproducible estimate. The report’s own case rows sum to 36, while its denominator says 34. Two cascade cases could overlap with the four Qwen config-precedence cases, but no stable event IDs or explicit deduplication rule establishes that overlap. The category totals are constructed to sum to 34, and the same 70.6% number is repeated in a second audit report; that repetition is not independent evidence. Treat 70.6% as an unsupported retrospective narrative, not a measured rate.

The pipeline audit also confirmed two concrete baseline defects: the isolated guarded-edit launcher fails when invoked from a task workspace without repository PYTHONPATH, and private test diagnostics/results can affect cascade repair and escalation. Those defects establish real validity risks, but they do not validate the 70.6% denominator or the exclusive causal labels.

## Thirty checks

“Unverified” means this audit did not establish the property with a direct test or complete artifact. A policy setting or report statement alone is not treated as proof of an OS or network boundary.

| # | Finding and evidence | Confidence | Next action |
|---|---|---|---|
| 1 | **Baseline fail; reproduction recorded in the pipeline audit.** At `b693a32`, the guarded-edit wrapper is present in the isolated PATH, but the isolated launch fails from the workspace. See benchmark/harness_runner.py:295–326 and tests/test_model_quality_paired.py:532–543. | High | The correction at `d349712` passed the final full suite; retain the isolated-cwd acceptance criterion and do not infer an OS sandbox. |
| 2 | **Baseline fail; reproduction recorded.** The module command cannot resolve benchmark.guarded_edit when cwd is the workspace and PYTHONPATH omits the repository; the scrubbed environment does not add the package root. | High | Validate the deployed wrapper from the same cwd/env as the agent, not from repo root. |
| 3 | **Yes at baseline.** The grader extracts AST function names and checks them against required names in several tasks (benchmark/harness_eval.py:306–326, 405–417, 487–500, 569–584, 651–667, 735–749). Calculator uses keyword matching on names for positive/negative/zero cases (benchmark/harness_eval.py:20–53). | High | Remove lexical test-name checks from functional correctness; retain only explicit task-contract checks as a separate dimension. |
| 4 | **No.** Exact method names are not evidence of behavior unless a task explicitly makes the name part of its API contract. The historical calculator task asked for focused tests without naming methods; see comprehensive-eval-audit-v2-20261013.md:42–45. | High | Score behavior externally; report test presence/quality separately. |
| 5 | **Yes.** The same six tasks recur across model, harness, cache, MTP, and routing work, so they are development/regression data, not independent capability confirmation. | High | Keep them in regression/dev; use new task families for confirmation. |
| 6 | **No verified private holdout was found.** This is limited to the inspected repository and supplied local archives; it is not a claim about every external storage location. | Medium | Create a separately controlled holdout only after access controls and custody are defined. |
| 7 | **Not private.** Held-out suite files are versioned in the same repository. Workspace separation may hide paths from a run, but it does not make artifacts private or training-unseen. | High | Call them external-to-workspace probes; reserve “private holdout” for separately controlled artifacts. |
| 8 | **Unverified.** The protocol contains tool permission settings, but no completed adversarial filesystem-boundary test is in the evidence examined here. A tool permission is not proof of OS isolation. | Low | Run a benign sibling-file sentinel under the exact agent process and document mounts, uid, and path boundary. |
| 9 | **Not demonstrated.** The inspected records use a local inference endpoint, but no evidence establishes network denial or an egress allowlist for agent processes. No live egress test was run in this audit. | Low | Inspect the OS/network sandbox and test only the declared policy endpoint and a controlled denied destination. |
| 10 | **Unverified.** The evidence set does not establish that every candidate patch is replayed and regraded in a fresh pristine fixture. | Low | Export the final diff, apply it to a clean fixture, and run the authoritative verifier there. |
| 11 | **Not tested in this audit.** No retained no-op-patch result was found in the examined reports. | Low | Require a no-op control that must fail the task contract. |
| 12 | **Not tested in this audit.** No retained reference-patch acceptance result was found for the current protocol. | Low | Require a known-good patch control that passes from a pristine fixture. |
| 13 | **Not tested in this audit.** No mutation-suite result was found that demonstrates rejection of required behavior removals. | Low | Add focused mutations and retain mutation score and failed mutants by task. |
| 14 | **Partial.** Git history versions code changes, and the local Qwen v2 protocol records source, prompt, fixture, model, profile, and runtime hashes. Targeted WSL2 inventory found local Granite/Gemma admission and diagnostic records, but comparable per-run source/task/grader manifests are still incomplete. | High | Require immutable protocol/task/prompt/scaffold/grader/runtime hashes in every run manifest. |
| 15 | **Yes, for the 70.6% historical aggregation.** It combines results from tasks and grader/harness states that changed across P0/P1/P2. The reports discuss those fixes after the historical failure matrix. | High | Never pool pre/post protocol results without regrading the same patches under one frozen verifier. |
| 16 | **Partial.** Pi/Vibe context and cascade raw records are tracked. Qwen v2 records exist locally but are ignored by Git. A targeted WSL2 check found Granite/Gemma admission records and logs in local-only raw directories; they are not repo-tracked, and this search does not establish complete public availability. Exact top-level files and hashes are indexed. | High | Publish or archive raw data with a location manifest and hashes; mark missing evidence explicitly. |
| 17 | **Partial.** Raw records expose some separate fields, but reports use strict pass/fail as a summary across functional, scope, test, and workflow checks. | High | Publish each dimension and its missing/not-run state independently. |
| 18 | **Yes.** strict_pass is a composite gate in run records and tests; see tests/test_model_quality_paired.py:186 onward and the per-run grade fields. It must not be read as a pure model-function score. | High | Keep composites secondary and show all component dimensions. |
| 19 | **Repeated runs are not independent tasks.** The reports count failure observations, but this audit did not establish that they used repeats as independent units in an inferential model; the 70.6% report gives no uncertainty estimate. | High for task structure; not established for inferential misuse | Use task as the primary unit; report paired task-level outcomes and resample tasks for uncertainty. |
| 20 | **No.** Harness reports explicitly state that token counters differ and are directional rather than normalized; see results/reports/harness-evaluation.md:43, 69, 81. | High | Keep per-harness token metrics labeled with their source; do not rank across harnesses as comparable token counts. |
| 21 | **Unresolved.** The Qwen v2 protocol sets a 180-second task limit and its 24 measured rows have no timeout, but this does not establish fairness across other harnesses or historical reports. | Medium | Report timeout as a distinct censored outcome; compare budgets and include all-attempt latency. |
| 22 | **Partial.** Qwen v2 records model_load_seconds, but the evidence does not define a consistent user-facing latency boundary including model load and unload for all experiments. | Medium | Report cold-start, warm task, and unload/swap phases separately; say which is included in each latency. |
| 23 | **Yes across the historical experiments.** The admission reports use prompt caching, while the Qwen v2 manifest records prompt caching off; other experiment families explicitly vary cache/MTP. | High | Freeze these settings for a model comparison or declare them as experimental factors. |
| 24 | **Yes.** Repeated development and correction on the same six tasks creates benchmark contamination for future capability claims, even when it does not establish exposure during model training. | High | Mark those tasks regression/dev only and keep confirmatory tasks out of tuning. |
| 25 | **Yes, critical.** harness_eval.py:187–214,329 returns verbose held-out stderr; cascade_routing_matrix.py:249–255,339–383 uses it for repair feedback and hidden-inclusive success for escalation. tests/test_cascade_routing_matrix.py:98–115 asserts private assertion disclosure. | High | Keep routing on visible development feedback only; grade privately once after the final action. |
| 26 | **Partial.** Resource traces use one-second observations and system-wide snapshots, which support coarse run peaks but miss shorter spikes and do not attribute all usage to the agent process. | High | Label sampling interval and scope; add process-level counters where available and state gaps. |
| 27 | **Yes.** One-hertz sampling cannot guarantee capture of sub-second CPU/GPU/VRAM/power peaks. | High | Do not call one-second maxima hardware maxima; use faster event sampling or mark the estimate. |
| 28 | **System-wide for key resource values.** The harness report explicitly says WSL RAM values are system-wide and not comparable across sessions; see harness-evaluation.md:27. | High | Distinguish process, process-tree, GPU-device, and whole-system metrics in schema and summaries. |
| 29 | **Not established.** No idle power baseline is documented in the inspected run reports. Average/peak watts therefore are not attributable energy above idle. | Medium | Capture matched idle baselines and report device energy with an explicit integration method. |
| 30 | **Partial.** Qwen v2 has detailed environment/model/runtime/config and hashes; older admission results have reports and model digests but not the full per-run code/task/grader/runtime manifest or raw traces. | High | Make the manifest mandatory and record unknown fields as unknown rather than inferring them. |

## Additional implementation findings from independent review

These two baseline defects are additional to the original 30-check matrix and do not alter its counts. The retained review `D:/Usuario/Downloads/LLM/audit-session-20261013/research/p0-review.md` was performed against baseline `b693a32` and subsequent cascade/launcher corrections. It reports code inspection plus a benign temporary-file-only reproducer for the temporary-symlink case. This continuation did not rerun that reproducer, and the note does not contain its exact raw stdout; the result remains attributed to the reviewer. The final scoped review of `1aef34e..2a58d61` is clean; its hash is indexed.

| ID | Finding and evidence | Status | Required action |
|---|---|---|---|
| A1 | **Baseline timeout cleanup was not process-tree safe.** The baseline killed only the leader, allowing descendants to outlive the timeout. | The runner now cleans up its owned process group; full suite, focused safety tests, and final scoped review passed. A normal-exit descendant path was tested; no separate grandchild test is claimed. | Escaped or new-session descendants remain an OS sandbox gap; process-tree telemetry is unavailable. |
| A2 | **Baseline guarded edit lacked workspace confinement and used a predictable temporary path.** The baseline checked only the final path component (`benchmark/guarded_edit.py:113–120`) and wrote through a fixed `.tmp` path (`:214–218`). The retained reviewer note reports absolute/outside and parent-directory-symlink escapes plus a benign `.tmp`-symlink reproduction. | Path-scope correction is present at `031c8cf`; guarded-scope and final scoped reviews report no actionable defects, the focused safety subset and full suite passed. | Treat this as runner path validation, not an OS sandbox or proof of inaccessible observer storage. |

## Current implementation status addendum

This addendum is anchored to final source checkpoint `2a58d61e719ffbf64f879adee49e5a02d1acbcb5`; it does not rewrite the baseline findings or their line references. Code presence, tests, review, and artifact evidence are distinguished below.

| Baseline item | Current code state | Evidence and remaining validation |
|---|---|---|
| Checks 1–2, isolated guarded-edit launch | Launcher correction is present at `d349712`. | Final full suite passed; this confirms the tested launch paths, not a general OS boundary. |
| Check 25, private-oracle feedback | Oracle-boundary correction is present at `eeaf9e6`. | Final full suite passed and scoped review was clean; no private holdout or pristine external verifier is established. |
| A2, guarded-edit path scope | Scope correction is present at `031c8cf`. | Guarded-scope review reported no actionable defects; the 32-test focused safety subset and full suite passed. This is runner-level path validation, not OS isolation. |
| A1, owned process-group cleanup | The runner cleanup change is present at `1aef34e`. | Focused safety tests and full suite passed; normal-exit descendant cleanup was tested. No separate grandchild test is claimed. Process-tree telemetry remains absent. |
| Observer v1 | Integrated at `1aef34e` for the cascade runner; source is anchored at `2a58d61`. | The selected seven-file synthetic E2E ran without a model in 7.54 seconds. Its expected timeout outcome has complete artifacts and is an integration check, not a model result. The bounded overhead probe is reported in the observability protocol. |

Final verification at `2a58d61`: 286 pytest tests and 19 subtests passed in 54.65 seconds; full Ruff, compileall, and 41 shell syntax checks passed. Compileall is not a typecheck; mypy/pyright were unavailable and no tools were installed. The final independent review of the scoped changes from `1aef34e` through `2a58d61` was clean.

The overhead probe used six balanced pairs (12 runs) on WSL `/tmp`, verified as ext4. Baseline median was 7.540 ms, observer median 15.734 ms, and paired increment median 8.276 ms. Each observer run produced 10 lifecycle/event records and two complete snapshots. This warm-cache filesystem microprobe does not estimate agent/inference or production overhead, physical SSD throughput, or peak resource fidelity. WSL registration places Ubuntu 24.04 under `C:\Users\Andre\AppData\Local\wsl`; physical media identity and throughput were not measured.

The 30-check matrix remains the baseline assessment. Its original findings are not retroactively upgraded by code presence or these bounded validations. Remaining gates include enforced OS/filesystem isolation, network enforcement, pristine verifier replay, a separately controlled private holdout, normalized tool events, training-data integrations, same-user observer-file isolation, process-tree telemetry, and complete sampler unexpected/forced-kill evidence.

## Contradiction and evidence ledger

| Claim | Supporting evidence | Counterevidence or limitation | Confidence | Disposition |
|---|---|---|---|---|
| 70.6% of historical failures were methodological | comprehensive-eval-audit-v2-20261013.md:16,269–310,384–385; repeated in methodological-eval-audit-20261013.md:311–325 | Table counts sum to 36, not 34; two cascade rows may overlap but have no event IDs/dedupe rule. Cause labels mix model, grader, harness, and infrastructure. Targeted WSL2 raw Granite/Gemma files were later located, but remain local-only and do not resolve the 70.6% denominator or establish complete run provenance. The repeated report is not independent. | High that the rate is unsupported; low on the actual causal fraction | Retain the historical report; do not repeat 70.6% as a result. Rebuild only from an event-level adjudicated ledger and mark unknown causes. |
| Four package_refactor failures were all false negatives | The audit report says preserved workspaces were regraded and all four passed; Qwen v2 raw includes the four original attempts. | The original records show grader skipped after a workspace integrity-gate failure. The regrade claim is report-only here: no separate machine-readable regrade artifact/manifest was found. | Medium | Preserve as a reported correction, not independently reproduced in this audit. Emit and archive a clean regrade record before using the corrected rate. |
| Granite and Gemma admission results are fully reproducible | Tracked admission reports give model digests, config excerpts, run tables, and failure narratives; targeted WSL2 raw folders now contain local-only admission records and server logs. | The WSL files are not repo-tracked, nested run folders were not inspected, and comparable per-run source/task/grader hashes remain incomplete. | High for the provenance gap | Treat narratives as report-supported and the raw artifacts as local-only; do not claim public or complete reproducibility. |
| Local Qwen v2 raw records substantiate their run summary | Local records.jsonl has 28 rows: 2 calibration, 2 warm-up, 24 measured; 16 of 24 measured strict passes and zero timeouts. protocol.json carries source code, task, model, profile, runtime, and configuration hashes. | The entire results/raw tree is Git-ignored, so files are local-only in this checkout. Their presence does not establish public reproducibility. | High | Preserve external raw archive and hashes or publish a location manifest before claiming public reproduction. |
| Pi/Vibe context results and cascade records are available | results/raw/pi-context-stress.jsonl, vibe-context-stress.jsonl, cascade-routing-evaluation-20261012/records.jsonl are tracked. | Pi’s explicitly invalid exploratory JSONL must not be merged into valid counts; one-second resource data are coarse; cascade raw includes the oracle-feedback defect. | High | Retain raw, identify invalid runs, and re-evaluate cascade claims after the feedback boundary is fixed. |
| “Full conversations” were available | The supplied C:/Users/Andre/Desktop/CHATS.md was fully read (2,271 lines). | It is a synthesized history/summary attributed to prior assistants, not separate complete Gemini and ChatGPT transcripts. No other transcript files were supplied. | High | State this provenance limit; do not attribute claims to unseen conversation turns. |
| Timed-out agent and visible-test descendants cannot change the candidate before private grading | Timeout lifecycle correction is present at `1aef34e`; full suite, focused safety subset, and final scoped review passed for tested paths. | Baseline killed only direct leaders. Current observer still lacks process-tree telemetry and no OS isolation is established; a separate grandchild test is not claimed. | High for the baseline gap; bounded current implementation evidence | Limit the claim to tested runner cleanup paths; retain pristine final-grading and OS-isolation gates. |
| Guarded-edit operations are confined to the task workspace | Scope correction is present at `031c8cf`; guarded-scope and final scoped reviews report no actionable defects, and safety/full-suite checks passed. | The earlier review reports a benign `.tmp` symlink reproduction. Runner-level path checks do not prove OS isolation. | High for the baseline gap; bounded current implementation evidence | Retain tests and review hashes; keep OS sandbox and observer-storage isolation as open gates. |

## Supplied source review

All supplied files were extracted locally and read in full. The source list, original SHA-256 values, extraction hashes, byte counts, and PDF page counts are in the external evidence inventory at D:/Usuario/Downloads/LLM/audit-session-20261013/evidence/inventory.json and evidence-manifest.json. That external folder is local audit evidence, not part of the repository.

The linked evidence index carries source basenames, byte counts, hashes, classifications, read status, and references/hashes for relevant local raw/log artifacts. It contains metadata only; it does not embed article bodies, extracted text, or conversation text.

- CHATS.md: only supplied conversation artifact; synthesized history, not full original chat logs.
- Five saved MHTML articles: “How to Govern AI Agents” (Towards Data Science), “Designing Agents That Create Their Own Tools” (ShipAI), the Anthropic Mods article (The New Stack), and two AI code-quality articles (The New Stack). These are secondary/practitioner coverage, class C under the governing prompt; useful for hypotheses, not proof of local behavior or causal percentages. The two Sonar-branded code-quality pieces are sponsored.
- CognitiveComplexity.pdf: 22 pages. The whitepaper defines Cognitive Complexity as a relative understandability estimate focused on breaks in linear flow and nesting. It does not define general code correctness or prove that complexity predicts task success.
- Local laboratory report PDF: 32 pages. Its first page distinguishes local measurements from external evidence and says proposed conclusions should be labeled as hypotheses/premises/gates. It is an engineering report, class B; it is not a substitute for missing raw run files.
- Governing prompt: read in full from the supplied attachment. Historical text inside CHATS.md and saved pages was treated as untrusted data, not executable instruction.
- No live web retrieval was used for the local evidence audit. For primary research and benchmark design, see [the research ledger](../../research/evaluation-v3-sources-20261013.md).

## Orchestration auditability boundary

The orchestration record is not a complete inference trace. Worker briefs, status updates, and available execution logs support task-level provenance, but the platform does not expose all worker inference parameters, model-file hashes, runtime/KV settings, or host resource attribution for cloud subagents. The parent/controller used a GPT-6-family model and delegated Luna xhigh workers, with up to three concurrently; those labels are not a reproducible model/config manifest. Passive observation is a MUST early in the implementation sequence, after validity-blocking P0s and before a new capability campaign. Observer v1 is scoped only to the cascade runner. It does not establish process-tree coverage, network visibility or denial, sandbox isolation, or a separately controlled private holdout. Do not describe either orchestration or observer v1 as total observability, and do not claim complete prompt/transcript access beyond the supplied CHATS.md.

## Evidence availability and reproducibility

| Artifact | Availability at audit snapshot | Reproducibility limit |
|---|---|---|
| Historical audit/admission/context reports | Tracked in the local Git repository | Local Git tracking does not by itself confirm public remote visibility. |
| Qwen model-quality-v2 raw: records.jsonl, protocol.json, summary.json and run folders | Present locally under results/raw/model-quality-v2-20261012-195743; ignored by .gitignore:11 | Local-only until a checksummed archive/location is committed or data are made publicly available. |
| Cascade, Pi context, Vibe context raw JSONL | Tracked under results/raw | Cascade contains oracle-feedback behavior; Pi exploratory-invalid records remain separately labeled. |
| Granite/Gemma admission run records | Targeted top-level WSL2 directories contain local-only records, protocols, summaries, and server logs; hashes are in the index | The artifacts are not repo-tracked; nested directories were not traversed, and complete manifests/public reproducibility remain unestablished. |
| Original full Gemini/ChatGPT transcripts | Not supplied | Cannot audit their complete provenance or quote them as evidence. |

## Prioritized roadmap

Implementation code for the listed items is present through checkpoint `2a58d61`; this round's test/quality checks and scoped review passed as detailed in the current-status addendum. Cost is an engineering estimate, not a measured duration.

### P0 — MUST: close private-oracle feedback loop

- **Problem/evidence:** Private unittest stderr and success state feed cascade repair/escalation (harness_eval.py:187–214,329; cascade_routing_matrix.py:249–255,339–383).
- **Risk:** The evaluated agent can learn hidden assertions and the score affects its own behavior.
- **Solution/files:** Separate visible development feedback from evaluator-only grading; keep repair/routing limited to visible feedback and operational completion. benchmark/cascade_routing_matrix.py, benchmark/harness_eval.py, focused tests.
- **Dependencies/cost/GPU:** Existing runner seam; medium; no GPU.
- **Acceptance/validation:** Private sentinel absent from all repair input; alter private pass/fail while keeping visible feedback fixed and show routing is unchanged; event ordering proves final-only private grading; focused fake-server/process tests plus cascade regression suite.

### P0 — MUST: make guarded-edit launch in the actual isolated environment

- **Problem/evidence:** Wrapper calls python3 -m benchmark.guarded_edit without repository PYTHONPATH; the sanitized environment and workspace cwd reproduce ModuleNotFoundError (harness_runner.py:295–326).
- **Risk:** Agent receives a tool that appears available but cannot execute.
- **Solution/files:** Fix the existing wrapper with the narrowest explicit package entry point; benchmark/harness_runner.py and launcher tests.
- **Dependencies/cost/GPU:** No new dependency; small-to-medium; no GPU.
- **Acceptance/validation:** From isolated cwd and scrubbed env, the wrapper applies a real patch, returns the expected result, and blocks out-of-scope edits; test both supported OS/runtime paths used by the lab.

### P0 — MUST: Task 2b, enforce guarded-edit path confinement

**Code status:** Implemented at `031c8cf`; guarded-scope and final scoped reviews report no actionable defects. The focused safety subset and full suite passed.

- **Problem/evidence:** Baseline `guarded_edit.py:113–120,214–218` checks only the final component for a symlink and uses a predictable `.tmp` path. The retained independent review reports absolute/outside and parent-directory-symlink escapes and a benign `.tmp`-symlink reproduction.
- **Risk:** A task edit can modify files outside its allowed workspace, including through a symlinked parent or temporary path.
- **Solution/files:** Resolve and enforce the workspace root for every target; reject absolute/outside and parent-traversal paths plus symlink components; use a unique exclusively created adjacent temp file with no symlink following. `benchmark/guarded_edit.py` and its focused tests.
- **Dependencies/cost/GPU:** Independent of model work; small-to-medium; no GPU.
- **Acceptance/validation:** Benign sentinel tests prove outside absolute paths, `..`, parent symlinks, leaf symlinks, and pre-created `.tmp` symlinks are rejected without changing outside bytes; normal in-scope edits still succeed.

### P0 — MUST: Task 3, terminate process trees before grading

**Code status:** Owned process-group cleanup is present at `1aef34e`; the full suite, focused safety subset, and final scoped review passed for this implementation round. Escaped/new-session descendants remain an OS sandbox gap.

- **Problem/evidence:** The independent review found cascade timeout handling that kills only the leader and visible-test timeout handling without process-group cleanup; descendants may continue mutating the candidate during grading.
- **Risk:** The final candidate is not stable at the verifier boundary, so the recorded grade may not describe the bytes that were actually checked.
- **Solution/files:** Put agent and visible-test subprocesses under exception-safe lifecycle management, terminate their complete process groups/trees on timeout, and wait/reap descendants before proceeding to private grading. Cover initial and repair phases. `benchmark/cascade_routing_matrix.py`, `benchmark/visible_feedback.py`, and focused tests.
- **Dependencies/cost/GPU:** Independent of model work; medium; no GPU.
- **Acceptance/validation:** Cover leader timeout and normal-exit descendant cleanup, including sentinel attempts. Current reviewed evidence does not claim a separate grandchild test. Exercise spawn and cleanup errors while preserving native logs.

### P0 — MUST: define dimension scores and verifier controls

- **Problem/evidence:** Name checks and strict_pass combine independent properties; no retained no-op/reference/mutation control results were found in this audit.
- **Risk:** Behavior, test style, workflow, and infrastructure failures are conflated.
- **Solution/files:** Keep functional, regression, integrity, scope, workflow, tool reliability, test quality, code quality, completion, and resource efficiency separate. Add deterministic no-op, known-good reference, and targeted mutation fixtures. benchmark/harness_eval.py, task/eval fixtures, tests, results schema.
- **Dependencies/cost/GPU:** Requires P0 oracle boundary; medium; no GPU.
- **Acceptance/validation:** No-op fails; reference patch passes; each mutation designed to violate a required behavior fails; strict summary can be derived but each component remains visible in JSON and reports.

### Short term — MUST: pristine final re-grade and honest access boundaries

- **Problem/evidence:** A private suite in the same repository is not a private holdout; current evidence does not demonstrate pristine patch replay, filesystem isolation, or network denial.
- **Risk:** Hidden data, repository history, or agent-controlled workspace state can invalidate evaluation.
- **Solution/files:** Export a candidate patch; apply to a clean fixture; verify in evaluator-owned process/container. Run benign filesystem sentinels, document mounts/uid, and implement a declared network policy. Keep any true private tests/reference patches outside agent-visible mounts and repository refs. Runner, sandbox configuration, fixture preparation, grader.
- **Dependencies/cost/GPU:** Depends on P0; medium-to-large; no GPU for sentinels, GPU only for later model runs.
- **Acceptance/validation:** Demonstrate expected deny/allow behavior for filesystem and network probes; pristine replay passes reference, rejects no-op/mutations, and never exposes verifier diagnostics to the agent.

### Short term — MUST: immutable run manifest and raw archive

- **Problem/evidence:** Qwen v2 has detailed hashes but is Git-ignored; targeted WSL2 checks found local-only Granite/Gemma raw files, while complete comparable manifests and public availability remain unestablished.
- **Risk:** Historical claims become unauditable and protocols cannot be reconstructed.
- **Solution/files:** Require run ID, task/prompt/scaffold/grader/protocol hashes, source commit and dirty state, model digest/quant, runtime build, full inference/tool config, budget, hardware, seed, stage, timestamps, raw/log/archive locations, and SHA-256. Results manifest tooling, protocol docs, archive locator.
- **Dependencies/cost/GPU:** None for metadata; medium; no GPU.
- **Acceptance/validation:** Every record resolves all artifacts or explicitly records missing; verify hashes after archive round-trip and reproduce the summary from raw.

### Short term — MUST early: passive observation and resource scope labels

- **Problem/evidence:** Resource traces are one-second, mainly system-wide snapshots; peak and per-process claims exceed that evidence.
- **Risk:** Short spikes and background load are missed or misattributed.
- **Solution/files:** Add passive evaluator-owned event logs with wall and monotonic time; identify process-tree, device, and system metrics; report sampling interval, idle baseline, and missing coverage. Benchmark resource sampler and observer.
- **Dependencies/cost/GPU:** User-required early work after validity P0s; depends on manifest and isolated sink; medium; no GPU for synthetic observer validation.
- **Acceptance/validation:** Correlate phases and tool/process events without exposing observer files to the agent; test failure paths and report gaps. Compare telemetry overhead in a bounded synthetic probe. Do not claim complete OS observability.

### Medium term — MUST: decontaminated task sets and task-level statistics

- **Problem/evidence:** Six repeatedly tuned tasks are unsuitable as a capability holdout; repeated runs are not independent task samples.
- **Risk:** Overconfident claims and benchmark leakage.
- **Solution/files:** Version regression/dev/diagnostic/adversarial/private-confirmatory suites; author new private tasks under separate custody; publish task-level outcomes and paired task bootstrap intervals. Dataset registry, task manifest, summary scripts.
- **Dependencies/cost/GPU:** Depends on access controls and frozen verifier; medium-to-large; GPU for model trials, not dataset curation.
- **Acceptance/validation:** Demonstrate no dev path to private fixtures or Git refs; report task as primary unit, repeats nested within task, all attempts and uncertainty; reserve holdout until final protocol freeze.

### Medium term — SHOULD: quality and system ablations

- **Problem/evidence:** The lab’s task score alone cannot show whether an agent improves maintainability or whether model/harness/edit-interface changes drive outcomes.
- **Risk:** “Success” can conceal regressions or debt.
- **Solution/files:** Compare before/after code on complexity, duplication, diff size, function size, lint/type/static checks, tests, and mutation score. Separately ablate model, harness, and edit backend on dev tasks; freeze confirmatory configuration. Quality summarizer, experiment manifest, report tooling.
- **Dependencies/cost/GPU:** Needs new task sets and stable manifests; large; GPU for model comparisons.
- **Acceptance/validation:** Report each quality dimension and baselines; use Cognitive Complexity only as a relative understandability indicator, not universal quality score; preserve paired task outcomes and confidence intervals.

### Long term — EXPERIMENTAL/LATER: fine-tuning, routing, and self-created tools

- **Problem/evidence:** Existing QLoRA and cascade plans do not justify capability claims if errors are caused by prompt, grader, harness, or feedback defects. Saved articles are secondary demonstrations, not proof.
- **Risk:** Spend GPU and contaminate confirmation data without evidence of a model-level error.
- **Solution/files:** Gate fine-tuning on a recurrent cross-task error surviving prompt, harness, and edit-backend ablations with clean data and holdout. Test routing only with visible operational triggers; test self-created tools only after static/security review, sandbox execution, temporary registration, observability, and cleanup. Training/routing/tool registry projects.
- **Dependencies/cost/GPU:** All gates first; high; GPU required for model training/campaigns, optional for tool-infrastructure tests.
- **Acceptance/validation:** Pre-register the intervention and holdout; compare baseline under one protocol; record successful, unnecessary, and missed escalation, latency, load/swap, resource, and quality dimensions; reject any design where private grader output changes agent behavior.

## Current implementation boundary

The source checkpoint `2a58d61` contains the oracle-boundary, launcher, guarded-scope, timeout-lifecycle, and cascade observer-v1 changes. The observer is implemented only for the cascade runner and is not total observability. Final validation recorded 286 pytest passes plus 19 subtests, Ruff, compileall, and 41 shell syntax checks; typechecking was unavailable. The 32-test focused safety subset plus Ruff passed, the post-commit synthetic E2E completed in 7.54 seconds with an expected timeout outcome and complete artifacts, and the final scoped review was clean. The six-pair warm-cache ext4 microprobe measured a 7.540 ms baseline median, 15.734 ms observer median, and 8.276 ms paired increment median; this is not agent/inference or production overhead, physical SSD throughput, or peak-resource evidence. No verified isolated OS boundary, network enforcement, pristine private verifier replay, separately controlled private holdout, normalized tool-event stream, training-data integration, process-tree telemetry, or same-user observer-file isolation is established. Sampler unexpected/forced-kill evidence also remains incomplete.
