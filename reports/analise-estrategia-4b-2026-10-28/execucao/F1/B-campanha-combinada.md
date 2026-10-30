# Campanha combinada: MTP, checkpoints e escalada com thinking, Q4 e Q6

Data: 30/10/2026, das 01h37 às 03h38. Rodou com o runner `benchmark/baseline_stage5.py --config benchmark/configs/qwen-4b-opencode-combined.json`, no branch `bench/combined-config`, commit `1b908ac`. O protocolo é `qwen-4b-opencode-combined-v2`, e os resultados estão em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-combined-v2`.

Desenho: 2 braços × 12 tarefas × 3 repetições, num total de **72 episódios**, sem falhas de infraestrutura. Os dois braços usam:
- KV q4_0, 64K de contexto, cache de prompt e temperatura 0;
- MTP com `--spec-draft-n-max 2`;
- checkpoints de contexto (`--ctx-checkpoints 64 --checkpoint-min-step 1024`);
- `--cache-ram 2048`;
- escalada com thinking quando a verificação visível falha.

| Braço | Modelo |
|---|---|
| R-q4 | Q4_K_M (bartowski) |
| R-q6 | Q6_K_L (bartowski) |

A comparação é com o braço X-think da replicação `stage5-rep3-v2`. Ele usa a mesma escalada, sem MTP nem checkpoints, com o cache em RAM no padrão de 8 GiB.

## Interrupção da v1

A v1 parou no 8º episódio, com o Linux do WSL matando o `llama-server` por falta de memória (RSS de 6,9 GB). O cache de prompts em RAM do llama.cpp tem 8 GiB por padrão, o mesmo tamanho da RAM total do WSL. Com MTP e checkpoints, cada entrada do cache chegou a 1,2 GiB. A v2 limita esse cache a 2 GiB. Isso é uma diferença em relação ao braço de comparação.

## Resultado

| Braço | 1ª tentativa | Final | Escaladas (resgates) | Tempo mediano por episódio | Tempo total | Pico de VRAM |
|---|---|---|---|---:|---:|---:|
| X-think (replicação) | 22/36 = 61% | **30/36 = 83%** | 10 (8) | 53,8 s | 77 min | 4.546 MiB |
| R-q4 | **27/36 = 75%** | 29/36 = 81% | 3 (2) | 40,3 s | 72 min | 5.800 MiB |
| R-q6 | 23/36 = 64% | 28/36 = 78% | 7 (5) | 38,0 s | 59 min | 6.618 MiB |

Comparações pareadas por tarefa e repetição (McNemar exato):

| Comparação | Só a 1ª passou | Só a 2ª passou | p |
|---|---:|---:|---:|
| R-q4 contra X-think, 1ª tentativa | 3 | 8 | 0,23 |
| R-q4 contra X-think, final | 2 | 1 | 1,00 |
| R-q6 contra X-think, final | 4 | 2 | 0,69 |
| R-q4 contra R-q6, 1ª tentativa | 7 | 3 | 0,34 |
| R-q4 contra R-q6, final | 3 | 2 | 1,00 |

## Leitura

- **O acerto final se mantém.** R-q4 fica em 81% e X-think em 83%. A diferença é de 1 episódio, sem significância. MTP e checkpoints não prejudicam a qualidade.
- **A 1ª tentativa melhorou com R-q4 (61% para 75%), mas sem significância.** Por isso, a escalada foi menos usada (3 contra 10), e a mediana por episódio caiu de 54 s para 40 s. Ainda não está claro se a causa é o MTP, os checkpoints, o cache menor ou variação. Seria preciso uma campanha com um fator por vez para separar.
- **Os sucessos na 1ª tentativa não ficaram mais rápidos.** A mediana foi de 35,5 s no R-q4 contra 28,4 s no X-think. O ganho de decode do MTP, de cerca de +55% na etapa 4, não aparece no tempo do episódio. A hipótese é que o tempo seja dominado pelo prefill, pelas ferramentas e pelo número de turnos.
- **O Q6 não compensa.** Ele usou 0,8 GB a mais de VRAM e não teve ganho de acerto (78% contra 81%). Foi mais rápido no total (59 min), mas com mais escaladas. Fica com o Q4.
- **O custo de VRAM do MTP e dos checkpoints** é de cerca de 1,25 GB a mais no pico: 5,8 GB contra 4,5 GB. Ainda cabe com folga numa placa de 8 GB.
- `py_range` continua em 0 em todos os braços. `recover_date` caiu no R-q4 (0/3 contra 2/3 no X-think).

## Recomendação

A configuração de uso é **Q4_K_M + KV q4_0 + 64K + cache + `--cache-ram 2048` + MTP n-max 2 + checkpoints + temperatura 0**, com thinking desligado na 1ª tentativa e ligado na escalada. Ela tem o mesmo acerto final da escalada sem MTP, usa a escalada com menos frequência e cabe em 5,8 GB.

Arquivos:
- agregado em `results/3070-benchmark/combined-summary.txt`;
- script em `scratchpad/combined_compare.py`.
