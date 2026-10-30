# Etapa 5: replicação de X-think e T5-rtk (3 repetições)

Data: 29/10/2026, das 19h04 às 21h39. Runner `benchmark/baseline_stage5.py --config benchmark/configs/qwen-4b-opencode-stage5-rep3.json`, branch `bench/stage5-replication`, commit `956f489`. Protocolo `qwen-4b-opencode-stage5-rep3-v2`, com resultados em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-stage5-rep3-v2`.

O desenho tem 2 braços × 12 tarefas × 3 repetições, ou **72 episódios**. Nenhum episódio terminou em infraestrutura. A primeira tentativa do X-think roda o controle (Q4_K_M, KV q4_0, 64K, cache, thinking desligado, temperatura 0) e serve de par para o T5-rtk na mesma tarefa e repetição.

## Interrupções

- **v1:** parou no episódio 34. Um timeout do modelo deixava um `ConnectionResetError` no proxy, e a regra de prioridade do PR #45 transformava isso em `server_http_error`. A regra foi corrigida em `956f489`: depois de um timeout, uma desconexão do cliente não conta como falha do servidor. A v1 foi descartada, e a v2 recomeçou do zero.
- **v2:** parou no episódio 56, quando a sessão do orquestrador reiniciou. O episódio incompleto (`T5-rtk/recover_date-r2`) foi arquivado em `stage5-rep3-v2-interrupted`. A campanha foi retomada com o mesmo manifesto, refez esse episódio do zero e pulou os 55 já concluídos.

## Resultado

| Braço | 1ª tentativa | IC95 | Final | IC95 |
|---|---|---|---|---|
| X-think (controle + escalada com thinking) | 22/36 = 61% | 45–75% | **30/36 = 83%** | 68–92% |
| T5-rtk | 17/36 = 47% | 32–63% | 17/36 = 47% | 32–63% |

Por repetição:
- X-think, 1ª tentativa → final: 8 → 10, 7 → 10 e 7 → 10.
- T5-rtk: 5, 7 e 5.

## Cascata com thinking: confirmada

- **10 escalonamentos, 8 resgates e nenhuma perda.** O teste de McNemar exato, comparando 1ª tentativa e final, dá p = 0,008.
- Os resgates aconteceram em:
  - `cont_quote`: 3/3;
  - `py_query`: 2/3;
  - `tests_query`: 1/3;
  - `tests_range`: 2/3.
- Somado à etapa 5 original (7 → 11/12), o total fica em **29/48 → 41/48 (60% → 85%)**, com 12 resgates em 14 escalonamentos.
- `py_range` segue em 0 em todas as repetições, com e sem thinking.

## RTK: tendência negativa, sem significância

| Comparação pareada (mesma tarefa e repetição) | Contagem |
|---|---:|
| Só o controle passou | 8 |
| Só o RTK passou | 3 |
| Os dois passaram ou os dois falharam | 25 |

- O teste de McNemar exato dá p = 0,23. A piora, de 61% para 47%, repete a direção da etapa 5 (6/12), mas não é significativa.
- O RTK perde de forma consistente em `recover_date`, `js_sign` e `cont_path`, e ganha em `cont_quote`.
- A hipótese segue sem verificação: a saída do pytest resumida esconderia o erro do modelo.

## Por tarefa

Legenda: `1` passou na 1ª tentativa; `F` passou só depois da escalada; `0` falhou. A ordem é r1, r2, r3.

| Tarefa | X-think | T5-rtk |
|---|---|---|
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

## Conclusão

1. **Adotar a cascata 4B → 4B com thinking** como configuração do worker. É o único efeito estatisticamente confirmado até aqui.
2. **Manter o RTK fora.** Retestar só com o pytest fora do filtro, se ainda houver interesse.

Agregado: `results/3070-benchmark/stage5-rep3-summary.txt`. Script: `scratchpad/rep3_summary.py`.
