# T2: resultados das tarefas longas (v2)

Data: 29/10/2026, das 10h21 às 10h47. Runner `benchmark/long_tasks.py`, commit `31a1d4b`, protocolo `qwen-4b-opencode-long-tasks-20261029-v2`. Resultados em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-long-tasks-20261029-v2/campaign`.

O desenho é de 4 braços × 2 maratonas × 1 repetição, totalizando **8 unidades**. Houve **zero falhas de infraestrutura**: o `grader_infrastructure` da v1 foi corrigido com `candidate_exception_only`.

Cada maratona encadeia objetivos no mesmo workspace:
- M1: `py_query`, `py_range`, `cont_quote` (duas fases) e `recover_decode`. São 4 oráculos privados.
- M2: `mcp_header`, `mcp_params`, `recover_date`, `cont_path` (duas fases) e `tests_range`. São 5 oráculos privados.

Os braços são:
- **L-bigctx:** contexto grande, sem compactação;
- **L-compact:** compactação nativa do OpenCode;
- **L-headroom:** compressão via Headroom;
- **L-reset:** sessão nova por objetivo, com `PROGRESS.md` salvo no workspace.

## Resultado

"Oráculos finais" conta os oráculos privados que passam ao fim da maratona.

| Braço | M1 (de 4) | M2 (de 5) | Total | Maratonas completas | Tempo M1 / M2 | Chamadas ao modelo | Tokens de prompt | Pico de VRAM |
|---|---|---|---|---|---|---:|---:|---:|
| **L-bigctx** | **4** | **5** | **9/9** | 2/2 | 503 s / 168 s | 187 | 7,87 M | 5.432 MiB |
| L-headroom | 2 | **5** | 7/9 | 1/2 | 125 s / 216 s | 161 | 2,41 M | 4.077 MiB |
| L-compact | 3 | 3 | 6/9 | 0/2 | 97 s / 108 s | 108 | 1,52 M | 4.103 MiB |
| L-reset | 3 | 2 | 5/9 | 0/2 | 133 s / 261 s | 164 | 2,01 M | 4.077 MiB |

Em nenhum braço houve regressão: nenhum oráculo que passou depois de um objetivo voltou a falhar mais tarde. Também não houve OOM.

O L-reset M2 registrou uma vez contexto excedido, duas falhas de ferramenta e terminou em `model_cli_failure`.

## Leitura

- **L-bigctx foi o único braço que completou as duas maratonas.** O custo foi alto: 3 a 5× mais tokens de prompt e 1,3 GB a mais de VRAM, ou seja, contexto maior com KV q4_0. Na M1 ele fez 120 chamadas em 503 s.

  Quase todo o prompt veio do cache: 5,69 M de 5,80 M tokens na M1. Por isso o tempo cresceu muito menos que o volume.
- **L-headroom** completou a M2 e caiu na M1, em `py_range` e `cont_quote:2`. A taxonomia registrou `step_cap` e uma quebra do teste visível no meio.
- **L-compact e L-reset** perdem objetivos do meio da maratona. A falha de `py_range` é comum aos três braços com contexto reduzido, mas `py_range` também é a tarefa mais difícil isoladamente (0/5 no controle da etapa 4).

  Portanto, parte do efeito é dificuldade da tarefa, não perda de memória.
- **Ordem observada:** bigctx > headroom > compact > reset. Com uma repetição por maratona, isso é um indício, não uma conclusão. A única diferença que parece robusta é bigctx contra os outros três.

## Ressalvas

- O campo `compaction_observation` diz "SQLite compaction parts requested; completion not established". O runner vê o pedido de compactação, mas não confirma que ela terminou.

  O contador `usage.compactions` ficou em 0 em todas as unidades, enquanto `compactions` (no nível da unidade) ficou entre 1 e 6. A instrumentação de compactação ainda não é confiável para afirmar quantas compactações aconteceram de fato.
- Os objetivos de fase 1 (`cont_quote:1`, `cont_path:1`) não têm oráculo privado próprio.

## Recomendação

1. Para tarefas longas no 3070, **contexto grande com KV q4_0 e cache de prompt** é a opção mais segura enquanto couber na VRAM. O pico de 5,4 GB deixa folga em 8 GB.
2. Headroom é o melhor compromisso quando o contexto precisa ser limitado.
3. **Próximo:** 3 repetições de L-bigctx contra L-headroom, e corrigir a confirmação de compactação antes de comparar compact contra reset.
