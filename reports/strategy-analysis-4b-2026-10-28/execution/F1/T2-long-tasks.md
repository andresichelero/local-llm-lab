# T2 — long-task robustness

Status: implementation, offline checks and two GPU smokes completed. The campaign was not run. Limitations of phase 1 oracles and adversarial grader integrity remain open.

## Corpus design and limits

Each marathon uses a copy of Bottle with all pertinent bug patches applied before the first submission. M1 contains `py_query`, `py_range`, `cont_quote:1`, `cont_quote:2` and `recover_decode`. M2 contains `mcp_header`, `mcp_params`, `recover_date`, `cont_path:1`, `cont_path:2` and `tests_range`: there are **six** objectives in the requested enumeration, despite the reference to five in the request text. Objectives are released in order after the previous call ends, without requiring it to pass. The maximum is 40 steps per objective and 1800 s per marathon, including preparation and evaluation; the supervisor reserves time for evaluations and classifies termination due to that reservation separately as `supervisor_wall_budget`. In embedded OpenCode 1.19.5 code, the `agent.steps` counter resets per prompt even when resuming a session; it counts agent iterations, including compaction processing, and does not necessarily correspond to the number of `step_finish` events.

The corpus has no private oracle for the first phases of `cont_quote` and `cont_path`. Their visible tests already pass with the bugs applied. The private result of these phases is therefore `null`, with `no_private_phase1_oracle`; visible tests are recorded separately. It is incorrect to say that all objectives have a private oracle or that all initially fail. There are private oracles for the final contracts of both tasks.

Offline check of combinations: all four private M1 oracles and all five M2 oracles failed with combined bugs and passed with all combined references. Patches applied without conflict. `tests_range` has an empty `bug.patch`; its oracle initially fails because the required test is absent.

## Arms and isolation

All use control Q4_K_M, KV K/V q4_0, prompt cache enabled, thinking disabled, temperature 0 and the control output limit. `L-compact` uses one session and context 32768; `L-bigctx`, one session and 131072; `L-reset`, context 32768 and a new session per objective, with `PROGRESS.md` containing previous objectives, `git diff --stat` and visible results, without private results. `L-headroom` uses one session, 32768, plugin 0.42.0 mounted read-only and a local Headroom proxy chained to the metrics proxy. The plugin does not load with `--pure`, so only this arm removes that option. The proxy uses `--stateless --no-cache --disable-kompress --no-telemetry --no-subscription-tracking`: disabling Kompress avoids depending on downloads; other optimization mechanisms remain enabled. llama-server prompt cache remains enabled.

OpenCode 1.19.5 accepts `compaction: {"auto": true}`; the binary reports that the default is also true. Compaction requests are counted in session SQLite `type=compaction` parts; this does not confirm that the summary completed. The `run --format json` stream does not expose these parts. An offline test with a fake provider observed one compaction part, and another fake-provider test confirmed plugin loading and `headroom_retrieve` inside bwrap, along with two forwarded requests and schema compaction. Temporary files from these proofs were removed; this evidence does not establish history compression in real inference.

An initial plugin proof attempted to query `models.opencode.ai` and failed resolution. The runner sets `OPENCODE_DISABLE_MODELS_FETCH=true` to prevent that query. The OpenCode sandbox shares the host network, as in baseline; it is not a barrier to network calls made by bash. Visible and private graders use another bwrap, with read-only workspace and isolated network. Their private results are not delivered to the model. Integrity limitation: evaluated code and oracle share the grader process and namespace; adversarial code can read the oracle or tamper with the grader report. The implementation does not provide adversarial isolation between test and evaluated code.

The runner stores evaluations after each released objective and at the end, regressions after an observed pass, duration, tokens when available, requested compactions, resets, evolution of `prompt_n + cache_n` per request with observed completion time, context errors, resource samples and applicable baseline metrics. A missing value remains `null`. The primary `compactions` field comes from SQLite; nested `usage.compactions` is inherited from JSON event summarization and does not detect these requests. VRAM sampling covers the entire device. Each marathon starts its own server process; the manifest records this difference from baseline. The lock is shared by T2 modes and baseline/llama processes are checked before starting; other supervisors that do not share this lock can still introduce a startup race.

## Execution

The `--dry-run` mode lists the eight units, interleaving arms and marathons. The smoke uses the first two M1 objectives in `L-compact` and `L-reset`. The full campaign is left to the orchestrator:

```sh
cd /path/to/worktree
/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.long_tasks --dry-run
/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.long_tasks --smoke
# Somente pelo orquestrador, depois de avaliar as limitações acima:
/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.long_tasks --run
```

## Smokes and checks

Stage 3 was active at the first check; the authorized 60 s loop waited until the process exited. Both smokes ran afterward, without running the campaign:

```text
{"unit": {"arm": "L-compact", "marathon": "M1", "repetition": 1}, "failure": "model_oracle_failed", "error": null, "passed_final": 1}
{"unit": {"arm": "L-reset", "marathon": "M1", "repetition": 1}, "failure": "model_oracle_failed", "error": null, "passed_final": 1}
```

| Measure | L-compact | L-reset |
| --- | ---: | ---: |
| Final oracles `py_query`, `py_range` | passed, failed | passed, failed |
| Visible checks for each submission | passed, passed | passed, passed |
| Submission time | 24,80 s; 15,37 s | 23,52 s; 21,85 s |
| Total attempt time | 48,57 s | 54,61 s |
| OpenCode prompt / generated tokens | 217.337 / 1.892 | 249.916 / 1.570 |
| Requests with timings / total | 18 / 18 | 19 / 19 |
| Compaction requests in SQLite | 1 | 2 |
| Resets | 0 | 1 |
| Peak device VRAM | 4.079 MiB | 4.076 MiB |
| Detected context overflow occurrences / OOM evidence | 0 / no | 0 / no |

In both, the `py_query` oracle passed after the first submission and remained passing after the second; `py_range` failed final evaluation despite passing the visible test. No regression was observed. `L-compact` retained the same ID across both calls; `L-reset` used different IDs and the inspected `PROGRESS.md` contained the previous objective, visible status and diff. Both OpenCode isolation proofs passed. Per-objective results are not proof of statistical efficacy.

Raw artifacts in WSL: `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-long-tasks-20261029-v1/smoke/L-compact-M1-r1/attempt-01/` and `.../smoke/L-reset-M1-r1/attempt-01/`, including `result.json`, `events.jsonl`, per-stage evaluations, `workspace.diff` and isolation proof. The smoke servers were stopped.

Final checks: `pytest -q tests/test_long_tasks.py tests/test_opencode_baseline.py tests/test_baseline_report.py tests/test_qwen_f1_diagnostic.py tests/test_opencode_controlled_probe.py` with the requested Python: **63 passed**. Ruff on T2 files and covered baseline/report files: **All checks passed**. `compileall` ended with code 0; no typecheck configuration was found in the project, and compilation is not typecheck. The existing baseline schedule test was updated from 276/144 to 300/168 units after an external commit added two repetitions of `C4-think`; the two protected files were not edited by T2.

The full `pytest -q` suite is not green: **16 failed, 1083 passed, 19 skipped, 187 subtests passed**. Rerunning only the failures confirmed: six failures where WSL Git cannot resolve the Windows path in this worktree's `.git` file; eight failures from missing manifests/catalogs of other campaigns; and two from insufficient space for download and hot-cache test floors. At verification there were approximately 6,7 GiB free on the Linux filesystem. These problems were not fixed with global changes, fabricated files or data cleanup. The 63 focused tests above passed independently of the full suite.
