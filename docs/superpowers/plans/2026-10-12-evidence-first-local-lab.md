# Evidence-first local LLM round plan

> **For agentic workers:** Use Luna High for execution, probing and logs under the parent orchestrator. Preserve concurrent work. Execute gated rounds individually, not the entire list automatically.

**Goal:** Select useful model–harness configurations for the RTX 3070 and measure low-cost optimizations before implementing live routing.

**Architecture:** Reuse SSD launchers, provenance, graders and samplers. First freeze paired quality controls, then vary one model/runtime/cache factor. Offline routing consumes observed capabilities; live execution follows only after destinations pass.

**Tech Stack:** Existing pinned llama.cpp CUDA, Qwen3.5-4B/9B Q4_K_M, OpenCode 1.19.0 and Pi 1.1.0; Python 3.12 and WSL Ubuntu 24.04. New weights/forks are conditional candidates.

**Spec:** `results/reports/state-of-art-20261012.md`, the user's original machine/storage/cost constraints and retained raw reports. This supersedes the previous plan's router-first next-round recommendation; it does not reopen its failed calibration.

## Global constraints

- C-backed WSL ext4 for all active inputs/libraries/workspaces/logs; E only for verified archives. No HDD benchmarks.
- Keep at least 8 GiB free ext4. At the audited 16 GiB free, allocate at most 6 GiB for one new weight file and 1 GiB scratch; a fork/build needs its own space preflight. Do not stage multiple new candidates together. Do not delete existing models/datasets to make space.
- No driver update, Windows reboot, unapproved WSL RAM increase, paid provider call or dependency upgrade in a control round.
- One inference server and one model at a time; no simultaneous GPU subagents. Preserve 8 GiB WSL RAM and 4 GiB swap.
- Temperature 0, seed 1234 where supported, one slot, fixed GPU/KV/FA settings and isolated fresh sessions. Pin runtime, prompt/template/model/config hashes.
- Freeze task sets, prompts, profiles, graders and output/step/time caps before measured arms. Any change after observing results starts a separately identified series; retain historical rows.
- Predeclare output/step/time caps. Keep timeout/OOM/invalid-protocol rows; distinguish setup-invalid from measured failures. Stop on OOM or swap growth above 512 MiB over the pre-run baseline for at least 10 consecutive one-second samples; retain the memory failure rather than silently reduce settings.
- Coding bash is not OS-sandboxed by application permissions. Revalidate effective rules and scoped files before trusting a new harness/profile.
- No main push, force push, automatic merge or rewriting historical results.

## Review focus

- A runtime flag or tensor presence does not establish MTP activation.
- Cold first turns and cached later turns must be separated; harness-reported input includes reused tokens.
- Tests written by the model cannot substitute for protected independent behavior checks.
- Model-specific templates can be necessary; record them rather than pretend all models use an identical template.
- A disk-fit prediction is not GPU/RAM fit; compression format and effective runtime matter.

## Round 0 — Close provenance and permission prerequisites

**2026-10-12 execution:** preflight passed at `a734283`; the single hardened smoke failed its delegation gate (13.716 s, exact names, zero changes, no explorer). All 14 effective-profile diagnostics passed. No retry or permission widening. Delegation remains unresolved. Before any Round 1 measurements, technical review removed the unrelated delegation dependency: the separately identified single-agent protocol below must pass its own load/profile/bash/edit gates for both models. Independent Round 2 activation and Round 4 offline checks also use their own prerequisites. See `results/reports/round0-permission-smoke-20261012.md`.

**Files:** Existing `benchmark/opencode_controlled_probe.py`, `benchmark/configs/harnesses/opencode-subagents.json`, `results/system-audit/`, `config/experiments.yaml`, `versions.lock`.

Question: does the revised no-auto-approval policy actually execute a local request?

- [x] Recheck checkout/PR head, processes, space, hashes, SSD shared-library resolution and profile diagnostics. Record installed versions; do not auto-update.
- [x] Run one read-only smoke with the hardened runner, 90 s cap, exact output, completed explorer and zero workspace changes. Completed attempt failed the explorer requirement; completion of this action is not a passing gate.
- [ ] Stop if a permission prompt, protocol error or denied necessary tool prevents completion. Diagnose without widening permission rules or rerunning the failed historical coding pair.
- [x] Save the new source/profile hashes, raw events and sampled resources. This prerequisite is not a multiagent benefit trial.

## Round 1 — Matched model quality, then harder capability tasks

**Prospective protocol revision:** `model-quality-paired-20261012-r1c`, frozen before measured arms. Round 0 is still failed and is never reclassified. This single-agent study denies `task` and requires its own compatibility probes for both models: correct load/context, exact effective permissions, completed real bash and edit calls. Either compatibility failure stops the matrix. Explicit `--single-agent-release` follows code review and a clean committed SSD snapshot; it is not a delegation release. The preceding `r1b` call failed before loading any model because the executor expected ten commit characters from a runtime that prints nine. Preserve that setup-invalid attempt; `r1c` corrects only the version comparison and series identity, with unchanged caps, profiles, prompts and graders.

**Files:** Reuse `benchmark/harness_runner.py`, `benchmark/harness_eval.py` and existing fixtures. Add a focused capability fixture under `benchmark/fixtures/` and independent grader cases in the existing test structure only when its contract is frozen.

Question: when harness and budget are fixed, does 9B earn its memory/latency cost over 4B?

- [ ] Freeze three existing regression tasks and a blind grading contract. Use OpenCode single-agent, 16K context, Q4_0 K/V, cache off and reasoning off for both existing models. Cap each task at 180 s and 20 primary steps; preserve the effective profile and its hash.
- [ ] Calibrate one task for each model; keep calibration as diagnostic rows excluded from measured denominators. If either cannot load or use tools, record compatibility failure and stop the matrix. A behavior failure with functioning tools does not stop the matrix; retain it as a measured failure when it occurs in a measured attempt.
- [ ] Run one excluded warmup per model and three measured attempts per model/task (18 rows). Alternate model blocks; reset sessions/caches and record model load separately from task latency. Cap the round at 75 minutes including loading.
- [ ] Record independent correctness, unchanged protected files/modes, required workflow completion, protocol/tool failures, actual prefill/decode work, tokens, wall time, VRAM/RAM/swap. Report fractions and per-task medians/ranges; three repeats are exploratory, not a stable ranking.
- [ ] Define saturation before running as both models achieving 3/3 strict passes on every regression task. If both models saturate these tasks, add two bounded capability tasks: a multi-file bug with regression protection and an iterative tool/error-recovery task. Prove graders fail on the initial fixture and pass on a reference solution before inference. Hold out edge cases. Pilot at most four model/task observations before determining eligibility for repeats. These diagnostic pilots do not join the primary denominator. Freeze the harder task set and repeat protocol before a separately named measured series.
- [ ] On two frozen tasks, compare Pi and OpenCode with the same selected model only if a harness effect remains unresolved. Do not multiply all models by all harnesses.

Deliverable: `results/reports/model-quality-paired-20261012.md`, raw JSONL and a destination capability table. No winner if quality is tied or the tasks remain saturated.

## Round 2 — No-download speculation and independent cache experiments

**Probe correction:** the first MTP launch reached health but sent no generation because the executor incorrectly required `/openapi.json`, which the pinned server does not serve. Preserve that attempt as setup-invalid/incomplete. A separately identified `mtp-activation-corrected-20261012` diagnostic uses the pinned source's documented `POST /completion`, with the prompt/payload frozen before launch, the same settings and 180-second cap. One corrected attempt is allowed; no further retry or runtime change. Initialization alone does not satisfy the draft-activity gate.

**Files:** Existing `scripts/` llama launchers, `benchmark/llama_cpp_bench.py`, `benchmark/quality_smoke.py` and result summaries; add a small speculation summary only if current logs cannot express draft/acceptance counts.

Question A: can the local 4B MTP head activate, preserve task correctness and reduce generation time?

- [ ] Inspect pinned binary help and existing GGUF metadata/logs. Use its verified syntax, not mutable upstream examples. Permit one activation smoke of at most 3 minutes; require nonzero draft activity and explicit runtime activation.
- [ ] If incompatible, record the blocker and stop MTP; do not install a nightly stack to force success. One no-weight n-gram mode can be a separate fallback experiment.
- [ ] If compatible, compare speculation off/on on one iterative coding prompt and one nonrepetitive prompt, 1 warmup per arm/prompt and 3 alternating measured pairs (12 rows), 512 output-token cap, same 16K context, total cap 30 minutes. Retain token IDs when exposed; do not assert exact equivalence from similar-looking text.
- [ ] Track draft acceptance, generated tokens, decode tok/s, TTFT, total wall time and memory. Re-run strict JSON, real tool round trip and a coding behavior gate. Promote only with no correctness regression and at least 10% observed end-to-end improvement on the target workload; otherwise record no useful gain. This threshold is a practical decision rule, not statistical significance.

Question B: does prefix reuse improve an actual multi-turn harness workload?

- [ ] Separately compare cache off/on in one single-agent model/harness on two frozen tasks, three alternating pairs, 180 s/task and 45-minute total cap. Keep speculation off. Cold sessions between attempts; allow reuse only within an attempt.
- [ ] Confirm cache hits in server logs/counters and report processed versus reused prompt tokens. Require identical graders and at least 10% observed end-to-end gain before changing the operational default. A cached input-token counter alone is insufficient.

## Round 3 — One new candidate at a time

**Files:** `config/models.yaml`, `versions.lock`, existing downloader/preflights and quality harness. Exact researched revisions/hashes are in the research report; revalidate before acquisition.

- [ ] First candidate: OmniCoder-9B Q4_K_M, because the controlled question is coding post-training with similar architecture/footprint. Download only the pinned 5.34 GiB file if space permits; verify checksum, template and local-only endpoint.
- [ ] Gate at 2K–4K with strict JSON and a real tool round trip, then test 16K fit before a same-context coding comparison. If 16K cannot fit, declare a distinct constrained configuration and compare all controls at the same smaller context; do not hide the context difference.
- [ ] Compare against the selected existing model on two unsaturated frozen tasks, three repeats each, 180 s/task, maximum 45 minutes. Stop at protocol, scope or memory failure. Archive before considering the next candidate, but archiving alone does not free disk. If another candidate cannot be staged while preserving models and the reserve, defer it rather than delete weights. Use the same harness, graders, frozen tasks and budgets as the control; record the candidate-specific template.
- [ ] Second independent-architecture candidate: Gemma 4 E4B Q4_K_M, only after the same admission gates. Do not equate its effective-parameter name with its total memory requirement.
- [ ] High-upside compatibility candidate: Bonsai 2 PTQ1_0. Before downloading, pin/audit Prism fork release `prism-b10772-e8fd209` and validate CUDA sm86 support and build footprint; cap compatibility preparation at 60 minutes. Keep the reference llama.cpp untouched. No stock-runtime substitution for the required transforms. Only a working pinned fork and adequate space permit the single 5.54 GiB text-only file and the same correctness/load gates.
- [ ] Qwen2B is conditional on a concrete cheaper-tier need. Ordinary Qwen27B/35B MoE, vLLM/SGLang, new training and restored EXL3 weights are deferred unless these rounds reveal a specific gap.

## Round 4 — Evidence-based routing and continuity

**Files:** `router/rules.py`, `router/README.md`, `tests/test_router.py`; a small live runner only after destination evidence exists.

- [ ] Offline: exercise health failure, unsupported tool/template, excessive context, deadline exhaustion and no eligible destination. Return an explicit failure rather than secretly calling cloud. Use the measured capability table, not model names as quality proxies.
- [ ] Live local-only: compare always-4B, always-selected-model and deterministic 4B-to-selected-model escalation, using the same frozen harness in all policies on six frozen tasks, two attempts per policy/task, 36 rows maximum and 2-hour round cap. Two attempts per task are a feasibility signal, not a reliability estimate or causal ranking. Count all attempts, model reload time and escalation work. Preserve scope/test/deadline gates; do not retry endlessly.
- [ ] Escalate only on explicit failure signals. A silent semantically wrong answer is a separate grading problem, not something a health check detects. Evaluate whether escalation improves completion under a fixed total deadline.
- [ ] Cloud remains disabled. Actual paid fallback needs a chosen provider, a verified price and an explicit spend ceiling; a mock failure test establishes no cloud quality or cost result.
- [ ] Continuity: use one model and the same 32-file contract to fill the missing OpenCode observation, then compare explicit state/checkpoint handling with automatic compaction. Start one 6-minute pilot; repeat only after full file coverage/canary/tests/modes gates pass. Existing Pi/Vibe totals remain historical, not a matched comparison with a changed checkpoint protocol.

## Publication gate and remaining scope

- [ ] After each eligible round, update raw JSONL, reports, status, versions and ledger, run focused/full checks for code changes, verify hashes and archive, review and publish on a feature branch. No configured linter/typechecker means explicitly report that absence.
- [ ] Record separately researched / installed / runtime-compatible / measured / failed / not started. Finish a round without claiming the broad laboratory complete.

MoE/expert caching, useful adaptation beyond synthetic training, wider quantization quality, remaining named harnesses and paid fallback cost/quality remain open. This is a priority queue with gates, not a Cartesian execution matrix.
