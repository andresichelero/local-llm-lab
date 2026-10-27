# Qwen3.5 quantization and harness campaign

**Latest data capture:** 2026-10-27 07:58 UTC (04:58 BRT)
**Scope:** mixed-protocol progress and selected qualification observations; no final selection
**Campaign checkout:** `D:\Usuario\Downloads\LLM\.worktrees\practical-agent-v2`

This document records the latest supplied data capture and the earlier saved assessment. It is a historical snapshot, not a live process check. The assessment at 02:13 UTC reported 147 finalized records; the later `report-data.json` capture has 159. Their schedules and record coverage differ, so use the latest capture for progress and the assessment report for its detailed interpretation of context, development, and measurement limits.

## Objective and selection rules

The campaign aims to choose **four measured Qwen3.5 configurations**, two each for 4B and 9B. It evaluates GGUF quantizations and compatible alternative engines while preserving existing installations, model weights, evidence, and protocol lineage. The selection is gated by correctness, useful context, generation speed, and memory headroom; a fast qualification attempt alone cannot make a finalist.

For each model, the planned selections are:

1. The fastest eligible configuration among those with the best task completion.
2. The configuration with the largest verified useful context that stays within one task of the best completion rate, with any shortfall reported.

The frozen plan calls for a floor of 10/12 qualification checks; three performance repetitions at 16K, 32K, 64K, and 128K where safe; and six development tasks for each eligible artifact. After quantization selection, compare all eleven historical/current harness candidates on six tasks per harness/configuration. Deepen the top three to twelve tasks, two seeds, and both model sizes, then run the separately gated ablations and six fresh confirmation tasks across two seeds. Install checks or simulated-provider smokes do not count as model-quality comparisons.

The planned reasoning-profile follow-up (off, low, and medium) is separate from recovery-r2. It uses one fixed 9B artifact and holds engine, harness, task set, seeds, context, sampling, output ceiling, cache policy, and thread count constant. First verify that the pinned chat template honors the requested effort; otherwise describe the arms as budget-defined profiles. Run a six-task, one-seed pilot first, and expand only if controls and final answers are valid. Record reasoning and answer tokens separately. Do not append this work to a recovery manifest.

## Latest progress capture

`D:\Usuario\Downloads\LLM\reports\outputs\qwen-performance-20261027\source\report-data.json` contains **159 records**, **585 pending units**, and **744 scheduled units**. The schedule is adaptive and can grow as qualification gates pass. Its stage counts are:

| Stage | Records |
|---|---:|
| Qualification | 141 |
| Capacity | 12 |
| Development | 6 |

The records include 79 v4, 61 recovery-r2, 18 recovery-r3-dns, and one qualification record whose protocol is unregistered. The saved 02:13 UTC assessment predates this capture: it had 147 records, 579 pending of 726 scheduled, and only seven r3-dns records. Do not substitute those earlier totals for this later progress checkpoint or imply that all 159 records share one unchanged protocol.

Overall statuses in the latest capture are 42 `complete`, 61 `model_failure`, and 56 `blocked`. These are stored labels across multiple stages and protocol cohorts; `model_failure` is not a fresh causal audit. Keep model, harness, tool, transport, telemetry, and infrastructure explanations distinct. The assessment's official selection state is `mixed_protocols_requires_review`; no final quantization or harness selection is established here. **R4 has not been verified in the supplied evidence.**

The assessment source for its detailed qualification analysis is `results/reports/qwen-live-assessment-20261027T021305Z/README.md` in the separate campaign checkout. Its 02:13 UTC qualification table reports 19 4B and 11 9B artifacts at or above 10/12. The newer capture adds records, but this document does not independently recompute a final eligible-artifact set from them.

## Recent qualification observations

The following rows are individual qualification observations from the later capture. Tok/s values are per-attempt averages over recorded calls at 16K context. They are not repeated performance trials or a robust ranking.

| Model and artifact | Protocol | Checks | Recorded average |
|---|---|---:|---:|
| Qwen3.5-4B, Unsloth UD-IQ3_XXS | v4 | 10/12 | 103.61 tok/s |
| Qwen3.5-9B, mradermacher I1-IQ4_XS | v4 | 10/12 | 67.28 tok/s |
| Qwen3.5-9B, mradermacher IQ4_XS | v4 | 12/12 | 66.74 tok/s |

These are candidates for continued evaluation only. The apparent speed differences are not sufficient to select a quantization: qualification includes a small fixed check set, its task completion and resource behavior need deeper evaluation, and the planned three-repetition performance/context measurements and development tasks are incomplete. Compare artifacts only within matched protocols, hardware conditions, contexts, and telemetry coverage.

## Context and development evidence

The earlier 02:13 UTC assessment contains a separate r2 context probe for Qwen3.5-9B Unsloth Q4_K_M. It recovered three planted markers in three repeats at total contexts 16,384, 32,768, and 65,536; actual inputs were about 11,978, 28,362, and 61,130 tokens, each with a 4,096-token output reserve. Median TTFT was 5.91, 15.05, and 35.99 seconds. At 65,536, the device-wide GPU peak was 7,281–7,285 MiB. Three 131,072-context attempts could not retain the 512 MiB reserve after warm-up. This is a synthetic marker-recovery and capacity result for one r2 configuration, not repository-scale context quality or a comparison of current quantizations.

In six historical development tasks for that same r2 Q4_K_M/9B setup, two completed, three were recorded as `model_failure` (two no-progress stops and one compaction-budget stop), and one required transport/configuration review. A JavaScript task returned HTTP 500 while the server parsed tool arguments; its cause was unresolved in the assessment and should not be assigned to the model without evidence.

The earlier assessment found incomplete GPU telemetry in five of seven then-finalized r3 qualifications; all three that reached 10/12 were in that group. The later data capture has 18 r3-dns qualification records, so that earlier telemetry count is not a summary of all later r3 records. The cause of the recorded 15-second `nvidia-smi` timeouts was unproven. Do not promote results with missing telemetry to memory-capacity finalists until the resource evidence is adequate.

## Priorities and operating constraints

1. Preserve R3 and the v4/r1/r2 evidence lineage for as long as they are needed. Keep manifests, raw attempts, imported provenance, and reports intact; do not overwrite or retrospectively reclassify them. The supplied assessment specifically separates v4, r2, and r3-dns cohorts, while r1 is part of the historical lineage to retain where present.
2. Establish useful context per configuration, including output reserve, answer correctness, TTFT, memory headroom, and desktop responsiveness. Do not equate a context-window setting or synthetic marker recovery with usable coding context.
3. Complete qualification and matched performance/development measurements before selecting artifacts; then compare all eleven harness candidates under the planned matched tasks and deepen only the top three.
4. Compare harnesses and reasoning profiles only with pinned configurations and their own explicit protocols. Keep install/connectivity readiness separate from real-model task results and keep protocol cohorts separate in analysis.
5. Respect shared GPU and memory resources: the Windows desktop uses the same RTX 3070. Serialize GPU measurements, protect the memory reserve, and do not run project tests or graders concurrently with inference. Check current resource availability before any authorized continuation.
6. Treat incomplete telemetry, unregistered protocol provenance, and unresolved transport/tool failures as review items. Add new cases or change criteria only under a new protocol; retain the existing records unchanged.
7. No R4 output or final R4 state is verified by the supplied capture. Verify the exact output and protocol before making any later R4 claim.

## Checkout and documentation boundary

The campaign plan and source assessment live in `D:\Usuario\Downloads\LLM\.worktrees\practical-agent-v2`; the newest supplied capture is `D:\Usuario\Downloads\LLM\reports\outputs\qwen-performance-20261027\source\report-data.json`. The active checkout has local uncommitted scripts/configuration and is not represented by this documentation branch. This branch documents the evidence and decisions; it does not provide those local campaign scripts or a monitor command. Snapshot counts can become stale as the separate checkout changes.

This documentation update did not start inference, tests, or graders; the existing campaign continued independently.
