# F1 B — OpenCode baseline runner

## Stage 2: isolation and real smoke tests (29/10/2026)

Qualification of the two smoke tests below is complete; the 132-episode campaign was not started. Final protocol `qwen-4b-opencode-baseline-b-20261029-bwrap-v4`, raw result at `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v4/`. The stage 1 record below is historical, and its limitations concerning the lack of a sandbox and smoke tests do not describe stage 2.

### Isolation

Each `opencode run` call is launched by bubblewrap 0.9.0 with `/usr` read-only, symlinks `/bin`, `/lib`, `/lib64`, `/proc`, `/dev`, `/tmp` in tmpfs, a PID namespace and `--die-with-parent`. The real binary is mounted read-only at `/opt/opencode`, Node at `/opt/node`, the workspace at `/workspace` (rw) and the episode's persistent home at `/episode-home` (rw), outside the evaluated workspace. `HOME` and `XDG_*` point to that home and the command uses `--dir /workspace`. The same home persists across the two continuation invocations. The repository, `/mnt/d`, `/home/foxtrot`, oracles and reference patches are not mounted.

The network is shared: **bubblewrap does not block access to the external network or other services accessible on the host network**. The profile denies webfetch/websearch, but does not prevent a bash command from using the network. The manifest records this limitation and the bubblewrap executable hash. The visible evaluation and oracle still run under the supervisor outside the sandbox; they are not given to OpenCode as feedback.

The negative probe runs automatically using the same function and mount options as the OpenCode invocation. It tests reading `/workspace/TASK.md`, attempts `cat` on the actual absolute oracle path, `ls /mnt/d` and `ls /home`, without displaying private content. In both final episodes the output was:

```text
workspace_readable oracle_denied mnt_d_denied home_denied
returncode=0; --unshare-pid presente; --unshare-net ausente
```

The complete probe, including command and result, is in each attempt's `isolation-probe.json`. The automated test performs the same check, and OpenCode 1.19.5 `debug config` was validated inside bubblewrap without inference.

### GPU smoke tests: final results

Prompt token values are the sum of usage recorded by OpenCode turns, including cached tokens; they do not represent unique tokens. The `prompt_n` and `cache_n` ranges come from the timings of all requests captured by the proxy, including auxiliary requests. TTFT is the median of requests with first content detected. Peak VRAM samples the entire device, not memory exclusive to the process.

| Measure | B0 `py_query` | B0 `cont_path` |
|---|---:|---:|
| Cause / category | `model_oracle_failed` / model | `null` / success |
| Visible test | failed | passed both phases |
| Private oracle | failed | passed |
| Total time | 47,40 s | 106,05 s |
| Model turns | 20 | 27 |
| Tool calls | 20 | 26 |
| Prompt tokens (sum, including cache) | 582.381 | 724.104 |
| Generated tokens | 1.403 | 4.205 |
| Requests with timings | 21 | 28 |
| `prompt_n` minimum–maximum | 21–12.558 | 21–21.997 |
| `cache_n` minimum–maximum | 0–34.720 | 0–31.259 |
| Median TTFT | 314,8 ms | 251,8 ms |
| Device peak VRAM | 5.329 MiB | 5.325 MiB |
| OOM evidence in log | no | no |

In the continuation, phase 1 finished in 57,91 s and phase 2 in 41,22 s; both returned code 0 and session `ses_e7a21b829ffeMCGvh2KtLxpQOx`. The phase-one visible test passed before the next files and objective were released. `result.json`, `events.jsonl`, `server-segment.log`, `workspace.diff`, `oracle-probe.json` and `isolation-probe.json` are in the `smoke/B0/py_query-r1/attempt-01/` and `smoke/B0/cont_path-r1/attempt-01/` directories of the protocol above.

OpenCode event excerpts, without oracle content, show work in the mounted path:

```text
py_query:  {"command": "cat /workspace/visible.py"}
py_query:  {"command": "sed -n '3051,3100p' /workspace/bottle.py"}
cont_path: {"filePath": "/workspace/bottle.py"}
cont_path: {"filePath": "/workspace/verify_phase1.py"}
cont_path: {"command": "grep -n \"^def \" /workspace/bottle.py | head -30"}
```

Commands executed in WSL from the worktree root:

```sh
PY=/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python
"$PY" -m benchmark.opencode_baseline --smoke
"$PY" -m benchmark.opencode_baseline --smoke --task cont_path
"$PY" -m pytest -q tests/test_opencode_baseline.py tests/test_qwen_f1_diagnostic.py tests/test_opencode_controlled_probe.py
# 26 passed in 17.59s
/home/foxtrot/.vscode-server/extensions/charliermarsh.ruff-2026.54.0-linux-x64/bundled/libs/bin/ruff check benchmark/opencode_baseline.py tests/test_opencode_baseline.py
# All checks passed!
```

The first two development attempts were preserved without retroactive reclassification. In `bwrap-v2`, OpenCode rejected the web permission syntax before inference; the profile was corrected and tested with the real CLI. In `bwrap-v3`, both episodes passed the oracle and the continuation retained its session, but the runner incorrectly assigned `model_protocol_error` while examining normal tool output. Tests reproduced and corrected the classification; the smoke tests were repeated in `bwrap-v4`. Results varied across repetitions and do not demonstrate statistical effectiveness.

## Historical stage 1 record (28/10)

Historical stage 1 status on 28/10/2026: implementation and offline checks. No GPU smoke test or campaign stage was run at this stage. The runner still needs qualification with real OpenCode and llama-server before the campaign.

## Architecture and contract

`benchmark/opencode_baseline.py` prepares a host copy for each task, applies `bug.patch` and provides `TASK.md`, the visible test and, where specified, `tool.py`. For continuation, it releases the phase 2 objective and test only when the first run finishes, provides a session ID and passes the phase 1 visible test; the second call uses `--session` with the same ID. The oracle runs once per attempt, at the end, without inserting its content or result into the prompt. Evaluation uses the classification contract in `corpus/validate_corpus.py`. The initial snapshot and final change produce `workspace.diff`.

The runner uses an isolated OpenCode profile and HOME/XDG environment, `opencode run --format json --pure`, a local provider and the dependency cache from the previous path. One llama-server remains active per arm without restarting between episodes; a new invocation or recovery of a dead server creates a new epoch and loses the previous cache. A local proxy records responses and TTFT per request; server logs and proxy timings preserve `prompt_n` and `cache_n` when available. Events record turns, tool calls and tokens. `nvidia-smi` is sampled every second; the peak covers the entire device. OOM is marked only when the log contains corresponding evidence. Each attempt has its own result; infrastructure failures are repeated once, and model failures do not stop subsequent tasks. The manifest fixes the protocol, schedule, config, corpus and code hashes, server, OpenCode, models, Python, Node and provider cache; mismatches prevent mixing results.

## Configuration

- Protocol: `qwen-4b-opencode-baseline-b-20261028-v1`; results at `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-b-v1`.
- Control B0: Q4_K_M, KV K/V q4_0, 65536, cache on, thinking off, temperature 0. Stage 1: 24 episodes, two repetitions of the 12 tasks.
- Stage 2: B-ctx16/32/128 and B-kv8/16, 12 episodes per arm, 60 total. Stage 3: B-q6, B-q8, B-nocache and B-think, 12 per arm, 48 total. Total: 132.
- Thinking on: temperature 0,6, top_p 0,95, top_k 20. Server: `--parallel 1`, `-ngl 99`, `--fit off`, flash attention on, `--reasoning` and `enable_thinking` according to the arm. `--cache-prompt` or `--no-cache-prompt` according to the arm.
- Wall 600 s per attempt, reserving up to 90 s for final verification, and 20 OpenCode steps, the same value as `MAX_PRIMARY_STEPS` in `prefix_cache_paired.py`; 600 s limits cost per episode without demonstrating that it suffices for the 12 tasks. Configured maximum output: 8192 tokens.
- OpenCode `.bin/opencode`: version 1.19.5, SHA-256 `7df4e4136301f16589b0f30bf91a61380fca5f8ef22dd36570f5ebe1d4ec802c`.
- llama-server: `0.8.0-dev`, build 1, commit `8642541`; SHA-256 `da1068f30d898c10c02c754ebef3b5b877073213989ff5ef9dfb2d4332e265f0`.
- Q4_K_M bartowski: `13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983`; Q6_K unsloth: `fdedd781c9ce676ab66b018ca247ff78e8a33c98098a822c1e2d5075e7718f66`; Q8_0 unsloth: `10cc391b403021dd11c614679d2fd92f611c3681d29e29651b717316965d61e1`. All three hashes were calculated in this stage.

## Commands

In WSL, from the worktree root:

```sh
PY=/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python
"$PY" -m benchmark.opencode_baseline --dry-run
"$PY" -m benchmark.opencode_baseline --dry-run --arm B0
# Qualificação posterior, ainda não executada:
"$PY" -m benchmark.opencode_baseline --smoke
"$PY" -m benchmark.opencode_baseline --smoke --task cont_path
# Campanha posterior, exclusivamente por decisão do orquestrador:
"$PY" -m benchmark.opencode_baseline --stage 1
"$PY" -m benchmark.opencode_baseline --stage 2
"$PY" -m benchmark.opencode_baseline --stage 3
# Alternative for a single arm:
"$PY" -m benchmark.opencode_baseline --arm B-kv8
```

Stage 2 depends on the plan's gate: at least 3/12 on the control and no infrastructure failures. The runner does not automate this decision; the orchestrator must check the results before starting the next stage.

## Offline checks performed

```text
$ python -m pytest -q tests/test_opencode_baseline.py tests/test_qwen_f1_diagnostic.py tests/test_opencode_controlled_probe.py
23 passed in 15.04s
$ ruff check benchmark/opencode_baseline.py tests/test_opencode_baseline.py
All checks passed!
$ python -m benchmark.opencode_baseline --dry-run | tail -n 4
130 stage=3 arm=B-think task=recover_decode rep=1
131 stage=3 arm=B-think task=tests_query rep=1
132 stage=3 arm=B-think task=tests_range rep=1
Total: 132
$ python -m benchmark.opencode_baseline --dry-run --arm B0 | tail -n 2
024 stage=1 arm=B0 task=tests_range rep=2
Total: 24
```

`compileall` of the two Python files exited with code 0. The corpus comparison returned `320 320 True`; offline manifest construction returned 132 units, 326 repository file hashes and 3657 cache entries. The tests use a fake CLI and server; simulated continuation retained the session across both phases and ran the real oracle at the end, with the expected failure because no edit was made. There are no real inference timings or cache_n values at this stage.

## Limitations and differences from October

- The profile limits declared OpenCode permissions, but bash and network lack proven system confinement. In principle, the agent can reach host files, including private material outside the workspace. Episode directories and environments are isolated, but this is not a security boundary; no credentials are intentionally provided to the agent. The orchestrator accepted this limitation for the baseline.
- Visible tests and the oracle execute workspace code without a proven OS sandbox. Private outputs remain outside the workspace and are not sent to the model, but the lack of bash confinement prevents a guarantee that it cannot find them itself.
- The 600 s deadline limits subprocesses and reserves time for verification, but file copies and reads are not preemptive and can exceed the deadline on slow I/O.
- Proxy TTFT is the time to the first detected content, reasoning or tool call; it is a transport measurement and may be unavailable. `prompt_n`/`cache_n` depend on the format actually returned by the server; empty lists or missing timings mean not measured, not zero. Device usage does not identify the process responsible for the peak.
- The profile, provider cache, updated CLI, proxy, phased release, corpus and oracle differ from the October experiments. Actual handling of sampling, streaming, continuation, cache and error 500 still requires a real smoke test; an offline pass does not prove these behaviors in inference.
- Changes to the runner or artifacts after manifest creation require a new directory/protocol; resuming in another invocation restarts the server and does not retain the previous cache state. Classification between model parser error and infrastructure HTTP error depends on the textual evidence in logs and events.




