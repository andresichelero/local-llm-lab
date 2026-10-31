# F1: diagnosis interrupted by a harness defect

Date: 28/10/2026. Author: Claude (orchestrator). Status: **deliberately interrupted at episode 18 of 24**, after the dominant cause of failures was identified.

## Configuration

- Protocol `qwen-4b-f1-diagnostic`. Runner `benchmark/qwen_f1_diagnostic.py`, commit `8e68478` on branch `feat/4b-worker-v2`.
- Model and server: Qwen3.5-4B Q4_K_M with KV q4_0, 16K context, llama.cpp v0.8.0.
- Arms:
  - **D1:** thinking on, temperature 0,6, cache off, `max_tokens` 8192.
  - **D2:** thinking off, temperature 0, cache on, `max_tokens` 2048.
- Raw results in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-f1-diagnostic/`.

## Results up to interruption

There were 17 episodes with results and **0 successes**. Causes recorded by the runner:

| Task | D1 | D2 |
|---|---|---|
| python_fix s101 | interrupted by operator | model_no_progress |
| python_fix s202 | budget_exhausted | model_no_progress |
| javascript_fix s101 | budget_exhausted | model_no_progress |
| javascript_fix s202 | model_no_progress | model_no_progress |
| authored_tests s101 | grader_or_completion_failed | model_protocol_error (tool call JSON truncated at 2048 tokens) |
| authored_tests s202 | budget_exhausted | model_protocol_error (same) |
| continuation s101 | model_no_progress | model_no_progress |
| continuation s202 | model_no_progress | model_no_progress |
| mcp s101 | grader_or_completion_failed | interrupted |

## Main cause: the harness rejects the path it instructs the model to use

The system prompt and the `read` tool schema say: *"All paths are relative to /workspace"*. The model then calls `read {"path": "/workspace/TASK.md"}`.

`safe_path()` (`benchmark/qwen_workloads.py:37-40`) rejects every absolute path with the message *"path must stay inside /workspace"*. That message is misleading because the requested path **is** inside /workspace. The model repeats the same call, and the repetition detector ends the episode as `model_no_progress`.

In each episode's final message window, that is, after compaction:

| Episode | `/workspace/...` calls | Rejected | Outcome |
|---|---:|---:|---|
| all 9 `model_no_progress` episodes with data, except javascript_fix s202 D1 | 2–8 | 1–8 | model_no_progress |
| python_fix s202 D1, javascript_fix s101 D1 | 8 and 6 | 8 and 6 | budget_exhausted |
| mcp s101 D1 | 5 | 5 | grader_or_completion_failed |
| authored_tests (4) | 0 | 0 | other causes |

The typical trigger is **resumption after compaction**: the checkpoint says "reread TASK.md", and the model uses the `/workspace` prefix suggested by the prompt. This turns the mechanism the old plan described as "plausible" (rereading + detector) into a **concrete, reproducible harness defect**. The count does not include messages before compaction.

## Other findings

- `max_tokens` of 2048 in D2 is insufficient to write an entire test file in one tool call. llama-server returns HTTP 500 with truncated JSON.
- The runner treats `model_protocol_error` as fatal to the entire campaign. In F1 this was worked around by resuming the campaign.

## Historical audit (Luna, 28/10, 23h)

See [historical-workspace-audit.md](historical-workspace-audit.md). The same `safe_path` was in the `-final-oom-v2` campaign. There were 101 `/workspace` calls, 95 of which were rejected, almost all after compaction.

Even so, **only 2 of the 14 4B failures** (python_fix and continuation) end with that pattern. Another attempt had 20 rejections and ended with budget exhausted. The other repetition failures **have no `/workspace` calls**.

This corrects the hypothesis raised by the orchestrator: the defect existed, but **does not explain most of the historical 4/18**. In F1 it dominated, probably because the configuration changed (Q4_K_M and checkpoint rewording). The conclusion remains the same: the custom harness has several failure modes, so the baseline moves to OpenCode.

## Consequences

1. The F1 numbers **do not measure 4B capability**: they measure this defect. The same defect probably affected the historical 4/18; the raw evidence from the final campaign still needs checking.
2. The custom harness is no longer the measurement baseline. The new strategy is in PLANO-ESTRATEGICO-v2, section "Review of 28/10, 22h".
