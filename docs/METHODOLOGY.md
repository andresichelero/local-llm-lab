# Methodology

This document describes how the OpenCode baseline measures the agent, what counts as a pass, and how results are analyzed. The numbers are in [RESULTS.md](RESULTS.md).

## 1. Question and design

The question is how much each runtime factor changes a local coding agent's pass rate and cost: context, KV cache type, weight quantization, prompt cache, and reasoning mode (thinking).

The design is a one-factor-at-a-time matrix based on a control (B0). Each arm changes a single factor relative to the control. The matrix has 132 episodes in stages 1 through 3, and stage 4 was configured with another 168. Each stage starts only after the previous one passes its gate. Stage 1 requires at least 3 passes out of 12 in the control, with no infrastructure failures.

## 2. Corpus

Stages 1 through 5, T2, T3b, the replication and the combined campaign used the original 12-task corpus, 2 in each of 6 classes:

| Class | Tasks | Editable file | Host |
|---|---|---|---|
| python_fix | `py_range`, `py_query` | `bottle.py` | Bottle 0.13.2 |
| javascript_fix | `js_sign`, `js_plural` | `index.js` | ms 2.1.3 |
| authored_tests | `tests_query`, `tests_range` | `test/test_*.py` | Bottle 0.13.2 |
| continuation | `cont_quote`, `cont_path` | `bottle.py`, in two phases | Bottle 0.13.2 |
| mcp | `mcp_header`, `mcp_params` | `bottle.py`, with local stub | Bottle 0.13.2 |
| tool_recovery | `recover_date`, `recover_decode` | `bottle.py`, with local stub | Bottle 0.13.2 |

- **Hosts.** Bottle 0.13.2 and ms 2.1.3 are snapshots of MIT projects, with the commit and `git archive` SHA-256 recorded in `corpus/README.md`. Each task starts from the host with `bug.patch` applied. `bottle.py` has approximately 51 thousand tokens, estimated from character count, plus approximately 7 thousand from the OpenCode prompt. Therefore the control uses 64K.
- **Validation.** `corpus/validate_corpus.py` checks the hash manifest, applies patches to disposable copies, and requires the bug to fail by assertion while the reference, visible test, and original tests pass. For `authored_tests` tasks, the oracle is also validated against correct code and two distinct mutants. The correct code passes and the mutants fail. On the original corpus, all 12 tasks returned `PASS`.
- **Corpus v2.** 24 more tasks on the same hosts bring the corpus to 36 (10 python_fix, 5 javascript_fix, 6 continuation, 5 mcp, 5 tool_recovery, 5 authored_tests). They are not calibrated yet; see [corpus-v2-design.md](../reports/strategy-analysis-4b-2026-10-28/execution/F1/corpus-v2-design.md). The validator requires this frozen distribution and passes on all 36.
- **Stubs.** The `mcp` and `tool_recovery` tasks read output from a deterministic `tool.py`. It simulates external evidence but is not a real MCP server.
- **Continuation.** Phase 1 provides `TASK.md`, `verify_phase1.py`, and `visible_phase1.py`. Phase 2 (`followup.json`, `verify.py`, and `visible.py`) is released only after phase 1 passes the visible test, in the same OpenCode session.

The oracles, reference patches, and manifest are never copied to the agent's workspace. The runner copies only the host with the bug, `TASK.md`, the visible test, and the stub when applicable.

## 3. Private oracle and visible test

Each attempt has two evaluations.

- **Visible.** `verify.py` (or `verify_phase1.py`) runs in the workspace after the episode. It is for the agent, and failure counts as `model_visible_failed`.
- **Private.** The oracle at `corpus/oracles/<tarefa>/oracle.py` runs once at the end of the attempt, with pytest and the `corpus_probe` plugin. The plugin classifies each failing test as an assertion failure (or `pytest.fail`) or another error. The oracle passes if no test fails. It is a model failure if at least one test fails by assertion and none fails with another error. Any other combination, such as an import or execution error, is infrastructure (`grader_infrastructure`).

The oracle's content and result never enter the prompt or feedback given to the agent. An episode succeeds when there is no model failure, the oracle passes, and the visible test passes.

## 4. Isolation

Each `opencode run` runs inside bubblewrap 0.9.0. The arguments are as follows (`bwrap_command` in `benchmark/opencode_baseline.py`):

- `--die-with-parent` and `--unshare-pid`. Without `--unshare-net`, so networking is not blocked.
- `/usr` read-only, with `/bin`, `/lib`, and `/lib64` as links to it.
- `/proc` and `/dev`, with `/tmp` in tmpfs.
- The OpenCode binary mounted read-only at `/opt/opencode`, and Node at `/opt/node`.
- The episode workspace at `/workspace` (read and write), and the episode home at `/episode-home` (read and write). The home persists between the two continuation invocations.

The repository, `/mnt/d`, `/home`, oracles, and reference patches are not mounted. Before each attempt, `verify_isolation` runs a negative probe with the same mount options. It confirms that the workspace is readable and that the oracle, `/mnt/d`, and `/home` are not. The result goes to `isolation-probe.json`.

The OpenCode profile denies `webfetch`, `websearch`, subagents (`task`), and access to external directories (`external_directory`). It allows `bash` and `edit` in the workspace.

**Known limits.** Networking is not blocked. `bash` confinement has not been proven for all possible commands. The visible test and oracle run under the supervisor, outside the sandbox, and are not given to the agent.

## 5. Server and sampling

Each arm starts one `llama-server` instance with `--parallel 1`, `-ngl 99`, `--fit off`, `--flash-attn on`, `--jinja`, and `--no-webui`. Context, KV, and prompt cache come from the arm. An arm's episodes use the same server without restarting it. If the server dies, a new epoch starts and the previous cache is lost.

- **Thinking off:** temperature 0 (`--temp 0`), with `--reasoning off` and `enable_thinking=false`.
- **Thinking on:** temperature 0,6, top_p 0,95, top_k 20.
- **Prompt cache:** `--cache-prompt` in the control and `--no-cache-prompt` in arm `B-nocache`.

The runner uses a supervisor lock and refuses to start if `pgrep -x llama-server` finds another instance. A local proxy between OpenCode and the server records each request, TTFT (time to first content, reasoning, or tool call), and timings returned by the server (`prompt_n`, `cache_n`).

## 6. Per-attempt limits

- OpenCode runs with `--format json --pure`, `--agent build`, and model `local/local-qwen`.
- Steps: 40 in protocols v5 and v6. Arm `S-steps80` (stage 4) uses 80.
- Wall time: 600 s per attempt. Of these, 90 s are reserved for final verification.
- Output: 8 192 tokens per response.

## 7. Counting the first attempt

Each unit (arm, task, repetition) produces an attempt, and the first counts. The only exception is explicit infrastructure failure: `server_exited`, `server_http_error`, `harness_configuration_error`, and `grader_infrastructure`. These are retried once. If the second attempt is also an infrastructure failure, the stage stops.

A model failure is never retried. This rule was corrected in v6 (see section 9). The analysis tool (`baseline_report.py`) selects the first attempt and uses the second only when the first has one of the infrastructure failures above. The analysis uses the `failure` field, not `category`.

## 8. Failure classification

| Category | Label (`failure`) | Short label in tables |
|---|---|---|
| model | `model_oracle_failed` | oracle |
| model | `model_visible_failed` | visible |
| model | `model_phase1_incomplete` | phase 1 |
| model | `model_wall_timeout` | time |
| model | `model_cli_failure` | CLI |
| model | `model_protocol_error` | protocol |
| infrastructure | `server_exited`, `server_http_error`, `grader_infrastructure`, `harness_configuration_error` | server, grader |
| harness | `harness_missing_session`, `harness_session_mismatch` | session |

The current code also records a termination taxonomy with tags `wall_timeout`, `context_overflow`, `tool_error_loop`, `step_cap`, `no_edit`, `gave_up`, `wrong_file`, `broke_visible`, and `oracle_only`. **This taxonomy is not populated in v5 and v6 results**: the `taxonomy` field is null on failures, and diff and request metric fields do not exist because they were added to the runner later. Therefore the causes for stages 1 through 3 come from `failure` labels, and the tags do not appear in any claims.

## 9. Correction history

| Revision | Change | Reason |
|---|---|---|
| bwrap-v2 | corrected permission profile | OpenCode rejected the web permission syntax before inference |
| bwrap-v3 → v4 | corrected classification; repeated smokes | the runner assigned `model_protocol_error` to normal tool outputs |
| v4 → v5 | step limit from 20 to 40; `CORPUS_SUPPORT` passed to oracle | in v4, one episode (`tests_query` r2) aborted because `CORPUS_SUPPORT` was missing from the oracle environment and was excluded from the count. The limit change did not detectably change the rate (15 out of 23 versus 16 out of 24) |
| v5 → v6 | model failures are never retried | in v5, a phase 1 that exhausted 40 steps was classified as infrastructure and retried. The second attempt passed, inflating the pass rate |

In v5, control episode `cont_path` r2 is counted by its first attempt (failure). This is the rule in section 7.

## 10. Metrics

For each episode, the runner records:

- private oracle and visible test results;
- total time, TTFT per request, `prompt_n` and `cache_n` per request, and prompt and generation tokens summed across OpenCode turns;
- device VRAM sampled at approximately 1 Hz with `nvidia-smi`, with minimum, maximum, and mean;
- number of turns and tool calls;
- termination cause from the `failure` label.

Definitions of each aggregate metric are in [RESULTS.md](RESULTS.md). Proxy TTFT measures transport, not generation latency. VRAM measures the whole device.

## 11. Statistical analysis

- **Rate and interval.** 95% Wilson interval for each rate. With 12 episodes, the interval is wide.
- **Paired comparison.** Each arm is paired with the control by (task, repetition). Only pairs with both attempts are included. The test is exact, two-sided McNemar on discordant pairs.
- **Noise.** In the control, four tasks changed result between repetition 1 and 2. Differences of one or two episodes do not establish an effect.

## 12. Reproducibility

On the first run, `ensure_manifest` writes a `manifest.json` with the protocol, complete configuration, hashes of every runner, corpus, harness, and manifest file, the schedule, hashes of OpenCode, the server, bubblewrap, Node, Python, and each GGUF, and hashes of the provider dependency cache. If a result directory's manifest does not match the current one, the runner refuses to continue. This prevents results from different protocols from being mixed.

Raw results (workspaces, logs, and JSON per attempt) remain outside the repository. The repository contains aggregates in `results/3070-benchmark/` and stage reports in `reports/`.
