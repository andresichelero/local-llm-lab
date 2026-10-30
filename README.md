# Local LLM benchmark: Qwen3.5-4B on RTX 3070 (8 GB)

> **English summary.** This repository benchmarks a local coding agent on one RTX 3070 8 GB under WSL2. Qwen3.5-4B runs on llama.cpp v0.8.0 and OpenCode 1.19.5. The 12-task pilot corpus uses private oracles. A three-repeat stage 5 replication confirmed that retrying a visibly failed attempt with thinking enabled raises accuracy from 29/48 to 41/48 across the original stage 5 and its replication (McNemar p=0.008 in the replication). RTK scored 17/36 against 22/36 for the paired control (p=0.23). The combined MTP, context-checkpoint and 2 GiB prompt-cache profile kept final accuracy near the control (29/36 vs 30/36) and used fewer escalations; Q6_K_L gave no accuracy gain and used 0.8 GB more VRAM. The cache limit addresses a WSL out-of-memory event, but its effect was not isolated. Long-task marathons favoured a large context over compaction or resets, and a cached 46K-token repository prefix cut time to first token from 16 s to 0.16 s. Campaigns before 2026-10-28 were removed from this tree and remain in the git history.

## Summary

This repository measures, on one machine, how much each runtime choice changes a local coding agent's pass rate and cost.

- **Model and runtime:** Qwen3.5-4B in GGUF, served by llama.cpp v0.8.0 `llama-server` (commit `8642541`) with CUDA. One instance per arm, `--parallel 1`, serial execution.
- **Agent:** OpenCode 1.19.5 (`opencode run --format json --pure`), isolated in bubblewrap 0.9.0. The sandbox does not mount the repository, `/mnt/d`, `/home`, or the oracles.
- **Corpus:** 12 pilot tasks in 6 classes (2 per class), with a private oracle evaluated once at the end of each attempt. The oracle never enters the prompt.
- **Matrix:** the initial stages vary one factor at a time from control B0 (Q4_K_M, KV q4_0, 64K, prompt cache on, thinking off, temperature 0). The cascade replication and combined campaign followed.

Details: [methodology](docs/METHODOLOGY.md), [machine and versions](docs/HARDWARE.md), [all tables](docs/RESULTS.md).

## Main results

The table below preserves results for stages 1 through 3, with 95% Wilson intervals. "Paired" compares each arm with the control by task and repetition 1 (exact, two-sided McNemar).

| Stage | Arm | Change relative to control | Passes | Rate (95% CI) | Median time, all (s) | Median time, successes (s) | Median TTFT (ms) | Peak VRAM, maximum (MiB) | Cached prompt fraction | Paired with control (wins / losses / ties; exact p) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Stage 1 | `B0` | control: Q4_K_M, KV q4_0, 64K, cache on, thinking off, temp 0 | 16/24 | 67% (47%–82%) | 42.3 | 36.4 | 296 | 4567 | 0.94 | control |
| Stage 2 | `B-ctx16` | context 16K | 3/12 | 25% (9%–53%) | 16.4 | 27.6 | 448 | 3858 | 0.87 | 0 / 5 / 7; p = 0.0625 |
| Stage 2 | `B-ctx32` | context 32K | 9/12 | 75% (47%–91%) | 46.1 | 38.1 | 235 | 4105 | 0.92 | 2 / 1 / 9; p = 1.0000 |
| Stage 2 | `B-ctx128` | context 128K | 9/12 | 75% (47%–91%) | 58.2 | 37.8 | 294 | 5422 | 0.94 | 1 / 0 / 11; p = 1.0000 |
| Stage 2 | `B-kv8` | KV q8_0 | 9/12 | 75% (47%–91%) | 39.0 | 30.5 | 265 | 5038 | 0.92 | 1 / 0 / 11; p = 1.0000 |
| Stage 2 | `B-kv16` | KV f16 | 7/12 | 58% (32%–81%) | 34.6 | 32.0 | 306 | 5754 | 0.91 | 1 / 2 / 9; p = 1.0000 |
| Stage 3 | `B-q6` | Q6_K (unsloth) | 10/12 | 83% (55%–95%) | 37.0 | 34.3 | 301 | 5162 | 0.92 | 2 / 0 / 10; p = 0.5000 |
| Stage 3 | `B-q8` | Q8_0 (unsloth) | 8/12 | 67% (39%–86%) | 38.5 | 32.2 | 317 | 6033 | 0.94 | 1 / 1 / 10; p = 1.0000 |
| Stage 3 | `B-nocache` | prompt cache off | 9/12 | 75% (47%–91%) | 115.5 | 81.7 | 7498 | 4521 | 0.00 | 2 / 1 / 9; p = 1.0000 |
| Stage 3 | `B-think` | thinking on (temp 0,6, top_p 0,95, top_k 20) | 11/12 | 92% (65%–99%) | 110.1 | 108.9 | 214 | 4535 | 0.95 | 3 / 0 / 9; p = 0.2500 |

Interpretation, with caution:

- **Control:** 16 of 24 episodes (67%, 95% CI 47–82%).
- **Context:** at 16K, passes fall to 3 of 12. Nine episodes ended in a CLI error, and the stage 2 report records a context exceeded message (16 384 tokens). At 32K, 64K (control), and 128K, pass rates are between 67% and 75%, with no detectable difference. 128K uses more VRAM (peak 5 422 MiB, versus 4 567 MiB in the control).
- **KV cache:** q8_0 passed 9 of 12 and f16 passed 7 of 12. The control's q4_0 passed 16 of 24. The differences are within the noise. Among KV arms, f16 has the highest peak VRAM (5 754 MiB).
- **Weights:** Q6_K (unsloth) passed 10 of 12 and Q8_0 (unsloth) passed 8 of 12. The control uses another quantizer (bartowski), so the effect of bit width cannot be separated from the quantizer effect.
- **Prompt cache:** without caching, median TTFT increases from 296 ms to about 7,5 s and median episode time from 42 s to 115 s. The pass rate did not change detectably (9 of 12, paired p = 1,0).
- **Thinking always on:** 11/12 in stage 3 and 16/24 in stage 4; the advantage did not repeat. Thinking as escalation was confirmed, however: in the stage 5 replication, the cascade rose from 22/36 to 30/36 (McNemar p = 0,008). Combined with the original stage 5, it rose from 29/48 to 41/48.
- **Stage 4 (replication and server):** control 25/36, Q6_K 27/36, MTP with 55% faster decode, context checkpoints with 34% lower success time. Full table in [docs/RESULTS.md](docs/RESULTS.md), section 7.
- **Stage 5 and replication:** the thinking cascade rose from 7/12 to 11/12 in the first collection and from 22/36 to 30/36 in replication. RTK scored 17/36 versus 22/36 for the replicated control (p = 0,23), with no significant difference. See [docs/RESULTS.md](docs/RESULTS.md), sections 8 and 11.
- **Combined campaign:** MTP, checkpoints, and the 2 GiB cache limit kept Q4's final pass rate close to control (29/36 versus 30/36) and reduced escalations from 10 to 3. Q6_K_L scored 28/36, with no gain over Q4 (29/36), and used 0,8 GB more VRAM. RAM cache changed alongside the other factors. See [docs/RESULTS.md](docs/RESULTS.md), section 12.
- **Long tasks (T2):** in marathons of 5 to 6 objectives, large context passed 9/9 oracles. Headroom scored 7/9, OpenCode compaction 6/9, and reset with `PROGRESS.md` 5/9. See section 9.
- **Cached repository prefix (T3b):** with about 46 thousand tokens already cached, TTFT falls from 16,1 s to 0,16 s. v3 recorded 2/12 in all three arms. Excluding `js_sign` from P-W16 due to a proven verifier failure leaves that arm at 2/11; other episodes also received environmental diagnoses. The quality comparison is inconclusive. See section 10.
- **Significance:** the thinking cascade in the stage 5 replication is the only new comparison with a significant result (p = 0,008). Paired comparisons in the combined campaign and RTK do not reach p < 0,05. In the 16K arm, with 5 losses and no wins, p = 0,0625 is the smallest possible value with five discordant pairs in the same direction. Treat the other numbers as signals, not a ranking.

## Recommended configuration

These recommendations come from stages 1 through 5, the stage 5 replication, and the combined, T2, and T3b campaigns (details in [docs/RESULTS.md](docs/RESULTS.md), sections 7 through 12).

- **Context:** 32K is the minimum, and 64K provides headroom. With OpenCode, 16K is unsuitable for this corpus.
- **KV cache:** q4_0. There was no measurable loss and it uses the least VRAM.
- **Weights:** Q4_K_M. Q6_K_L scored 28/36 versus 29/36 for combined Q4 and used 818 MiB more. Stage 4 also showed no significant difference between Q4_K_M and Q6_K.
- **Prompt cache:** on. Without it, latency increases about 25 times.
- **Thinking:** off on the first attempt and on only for escalation. Replication rose from 22/36 to 30/36 (8 rescues in 10 escalations; McNemar p = 0,008). Combined with the original stage 5, the cascade rose from 29/48 to 41/48.
- **RTK:** keep off. In replication it scored 17/36 versus 22/36 for the control, with no significant difference (p = 0,23).
- **MTP and checkpoints:** enable `--spec-type draft-mtp --spec-draft-n-max 2` and `--ctx-checkpoints 64 --checkpoint-min-step 1024`. In the combined campaign, Q4 maintained final passes (29/36 versus 30/36) and used 3 escalations versus 10. Because factors changed together, this result cannot be attributed to one alone.
- **RAM cache:** limit with `--cache-ram 2048`. The 8 GiB default equals all RAM configured for WSL and caused OOM during the combined campaign. The comparison arm used the 8 GiB default; the limit's effect was not isolated.
- **Tools:** keep RTK off. The initial collection scored 6/12; replication scored 17/36 versus 22/36 for the control (p = 0,23). LSP was neutral, and the model did not call the lsp tool on its own.
- **Long tasks:** large context with caching, while it fits in VRAM (peak 5,4 GB). If context must be limited, Headroom was better than native compaction and reset.
- **Server:** MTP raised decode from 74 to 115 tok/s in stage 4 (91% acceptance). Checkpoints reduced success time from 37 to 25 s. In the combined campaign, both were used with the cascade; the design does not separate their effects.
- **Sampling:** temperature 0 on the first attempt. For thinking escalation, temperature 0,6, top_p 0,95, and top_k 20. Qwen's recommended sampling scored 6/12.
- **OpenCode steps:** 40. With 80 the result was 10/12, with no clear gain.

### Ready-to-use profile

Replace `<models>` with the directory containing the GGUF and start the recommended server:

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
  --ctx-checkpoints 64 --checkpoint-min-step 1024 \
  --cache-ram 2048
```

An `opencode.json` snippet for the local provider. Thinking is off on the server; the 40 steps and temperature 0 are in the model profile.

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

To escalate manually, start a second server or restart the same server with different thinking and sampling options:

```sh
--reasoning on \
--chat-template-kwargs '{"enable_thinking": true}' \
--temp 0.6 --top-p 0.95 --top-k 20
```

In the OpenCode profile, also use `"options": { "temperature": 0.6, "topP": 0.95, "topK": 20 }`. The benchmark runner escalates automatically when an attempt fails the visible test; in manual use, this is a second step.

## Reproduction

### Prerequisites

- Windows with WSL2 (Ubuntu 24.04) and an 8 GB NVIDIA GPU. Tested with RTX 3070, driver 610.62, and CUDA Toolkit 13.0 (see [docs/HARDWARE.md](docs/HARDWARE.md)).
- Binaries and weights at the paths and with the SHA-256 hashes in `benchmark/configs/qwen-4b-opencode-baseline.json`: llama.cpp v0.8.0 `llama-server`, OpenCode 1.19.5, Node, bubblewrap, and the GGUF files. None are in the repository.
- Python 3.12 with pytest and ruff. Versions used: pytest 9.1.1 and ruff 0.17.3.

### Commands without GPU

From the repository root:

```sh
export PYTHONDONTWRITEBYTECODE=1
PY=python3   # use o Python 3.12 do ambiente de validação
$PY -m pytest -p no:cacheprovider -q                  # 19 arquivos de teste, ver Limitações
$PY -m benchmark.opencode_baseline --dry-run          # lista as 300 unidades do protocolo atual
$PY -m benchmark.opencode_baseline --dry-run --arm B0 # 24 unidades
PYTHONDONTWRITEBYTECODE=1 $PY corpus/validate_corpus.py --node /caminho/para/node   # 12/12 PASS, cerca de 2 min
```

### Commands with GPU

These commands start `llama-server`. Run only when the GPU is free. The runner refuses to start if a `llama-server` is already active.

```sh
$PY -m benchmark.opencode_baseline --smoke                  # 1 episódio: B0, tarefa py_query
$PY -m benchmark.opencode_baseline --smoke --task cont_path # outra tarefa
$PY -m benchmark.opencode_baseline --arm B-kv8              # um braço
$PY -m benchmark.opencode_baseline --stage N                # todas as unidades da etapa N (N de 1 a 4)
```

The current protocol writes to `results/qwen-4b-opencode-baseline-bwrap-v7` because `benchmark/configs/qwen-4b-opencode-baseline.json` is already the stage 4 v7 revision. To reproduce stages 1 through 3, use the v5 and v6 configs from earlier commits in the git history (the last commit before this refactoring is `c2cf750`). Results with different manifests are not mixed: the runner refuses them.

### Reports

```sh
$PY -m benchmark.baseline_report DIR_v5 DIR_v6 \
  --markdown relatorio.md --csv relatorio.csv \
  --control-dir DIR_v5 --control B0
```

Generated aggregates are in [results/3070-benchmark/](results/3070-benchmark/). Raw results (workspaces, logs, and JSON per attempt) remain outside the repository.

## Repository structure

```
README.md
docs/
  METHODOLOGY.md          método: corpus, oráculo, isolamento, contagem, classificação
  HARDWARE.md             máquina, versões, pesos e armazenamento
  RESULTS.md              todas as tabelas: por braço, por tarefa, pareadas e configuração
  restricted-python-v2.md, methodology/pristine-grading-protocol.md
                          documentação de código mantido (candidatos a remoção)
benchmark/
  opencode_baseline.py    runner da linha de base: protocolo, manifesto, isolamento e oráculo
  baseline_report.py      relatório offline: Wilson, McNemar, tempos, TTFT e VRAM
  worker_contract.py, worker_runner.py, guarded_edit.py
                          contrato e runner do trabalhador delimitado; não avaliado nesta linha de base
  harness_runner.py, harness_eval.py, pristine_grading.py, restricted_python.py,
  run_observer.py, provenance.py, resource_sampler.py, safe_execution_guard.py
                          dependências importadas pelo runner
  configs/                protocolo atual e perfis do harness (OpenCode, Pi, Vibe)
  fixtures/               seis fixtures de tarefa usadas pelo harness e pelo grader
  eval_suites/            sondas de comportamento das fixtures
corpus/                   12 tarefas: hosts (Bottle 0.13.2 e ms 2.1.3), tarefas, oráculos,
                          stubs, suporte, prefixos e manifesto de hashes
tests/                    19 arquivos de teste dos módulos mantidos
results/3070-benchmark/   agregados das etapas 1 a 5, replicação, campanha combinada, T2 e T3b
reports/                  relatórios das etapas F0, F1, F3 e T1, copiados sem logs nem snapshots
```

## Limitations

- **Small, saturated corpus.** There are 12 pilot tasks. Eight almost always pass; py_range never passed. Many arms have only 12 episodes; comparisons with 36 episodes still have little power for small differences.
- **Different quantizers.** The control uses bartowski Q4_K_M. Q6_K and Q8_0 are from unsloth, and unsloth Q4_K_M only appears in stage 4.
- **Storage.** Q6_K and Q8_0 GGUF files are read from `/mnt/d` (D: drive). The laboratory rule requires WSL ext4. The effect on metrics was not measured.
- **Sandbox.** OpenCode execution permits networking; bash confinement has not been proven for all commands. Current evaluations use a separate sandbox without networking; historical results were produced with earlier versions.
- **Device VRAM.** VRAM is sampled for the whole device at about 1 Hz, and the Windows desktop shares the GPU. It is not exclusive process memory.
- **Proxy TTFT.** TTFT measures time until the first content, reasoning, or tool call, as seen by the local proxy. It may be unavailable for some requests.
- **Combined factors.** MTP, checkpoints, and the 2 GiB RAM cache limit were enabled together. The comparison used an arm with the default 8 GiB RAM cache as reference; the isolated effect of the limit is unknown.
- **Missing fields in v5 and v6 results.** Automatic termination taxonomy and diff quality metrics (lines, scope, weakened tests) were added later. Results for stages 1 through 3 have these fields empty or null. Failure causes come from `failure` labels recorded by the runner.
- **Infrastructure retries.** Two v6 units had their first attempt invalidated by grader failure. The second attempt, which passed, counted as a pass. This follows the protocol. In v5, a model failure was classified as infrastructure and retried. This classification was corrected in v6.
- **Timeouts in stages 4 and 5.** Nine final results and two intermediate attempts also recorded a connection reset. Current rules would prioritize the server error, but logs do not prove whether the reset preceded the timeout; historical numbers were retained. See the [revalidation](reports/analise-estrategia-4b-2026-10-28/execucao/F1/revisao-pr45-correcoes.md).
- **Unequal repetitions.** Many exploratory arms in stages 4 and 5 have 12 episodes. The replicated cascade and combined campaign have 36 episodes per arm. T2 still has one repetition per arm, and the conclusion about compaction does not confirm that it finished.
- **T3b.** The 4B writes the SEARCH block from memory and resubmits rejected edits. OpenSSL errors affected v2 and v3 verification; historical passes do not isolate the context effect. See the [revalidation](reports/analise-estrategia-4b-2026-10-28/execucao/F1/revisao-pr45-correcoes.md).
- **Landlock on drvfs.** The historical T3b run used a repository copy on WSL ext4. The revised verifier was also tested on `/mnt/d`.
- **Pilot corpus.** The 12 tasks were not calibrated with the model and are not a confirmation set. `bottle.py` has about 51 thousand tokens, estimated from character count.
- **Reproduction on another machine.** The config has laboratory paths and SHA-256 hashes. A different machine requires a new `protocol_id` because the manifest refuses to mix protocols.

## Roadmap

Completed: stage 4, stage 5 and its three-repetition replication, the combined MTP and checkpoints campaign, long tasks (T2), and cached prefix (T3b).

Next steps:

1. **Expand the corpus:** from 12 to 24–36 new tasks.
2. **Repeat T2:** three repetitions per arm and confirmation that compaction finished.
3. **P1 backlog:** compare ExLlamaV3 with TabbyAPI against llama.cpp after checking hybrid Qwen3.5 tool calls; compare cost with a large model on the same corpus.
4. **MCP and new quantizations**, as they are released.

Backlog:

- **P2:** mistral.rs with the same GGUF; bounded worker at scale; native Windows llama.cpp versus WSL2; rebuild with GGML_CUDA_FA_QUANTS for mixed KV.
- **P3, outside the 4B scope:** vLLM or LMDeploy with AWQ and GPTQ-Marlin; offload of MoE larger than VRAM; models from 7 to 14B; agent LoRA.

## History

Campaigns before 28/10/2026 were removed from this tree. They remain in git history through commit `c2cf750` of `refactor/3070-benchmark` and its predecessors. The refactoring pull request lists what was removed and why.
