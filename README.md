# Benchmark de LLM local: Qwen3.5-4B em RTX 3070 (8 GB)

> **English summary.** This repository benchmarks a local coding agent on one RTX 3070 8 GB under WSL2. Qwen3.5-4B runs on llama.cpp v0.8.0 and OpenCode 1.19.5. The 12-task pilot corpus uses private oracles. A three-repeat stage 5 replication confirmed that retrying a visibly failed attempt with thinking enabled raises accuracy from 29/48 to 41/48 across the original stage 5 and its replication (McNemar p=0.008 in the replication). RTK scored 17/36 against 22/36 for the paired control (p=0.23). The combined MTP, context-checkpoint and 2 GiB prompt-cache profile kept final accuracy near the control (29/36 vs 30/36) and used fewer escalations; Q6_K_L gave no accuracy gain and used 0.8 GB more VRAM. The cache limit addresses a WSL out-of-memory event, but its effect was not isolated. Long-task marathons favoured a large context over compaction or resets, and a cached 46K-token repository prefix cut time to first token from 16 s to 0.16 s. Campaigns before 2026-10-28 were removed from this tree and remain in the git history.

## Resumo

Este repositório mede, em uma única máquina, quanto cada escolha de runtime muda a taxa de acerto e o custo de um agente de programação local.

- **Modelo e runtime:** Qwen3.5-4B em GGUF, servido pelo `llama-server` do llama.cpp v0.8.0 (commit `8642541`) com CUDA. Uma instância por braço, `--parallel 1`, execução serial.
- **Agente:** OpenCode 1.19.5 (`opencode run --format json --pure`), isolado em bubblewrap 0.9.0. O sandbox não monta o repositório, `/mnt/d`, `/home` nem os oráculos.
- **Corpus:** 12 tarefas de piloto em 6 classes (2 por classe), com oráculo privado avaliado uma vez ao fim de cada tentativa. O oráculo nunca entra no prompt.
- **Matriz:** as etapas iniciais variam um fator por vez a partir do controle B0 (Q4_K_M, KV q4_0, 64K, cache de prompt ligado, thinking desligado, temperatura 0). Depois vieram a replicação da cascata e a campanha combinada.

Detalhes: [método](docs/METHODOLOGY.md), [máquina e versões](docs/HARDWARE.md), [todas as tabelas](docs/RESULTS.md).

## Principais resultados

A tabela abaixo preserva os resultados das etapas 1 a 3, com intervalo de Wilson de 95%. "Pareado" compara cada braço com o controle, por tarefa e repetição 1 (McNemar exato, bilateral).

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
- **Thinking sempre ligado:** 11/12 na etapa 3 e 16/24 na etapa 4; a vantagem não se repetiu. Como escalada, porém, o thinking foi confirmado: na replicação da etapa 5, a cascata passou de 22/36 para 30/36 (McNemar p = 0,008). Somada à etapa 5 original, passou de 29/48 para 41/48.
- **Etapa 4 (replicação e servidor):** controle 25/36, Q6_K 27/36, MTP com decode 55% mais rápido, checkpoints de contexto com tempo dos sucessos 34% menor. Tabela completa em [docs/RESULTS.md](docs/RESULTS.md), seção 7.
- **Etapa 5 e replicação:** a cascata com thinking passou de 7/12 para 11/12 na primeira coleta e de 22/36 para 30/36 na replicação. O RTK marcou 17/36 contra 22/36 do controle replicado (p = 0,23), sem diferença significativa. Ver [docs/RESULTS.md](docs/RESULTS.md), seções 8 e 11.
- **Campanha combinada:** MTP, checkpoints e o limite de cache de 2 GiB mantiveram o acerto final do Q4 próximo ao controle (29/36 contra 30/36) e reduziram as escaladas de 10 para 3. Q6_K_L fez 28/36, sem ganho sobre o Q4 (29/36), e usou 0,8 GB a mais de VRAM. O cache RAM mudou junto com os outros fatores. Ver [docs/RESULTS.md](docs/RESULTS.md), seção 12.
- **Tarefas longas (T2):** em maratonas de 5 a 6 objetivos, o contexto grande passou em 9/9 oráculos. Headroom ficou em 7/9, a compactação do OpenCode em 6/9 e o reset com `PROGRESS.md` em 5/9. Ver seção 9.
- **Prefixo do repositório em cache (T3b):** com cerca de 46 mil tokens já no cache, o TTFT cai de 16,1 s para 0,16 s. A v3 registrou 2/12 nos três braços. Excluindo a tarefa `js_sign` do P-W16 por falha comprovada do verificador, esse braço fica em 2/11; outros episódios também sofreram diagnósticos ambientais. A comparação de qualidade é inconclusiva. Ver seção 10.
- **Significância:** a cascata com thinking na replicação da etapa 5 é a única comparação nova com resultado significativo (p = 0,008). As comparações pareadas da campanha combinada e do RTK não atingem p < 0,05. No braço de 16K, com 5 derrotas e nenhuma vitória, p = 0,0625 é o menor valor possível com cinco pares discordantes na mesma direção. Use os demais números como sinais, não como ranking.

## Configuração recomendada

Estas recomendações saem das etapas 1 a 5, da replicação da etapa 5 e das campanhas combinada, T2 e T3b (detalhes em [docs/RESULTS.md](docs/RESULTS.md), seções 7 a 12).

- **Contexto:** 32K é o mínimo, e 64K dá margem. Com OpenCode, 16K não serve neste corpus.
- **KV cache:** q4_0. Não houve perda mensurável e é o de menor VRAM.
- **Pesos:** Q4_K_M. Q6_K_L fez 28/36 contra 29/36 no Q4 combinado e usou 818 MiB a mais. A etapa 4 também não mostrou diferença significativa entre Q4_K_M e Q6_K.
- **Cache de prompt:** ligado. Sem ele, a latência cresce cerca de 25 vezes.
- **Thinking:** desligado na primeira tentativa e ligado só na escalada. A replicação passou de 22/36 para 30/36 (8 resgates em 10 escaladas; McNemar p = 0,008). Somada à etapa 5 original, a cascata passou de 29/48 para 41/48.
- **RTK:** manter desligado. Na replicação, fez 17/36 contra 22/36 do controle, sem diferença significativa (p = 0,23).
- **MTP e checkpoints:** habilitar `--spec-type draft-mtp --spec-draft-n-max 2` e `--ctx-checkpoints 64 --checkpoint-min-step 1024`. Na campanha combinada, o Q4 manteve o acerto final (29/36 contra 30/36) e usou 3 escaladas contra 10. Como os fatores mudaram juntos, não se pode atribuir esse resultado a um só deles.
- **Cache RAM:** limitar com `--cache-ram 2048`. O padrão de 8 GiB coincide com toda a RAM configurada para o WSL e causou OOM durante a campanha combinada. O braço de comparação usou o padrão de 8 GiB; o efeito do limite não foi isolado.
- **Ferramentas:** manter o RTK desligado. A coleta inicial fez 6/12; a replicação marcou 17/36 contra 22/36 do controle (p = 0,23). O LSP foi neutro, e o modelo não chamou a ferramenta lsp por conta própria.
- **Tarefas longas:** contexto grande com cache, enquanto couber na VRAM (pico de 5,4 GB). Se for preciso limitar o contexto, Headroom foi melhor que a compactação nativa e que o reset.
- **Servidor:** MTP elevou o decode de 74 para 115 tok/s na etapa 4 (aceitação 91%). Checkpoints reduziram o tempo dos sucessos de 37 para 25 s. Na campanha combinada, os dois foram usados junto com a cascata; o desenho não separa seus efeitos.
- **Amostragem:** temperatura 0 na primeira tentativa. Na escalada com thinking, temperatura 0,6, top_p 0,95 e top_k 20. A amostragem recomendada pela Qwen teve 6/12.
- **Passos do OpenCode:** 40. Com 80 o resultado foi 10/12, sem ganho claro.

### Perfil pronto

Substitua `<models>` pelo diretório que contém o GGUF e inicie o servidor recomendado:

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

Trecho de `opencode.json` para o provider local. O thinking fica desligado no servidor; os 40 passos e a temperatura 0 ficam no perfil do modelo.

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

Para escalar manualmente, suba um segundo servidor ou reinicie o mesmo servidor trocando as opções de thinking e amostragem:

```sh
--reasoning on \
--chat-template-kwargs '{"enable_thinking": true}' \
--temp 0.6 --top-p 0.95 --top-k 20
```

No perfil do OpenCode, use também `"options": { "temperature": 0.6, "topP": 0.95, "topK": 20 }`. O benchmark faz essa escalada automaticamente pelo runner quando a tentativa falha na verificação visível; no uso manual, ela é um segundo passo.

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
results/3070-benchmark/   agregados das etapas 1 a 5, replicação, campanha combinada, T2 e T3b
reports/                  relatórios das etapas F0, F1, F3 e T1, copiados sem logs nem snapshots
```

## Limitações

- **Corpus pequeno e saturado.** São 12 tarefas de piloto. Oito quase sempre passam; py_range nunca passou. Muitos braços têm só 12 episódios; as comparações com 36 episódios ainda têm pouca potência para diferenças pequenas.
- **Quantizadores diferentes.** O controle usa Q4_K_M do bartowski. Q6_K e Q8_0 são do unsloth, e o Q4_K_M do unsloth só aparece na etapa 4.
- **Armazenamento.** Os GGUF de Q6_K e Q8_0 são lidos a partir de `/mnt/d` (disco D:). A regra do laboratório pede o ext4 do WSL. O efeito sobre as métricas não foi medido.
- **Sandbox.** A execução do OpenCode permite rede; o confinamento do bash não foi comprovado para todos os comandos. As avaliações atuais usam sandbox separado sem rede; os resultados históricos foram produzidos com as versões anteriores.
- **VRAM do dispositivo.** A VRAM é amostrada no dispositivo inteiro, a cerca de 1 Hz, e o desktop do Windows compartilha a GPU. Não é a memória exclusiva do processo.
- **TTFT por proxy.** O TTFT mede o tempo até o primeiro conteúdo, reasoning ou chamada de ferramenta, visto pelo proxy local. Pode estar indisponível para algumas requisições.
- **Fatores combinados.** MTP, checkpoints e o limite de cache RAM de 2 GiB foram ativados juntos. A comparação usou como referência um braço com cache RAM padrão de 8 GiB; o efeito isolado do limite não é conhecido.
- **Campos ausentes nos resultados v5 e v6.** A taxonomia automática de término e as métricas de qualidade do diff (linhas, escopo, testes enfraquecidos) foram adicionadas depois. Os resultados das etapas 1 a 3 trazem esses campos vazios ou nulos. As causas de falha vêm dos rótulos `failure` gravados pelo runner.
- **Retentativas por infraestrutura.** Duas unidades de v6 tiveram a primeira tentativa anulada por falha do avaliador. A segunda tentativa, que passou, entrou no acerto. Isso segue o protocolo. Em v5, uma falha do modelo foi classificada como infraestrutura e repetida. Essa classificação foi corrigida em v6.
- **Timeouts nas etapas 4 e 5.** Nove resultados finais e duas tentativas intermediárias também registraram reset de conexão. As regras atuais dariam prioridade ao erro de servidor, mas os logs não provam se o reset ocorreu antes do timeout; os números históricos foram mantidos. Veja a [revalidação](reports/analise-estrategia-4b-2026-10-28/execucao/F1/revisao-pr45-correcoes.md).
- **Repetições desiguais.** Muitos braços exploratórios das etapas 4 e 5 têm 12 episódios. A cascata replicada e a campanha combinada têm 36 episódios por braço. O T2 ainda tem uma repetição por braço, e a conclusão sobre compactação não confirma que ela terminou.
- **T3b.** O 4B escreve o bloco SEARCH de memória e reenvia edições rejeitadas. Erros de OpenSSL afetaram verificações v2 e v3; os acertos históricos não isolam o efeito do contexto. Veja a [revalidação](reports/analise-estrategia-4b-2026-10-28/execucao/F1/revisao-pr45-correcoes.md).
- **Landlock em drvfs.** A execução histórica do T3b usou uma cópia do repositório no ext4 do WSL. O verificador revisado foi testado também em `/mnt/d`.
- **Corpus piloto.** As 12 tarefas não foram calibradas com o modelo nem são um conjunto de confirmação. O `bottle.py` tem cerca de 51 mil tokens, estimados por caracteres.
- **Reprodução em outra máquina.** O config tem caminhos e SHA-256 do laboratório. Para outra máquina, é preciso um novo `protocol_id`, pois o manifesto recusa misturar protocolos.

## Roadmap

Concluídos: etapa 4, etapa 5 e sua replicação em três repetições, campanha combinada de MTP e checkpoints, tarefas longas (T2) e prefixo em cache (T3b).

Próximos passos:

1. **Ampliar o corpus:** de 12 para 24–36 tarefas inéditas.
2. **Repetir T2:** três repetições por braço e confirmação de que a compactação terminou.
3. **Backlog P1:** comparar ExLlamaV3 com TabbyAPI contra llama.cpp após verificar as chamadas de ferramenta do Qwen3.5 híbrido; comparar o custo com um modelo grande no mesmo corpus.
4. **MCP e quantizações novas**, conforme forem lançadas.

Backlog:

- **P2:** mistral.rs com o mesmo GGUF; trabalhador delimitado em escala; llama.cpp nativo no Windows contra WSL2; recompilar com GGML_CUDA_FA_QUANTS para KV misto.
- **P3, fora do escopo do 4B:** vLLM ou LMDeploy com AWQ e GPTQ-Marlin; offload de MoE maior que a VRAM; modelos de 7 a 14B; LoRA de agente.

## Histórico

As campanhas anteriores a 28/10/2026 foram removidas desta árvore. Estão no histórico do git, até o commit `c2cf750` de `refactor/3070-benchmark` e seus antecessores. A lista do que saiu e por quê está no Pull Request de refatoração.
