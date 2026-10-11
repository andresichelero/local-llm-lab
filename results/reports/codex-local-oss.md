# Codex CLI local OSS endpoint probe

Date: 2026-10-11. This tests endpoint compatibility only; it produced no task-quality score.

## Setup

- Host CLI: Codex `0.162.0-alpha.17.2` on Windows 10.
- Endpoint: llama.cpp `d81235049384534c167caea52b85a694f6103d14` serving Qwen3.5-9B Q4_K_M from `/home/foxtrot/local-llm-benchmark` on C:-hosted WSL ext4; context 16,384; K/V Q4_0.
- Scratch project and events were on C: under `AppData\Local\Temp\codex-oss-local-bench-20261011`. Invocation ignored the user's Codex config and used only the local OSS endpoint override. No paid API or credentials were used.
- The deterministic coding task was to clamp a score to 0..100 and run the existing `unittest` suite. Before agent execution the test failed on `-4`, as expected.

## Outcome

- The endpoint health check succeeded. Codex required selecting `--local-provider lmstudio`; a short alias caused its setup path to try downloading that model. Using the exact `/v1/models` identifier let the CLI continue, but its model-catalog parser reported an incompatible response shape.
- The CLI then called the local Responses API. llama.cpp reported that it skipped Responses tool types `namespace` and `web_search`. The Qwen3.5 chat template then returned HTTP 500 because the incoming system message was not at the beginning. Codex retried five times and failed the turn. The installed CLI refused a `wire_api="chat"` override, saying this provider requires Responses.
- The task did not complete: no scratch source file changed, the tests were not rerun, and there is no task success, tool success, TTFT, or coding-quality score. No benchmark comparison against Pi/OpenCode/Vibe is valid from this probe.
- The local llama-server was stopped after the attempt. The event stream in `results/raw/codex-local-oss.jsonl` preserves the CLI-visible failure without storing its full system prompt or tool schemas.

The upstream Codex CLI README documents `--oss` and `CODEX_OSS_BASE_URL` for an OpenAI-compatible local host: [OpenAI Codex CLI README](https://github.com/openai/codex#using-open-source-models). That documents the intended configuration; this local run establishes that the tested llama.cpp/Qwen3.5 combination was not compatible with the current installed CLI build.
