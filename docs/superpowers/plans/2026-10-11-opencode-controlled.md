# Controlled OpenCode continuation implementation plan

> **For agentic workers:** Execute the tasks with Luna High workers under the parent orchestrator. Preserve other workers' changes.

**Goal:** Audit the real lab, repair stale summaries, and test whether bounded local delegation completes a fixed coding/review workflow.

**Architecture:** Preserve historical raw evidence. Run a new gated series with isolated OpenCode homes and workspaces on C-backed WSL ext4, using the existing grading/resource helpers. Publish small reproducible records and checksum archives after timing.

**Tech Stack:** OpenCode 1.19.0, llama.cpp d81235049, pinned Qwen3.5-9B Q4_K_M, Python 3.12, WSL Ubuntu 24.04.

**Spec:** User continuation instructions and results/reports/progress-resume-20261011.md; this plan replaces its suggested sequence with evidence-based gates.

## Global constraints

- Active input/runtime/libraries/workspace/cache/logs/results on C-backed ext4; D checkout and E archives are storage only. No HDD benchmarks.
- No driver changes, Windows reboot, model/dataset deletion, paid API or new dependency required in this round.
- Keep 8 GiB WSL RAM / 4 GiB swap; no repeated resize or service shutdown without need.
- Never push main, force-push, discard concurrent changes, or rewrite raw history.
- Current free ext4 space about 16 GiB: reserve at least 8 GiB and cap new scratch at 1 GiB.

## Review focus

- A C executable can resolve D libraries without LD_LIBRARY_PATH: require SSD bundle preflight before launch.
- A configured worker is not proof of invocation: require completed task events identifying both intended children.
- Exit zero is not task success: require tests, independent behavior, scope and review completion separately.
- Context/step/time exhaustion remains a failed observation, not an excluded success-rate denominator.
- Invalid launch/provenance is retained as diagnostic evidence, separated from measured comparisons.

## Task 1: Current audit and evidence report

- [x] Verify clean checkout, live PR head/base/checks, host/WSL resources, processes, model hash and runtime dependencies.
- [x] Independently review and integrate PR34 with expected-head guard; fast-forward main and create feature branch.
- [x] Write results/reports/audit-continuation-20261011.md with comparative table, primary evidence, measured/installed/researched/incomplete distinctions and gaps.
- [x] Correct status.md step-result reversal, README/source ledger Vibe total (1/4), and cite baseline selected raw rows 21–29.

## Task 2: Effective-profile and bounded compatibility gate

- [x] Add a small reproducible runner in benchmark/opencode_controlled_probe.py, reusing existing isolation, grading, usage/resource helpers where suitable; add focused tests in tests/test_opencode_controlled_probe.py for gates and event parsing.
- [x] Copy a clean committed source snapshot to a unique SSD-side checkout; record Git SHA, config/fixture hashes and exact invocation.
- [x] Inspect debug config and debug agent details for the exact corrected profile in isolated HOME; assert local endpoint, auto-update off, allowed children and denied child bash/edit.
- [x] Start only the owned server (16K, Q4_0 KV, FA, 99 GPU layers, reasoning off, one slot; no prompt caching) after SSD/model/resource preflight.
- [x] Run a read-only delegation with 90-second cap; require exact test names, completed explorer event and zero workspace changes. Preserve events, stdout/stderr, effective settings and resource samples.

## Task 3: Matched coding gate and bounded repetitions

Hypothesis: one read-only explorer and one independent reviewer can complete the same calculator task within 20 primary steps and 180 seconds; the extra coordination may cost time without improving this saturated task.

- [x] If Task 2 passes, run one calibration pair: control denies task calls; treatment permits only the two named children and explicitly requests explorer, implementation/tests, then independent review. Same fixture/model/server settings, equal 20-step and 180-second limits, temperature zero and isolated fresh sessions.
- [ ] Not eligible after calibration failure: one warm-up per arm plus three measured pairs, alternating order. Keep cache off; cap total round at 35 minutes. Stop escalation after failed calibration, do not tune until success.
- [x] Record behavior/tests/scope, delegation/review completion, wall seconds, tool failures, token counters and sampled resources separately. Include all valid measured failures in denominators. Do not infer general quality advantage from this one task.
- [x] Stop only owned processes. Archive completed series to E and verify SHA-256; preserve active data and all failed attempts. Archive SHA256 is recorded in the probe report and versions.lock.

## Task 4: Validation and publication

- [x] Run focused tests, full suite in its Linux Bash environment using a small isolated pytest environment (none was already installed), Python syntax/compile checks, shell syntax where applicable, JSON parsing and git diff --check. No linter/typechecker is configured; report this explicitly. Final source passed 79 tests and 3 subtests.
- [x] Revalidate at least three 2026 candidates from official sources without downloads; distinguish upstream claims from installed/measured fit.
- [x] Update README/status/versions/source ledger and audit report with actual gate outcome; commit small artifacts, review full diff, push feature branch and open/attach new PR. PR35 is open and attached: https://github.com/andresichelero/local-llm-lab/pull/35. Its CodeQL checks were inspected after publication; pending checks are not a completed CI result.

## Decision after this round

If delegation fails, prioritize an operational router that chooses a bounded local harness by task and escalates on deterministic failure, before more subagent tuning. If it passes, broader unsaturated coding tasks are needed before quality claims. MoE/expert caching, MTP/speculation, broader weight quantization, remaining harness interoperability and cloud cost/quality remain independent future rounds requiring fit/release/license research first. The lab is not complete.
