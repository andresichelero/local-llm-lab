# Resultados completos

Este documento reúne todas as tabelas das etapas 1 a 4. O resumo e a leitura estão no [README](../README.md).

## Fontes e escopo

- **Dados brutos (fora do repositório).** `qwen-4b-opencode-baseline-bwrap-v5` (controle B0, 24 episódios) e `qwen-4b-opencode-baseline-bwrap-v6` (nove braços, 12 episódios cada), no ext4 do WSL.
- **Protocolos.** `qwen-4b-opencode-baseline-b-20261029-bwrap-v5` e `qwen-4b-opencode-baseline-b-20261029-bwrap-v6`, como registrados nos manifestos.
- **Agregados.** [baseline-report-v5-v6.md](../results/3070-benchmark/baseline-report-v5-v6.md) e [baseline-report-v5-v6.csv](../results/3070-benchmark/baseline-report-v5-v6.csv), gerados por `benchmark/baseline_report.py` com `--control-dir` apontando para v5 e `--control B0`. A saída de [arm-summary-v5-v6.txt](../results/3070-benchmark/arm-summary-v5-v6.txt) veio de um script auxiliar só de leitura, fora do repositório. Ela traz as colunas de VRAM máxima e de fração de cache, que o relatório não calcula.
- **Verificação da configuração.** Os 10 braços das etapas 1 a 3, registrados nos manifestos de v5 e v6, são idênticos aos do config atual. Não há nenhuma diferença.

## 1. Configuração de cada braço

A tabela lista todos os braços do config atual (`benchmark/configs/qwen-4b-opencode-baseline.json`), inclusive a etapa 4. As etapas 1 a 3 rodaram com as mesmas especificações. Os resultados da etapa 4 estão na seção 7.

| Etapa | Braço | Repetições | Pesos | Contexto (tokens) | KV K/V | Cache de prompt | Thinking | Amostragem | Passos | Argumentos extra do servidor |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Etapa 1 | `B0` | 2 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 2 | `B-ctx16` | 1 | Q4_K_M (bartowski, controle) | 16384 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 2 | `B-ctx32` | 1 | Q4_K_M (bartowski, controle) | 32768 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 2 | `B-ctx128` | 1 | Q4_K_M (bartowski, controle) | 131072 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 2 | `B-kv8` | 1 | Q4_K_M (bartowski, controle) | 65536 | q8_0/q8_0 | sim | não | temp 0 | 40 | — |
| Etapa 2 | `B-kv16` | 1 | Q4_K_M (bartowski, controle) | 65536 | f16/f16 | sim | não | temp 0 | 40 | — |
| Etapa 3 | `B-q6` | 1 | Q6_K (unsloth) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 3 | `B-q8` | 1 | Q8_0 (unsloth) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 3 | `B-nocache` | 1 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | não | não | temp 0 | 40 | — |
| Etapa 3 | `B-think` | 1 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | sim | sim | temp 0.6, top_p 0.95, top_k 20 | 40 | — |
| Etapa 4 | `C4-q4` | 3 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 4 | `C4-think` | 2 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | sim | sim | temp 0.6, top_p 0.95, top_k 20 | 40 | — |
| Etapa 4 | `C4-q6` | 3 | Q6_K (unsloth) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 4 | `S-qwen-sampling` | 1 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | sim | não | temperature=0.7, top_p=0.8, top_k=20, min_p=0, presence_penalty=1.5 | 40 | — |
| Etapa 4 | `S-steps80` | 1 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 80 | — |
| Etapa 4 | `S-ctx48` | 1 | Q4_K_M (bartowski, controle) | 49152 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |
| Etapa 4 | `S-checkpoints` | 1 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 40 | `--ctx-checkpoints 64 --checkpoint-min-step 1024` |
| Etapa 4 | `S-mtp` | 1 | Q4_K_M (bartowski, controle) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 40 | `--spec-type draft-mtp --spec-draft-n-max 2` |
| Etapa 4 | `S-q4-unsloth` | 1 | Q4_K_M (unsloth) | 65536 | q4_0/q4_0 | sim | não | temp 0 | 40 | — |

## 2. Resultados por braço (etapas 1 a 3)

Definições:

- **Acertos e taxa.** Primeira tentativa por unidade, exceto falhas de infraestrutura repetidas uma vez (ver [METHODOLOGY](METHODOLOGY.md), seção 7).
- **IC 95%.** Intervalo de Wilson.
- **Tempo mediano, todos.** Mediana do tempo total dos episódios do braço.
- **Tempo mediano, sucessos.** Mediana do tempo total só dos episódios com sucesso.
- **TTFT mediano.** Mediana, por episódio, do TTFT mediano das requisições. Os relatórios das etapas (`B-etapa1` a `B-etapa3`) usam a mediana sobre todas as requisições, por isso trazem valores diferentes, como 273 ms no controle e 7 704 ms sem cache.
- **VRAM pico.** Máximo entre os episódios do braço, do dispositivo inteiro.
- **Fração do prompt em cache.** Soma de `cache_n` dividida pela soma de `prompt_n` mais `cache_n`, em todas as requisições do braço.
- **Pareado com o controle.** Vitórias, derrotas e empates nos pares de mesma tarefa e repetição 1, contra B0 de v5. O p é do teste de McNemar exato, bilateral.

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

## 3. Métricas detalhadas

Prefill e geração são medianas, por episódio, das taxas que o servidor devolve nos timings. A VRAM mediana é a mediana dos picos por episódio. As causas são os rótulos `failure` gravados pelo runner (ver [METHODOLOGY](METHODOLOGY.md), seção 8).

| Braço | Tempo médio, todos (s) | Tempo mediano, todos (s) | Tempo mediano, sucessos (s) | TTFT mediano (ms) | Prefill mediano (tok/s) | Geração mediana (tok/s) | VRAM mediana por episódio (MiB) | Falhas do modelo por causa |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `B0` | 97.8 | 42.3 | 36.4 | 296 | 714 | 71.2 | 4536 | oráculo 5; fase 1 1; tempo 1; CLI 1 |
| `B-ctx16` | 27.1 | 16.4 | 27.6 | 448 | 1403 | 80.6 | 3847 | CLI 9 |
| `B-ctx32` | 57.8 | 46.1 | 38.1 | 235 | 737 | 82.7 | 4074 | oráculo 3 |
| `B-ctx128` | 107.0 | 58.2 | 37.8 | 294 | 830 | 75.8 | 5422 | oráculo 2; tempo 1 |
| `B-kv8` | 71.5 | 39.0 | 30.5 | 265 | 850 | 76.8 | 5036 | oráculo 2; CLI 1 |
| `B-kv16` | 109.9 | 34.6 | 32.0 | 306 | 984 | 77.7 | 5747 | oráculo 4; tempo 1 |
| `B-q6` | 105.5 | 37.0 | 34.3 | 301 | 858 | 65.4 | 5116 | oráculo 1; CLI 1 |
| `B-q8` | 54.3 | 38.5 | 32.2 | 317 | 758 | 59.0 | 6033 | oráculo 4 |
| `B-nocache` | 194.8 | 115.5 | 81.7 | 7498 | 3433 | 75.5 | 4509 | tempo 1; oráculo 1; CLI 1 |
| `B-think` | 122.6 | 110.1 | 108.9 | 214 | 1113 | 78.5 | 4528 | oráculo 1 |

## 4. Acertos por tarefa e repetição

Cada célula lista o resultado de cada repetição: 1 é acerto e 0 é falha. No controle há duas repetições, com a primeira à esquerda. Os demais braços têm uma repetição.

Dois acertos vêm da segunda tentativa, depois que o avaliador falhou na primeira: `recover_date` em `B-kv16` e `recover_decode` em `B-q8`. A regra do protocolo conta esses acertos. No controle, a primeira tentativa de `cont_path` r2 é uma falha do modelo. Em v5 ela foi classificada como infraestrutura e repetida, e a correção dessa classificação está na v6.

| Tarefa | B0 (v5) | B-ctx16 (v6) | B-ctx32 (v6) | B-ctx128 (v6) | B-kv8 (v6) | B-kv16 (v6) | B-q6 (v6) | B-q8 (v6) | B-nocache (v6) | B-think (v6) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `cont_path` | 10 | 0 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 1 |
| `cont_quote` | 11 | 0 | 1 | 1 | 1 | 0 | 1 | 1 | 1 | 1 |
| `js_plural` | 11 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `js_sign` | 10 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `mcp_header` | 11 | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `mcp_params` | 11 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `py_query` | 11 | 0 | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `py_range` | 00 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| `recover_date` | 01 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 1 | 1 |
| `recover_decode` | 11 | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| `tests_query` | 00 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 1 | 1 |
| `tests_range` | 01 | 0 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 1 |

## 5. Comparações pareadas

Cada braço é comparado com o controle B0 de v5, nos pares de tarefa e repetição 1. Como o braço tem doze tarefas, há doze pares. Vitórias são pares em que o braço acertou e o controle errou. Derrotas são o contrário. O p é bilateral e exato, sobre os pares discordantes.

| Braço | Pares | Vitórias do braço | Derrotas do braço | Empates | p exato de McNemar |
| --- | --- | --- | --- | --- | --- |
| `B-ctx16` | 12 | 0 | 5 | 7 | 0.0625 |
| `B-ctx32` | 12 | 2 | 1 | 9 | 1.0000 |
| `B-ctx128` | 12 | 1 | 0 | 11 | 1.0000 |
| `B-kv8` | 12 | 1 | 0 | 11 | 1.0000 |
| `B-kv16` | 12 | 1 | 2 | 9 | 1.0000 |
| `B-q6` | 12 | 2 | 0 | 10 | 0.5000 |
| `B-q8` | 12 | 1 | 1 | 10 | 1.0000 |
| `B-nocache` | 12 | 2 | 1 | 9 | 1.0000 |
| `B-think` | 12 | 3 | 0 | 9 | 0.2500 |

Com doze pares por braço, nenhuma comparação chega a p < 0,05. No braço de 16K há cinco derrotas e nenhuma vitória, e o p de 0,0625 é o menor possível com cinco pares discordantes na mesma direção.

## 6. Notas de leitura

- **Definições diferentes nos textos das etapas.** Os relatórios `B-etapa1` a `B-etapa3` usam a mediana de todas as requisições para o TTFT e a mediana dos sucessos para o tempo. As tabelas deste documento usam as definições acima. Os dois conjuntos de números são corretos e mostram o mesmo resultado.
- **Campos ausentes.** Nos resultados v5 e v6, o campo `taxonomy` é nulo nas falhas, e não existem os campos de diff (`diff_quality`) e de métricas de requisição (`request_metrics`). Por isso as análises de qualidade do código produzido e de tags de término não estão disponíveis para as etapas 1 a 3.
- **Desvio de armazenamento.** Os braços `B-q6` e `B-q8` leem os GGUF de D:, e isso não foi medido (ver [HARDWARE](HARDWARE.md)).
- **Quantizador.** O controle usa o Q4_K_M de bartowski. Q6_K e Q8_0 são de unsloth. Um efeito de quantização não pode ser separado do efeito de quantizador sem a etapa 4, que inclui Q4_K_M de unsloth.
- **Ruído entre repetições.** No controle, as tarefas `cont_path`, `js_sign`, `recover_date` e `tests_range` trocaram de resultado entre a repetição 1 e a 2.

## 7. Etapa 4: replicação e opções de servidor (v7)

Dados brutos: `qwen-4b-opencode-baseline-bwrap-v7` (168 episódios, protocolo v7, 40 passos, nenhuma falha de infraestrutura). Agregados: [arm-summary-v5-v6-v7.txt](../results/3070-benchmark/arm-summary-v5-v6-v7.txt) e [stage4-detail.txt](../results/3070-benchmark/stage4-detail.txt). Análise: [B-etapa4-replicacao-e-servidor.md](../reports/analise-estrategia-4b-2026-10-28/execucao/F1/B-etapa4-replicacao-e-servidor.md).

| Braço | Mudança | Acertos | Taxa | Tempo mediano, sucessos (s) | Geração mediana (tok/s) | VRAM pico (MiB) |
| --- | --- | --- | --- | --- | --- | --- |
| `C4-q4` | controle, 3 repetições | 25/36 | 69% | 37.5 | 74 | 4584 |
| `C4-q6` | Q6_K (unsloth), 3 repetições | 27/36 | 75% | 32.0 | 67 | 5127 |
| `C4-think` | thinking on, 2 repetições | 16/24 | 67% | 123.0 | 74 | 4529 |
| `S-ctx48` | contexto 48K | 11/12 | 92% | 45.4 | 76 | 4307 |
| `S-steps80` | 80 passos | 10/12 | 83% | 39.0 | 78 | 4531 |
| `S-checkpoints` | `--ctx-checkpoints 64 --checkpoint-min-step 1024` | 9/12 | 75% | 24.5 | 76 | 4531 |
| `S-mtp` | MTP, `--spec-draft-n-max 2` (aceitação 91%) | 8/12 | 67% | 24.8 | **115** | 5129 |
| `S-q4-unsloth` | Q4_K_M (unsloth) | 7/12 | 58% | 36.0 | 77 | 4379 |
| `S-qwen-sampling` | amostragem recomendada pela Qwen | 6/12 | 50% | 36.7 | 72 | 4531 |

Agregando as etapas 1 a 4 (IC 95% de Wilson): Q4_K_M 41/60 = 68% (56%–79%); Q6_K 37/48 = 77% (63%–87%); thinking 27/36 = 75% (59%–86%). No pareamento C4-q4 × C4-q6, por tarefa e repetição, há 4 casos só do Q4 e 6 só do Q6, sem significância.

Leitura: a vantagem do thinking na etapa 3 (92%) não se repetiu, e ele custa cerca de 3,3 vezes mais tempo. MTP (+55% de decode) e checkpoints de contexto reduzem o tempo mediano dos sucessos em cerca de um terço, sem efeito mensurável no acerto. Q6_K continua sendo o melhor peso, sem diferença significativa. Com o protocolo v7 e a etapa 4, o teste `test_schedule_matches_matrix` espera 300 unidades, igual ao config.

## 8. Etapa 5: pesos, ferramentas e cascatas (protocolo stage5-v2)

Os dados brutos estão em `qwen-4b-opencode-stage5-v2`: 96 episódios (8 braços × 12 tarefas × 1 repetição), sem nenhuma falha de infraestrutura.

- Agregado: [stage5-detail.txt](../results/3070-benchmark/stage5-detail.txt).
- Análise: [B-etapa5-pesos-ferramentas-cascatas.md](../reports/analise-estrategia-4b-2026-10-28/execucao/F1/B-etapa5-pesos-ferramentas-cascatas.md).

Conta a primeira tentativa.

| Braço | Mudança | Acertos | IC 95% (Wilson) | Tempo mediano (s) |
| --- | --- | --- | --- | --- |
| `Q5-Q6KL` | Q6_K_L (bartowski) | 10/12 | 55%–95% | 56.1 |
| `Q5-UDQ6XL` | UD-Q6_K_XL (unsloth) | 10/12 | 55%–95% | 40.1 |
| `T5-lsp-tool` | LSP + ferramenta `lsp` (0 chamadas) | 10/12 | 55%–95% | 37.8 |
| `Q5-UDQ4XL` | UD-Q4_K_XL (unsloth) | 9/12 | 47%–91% | 34.2 |
| `T5-lsp` | diagnósticos Pyright | 9/12 | 47%–91% | 67.0 |
| `X-9b` (1ª tentativa) | igual ao controle | 8/12 | 39%–86% | 37.3 |
| `X-think` (1ª tentativa) | igual ao controle | 7/12 | 32%–81% | 44.4 |
| `T5-rtk` | plugin RTK | 6/12 | 25%–75% | 44.2 |

As cascatas só escalam quando há falha visível ou falha do modelo:

| Cascata | 1ª tentativa | Escalonamentos | Resultado final | Tempo extra |
| --- | --- | --- | --- | --- |
| `X-think`: 2ª tentativa com thinking ligado | 7/12 | 4 | 11/12 | 465 s |
| `X-9b`: 2ª tentativa com o 9B Q4_K_M | 8/12 | 3 | 9/12 | 813 s |

Leitura:
- Nenhum braço difere do controle de forma significativa.
- A cascata com thinking resgatou todos os casos escalados, sem trocar de modelo.
- O RTK reescreve o pytest para `rtk pytest`, o que resume a saída. Foi o pior braço e o que mais gastou prompt.

## 9. Tarefas longas (T2, protocolo long-tasks-v2)

Os dados brutos estão em `qwen-4b-opencode-long-tasks-20261029-v2`: 8 maratonas (4 braços × 2 maratonas × 1 repetição), sem nenhuma falha de infraestrutura.

- Agregado: [t2-long-tasks-summary.txt](../results/3070-benchmark/t2-long-tasks-summary.txt).
- Análise: [T2-resultados-tarefas-longas.md](../reports/analise-estrategia-4b-2026-10-28/execucao/F1/T2-resultados-tarefas-longas.md).

| Braço | M1 (de 4 oráculos) | M2 (de 5 oráculos) | Total | Tokens de prompt | VRAM pico (MiB) |
| --- | --- | --- | --- | --- | --- |
| `L-bigctx` | 4 | 5 | 9/9 | 7,87 M | 5432 |
| `L-headroom` | 2 | 5 | 7/9 | 2,41 M | 4077 |
| `L-compact` | 3 | 3 | 6/9 | 1,52 M | 4103 |
| `L-reset` | 3 | 2 | 5/9 | 2,01 M | 4077 |

Não houve regressão nem OOM. A instrumentação registra o pedido de compactação, mas não confirma que ela terminou.

## 10. Prefixo do repositório em cache (T3b, protocolos prefix-cache-v2 e v3)

Os dados brutos estão em `qwen-4b-prefix-cache-v2`: 108 unidades (3 braços × 12 tarefas × 3 repetições), sem falhas de infraestrutura registradas na classificação final. A revalidação encontrou falhas ambientais do verificador em parte das unidades; veja abaixo. As repetições saíram idênticas com temperatura 0, então a amostra efetiva é de 12 tarefas por braço.

- Agregado: [t3b-prefix-cache-summary.json](../results/3070-benchmark/t3b-prefix-cache-summary.json).
- Análise: [T3b-prefixo-em-cache.md](../reports/analise-estrategia-4b-2026-10-28/execucao/F1/T3b-prefixo-em-cache.md).

| Braço | Tarefas aprovadas | TTFT mediano | Tokens do cache | Tempo mediano (s) | Mediana do pico de VRAM por episódio (MiB) |
| --- | --- | --- | --- | --- | --- |
| `P-W16`: trechos de até 16K | 2/12 | 82 ms | 2.844 | 8.3 | 3871 |
| `P-WL-cold`: prefixo de cerca de 46K, cache frio | 1/12 | 16,1 s | 0 | 22.1 | 4510 |
| `P-WL-warm`: o mesmo prefixo, já no cache | 2/12 | 158 ms | 45.455 | 9.2 | 4508 |

Conclusões:
- O cache torna viável um prefixo de 46 mil tokens na 3070.
- A qualidade é inconclusiva, por dois motivos:
  - o prefixo mascarado induz o marcador `# task-specific line withheld` no bloco SEARCH;
  - o worker F3 não repara edições rejeitadas.

### v3: desenho corrigido

Agregado com as 36 unidades e o manifesto: [t3b-v3-prefix-cache-summary.json](../results/3070-benchmark/t3b-v3-prefix-cache-summary.json).

Os dados brutos estão em `qwen-4b-prefix-cache-v3`: 36 unidades (3 braços × 12 tarefas × 1 repetição), sem falhas de infraestrutura registradas na classificação final. A v3 fez três mudanças:
- mostra nos pacotes WL o texto atual das linhas mascaradas;
- permite reparar uma edição rejeitada, com até 2 reparos por episódio;
- usa 1 repetição.

| Braço | Tarefas aprovadas | TTFT mediano | Tempo mediano (s) |
| --- | --- | --- | --- |
| `P-W16` | 2/12 | 1,0 s | 11.9 |
| `P-WL-cold` | 2/12 | 17,8 s | 32.3 |
| `P-WL-warm` | 2/12 | 2,1 s | 13.8 |

Conclusões:
- O marcador sumiu do SEARCH (0 de 36), mas o acerto não mudou: são as mesmas duas tarefas nos três braços.
- O 4B escreve o SEARCH de memória, e não por cópia.
- Com temperatura 0, ele reenvia a mesma edição rejeitada em 29 de 33 reparos WL.
- A comparação de qualidade é inconclusiva: verificações falharam por acesso negado à configuração do OpenSSL, e seus diagnósticos afetaram reparos.
- O prefixo em cache traz só ganho de latência.

Na revalidação, 9 notas privadas da v2 e 5 da v3 passaram em cópias isoladas, embora tenham falhado na execução histórica por erro ambiental. Todas as 14 entregas foram rejeitadas; isso não permite reconstruir os reparos que teriam ocorrido com o verificador saudável. Além disso, `P-W16/js_sign` foi rejeitada por diagnóstico ambiental, sem falha de modelo comprovada: excluindo essa tarefa, o resultado do P-W16 passa de **2/12 para 2/11** tanto na v2 (três repetições) quanto na v3 (uma). As tabelas mantêm os registros históricos. Outros episódios receberam diagnósticos ambientais, portanto 2/11 não torna a comparação de qualidade conclusiva. Nas etapas 4 e 5, 11 tentativas com timeout também registraram reset de conexão: a aplicação literal da nova prioridade classificaria 9 resultados finais e 2 tentativas intermediárias como infraestrutura, mas os logs não mostram se o reset precedeu o timeout. As tabelas preservam as classificações históricas. Os detalhes e os limites dos logs estão na [revisão do PR 45](../reports/analise-estrategia-4b-2026-10-28/execucao/F1/revisao-pr45-correcoes.md).

## 11. Replicação da etapa 5 (stage5-rep3-v2)

Dados brutos: /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-stage5-rep3-v2 (72 episódios: 2 braços × 12 tarefas × 3 repetições, sem falha de infraestrutura).

- Agregado: [stage5-rep3-summary.txt](../results/3070-benchmark/stage5-rep3-summary.txt).
- Análise: [B-etapa5-replicacao-rep3.md](../reports/analise-estrategia-4b-2026-10-28/execucao/F1/B-etapa5-replicacao-rep3.md).

| Braço | 1ª tentativa | Final | Escaladas | Resgates |
| --- | --- | --- | ---: | ---: |
| X-think | 22/36 = 61% (IC 45%–75%) | 30/36 = 83% (IC 68%–92%) | 10 | 8 |
| T5-rtk | 17/36 = 47% (IC 32%–63%) | 17/36 = 47% (IC 32%–63%) | 0 | 0 |

Comparações pareadas, por tarefa e repetição (McNemar exato):

| Comparação | Só a 1ª passou | Só a 2ª passou | p |
| --- | ---: | ---: | ---: |
| X-think: 1ª tentativa contra o resultado final | 0 | 8 | 0,008 |
| Controle X-think contra T5-rtk, 1ª tentativa | 8 | 3 | 0,23 |

Na cascata, 10 tentativas foram escaladas; 8 foram resgatadas e nenhum sucesso da primeira tentativa se perdeu no resultado final. Somada à etapa 5 original, a taxa final foi 41/48 (85%), contra 29/48 (60%) na primeira tentativa: 12 resgates em 14 escaladas.

| Tarefa | X-think (r1, r2, r3) | T5-rtk (r1, r2, r3) |
| --- | --- | --- |
| cont_path | 111 | 010 |
| cont_quote | FFF | 110 |
| js_plural | 111 | 111 |
| js_sign | 111 | 001 |
| mcp_header | 111 | 111 |
| mcp_params | 111 | 111 |
| py_query | 1FF | 000 |
| py_range | 000 | 000 |
| recover_date | 110 | 000 |
| recover_decode | 111 | 111 |
| tests_query | 0F1 | 000 |
| tests_range | F0F | 010 |

1 = passou na primeira tentativa; F = passou só após a escalada; 0 = falhou. A sequência representa as repetições 1 a 3.

Conclusões:
- A cascata com thinking foi confirmada nesta replicação (p = 0,008).
- O RTK manteve uma taxa menor que o controle, mas a diferença não foi significativa (p = 0,23). Não há evidência suficiente para adotar o filtro.
- py_range não passou em nenhuma repetição.

## 12. Campanha combinada (combined-v2)

Dados brutos: /home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-combined-v2 (72 episódios: 2 braços × 12 tarefas × 3 repetições, sem falha de infraestrutura). X-think é a referência da replicação stage5-rep3-v2 (36 episódios).

- Agregado: [combined-summary.txt](../results/3070-benchmark/combined-summary.txt).
- Análise: [B-campanha-combinada.md](../reports/analise-estrategia-4b-2026-10-28/execucao/F1/B-campanha-combinada.md).

| Braço | 1ª tentativa | Final | Escaladas (resgates) | Mediana por episódio (s) | Mediana dos sucessos na 1ª tentativa (s) | VRAM pico (MiB) | Tempo total |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| X-think (referência) | 22/36 = 61% | 30/36 = 83% | 10 (8) | 53,8 | 28,4 | 4546 | 77 min |
| R-q4 | 27/36 = 75% | 29/36 = 81% | 3 (2) | 40,3 | 35,5 | 5800 | 72 min |
| R-q6 | 23/36 = 64% | 28/36 = 78% | 7 (5) | 38,0 | 35,7 | 6618 | 59 min |

Os dois braços combinados usam MTP, checkpoints de contexto, KV q4_0, cache de prompt, contexto 64K, temperatura 0 e --cache-ram 2048. R-q4 usa Q4_K_M; R-q6 usa Q6_K_L. Ambos fazem escalada com thinking se a verificação visível falha.

Comparações pareadas (McNemar exato):

| Comparação | Só o primeiro passou | Só o segundo passou | p |
| --- | ---: | ---: | ---: |
| R-q4 contra X-think, 1ª tentativa | 3 (X-think) | 8 (R-q4) | 0,227 |
| R-q4 contra X-think, resultado final | 2 (X-think) | 1 (R-q4) | 1,000 |
| R-q6 contra X-think, 1ª tentativa | 5 (X-think) | 6 (R-q6) | 1,000 |
| R-q6 contra X-think, resultado final | 4 (X-think) | 2 (R-q6) | 0,688 |
| R-q6 contra R-q4, 1ª tentativa | 7 (R-q4) | 3 (R-q6) | 0,344 |
| R-q6 contra R-q4, resultado final | 3 (R-q4) | 2 (R-q6) | 1,000 |

| Tarefa | X-think (r1, r2, r3) | R-q4 (r1, r2, r3) | R-q6 (r1, r2, r3) |
| --- | --- | --- | --- |
| cont_path | 111 | 111 | F11 |
| cont_quote | FFF | 111 | 111 |
| js_plural | 111 | 111 | 010 |
| js_sign | 111 | 111 | 111 |
| mcp_header | 111 | 111 | 111 |
| mcp_params | 111 | 111 | 111 |
| py_query | 1FF | 111 | F1F |
| py_range | 000 | 000 | 000 |
| recover_date | 110 | 000 | 010 |
| recover_decode | 111 | 111 | 111 |
| tests_query | 0F1 | 1FF | 1F1 |
| tests_range | F0F | 101 | 01F |

1 = passou na primeira tentativa; F = passou só após a escalada; 0 = falhou. A sequência representa as repetições 1 a 3.

Leitura e conclusões:
- R-q4 terminou com 29/36 contra 30/36 em X-think; a diferença pareada não foi significativa (p = 1,000). A primeira tentativa subiu de 22/36 para 27/36, também sem significância (p = 0,227).
- R-q4 usou 3 escaladas, contra 10 na referência. O tempo mediano por episódio caiu de 53,8 s para 40,3 s, mas o tempo mediano dos sucessos na primeira tentativa foi maior (35,5 s contra 28,4 s).
- R-q6 terminou com 28/36, sem ganho sobre R-q4 (29/36), e consumiu 818 MiB a mais de VRAM (cerca de 0,8 GB).
- O limite de --cache-ram 2048 foi escolhido após o WSL encerrar o servidor por falta de memória: o RSS chegou a 6,9 GB, e o padrão de cache de 8 GiB coincide com os 8 GiB de RAM do WSL. Como X-think usou o cache padrão, esta comparação não isola o efeito do limite de 2 GiB.
- py_range falhou em todos os braços. O corpus também satura: 8 das 12 tarefas quase sempre passam.
