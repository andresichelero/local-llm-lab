<img src="docs/figures/hero.svg" alt="Local LLM Lab: Qwen3.5-4B, llama.cpp and OpenCode on an RTX 3070 with 8 GB." width="100%">

A coding agent is a program that reads a codebase, edits files and runs commands to finish a task on its own. Most of them depend on large cloud models. This repository tests how far one can go with a small model running at home, on a single 8 GB graphics card.

We plant bugs in two real open-source projects, ask the agent to fix them and check each fix with tests it never sees. Then we change one setting, run everything again and compare pass rate, time and video memory.

## Results so far

A close variant of the setup we recommend fixed 31 of 36 task attempts (86%) on llama.cpp master and peaked at 4,973 MiB of video memory.

- Retrying a failed attempt once, with the model's thinking mode on, raised one setup from 22 to 30 passes out of 36. This is the only statistically significant gain so far (p = 0.008).
- A 16K context window passed 3 of 12 attempts. At 32K and above, passes stayed between 67% and 75%.
- The prompt cache made the first token arrive 8 to 100 times sooner.
- Higher-precision weights, a larger KV cache and the RTK output filter showed no measurable benefit.

These numbers come from one machine and 12 tasks, so treat them as early results. The [limitations](#limitations) section lists what they cannot show.

To run this yourself, start at [Recommended setup](#recommended-setup). The method is in [How it works](#how-it-works), and every table is in [docs/RESULTS.md](docs/RESULTS.md).

## How it works

<img src="docs/figures/pipeline.svg" alt="Flow of one episode. A task goes to the OpenCode agent, which talks to llama-server. The visible test runs next. If it passes, the private oracle scores the attempt. If it fails, the agent retries once with thinking on." width="100%">

One run of one task is called an **episode**. The agent gets a copy of a project with a bug in it and a written request. It works until it stops on its own or reaches a limit of 40 steps or 10 minutes.

Two checks then run. The **visible test** is one the agent can read and run itself. The **private oracle** is a second set of tests kept outside the agent's sandbox, so it cannot adapt its answer to them. An episode passes only if both succeed.

If the visible test fails or the agent crashes, some setups retry once with thinking on. An attempt that passes the visible test and fails the oracle gets no retry, because the agent has no sign that anything is wrong.

### The tasks

The set of tasks is called the **corpus**. All results below use the 12 tasks in this table, on copies of two small open-source projects: [Bottle](https://github.com/bottlepy/bottle), a Python web framework, and [ms](https://github.com/vercel/ms), a JavaScript time-format library. The tasks are synthetic: we planted each bug ourselves, so we know the correct fix.

| Task | Project | Type | What the agent has to do |
| --- | --- | --- | --- |
| `py_query` | Bottle | Fix a bug | Decode form query strings: plus as space, percent escapes, blank values, repeated keys |
| `py_range` | Bottle | Fix a bug | Repair HTTP byte ranges: inclusive ends, clamping to the file length, skipping invalid ranges |
| `js_sign` | ms | Fix a bug | Parse signed durations, keeping fractions and case-insensitive units |
| `js_plural` | ms | Fix a bug | Restore the singular/plural limit at 1.5 units, for negative durations too |
| `tests_query` | Bottle | Write tests | Cover query parsing with new tests, without changing the code |
| `tests_range` | Bottle | Write tests | Write tests that catch byte-range regressions, without changing the code |
| `cont_quote` | Bottle | Two requests | Escape HTML characters, then also escape control whitespace in attributes |
| `cont_path` | Bottle | Two requests | Shift path fragments in both directions, then keep the trailing slash |
| `mcp_header` | Bottle | Use a tool first | Read a tool's report, then fix how header names are normalized |
| `mcp_params` | Bottle | Use a tool first | Read a report about a parser failure, then fix parameter names |
| `recover_date` | Bottle | Diagnose a failure | Read a failure report, then repair HTTP date conversion |
| `recover_decode` | Bottle | Diagnose a failure | Read a failure report, then repair byte-to-text conversion |

In the two-request tasks, the second request arrives in the same session after the first one passes its visible test. The `mcp` and `recover` tasks use a small scripted tool, not a live service.

The agent can give a different answer to the same task even at temperature 0, and in the control four tasks changed result between two runs. That is why tasks run more than once. Each run is a **repetition**, and each row of the [task chart](#6-the-corpus-is-now-the-main-limit) shows three squares per setup, one per repetition.

### What we change

**Control** is the baseline setup: Q4_K_M weights, q4_0 KV cache, 64K context, prompt cache on, thinking off, temperature 0. Each alternative setup, called an **arm**, changes something from the control.

| Setting | What it means | Values tried |
| --- | --- | --- |
| Context size | How many tokens the model can hold at once: the request, the code it read and the conversation so far | 16K, 32K, 48K, 64K, 128K |
| KV cache | How that context is stored in video memory. Smaller formats use less memory | q4_0, q8_0, f16 |
| Weights | The model file, stored at reduced precision so it fits the card. Higher numbers are larger and more precise | Q4, Q6 and Q8 variants |
| Prompt cache | Reuses work done on earlier text, so each turn processes only what is new | On, off |
| Thinking | The model writes out its reasoning before it answers, which takes longer | Off, always on, retry only |
| Sampling | How the next token is chosen. Temperature 0 always takes the most likely one | Temperature 0, 0.6, Qwen's recommended values |
| Steps | The limit on agent turns per attempt | 40, 80 |
| MTP | A small extra layer in the model guesses the next tokens ahead of time, which speeds up generation | Off, 2 tokens |
| Context checkpoints | The server keeps snapshots of its state, so it can go back to an earlier point without reprocessing the text | Off, 64 snapshots |
| `--cache-ram` | The limit on system memory used to keep prompts | 8 GiB (default), 2 GiB |
| RTK | [A tool](https://github.com/rtk-ai/rtk) that shortens command output before the agent reads it, for example keeping only test failures | Off, on |
| LSP | Gives the agent Pyright's code diagnostics | Off, on |

### What we ran

| Campaign | Question | Runs |
| --- | --- | --- |
| Stage 1 | How does the control perform? | 24 episodes |
| Stage 2 | Do context size and KV cache change the result? | 60 episodes |
| Stage 3 | Do weights, prompt cache and thinking change it? | 48 episodes |
| Stage 4 | Do the early results repeat? Do server options help? | 168 episodes |
| Stage 5 | Do other weights, code tools or a retry help? | 96 episodes |
| Replication | Does the retry with thinking hold up? Does RTK hurt? | 72 episodes |
| Combined | Do the best options work together? | 72 episodes |
| T2 | Which approach copes best with very long tasks? | 32 marathons |
| T3b | Does loading about 46K tokens of the repository up front help? | 144 episodes |

### Reading the charts

| Term | Meaning |
| --- | --- |
| Token | The unit a model reads and writes, roughly a short word or part of one |
| VRAM | Memory on the graphics card |
| Time to first token | How long the model takes to start answering |
| Pass rate | Passed episodes divided by all episodes in an arm |
| 95% interval | The range where the true pass rate probably sits. With 12 episodes it is very wide |
| p value | How likely a difference this large would be if two setups were equal. Below 0.05 is the usual bar |
| McNemar test | Compares two setups on the same tasks, counting only the runs where they disagree |

Details: [methodology](docs/METHODOLOGY.md), [machine and versions](docs/HARDWARE.md), [every table](docs/RESULTS.md).

## Findings

### 1. Retry once with thinking on

<img src="docs/figures/retry-with-thinking.svg" alt="Pass rates out of 36. Control with thinking retry goes from 22 to 30, p 0.008. The recommended profile goes from 27 to 29. The same profile with Q6_K_L goes from 23 to 28. The RTK filter passes 17 with no retry." width="100%">

Thinking on for every attempt costs about 3.3 times more time, and its early lead did not repeat (11/12, then 16/24). Using it only after a failure gives most of the benefit at a much lower cost: 8 of 10 retries succeeded, and no first-attempt success was lost.

Across the original stage 5 and its replication, this setup rose from 29/48 to 41/48.

The recommended profile starts stronger and needs fewer retries (3 instead of 10). Its 29/36 is not different from the control's 30/36 (p = 1.0).

### 2. Most single settings stay inside the noise

<img src="docs/figures/one-factor.svg" alt="Forest plot of ten arms with 95 percent Wilson intervals. The control passes 16 of 24. Context 16K passes 3 of 12. All other arms overlap the control's interval." width="100%">

With 12 tasks, small effects cannot be separated from chance. Only 16K context clearly fails: nine of its twelve episodes ended in a CLI error, and the stage 2 report records the context limit being exceeded. The other differences are signals, not a ranking.

### 3. Keep the prompt cache on

<img src="docs/figures/prompt-cache.svg" alt="Median time to first token without and with a cached prefix: agent episode 7.5 seconds to 0.30, 46K prefix in T3b v2 16.1 seconds to 0.16, 46K prefix in T3b v3 17.8 seconds to 2.1." width="100%">

Without the cache, median episode time rises from 42 s to 115 s. With it, a repository prefix of about 46K tokens becomes usable on the 3070. The prefix improved latency only: all three T3b v3 arms passed the same 2 of 12 tasks. The problem there is editing: to change code, the model has to quote the existing lines exactly, and the 4B writes them from memory instead of copying them.

### 4. 8 GB is enough

<img src="docs/figures/vram.svg" alt="Peak VRAM in MiB against the 8,192 MiB limit: control 4,567, context 128K 5,422, KV f16 5,754, recommended 5,800, weights Q8_0 6,033, recommended with Q6_K_L 6,618." width="100%">

Q6_K_L used 818 MiB more than Q4_K_M and finished at 28/36 against 29/36, so the extra precision did not pay for itself here.

### 5. Long tasks: compaction at 32K did best

A marathon gives the agent 5 or 6 objectives in a row on one copy of Bottle, using the bugs from the task table. The conversation grows with each objective until it no longer fits, so we compared four ways to handle that. Two marathons give 9 hidden tests per repetition, 27 over three repetitions.

| Approach | Context | What happens as the conversation grows |
| --- | --- | --- |
| Large context | 128K | One session that keeps the full history |
| Headroom | 32K | One session. [Headroom](https://github.com/headroomlabs-ai/headroom) is a third-party proxy that sits between the agent and the model and compresses tool output before the model sees it |
| OpenCode compaction | 32K | One session. OpenCode replaces older messages with a summary when the context fills up |
| Reset with `PROGRESS.md` | 32K | A new session for each objective. A notes file carries over past objectives, changed files and visible test results |

Prompt tokens count everything sent to the model across the marathon. The large context costs more because each turn carries the whole history.

| Approach | Hidden tests passed | Peak VRAM |
| --- | --- | --- |
| OpenCode compaction | 23/27 | 4,101 MiB |
| Large context | 18/27 | 5,435 MiB |
| Reset | 17/27 | 4,099 MiB |
| Headroom | 14/27 | 4,099 MiB |

A first run with one repetition had put the large context first, 9 of 9, and that ranking did not hold. Most of the gap comes from three objectives in one marathon, so treat the order as provisional. Only compaction against Headroom is clear (9 against 0, p = 0.004). Details are in the [T2 report](reports/strategy-analysis-4b-2026-10-28/execution/F1/T2-long-task-results-v3.md).

### 6. The corpus is now the main limit

<img src="docs/figures/task-outcomes.svg" alt="Outcome grid for 12 tasks across four arms and three repetitions. Most tasks pass nearly always, tests_query and tests_range vary, and py_range never passes." width="100%">

Most of the pilot tasks pass almost every time and `py_range` never does, so few tasks can separate one configuration from another. Corpus v2 adds 24 tasks, which are written and validated but not yet calibrated.

## Recommended setup

| Setting | Use | Why |
| --- | --- | --- |
| Weights | Q4_K_M | Q6 variants showed no significant gain and use more VRAM |
| Context | 64K (32K minimum) | 16K fails with OpenCode on this corpus |
| Long tasks | 32K with OpenCode compaction | 23/27 hidden tests against 18/27 with 128K, and 1.3 GB less VRAM |
| KV cache | q4_0 | No measurable loss, lowest VRAM |
| Prompt cache | On, `--cache-ram 2048` | 25 times lower latency; the 8 GiB default caused a WSL out-of-memory stop |
| Thinking | Off, then on for one retry | 22/36 → 30/36 (p = 0.008) |
| Server | llama.cpp master with MTP | Decode 73 → 108 tok/s from MTP, and 98 → 110 tok/s from master on the full profile; no measured change in passes |
| Sampling | Temperature 0, retry at 0.6 | Qwen's recommended sampling scored 6/12 |
| OpenCode steps | 40 | 80 steps scored 10/12, with no clear gain |
| RTK | Off | 17/36 against 22/36 (p = 0.23), no evidence to adopt it |
| LSP | Not needed | Neutral, and the model never called the `lsp` tool on its own |

A later campaign tested each setting alone on 18 calibrated tasks with three repetitions. A repeat of the control moved 9 of 54 outcomes, and no setting changed passes beyond that: 34 and 31 for the two controls, 29 with MTP, 32 with checkpoints, 32 with a 4 GiB cache. MTP raised decode speed by 44% to 48%, but total time stayed between the two controls. Checkpoints showed no benefit and used more RAM, so they left this profile. The exact combination below, master with MTP and no checkpoints, was measured in parts and not as one run. Details are in the [factor separation report](reports/strategy-analysis-4b-2026-10-28/execution/F1/factor-separation.md).

### Server

Replace `<models>` with the directory containing the GGUF.

```sh
llama-server \
  --model <models>/Qwen_Qwen3.5-4B-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8080 --alias local-qwen \
  --ctx-size 65536 --parallel 1 -ngl 99 \
  --fit off --flash-attn on \
  --cache-type-k q4_0 --cache-type-v q4_0 \
  --jinja --reasoning off \
  --chat-template-kwargs '{"enable_thinking": false}' \
  --temp 0 --top-p 0.95 --top-k 20 \
  --cache-prompt --no-webui \
  --spec-type draft-mtp --spec-draft-n-max 2 \
  --cache-ram 2048
```

<details>
<summary><strong>OpenCode profile</strong></summary>

Thinking is off on the server. The 40 steps and temperature 0 are in the model profile.

```json
{
  "autoupdate": false,
  "model": "local/local-qwen",
  "subagent_depth": 0,
  "provider": {
    "local": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Local llama.cpp",
      "options": {
        "baseURL": "http://127.0.0.1:8080/v1",
        "apiKey": "local"
      },
      "models": {
        "local-qwen": {
          "name": "local-qwen",
          "limit": { "context": 65536, "output": 8192 },
          "options": { "temperature": 0 }
        }
      }
    }
  },
  "agent": {
    "build": { "mode": "primary", "steps": 40 }
  }
}
```

</details>

<details>
<summary><strong>Escalating with thinking</strong></summary>

The benchmark runner escalates automatically when an attempt fails the visible test. In manual use, start a second server or restart the same one with these options:

```sh
--reasoning on \
--chat-template-kwargs '{"enable_thinking": true}' \
--temp 0.6 --top-p 0.95 --top-k 20
```

In the OpenCode profile, also use `"options": { "temperature": 0.6, "topP": 0.95, "topK": 20 }`.

</details>

## Next steps

| When | Work |
| --- | --- |
| Now | Add repetitions on the 12 tasks that separate configurations |
| Soon | Find out whether speed on this GPU follows power or memory, then work through the tuning options |
| Later | Try a new edit protocol for the bounded worker; compare ExLlamaV3 and a large model on the same corpus |
| Eventually | Build a separate confirmation set; add new host repositories; work through the remaining backlog |

<details>
<summary><strong>Backlog</strong></summary>

- **P2:** mistral.rs with the same GGUF; bounded worker at scale; native Windows llama.cpp versus WSL2; rebuild with GGML_CUDA_FA_QUANTS for mixed KV.
- **P3, outside the 4B scope:** vLLM or LMDeploy with AWQ and GPTQ-Marlin; offload of MoE larger than VRAM; models from 7 to 14B; agent LoRA.

</details>

## Reproduce

**You need:** Windows with WSL2 (Ubuntu 24.04) and an 8 GB NVIDIA GPU, plus Python 3.12 with pytest and ruff. We tested with an RTX 3070, driver 610.62, CUDA Toolkit 13.0, pytest 9.1.1, and ruff 0.17.3 ([details](docs/HARDWARE.md)). Binaries and weights are not in the repository: `benchmark/configs/qwen-4b-opencode-baseline.json` lists the paths and SHA-256 hashes for llama.cpp v0.8.0, OpenCode 1.19.5, Node, bubblewrap, and the GGUF files.

Without a GPU, from the repository root:

```sh
export PYTHONDONTWRITEBYTECODE=1
PY=python3   # use the Python 3.12 validation environment
$PY -m pytest -p no:cacheprovider -q                  # 20 test files, see Limitations
$PY -m benchmark.opencode_baseline --dry-run          # lists the 300 units of the current protocol
$PY -m benchmark.opencode_baseline --dry-run --arm B0 # 24 units
PYTHONDONTWRITEBYTECODE=1 $PY corpus/validate_corpus.py --node /path/to/node   # 36/36 PASS, a few minutes
```

With a GPU (run only when it is free; the runner refuses to start if a `llama-server` is already active):

```sh
$PY -m benchmark.opencode_baseline --smoke                  # 1 episode: B0, task py_query
$PY -m benchmark.opencode_baseline --smoke --task cont_path # another task
$PY -m benchmark.opencode_baseline --arm B-kv8              # one arm
$PY -m benchmark.opencode_baseline --stage N                # every unit of stage N (N from 1 to 4)
```

The current protocol writes to `results/qwen-4b-opencode-baseline-bwrap-v7`, because the config is already the stage 4 v7 revision. To reproduce stages 1 through 3, use the v5 and v6 configs from earlier commits (the last commit before the refactoring is `c2cf750`). The runner refuses to mix results with different manifests.

Reports and figures:

```sh
$PY -m benchmark.baseline_report DIR_v5 DIR_v6 \
  --markdown report.md --csv report.csv \
  --control-dir DIR_v5 --control B0
$PY docs/figures/build_figures.py
```

Generated aggregates are in [results/3070-benchmark/](results/3070-benchmark/). Raw results (workspaces, logs, and JSON per attempt) stay outside the repository.

<details>
<summary><strong>Repository structure</strong></summary>

```
README.md
docs/
  METHODOLOGY.md          method: corpus, oracle, isolation, counting, classification
  HARDWARE.md             machine, versions, weights and storage
  RESULTS.md              every table: per arm, per task, paired and configuration
  RENAMES.md              old Portuguese paths mapped to their English names
  figures/                README figures and the script that builds them
  restricted-python-v2.md, methodology/pristine-grading-protocol.md
                          documentation of retained code (removal candidates)
benchmark/
  opencode_baseline.py    baseline runner: protocol, manifest, isolation and oracle
  baseline_report.py      offline report: Wilson, McNemar, timings, TTFT and VRAM
  baseline_stage5.py      stage 5, replication and combined runner (--config)
  worker_contract.py, worker_runner.py, guarded_edit.py
                          bounded worker contract and runner; not evaluated in this baseline
  harness_runner.py, harness_eval.py, pristine_grading.py, restricted_python.py,
  run_observer.py, provenance.py, resource_sampler.py, safe_execution_guard.py
                          dependencies imported by the runner
  configs/                current protocols and harness profiles (OpenCode, Pi, Vibe)
  fixtures/               six task fixtures used by the harness and the grader
  eval_suites/            behavior probes for the fixtures
corpus/                   36 tasks: hosts (Bottle 0.13.2 and ms 2.1.3), tasks, oracles,
                          stubs, support, prefixes and hash manifest
tests/                    20 test files for the retained modules
results/3070-benchmark/   aggregates for stages 1 to 5, replication, combined campaign, T2 and T3b
reports/                  F0, F1, F3 and T1 reports, copied without logs or snapshots
```

</details>

## Limitations

Read every number here as a measurement of one machine on a small development corpus. The results have not been tested on a separate confirmation set.

<details>
<summary><strong>Full list</strong></summary>

- **Small, saturated corpus.** There are 12 pilot tasks. Eight almost always pass; py_range never passed. Many arms have only 12 episodes, and comparisons with 36 episodes still have little power for small differences.
- **Pilot corpus.** The results use the original 12 tasks, which were not calibrated with the model and are not a confirmation set. Corpus v2 adds 24 tasks (36 in total) that still await calibration. `bottle.py` has about 51 thousand tokens, estimated from character count.
- **Significance.** The thinking cascade in the stage 5 replication is the only new comparison with a significant result. In the 16K arm, with 5 losses and no wins, p = 0.0625 is the smallest possible value with five discordant pairs in the same direction.
- **Different quantizers.** The control uses bartowski Q4_K_M. Q6_K and Q8_0 are from unsloth, and unsloth Q4_K_M only appears in stage 4.
- **Storage.** Q6_K and Q8_0 GGUF files are read from `/mnt/d` (D: drive). The laboratory rule requires WSL ext4. The effect on metrics was not measured.
- **Sandbox.** OpenCode execution permits networking, and bash confinement has not been proven for all commands. Current evaluations use a separate sandbox without networking; historical results were produced with earlier versions.
- **Device VRAM.** VRAM is sampled for the whole device at about 1 Hz, and the Windows desktop shares the GPU. It is not exclusive process memory.
- **Proxy TTFT.** TTFT measures time until the first content, reasoning, or tool call, as seen by the local proxy. It may be unavailable for some requests.
- **Noise.** Repeating the control moved 9 of 54 outcomes and 54 minutes of arm time, so a difference of a few points or a few minutes cannot be read from one run.
- **Missing fields in v5 and v6 results.** Automatic termination taxonomy and diff quality metrics (lines, scope, weakened tests) were added later. Results for stages 1 through 3 have these fields empty or null. Failure causes come from `failure` labels recorded by the runner.
- **Infrastructure retries.** Two v6 units had their first attempt invalidated by grader failure. The second attempt, which passed, counted as a pass. This follows the protocol. In v5, a model failure was classified as infrastructure and retried; this classification was corrected in v6.
- **Timeouts in stages 4 and 5.** Nine final results and two intermediate attempts also recorded a connection reset. Current rules would prioritize the server error, but logs do not prove whether the reset preceded the timeout, so historical numbers were retained. See the [revalidation](reports/strategy-analysis-4b-2026-10-28/execution/F1/pr45-review-fixes.md).
- **Unequal repetitions.** Many exploratory arms in stages 4 and 5 have 12 episodes. The replicated cascade and combined campaign have 36 episodes per arm. T2 now has three repetitions per arm, still few, and its first ranking did not hold.
- **T3b.** The 4B writes the SEARCH block from memory and resubmits rejected edits. OpenSSL errors affected v2 and v3 verification, so historical passes do not isolate the context effect. Excluding `js_sign` from P-W16 due to a proven verifier failure leaves that arm at 2/11, and other episodes also received environmental diagnoses, so the quality comparison is inconclusive. See the [revalidation](reports/strategy-analysis-4b-2026-10-28/execution/F1/pr45-review-fixes.md).
- **Landlock on drvfs.** The historical T3b run used a repository copy on WSL ext4. The revised verifier was also tested on `/mnt/d`.
- **Reproduction on another machine.** The config has laboratory paths and SHA-256 hashes. A different machine requires a new `protocol_id`, because the manifest refuses to mix protocols.

</details>

## History

Campaigns before 2026-10-28 were removed from this tree. They remain in git history through commit `c2cf750` of `refactor/3070-benchmark` and its predecessors. The refactoring pull request lists what was removed and why. Reports written before the translation are mapped in [docs/RENAMES.md](docs/RENAMES.md).
