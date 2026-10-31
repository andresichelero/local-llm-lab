# T3a — stage 5 preparation, without GPU

Date: 29/10/2026. Runner `benchmark/baseline_stage5.py`, configuration `benchmark/configs/qwen-4b-opencode-stage5.json`, future results in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-stage5-v1`. Stage 5 was not executed. The stage 4 runner and configuration and the corpus were not changed.

## Matrix and download limit

Seven enabled arms, 12 tasks and one repetition: **84 units**. Inherited control: Q4_K_M bartowski, KV q4_0, 65536, cache enabled, thinking disabled, zero temperature and 40 steps. Q5-Q6KL and Q5-UDQ6XL change weights; T5-lsp enables LSP; T5-lsp-tool adds the experimental tool; T5-rtk enables the RTK plugin; X-think and X-9b are cascades. There is no additional control arm: for comparison, use the compatible stage 4 control with appropriate statistical care.

**Q5-UDQ4XL is disabled**. The three requested files total 11,016,974,624 bytes, above 10 GB and 10 GiB; searches in the caches at `/home/foxtrot` and `<local-model-cache>` found no copy. The two Q6 files total 8,104,864,896 bytes transferred. npm packages and the RTK file (6,844,596 bytes) are additional; exact npm traffic was not measured. The installed LSP directory occupies approximately 71 MiB; installed size is not a traffic measurement. The total for the three models alone prevents completing downloads within the authorized limit.

| Model | Status | Bytes | Revision | SHA-256 |
| --- | --- | ---: | --- | --- |
| [bartowski Q6_K_L](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/resolve/4168f45a16a1290d65a4ec0fa312ae917a4c15d6/Qwen_Qwen3.5-4B-Q6_K_L.gguf) | downloaded and verified | 3,959,316,448 | `4168f45a16a1290d65a4ec0fa312ae917a4c15d6` | `0d7931a7f143ccfdf675c0d84d542c387cd9255af94ee9c8fb5fa6f6df7c08a0` |
| [unsloth UD-Q6_K_XL](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-UD-Q6_K_XL.gguf) | downloaded and verified | 4,145,548,448 | `e87f176479d0855a907a41277aca2f8ee7a09523` | `87f58d94410b81429268d8389a3d686e6c6bffecf7852772720fbea059cbbb9d` |
| [unsloth UD-Q4_K_XL](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-UD-Q4_K_XL.gguf) | **not downloaded**; hash published in LFS, not verified locally | 2,912,109,728 | `e87f176479d0855a907a41277aca2f8ee7a09523` | `b252c5610a42ca82d20fe2a12813e9d069eed89292907e26c783eeb0bc961bc7` |

Both downloads are in `/home/foxtrot/local-llm-benchmark/models/gguf/qwen3.5-4b/`. The existing Q4_K_M 9B is [Unsloth](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-Q4_K_M.gguf), not bartowski: 5,680,522,464 bytes, SHA-256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`, revision `3885219b6810b007914f3a7950a8d1b469d598a5`. A 9B Q6_K was also found in `/home/foxtrot/local-llm-benchmark/state/qwen-hot/active/`; it is not used.

## Tools: offline evidence

The prefix `/home/foxtrot/local-llm-benchmark/envs/lsp-tools-20261029` contains pyright 1.1.414, typescript-language-server 6.0.2 and TypeScript 5.9.3. bwrap mounts only `node_modules` read-only at `/opt/lsp/node_modules`, with the runner's Node at `/opt/node`. `opencode debug config` accepted `lsp: true` in the sandbox with `--pure`. With `opencode debug lsp diagnostics /workspace/test.py`, Pyright returned a real diagnostic for assigning a string to `int`, identified by `source: Pyright`; a wrapper in HOME recorded its invocation. Evidence: `/tmp/stage5-tool-proof-20261029/lsp.out` and `home/pyright-start.log`. Per-episode wrappers record startup attempts in `home/lsp-starts.log`, and `lsp.log` retains OpenCode log lines. `lsp_started: null` means the invocation log alone does not confirm readiness; diagnostics/events are needed to establish it. `lsp_tool_calls` counts `tool_use` events for the `lsp` tool.

The TypeScript server is installed and accessible, but diagnostics for TS/JS files returned `{}` and an explicit configuration timed out; operation for JS was not established. This should not count as proof of startup or diagnosis.

RTK 1.1.0 is at `/home/foxtrot/local-llm-benchmark/envs/rtk-tools-20261029/rtk`; binary SHA-256 `f4d2f533d4e82e797cad3fbcd8d4a4f85351c4871d49a6202f5bc7a3e8c5c568`. The plugin was generated with `rtk init -g --opencode` in an isolated HOME. The runner copies only the plugin into the episode HOME and mounts only the binary read-only at `/opt/rtk/rtk`. Since `--pure` prevents external plugins, the RTK arm runs without it; this is a necessary part of the intervention. OpenCode 1.19.5, bwrap and a local fake provider, without inference, produced a bash event `input.command: "rtk git status"`, `status: completed`, `metadata.exit: 0`; evidence `/tmp/stage5-tool-proof-20261029/rtk.out` and `rtk.err`. `rtk hook opencode 'git status'` returned `{"command":"rtk git status"}`. This evidence does not measure filter gains or quality in real episodes.

The stage 5 manifest pins hashes of the runner, configuration, models, LSP dependencies, RTK binary and plugin, in addition to checks inherited from the runner. Evidence in `/tmp` is temporary; each episode's results will retain their own logs and events.

## Cascades, metrics and limits

The decision uses visible verification failure, including phase 1, or an identified model failure. An oracle-only failure does not escalate; server and harness failures do not become model failures. Private grader exceptions are recorded as infrastructure without erasing the visible result. The second attempt gets a new workspace directory and HOME. X-think restarts the server with reasoning on and sampling 0.6/0.95/20. X-9b uses the existing model, KV q4_0 and tries contexts 65536, 49152, 32768, 16384 and 8192 in order, requiring at least 500 MiB free at load and in episode sampling; confirmed OOM or insufficient headroom permits trying the next context. At 8192, the output limit is reduced from 8192 to 4096 to leave input space. A generic failure is not called OOM. Actual behavior, stability, viable context and peak have not yet been measured on GPU.

Attempts retain T1's `result.json`, events, diffs and metrics. `cascade.json` records both logical attempts, decision, times, samples and switches; additional OOM attempts remain in separate directories. Per-arm `summary.json` contains first-attempt rate, final rate, escalations, total time and extra time. Load logs and `model-switches.json` record contexts, OOM evidence and unload/load times; VRAM sampling covers the entire device at approximately 1 Hz and may miss brief peaks. The inherited `baseline_report` analysis selects attempts by its own policy and does not replace the stage 5 cascade summary.

## Verification and future execution

Tests with fake components cover attempt isolation, decisions without oracle, server failure, context switches, prior logs, OOM, wrappers and summary. The focused suite `tests/test_baseline_stage5.py tests/test_opencode_baseline.py tests/test_baseline_report.py` passed: **60 tests**, with `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`; Ruff on the two new Python files: **All checks passed**. The dry run listed 84 enabled units. The project has no typecheck configuration. A full suite was not run during the active campaign because it includes other launchers and processes that had not all been audited for this restriction.

After stage 4 finishes and the GPU is released, the command below runs only the **84 enabled episodes**, not the Q5-UDQ4XL arm:

```sh
cd /path/to/4b-worker-v2
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.baseline_stage5 --dry-run --stage 5
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.baseline_stage5 --stage 5
```

The runner refuses to start if `llama-server` is already running. An interrupted unit with partial attempts requires manual review; its files are not automatically overwritten.

## Orchestrator update (29/10, 06h)

Codex reached its usage limit before the commit. The orchestrator downloaded UD-Q4_K_XL (2,912,109,728 bytes, sha256 `b252c561…961bc7`, matching Hugging Face's `x-linked-etag` at revision `e87f1764`) and enabled the **Q5-UDQ4XL** arm. Stage 5 now has **96 episodes**. `tests/test_baseline_stage5.py`: 22 tests pass; `--dry-run` lists 96 units.
