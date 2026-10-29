# Benchmark de LLM local: Qwen3.5-4B em RTX 3070 (8 GB)

> **English summary.** This repository is a reproducible, single-machine benchmark of a local coding agent. Qwen3.5-4B runs on llama.cpp v0.8.0 (CUDA 13.0) on an NVIDIA RTX 3070 8 GB under WSL2, driven by OpenCode 1.19.5 inside a bubblewrap sandbox. A 12-task pilot corpus (Bottle 0.13.2 and ms 2.1.3) is graded by private oracles, and each runtime factor (context, KV cache type, weight quantization, prompt cache, thinking mode) is varied one at a time from a control arm. Stages 1 to 3 (132 episodes: 12 per arm and 24 for the control) show no statistically significant difference between arms. Prompt caching is essential for latency. Stage 4 replicated the control (25/36) and Q6_K (27/36), did not confirm the stage 3 thinking gain, and showed that MTP speculative decoding (+55% decode) and context checkpoints cut task time by about a third. Stage 5 found that a cascade that retries a visibly failed attempt with thinking enabled lifted 7/12 to 11/12, while the RTK output filter hurt (6/12). Long-task marathons favoured a large context over compaction or resets, and a cached 46K-token repository prefix cut time to first token from 16 s to 0.16 s. Campaigns before 2026-10-28 were removed from this tree and remain in the git history.

## Resumo

Este repositório mede, em uma única máquina, quanto cada escolha de runtime muda a taxa de acerto e o custo de um agente de programação local.

- **Modelo e runtime:** Qwen3.5-4B em GGUF, servido pelo `llama-server` do llama.cpp v0.8.0 (commit `8642541`) com CUDA. Uma instância por braço, `--parallel 1`, execução serial.
- **Agente:** OpenCode 1.19.5 (`opencode run --format json --pure`), isolado em bubblewrap 0.9.0. O sandbox não monta o repositório, `/mnt/d`, `/home` nem os oráculos.
- **Corpus:** 12 tarefas de piloto em 6 classes (2 por classe), com oráculo privado avaliado uma vez ao fim de cada tentativa. O oráculo nunca entra no prompt.
- **Matriz:** um fator por vez a partir do controle B0 (Q4_K_M, KV q4_0, contexto 64K, cache de prompt ligado, thinking desligado, temperatura 0).

Detalhes: [método](docs/METHODOLOGY.md), [máquina e versões](docs/HARDWARE.md), [todas as tabelas](docs/RESULTS.md).

## Principais resultados (etapas 1 a 3)

Taxa com intervalo de Wilson de 95%. "Pareado" compara cada braço com o controle, por tarefa e repetição 1 (McNemar exato, bilateral).

| Etapa | Braço | Mudança em relação ao controle | Acertos | Taxa (IC 95%) | Tempo mediano, todos (s) | Tempo mediano, sucessos (s) | TTFT mediano (ms) | VRAM pico, máximo (MiB) | Fração do prompt em cache | Pareado com o controle (vitórias / derrotas / empates; p exato) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Etapa 1 | `B0` | controle: Q4_K_M, KV q4_0, 64K, cache on, thinking off, temp 0 | 16/24 | 67% (47%–82%) | 42.3 | 36.4 | 296 | 4567 | 0.94 | controle |
| Etapa 2 | `B-ctx16` | contexto 16K | 3/12 | 25% (9%–53%) | 16.4 | 27.6 | 448 | 3858 | 0.87 | 0 / 5 / 7; p = 0.0625 |
| Etapa 2 | `B-ctx32` | contexto 32K | 9/12 | 75% (47%–91%) | 46.1 | 38.1 | 235 | 4105 | 0.92 | 2 / 1 / 9; p = 1.0000 |
| Etapa 2 | `B-ctx128` | contexto 128K | 9/12 | 75% (47%–91%) | 58.2 | 37.8 | 294 | 5422 | 0.94 | 1 / 0 / 11; p = 1.0000 |
| Etapa 2 | `B-kv8` | KV q8_0 | 9/12 | 75% (47%–91%) | 39.0 | 30.5 | 265 | 5038 | 0.92 | 1 / 0 / 11; p = 1.0000 |
| Etapa 2 | `B-kv16` | KV f16 | 7/12 | 58% (32%–81%) | 34.6 | 32.0 | 306 | 5754 | 0.91 | 1 / 2 / 9; p = 1.0000 |
| Etapa 3 | `B-q6` | Q6_K (unsloth) | 10/12 | 83% (55%–95%) | 37.0 | 34.3 | 301 | 5162 | 0.92 | 2 / 0 / 10; p = 0.5000 |
| Etapa 3 | `B-q8` | Q8_0 (unsloth) | 8/12 | 67% (39%–86%) | 38.5 | 32.2 | 317 | 6033 | 0.94 | 1 / 1 / 10; p = 1.0000 |
| Etapa 3 | `B-nocache` | cache de prompt off | 9/12 | 75% (47%–91%) | 115.5 | 81.7 | 7498 | 4521 | 0.00 | 2 / 1 / 9; p = 1.0000 |
| Etapa 3 | `B-think` | thinking on (temp 0,6, top_p 0,95, top_k 20) | 11/12 | 92% (65%–99%) | 110.1 | 108.9 | 214 | 4535 | 0.95 | 3 / 0 / 9; p = 0.2500 |

Leitura, com cautela:

- **Controle:** 16 de 24 episódios (67%, IC 95% 47–82%).
- **Contexto:** com 16K o acerto cai para 3 de 12. Nove episódios terminaram com erro do CLI, e o relatório da etapa 2 registra a mensagem de contexto excedido (16 384 tokens). Com 32K, 64K (controle) e 128K o acerto fica entre 67% e 75%, sem diferença detectável. O 128K usa mais VRAM (pico de 5 422 MiB, contra 4 567 MiB no controle).
- **KV cache:** q8_0 acertou 9 de 12 e f16 acertou 7 de 12. O q4_0 do controle acertou 16 de 24. As diferenças estão dentro do ruído. Entre os braços de KV, o f16 tem o maior pico de VRAM (5 754 MiB).
- **Pesos:** Q6_K (unsloth) acertou 10 de 12 e Q8_0 (unsloth) acertou 8 de 12. O controle usa outro quantizador (bartowski), então não é possível separar o efeito dos bits do efeito do quantizador.
- **Cache de prompt:** sem cache, o TTFT mediano sobe de 296 ms para cerca de 7,5 s e o tempo mediano dos episódios vai de 42 s para 115 s. A taxa de acerto não mudou de forma detectável (9 de 12, pareado p = 1,0).
- **Thinking:** 11 de 12 (92%), contra 16 de 24 no controle. O tempo mediano dos sucessos foi 109 s, contra 36 s. O pareamento dá 3 vitórias e nenhuma derrota (p = 0,25). Na replicação da etapa 4, o thinking acertou 16 de 24 (67%). Somando as duas, são 27 de 36 (75%), dentro do ruído do controle.
- **Etapa 4 (replicação e servidor):** controle 25/36, Q6_K 27/36, MTP com decode 55% mais rápido, checkpoints de contexto com tempo dos sucessos 34% menor. Tabela completa em [docs/RESULTS.md](docs/RESULTS.md), seção 7.
- **Etapa 5 (pesos, ferramentas e cascatas):** a cascata que repete com thinking ligado quando a verificação visível falha passou de 7/12 para 11/12 (4 de 4 resgates). A cascata para o 9B resgatou 1 de 3. O plugin RTK piorou (6/12). LSP, Q6_K_L, UD-Q6_K_XL e UD-Q4_K_XL ficaram entre 9 e 10/12, sem diferença significativa. Ver [docs/RESULTS.md](docs/RESULTS.md), seção 8.
- **Tarefas longas (T2):** em maratonas de 5 a 6 objetivos, o contexto grande passou em 9/9 oráculos. Headroom ficou em 7/9, a compactação do OpenCode em 6/9 e o reset com `PROGRESS.md` em 5/9. Ver seção 9.
- **Prefixo do repositório em cache (T3b):** com cerca de 46 mil tokens já no cache, o TTFT cai de 16,1 s para 0,16 s. A v3 registrou 2/12 nos três braços. Excluindo a tarefa `js_sign` do P-W16 por falha comprovada do verificador, esse braço fica em 2/11; outros episódios também sofreram diagnósticos ambientais. A comparação de qualidade é inconclusiva. Ver seção 10.
- **Significância:** nenhuma comparação atinge p < 0,05. No braço de 16K, com 5 derrotas e nenhuma vitória, o p bilateral é 0,0625, que é o menor valor possível com cinco pares discordantes na mesma direção. Use estes números como sinais para a próxima etapa, não como ranking.

## Configuração recomendada

Estas recomendações saem das etapas 1 a 5 e das campanhas T2 e T3b (detalhes em [docs/RESULTS.md](docs/RESULTS.md), seções 7 a 10).

- **Contexto:** 32K é o mínimo, e 64K dá margem. Com OpenCode, 16K não serve neste corpus.
- **KV cache:** q4_0. Não houve perda mensurável e é o de menor VRAM.
- **Pesos:** Q4_K_M ou Q6_K. Somando as etapas, Q6_K teve 77% (37/48) e Q4_K_M 68% (41/60), diferença não significativa. Q6_K usa cerca de 550 MiB a mais. O Q4_K_M da unsloth não foi melhor que o do bartowski (7/12).
- **Cache de prompt:** ligado. Sem ele, a latência cresce cerca de 25 vezes.
- **Thinking:** desligado na primeira tentativa e ligado só na escalada. Ligado sempre, a vantagem da etapa 3 (11/12) não se repetiu na etapa 4 (16/24), e o tempo cresce cerca de 3,3 vezes. Como cascata, quando a verificação visível falha, resgatou 4 de 4 casos na etapa 5, com cerca de 116 s extras por resgate.
- **Ferramentas:** sem RTK, que piorou o acerto (6/12). O LSP é neutro; o modelo nunca chamou a ferramenta `lsp` por conta própria.
- **Tarefas longas:** contexto grande com cache, enquanto couber na VRAM (pico de 5,4 GB). Se for preciso limitar o contexto, Headroom foi melhor que a compactação nativa e que o reset.
- **Servidor:** MTP (`--spec-type draft-mtp --spec-draft-n-max 2`) aumenta o decode de 74 para 115 tok/s (aceitação 91%). Checkpoints de contexto (`--ctx-checkpoints 64 --checkpoint-min-step 1024`) reduzem o tempo dos sucessos de 37 para 25 s. Nenhum dos dois teve efeito mensurável no acerto.
- **Amostragem:** temperatura 0. A amostragem recomendada pela Qwen teve 6/12.
- **Passos do OpenCode:** 40. Com 80 o resultado foi 10/12, sem ganho claro.

## Como reproduzir

### Pré-requisitos

- Windows com WSL2 (Ubuntu 24.04) e GPU NVIDIA de 8 GB. Testado com RTX 3070, driver 610.62 e CUDA Toolkit 13.0 (ver [docs/HARDWARE.md](docs/HARDWARE.md)).
- Binários e pesos nos caminhos e com os SHA-256 de `benchmark/configs/qwen-4b-opencode-baseline.json`: `llama-server` do llama.cpp v0.8.0, OpenCode 1.19.5, Node, bubblewrap e os GGUF. Nada disso está no repositório.
- Python 3.12 com pytest e ruff. Versões usadas: pytest 9.1.1 e ruff 0.17.3.

### Comandos sem GPU

A partir da raiz do repositório:

```sh
export PYTHONDONTWRITEBYTECODE=1
PY=python3   # use o Python 3.12 do ambiente de validação
$PY -m pytest -p no:cacheprovider -q                  # 19 arquivos de teste, ver Limitações
$PY -m benchmark.opencode_baseline --dry-run          # lista as 300 unidades do protocolo atual
$PY -m benchmark.opencode_baseline --dry-run --arm B0 # 24 unidades
PYTHONDONTWRITEBYTECODE=1 $PY corpus/validate_corpus.py --node /caminho/para/node   # 12/12 PASS, cerca de 2 min
```

### Comandos com GPU

Estes comandos iniciam o `llama-server`. Rode somente com a GPU livre. O runner se recusa a começar se já houver um `llama-server` ativo.

```sh
$PY -m benchmark.opencode_baseline --smoke                  # 1 episódio: B0, tarefa py_query
$PY -m benchmark.opencode_baseline --smoke --task cont_path # outra tarefa
$PY -m benchmark.opencode_baseline --arm B-kv8              # um braço
$PY -m benchmark.opencode_baseline --stage N                # todas as unidades da etapa N (N de 1 a 4)
```

O protocolo atual grava em `results/qwen-4b-opencode-baseline-bwrap-v7`, porque `benchmark/configs/qwen-4b-opencode-baseline.json` já é a revisão v7 da etapa 4. Para reproduzir as etapas 1 a 3, use o config das revisões v5 e v6, que está em commits anteriores do histórico do git (o último commit antes desta refatoração é `c2cf750`). Resultados com manifesto diferente não são misturados: o runner recusa.

### Relatórios

```sh
$PY -m benchmark.baseline_report DIR_v5 DIR_v6 \
  --markdown relatorio.md --csv relatorio.csv \
  --control-dir DIR_v5 --control B0
```

Os agregados já gerados estão em [results/3070-benchmark/](results/3070-benchmark/). Os resultados brutos (workspaces, logs e JSON por tentativa) ficam fora do repositório.

## Estrutura do repositório

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
results/3070-benchmark/   agregados das etapas 1 a 5, T2 e T3b
reports/                  relatórios das etapas F0, F1, F3 e T1, copiados sem logs nem snapshots
```

## Limitações

- **Poder estatístico baixo.** São 12 episódios por braço (24 no controle), com uma repetição por braço. Diferenças de 1 ou 2 episódios são ruído. No controle, quatro tarefas trocaram de resultado entre as duas repetições.
- **Quantizadores diferentes.** O controle usa Q4_K_M do bartowski. Q6_K e Q8_0 são do unsloth, e o Q4_K_M do unsloth só aparece na etapa 4.
- **Armazenamento.** Os GGUF de Q6_K e Q8_0 são lidos a partir de `/mnt/d` (disco D:). A regra do laboratório pede o ext4 do WSL. O efeito sobre as métricas não foi medido.
- **Sandbox.** A execução do OpenCode permite rede; o confinamento do bash não foi comprovado para todos os comandos. As avaliações atuais usam sandbox separado sem rede; os resultados históricos foram produzidos com as versões anteriores.
- **VRAM do dispositivo.** A VRAM é amostrada no dispositivo inteiro, a cerca de 1 Hz, e o desktop do Windows compartilha a GPU. Não é a memória exclusiva do processo.
- **TTFT por proxy.** O TTFT mede o tempo até o primeiro conteúdo, reasoning ou chamada de ferramenta, visto pelo proxy local. Pode estar indisponível para algumas requisições.
- **Campos ausentes nos resultados v5 e v6.** A taxonomia automática de término e as métricas de qualidade do diff (linhas, escopo, testes enfraquecidos) foram adicionadas depois. Os resultados das etapas 1 a 3 trazem esses campos vazios ou nulos. As causas de falha vêm dos rótulos `failure` gravados pelo runner.
- **Retentativas por infraestrutura.** Duas unidades de v6 tiveram a primeira tentativa anulada por falha do avaliador. A segunda tentativa, que passou, entrou no acerto. Isso segue o protocolo. Em v5, uma falha do modelo foi classificada como infraestrutura e repetida. Essa classificação foi corrigida em v6.
- **Timeouts nas etapas 4 e 5.** Nove resultados finais e duas tentativas intermediárias também registraram reset de conexão. As regras atuais dariam prioridade ao erro de servidor, mas os logs não provam se o reset ocorreu antes do timeout; os números históricos foram mantidos. Veja a [revalidação](reports/analise-estrategia-4b-2026-10-28/execucao/F1/revisao-pr45-correcoes.md).
- **Etapas 4 e 5 com uma repetição na maioria dos braços.** Os braços `S-*`, `Q5-*`, `T5-*` e `X-*` têm 12 episódios e só detectam diferenças acima de cerca de 25 pontos. As maratonas do T2 têm uma repetição cada.
- **T3b.** O 4B escreve o bloco SEARCH de memória e reenvia edições rejeitadas. Erros de OpenSSL afetaram verificações v2 e v3; os acertos históricos não isolam o efeito do contexto. Veja a [revalidação](reports/analise-estrategia-4b-2026-10-28/execucao/F1/revisao-pr45-correcoes.md).
- **Landlock em drvfs.** A execução histórica do T3b usou uma cópia do repositório no ext4 do WSL. O verificador revisado foi testado também em `/mnt/d`.
- **Corpus piloto.** As 12 tarefas não foram calibradas com o modelo nem são um conjunto de confirmação. O `bottle.py` tem cerca de 51 mil tokens, estimados por caracteres.
- **Reprodução em outra máquina.** O config tem caminhos e SHA-256 do laboratório. Para outra máquina, é preciso um novo `protocol_id`, pois o manifesto recusa misturar protocolos.

## Roadmap

Fonte da etapa 4: [relatório T1](reports/analise-estrategia-4b-2026-10-28/execucao/F1/T1-coleta-e-etapa4.md). O plano estratégico v2 e o backlog de 29/10/2026 ficam fora desta árvore; a ordem abaixo segue o que foi combinado neles.

Concluídos em 29/10/2026: etapa 4, etapa 5 (pesos, LSP, RTK e cascatas), tarefas longas (T2) e prefixo em cache (T3b).

1. **Confirmar as direções fortes:** replicar a cascata com thinking e o RTK em 3 repetições, e o T2 (contexto grande contra Headroom) em 3 repetições.
2. **Campanha combinada:** MTP, checkpoints e a cascata com thinking, com Q4_K_M e com Q6_K.
3. **MCP** e quantizações novas, conforme forem lançadas.
4. **Backlog P1:** consolidar a configuração de uso; ampliar o corpus de 12 para 24 a 36 tarefas inéditas; comparar ExLlamaV3 com TabbyAPI contra llama.cpp, depois de verificar as tool calls do Qwen3.5 híbrido; comparar o custo com um modelo grande no mesmo corpus.
5. **Backlog P2:** mistral.rs com o mesmo GGUF; trabalhador delimitado em escala; llama.cpp nativo no Windows contra WSL2; recompilar com `GGML_CUDA_FA_QUANTS` para KV misto.
6. **Backlog P3, fora do escopo do 4B:** vLLM ou LMDeploy com AWQ e GPTQ-Marlin; offload de MoE maior que a VRAM; modelos de 7 a 14B; LoRA de agente.

## Histórico

As campanhas anteriores a 28/10/2026 foram removidas desta árvore. Estão no histórico do git, até o commit `c2cf750` de `refactor/3070-benchmark` e seus antecessores. A lista do que saiu e por quê está no Pull Request de refatoração.
