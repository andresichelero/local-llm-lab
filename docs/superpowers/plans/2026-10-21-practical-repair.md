# Practical agent targeted repair implementation plan

> **For agentic workers:** use isolated ownership; execute the steps below after the source campaign completes.

**Goal:** Repair confirmed evaluation defects and rerun only the affected tasks, preserving the original campaign and evidence.

**Architecture:** Stage changes outside the active checkout. Use host-side deterministic replay of captured MCP calls to derive private grading state, a shared candidate shell environment, explicit outcome dimensions, and a selective resumable campaign with its own protocol and output directory.

**Tech Stack:** Existing Python, OpenCode, Node, Linux sandbox and pinned llama.cpp/Prism binaries; no dependencies or downloads.

## Constraints

- No software tests, model probes, or new inference before the source campaign is complete.
- Original campaign: practical-selection-7bplus-v1; immutable raw records and manifest.
- Preserve models, quantizations, sampling, contexts, seeds, repetitions and original affected profile schedules.
- Rerun only B2, C2, M1, M2, D2 and H2. Leave B1, C1, D1 and H1 untouched.
- Separate corrected measurements from inherited historical results; do not present a composite as a homogeneous fresh campaign.
- No new models, training, new academic experiments or combinatorial parameter sweep.

## Tasks

- [x] Add failing regression tests in staging; wait for source completion before running them.
- [x] Fix candidate PATH and verify Node through the actual shell; fail environment before consuming model requests.
- [x] Remove public MCP audit state; replay native calls on the host and verify public outcomes before grading.
- [x] Align report instructions and expose only task-relevant MCP tools; retain retries and exactly-once checks.
- [x] Separate functional correctness, authored-test status, agent completion, expected errors and avoidable errors.
- [x] Add selective schedule, source-completion/coverage guard, frozen provenance, resumability, capacity supervision and composite reports.
- [x] After source completion: run only changed/new software tests (red then green), focused shell/MCP integration, lint/compilation for changed files, and independent review.
- [x] Publish changes with a recoverable source backup and launch only the 93 affected episodes after validation passes.

## Verification focus

- Same shell environment for candidate test commands and driver preflight.
- No hidden audit data in MCP success or error payloads.
- Extra valid reads and idempotent confirmation remain accepted; mutation to a different object is rejected.
- A merely interrupted/blocked source or incomplete records cannot release the repair campaign.
- No unchanged task or historical record is silently rerun or reclassified.
- Exact source coverage, hashes and selected profile settings survive resume.
- Expected injected tool errors are not reported as avoidable errors.
