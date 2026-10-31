# T1 — collection and stage 4 preparation

Date: 29/10/2026. Worktree `feat/4b-worker-v2`. New protocol `qwen-4b-opencode-baseline-b-20261029-bwrap-v7`, output `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v7`. Stage 4 was not run. The ongoing v6 campaign and its results directory were not accessed.

## Collection

- `diff_quality` compares the initial and final snapshots and records added/removed lines, changed files outside `writable_files` and `relevant_files`, new files, deleted tests and potentially weakened tests. Files released by the supervisor during continuation are updated in the reference snapshot. If a binary file changes, line totals are `null`.
- Test heuristic: paths with test names are examined for `assert*`, `expect(...)` and `should(...)` expressions; a reduced count or increase in trivial asserts (`assert True`, `assert 1` and recognized equivalents) signals possible weakening. It does not prove semantic equivalence and may produce false positives and negatives.
- `tokens_after_last_edit` requires a completed edit event with a tool diff sharing a change with the final diff of the same file. A later bash command, incomplete usage data or lack of this evidence results in `null`; it discards the first `step_finish` after the edit, belonging to the response that requested it.
- Proxy timings preserve requests; `request_metrics` records medians of `prompt_per_second` and `predicted_per_second` and totals of `prompt_n`, `cache_n` and their sum. An incomplete total is `null`, not a partial sum. Values are sums per request, not unique tokens.
- Sampling at approximately 1 Hz: total WSL CPU via `/proc/stat`, available WSL RAM via `/proc/meminfo`, available Windows RAM via `Get-CimInstance` in an independent thread with timeout, and device VRAM via `nvidia-smi`. Samples and minimum, maximum and mean per episode are stored. The first CPU reading and unavailable readings are `null`; VRAM represents the entire device, not just the process. Windows RAM is `null` when interoperability fails or times out.

## Automatic taxonomy

The first tag in the order below is primary and the others are secondary. Signals are heuristic; success receives no tags and an absent event is not proof of absent behavior.

1. `wall_timeout`: failure `model_wall_timeout`.
2. `context_overflow`: context overflow message in events or stderr.
3. `tool_error_loop`: same tool and same error/output text at least three times; includes `error`/`failed` status and nonzero bash exit in `metadata.exit`.
4. `step_cap`: at least the configured limit of `step_finish` events in one phase.
5. `no_edit`: final diff without changed files.
6. `gave_up`: no edit, text after the last tool, ending with oracle/visible/phase 1 failure and no `step_cap`.
7. `wrong_file`: at least one changed file outside the relevant files.
8. `broke_visible`: visible verification failed.
9. `oracle_only`: visible passed and oracle failed.

## Analysis

`python -m benchmark.baseline_report DIR... --markdown relatorio.md --csv relatorio.csv` generates tables by arm, task/repetition, arm comparison by task and task/repetition pairs. It calculates Wilson 95%, exact McNemar, times, TTFT, rates, VRAM, tokens, waste and available tags. Missing values remain blank. A single repetition has `insufficient` stability. To use a control from another protocol, add `--control-dir DIR_CONTROLE --control B0`; data from distinct protocols are not merged.

It selects the first attempt except `server_exited`, `server_http_error`, `harness_configuration_error` or `grader_infrastructure`, using `failure`, not `category`. This retains the first attempt incorrectly classified as infrastructure in v5. Infrastructure-only attempts are excluded and not converted into model failures. Older results without taxonomy or complete timings do not receive invented values.

Run only on v5, without reading v6: B0 **16/24**, rate 0,6667, Wilson 95% [0.4671; 0.8203]; median time 42,2508 s; 6,722,306 prompt tokens, 85.053 generated and 1.528,6387 s in unsuccessful episodes. Server totals remained blank because not all requests had complete timings. Outputs persisted alongside this report: `T1-analysis-v5.md` and `T1-analysis-v5.csv`.

## Stage 4

All use Q4_K_M bartowski, KV q4_0/q4_0, context 65536, cache enabled, thinking disabled, temperature 0 and 40 steps, except for the indicated factor. There are 12 tasks per repetition.

| Arm | Change | Repetitions | Units |
| --- | --- | ---: | ---: |
| C4-q4 | control | 3 | 36 |
| C4-q6 | Q6_K Unsloth | 3 | 36 |
| S-qwen-sampling | temperature 0.7; top_p 0.8; top_k 20; min_p 0; presence_penalty 1.5 | 1 | 12 |
| S-steps80 | 80 steps | 1 | 12 |
| S-ctx48 | context 49152 | 1 | 12 |
| S-cache-reuse | `--cache-reuse 256 --ctx-checkpoints 16` | 1 | 12 |
| S-mtp | `--spec-type draft-mtp` | 1 | 12 |
| S-q4-unsloth | Q4_K_M Unsloth | 1 | 12 |

The v0.8.0 server `--help` confirms the three flag names; `common/speculative.cpp` creates the MTP draft context from the target, and the control GGUF contains `qwen35.nextn_predict_layers=1` and `blk.32.nextn.*` tensors. Interface support and metadata do not demonstrate operation or inference gains. The Unsloth model card at the revision below confirms general non-thinking parameters. The sampling profile was accepted by `opencode debug config` offline.

Unsloth model: `Qwen3.5-4B-Q4_K_M-unsloth.gguf`, 2,740,937,888 bytes, `/home/foxtrot/local-llm-benchmark/models/gguf/qwen3.5-4b/`; revision `e87f176479d0855a907a41277aca2f8ee7a09523`, SHA-256 `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4`, verified after download. URL: https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q4_K_M.gguf.

## Verification and future execution

In WSL, from `<workspace>`:

```text
$ /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -q tests/test_opencode_baseline.py tests/test_baseline_report.py tests/test_qwen_f1_diagnostic.py tests/test_opencode_controlled_probe.py
49 passed in 29.81s
$ /home/foxtrot/.local/bin/ruff check benchmark/opencode_baseline.py benchmark/baseline_report.py tests/test_opencode_baseline.py tests/test_baseline_report.py
All checks passed!
$ python -m compileall -q benchmark/opencode_baseline.py benchmark/baseline_report.py tests/test_opencode_baseline.py tests/test_baseline_report.py
exit 0
$ /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.opencode_baseline --dry-run --stage 4
001 stage=4 arm=C4-q4 task=cont_path rep=1
002 stage=4 arm=C4-q4 task=cont_quote rep=1
...
144 stage=4 arm=S-q4-unsloth task=tests_range rep=1
Total: 144
```

The `compileall` above used the same validation Python. The complete listing is in `T1-stage4-dry-run.txt` alongside this report. No typecheck configuration was identified in the project; compilation does not replace a type checker.

Command for later execution, **not run in this task**:

```sh
cd /path/to/worktree
/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.opencode_baseline --stage 4
```
