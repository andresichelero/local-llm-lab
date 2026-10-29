# Etapa 4: replicação dos finalistas e opções de servidor

Data: 29/10/2026. Protocolo `bwrap-v7` (40 passos), 168 episódios, de 04h59 a 09h24, nenhuma falha de infraestrutura. Resultados em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v7`. Contagem pela primeira tentativa (só uma falha real de infraestrutura daria direito a uma segunda), igual às etapas 1 a 3.

Controle: Q4_K_M bartowski, KV q4_0, contexto 64K, cache de prompt ligado, thinking desligado, temperatura 0, 40 passos. Cada braço muda um fator.

## Resultado por braço

| Braço | Mudança | n | Sucesso | Taxa | Mediana s (sucessos) | Decode tok/s | Pico VRAM MiB |
|---|---|---|---|---|---|---|---|
| C4-q4 | controle, 3 repetições | 36 | 25 | 69% | 37,5 | 74 | 4584 |
| C4-q6 | Q6_K unsloth, 3 repetições | 36 | 27 | 75% | 32,0 | 67 | 5127 |
| C4-think | thinking ligado, 2 repetições | 24 | 16 | 67% | 123,0 | 74 | 4529 |
| S-ctx48 | contexto 48K | 12 | 11 | 92% | 45,4 | 76 | 4307 |
| S-steps80 | limite de 80 passos | 12 | 10 | 83% | 39,0 | 78 | 4531 |
| S-checkpoints | `--ctx-checkpoints 64 --checkpoint-min-step 1024` | 12 | 9 | 75% | 24,5 | 76 | 4531 |
| S-mtp | MTP, `--spec-draft-n-max 2` | 12 | 8 | 67% | 24,8 | **115** | 5129 |
| S-q4-unsloth | Q4_K_M da unsloth | 12 | 7 | 58% | 36,0 | 77 | 4379 |
| S-qwen-sampling | amostragem recomendada pela Qwen | 12 | 6 | 50% | 36,7 | 72 | 4531 |

## Agregado com as etapas anteriores

| Configuração | Episódios | Taxa | IC95 (Wilson) |
|---|---|---|---|
| Q4_K_M (B0 v5 + C4-q4) | 60 | 68% (41) | 56–79% |
| Q6_K (B-q6 + C4-q6) | 48 | 77% (37) | 63–87% |
| Thinking (B-think + C4-think) | 36 | 75% (27) | 59–86% |

## Conclusões

1. **O thinking não se confirmou.** Na etapa 3 ele deu 11/12 (92%); na replicação, 16/24 (67%). Somando tudo fica em 75%, dentro do ruído do controle, e cada episódio leva cerca de 3,3 vezes mais tempo (123 s contra 37 s) porque o modelo gera em média 8.200 tokens em vez de 2.200. Não vale como padrão. Fica como candidato para a cascata (tentar com thinking só quando falhar), braço X-think da etapa 5.
2. **Q6_K é o melhor candidato de peso, mas a diferença não é significativa.** No pareamento por tarefa e repetição, o Q4 acertou 4 casos em que o Q6 errou, e o Q6 acertou 6 em que o Q4 errou (McNemar, p ≈ 0,75). O Q6 produz bem menos tokens por episódio (mediana de 780 contra 2.200), é 10% mais lento no decode e usa cerca de 550 MiB a mais de VRAM. Ainda cabe com folga numa placa de 8 GB.
3. **MTP é a melhor opção de servidor.** O decode sobe de 74 para 115 tok/s (+55%) com 91% de aceitação dos rascunhos, e a mediana dos episódios bem-sucedidos cai de 37,5 s para 24,8 s. A taxa (8/12) está dentro do ruído. Com temperatura 0, a decodificação especulativa em teoria não altera a saída (na prática, diferenças numéricas de lote podem mudar alguns tokens), então a diferença de acerto deve ser ruído, não efeito. Custo: cerca de 550 MiB a mais de VRAM.
4. **Checkpoints de contexto** dão velocidade parecida com o MTP (24,5 s) e mantêm a taxa (9/12). O ganho vem de reaproveitar o cache das camadas híbridas.
5. **ctx48 (11/12) e steps80 (10/12)** têm uma repetição só. Os resultados são compatíveis com o controle, e não há indício de que 64K ou 40 passos estejam limitando o resultado.
6. **Pioraram:** a amostragem recomendada pela Qwen (50%) e o Q4_K_M da unsloth (58%). Com 12 episódios os intervalos se sobrepõem aos do controle, mas não há motivo para adotar nenhum dos dois.
7. **Tarefas:** `py_range` falha em quase tudo (só Q6 acertou 2/3). `tests_query` e `tests_range` ficam perto de 50%. `recover_date` mostra a maior divergência entre braços: Q4 acertou 3/3 e Q6 errou 3/3. As outras oito tarefas estão saturadas, perto de 100%. O corpus discrimina pouco; ampliá-lo é prioridade (BACKLOG).

## Recomendação para o controle das próximas campanhas

Manter Q4_K_M + KV q4_0 + 64K + cache + thinking desligado como controle comparável. A configuração **recomendada para uso** passa a ser essa mesma **com MTP (n-max 2) e checkpoints de contexto**: ganhos de velocidade grandes e medidos, sem efeito esperado no acerto. Q6_K como alternativa de peso, quando a VRAM permitir. O próximo passo é medir MTP e checkpoints juntos e com Q6_K, numa campanha com pelo menos 3 repetições e corpus maior.

Limitações: 12 episódios por braço só detectam diferenças acima de cerca de 25 pontos percentuais. O ruído entre repetições é grande: 4 tarefas mudaram de resultado entre repetições do mesmo braço.
