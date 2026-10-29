# Etapa 5: pesos, ferramentas e cascatas

Data: 29/10/2026, 10h47 às 13h23. Runner `benchmark/baseline_stage5.py` no commit `31a1d4b`. Protocolo `qwen-4b-opencode-stage5-v2`. Resultados em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-stage5-v2`.

O desenho é de 8 braços × 12 tarefas × 1 repetição, totalizando **96 episódios**. Houve **zero falhas de infraestrutura**, depois das correções de classificação do `31a1d4b`.

Os braços mudam um fator por vez em relação ao controle da etapa 4, que é:
- Q4_K_M bartowski com KV q4_0;
- contexto de 64K e cache ligado;
- thinking desligado, temperatura 0 e 40 passos.

## Resultado na primeira tentativa

A contagem segue a mesma regra das etapas anteriores: vale a primeira tentativa, e a segunda só substitui a primeira quando esta falhou por infraestrutura.

O controle Q4_K_M somado (B0 da v5 mais C4-q4 da v7) ficou em **41/60 = 68%**, IC95 de 56% a 79%.

| Braço | Passou | IC95 (Wilson) | s/episódio (mediana) | Tokens de prompt | Falhas de ferramenta |
|---|---|---|---:|---:|---:|
| Q5-Q6KL (bartowski Q6_K_L) | 10/12 | 55–95% | 56,1 | 5,86 M | 4 |
| Q5-UDQ6XL (unsloth UD-Q6_K_XL) | 10/12 | 55–95% | 40,1 | 3,32 M | 6 |
| T5-lsp-tool (LSP + ferramenta `lsp`) | 10/12 | 55–95% | 37,8 | 5,24 M | 3 |
| Q5-UDQ4XL (unsloth UD-Q4_K_XL) | 9/12 | 47–91% | 34,2 | 3,90 M | 3 |
| T5-lsp (diagnósticos Pyright) | 9/12 | 47–91% | 67,0 | 6,13 M | 7 |
| X-9b, 1ª tentativa (= controle) | 8/12 | 39–86% | 37,3 | 4,38 M | 7 |
| X-think, 1ª tentativa (= controle) | 7/12 | 32–81% | 44,4 | 6,02 M | 6 |
| **T5-rtk (plugin RTK)** | **6/12** | 25–75% | 44,2 | 6,55 M | 7 |

A primeira tentativa dos braços X roda exatamente a configuração de controle. Somadas, dão **15/24 = 62%**, o que bate com os 68% do controle da etapa 4: o controle está estável entre campanhas.

Com 12 episódios por braço, **nenhuma diferença contra o controle é estatisticamente significativa**. Os intervalos se sobrepõem todos.

## Cascatas

As cascatas só escalam quando há falha visível ou falha identificada do modelo. Falha apenas do oráculo privado não escala, porque o agente não a enxerga.

| Cascata | 1ª tentativa | Escalonamentos | Final | Tempo total | Tempo extra da escalada |
|---|---|---:|---|---:|---:|
| X-think (2ª com reasoning ligado, sampling 0,6/0,95/20) | 7/12 | 4 | **11/12** | 1.518 s | 465 s |
| X-9b (2ª com Qwen3.5-9B Q4_K_M) | 8/12 | 3 | 9/12 | 2.083 s | 813 s |

Pontos principais:
- **X-think resgatou 4 de 4 escalonamentos.** Custou cerca de 116 s a mais por resgate e não exige troca de modelo.
- O 9B resgatou 1 de 3 escalonamentos, a um custo maior (271 s por escalonamento, com descarga e recarga do modelo).
- Nesta amostra, a cascata 4B → 4B com thinking é melhor e mais barata que 4B → 9B.

Uma ressalva: com 4 eventos, o resgate de X-think é uma evidência forte de direção, mas não uma estimativa precisa.

## Por tarefa

Legenda: `ok` = passou; `oráculo` = passou no teste visível e falhou no privado; `tempo` = estourou o tempo; `fase1` = fase 1 incompleta; `cli` = falha do CLI.

| Tarefa | Controle (5 execuções) | Q6KL | UDQ4XL | UDQ6XL | lsp | lsp-tool | rtk | 9b (1ª) | think (1ª) |
|---|---|---|---|---|---|---|---|---|---|
| cont_path | 4/5 | ok | ok | ok | ok | ok | oráculo | ok | ok |
| cont_quote | 4/5 | ok | ok | ok | fase1 | ok | ok | ok | ok |
| js_plural | 5/5 | ok | ok | ok | ok | ok | oráculo | ok | ok |
| js_sign | 3/5 | ok | ok | ok | ok | ok | ok | oráculo | oráculo |
| mcp_header | 5/5 | ok | ok | ok | ok | ok | ok | ok | ok |
| mcp_params | 5/5 | ok | ok | ok | ok | ok | ok | ok | ok |
| py_query | 3/5 | ok | ok | ok | cli | ok | ok | ok | oráculo |
| py_range | **0/5** | oráculo | oráculo | oráculo | **ok** | oráculo | oráculo | oráculo | oráculo |
| recover_date | 4/5 | ok | oráculo | ok | ok | oráculo | oráculo | ok | ok |
| recover_decode | 5/5 | ok | ok | ok | ok | ok | ok | ok | ok |
| tests_query | 1/5 | ok | oráculo | ok | ok | ok | oráculo | tempo | tempo |
| tests_range | 2/5 | tempo | ok | tempo | tempo | ok | tempo | oráculo | oráculo |

Leitura:
- **`py_range` continua sendo a tarefa mais difícil.** Só o braço LSP passou. O controle nunca passou nela (0/5), e com um único acerto não dá para separar efeito do LSP de sorte.
- **`tests_query` e `tests_range` ficam no limite de tempo.** Os braços Q6 e LSP estouram o tempo de parede em `tests_range`.

## Ferramentas: o que de fato foi usado

- **LSP.** O Pyright subiu em todos os episódios dos dois braços LSP. Os diagnósticos aparecem nos eventos do OpenCode.
- **Ferramenta `lsp`.** Em T5-lsp-tool, **o modelo nunca chamou a ferramenta**: `lsp_tool_calls = 0` em todos os 12 episódios. Logo, a diferença entre T5-lsp e T5-lsp-tool não pode ser atribuída à ferramenta. É variação entre execuções do mesmo efeito, os diagnósticos automáticos.
- **RTK.** O plugin reescreveu os comandos como esperado em 10 de 12 episódios. Os mais comuns foram:
  - `rtk pytest test/ -v 2>&1 | head -100` (70 vezes);
  - `rtk pytest <arquivo> -v` (60 vezes);
  - `rtk grep -n` (44 vezes).

  Também aparecem chamadas `rtk recall <id>`, em que o modelo precisa pedir de volta a saída que o RTK resumiu.

### Hipótese para a piora do RTK (não verificada)

O RTK teve o pior resultado (6/12) e o maior volume de prompt (6,55 M tokens, com 292 chamadas ao modelo). A explicação mais provável é esta: o RTK resume a saída do pytest, e o 4B perde detalhes do erro, como asserts e tracebacks. O modelo então gasta mais turnos e erra mais no oráculo privado; 4 dos 6 fracassos foram `oráculo`.

Isso contraria o objetivo do RTK, que é economizar contexto. Para confirmar, seria preciso comparar o conteúdo das saídas resumidas com as originais.

## Pesos

- **Q6_K_L e UD-Q6_K_XL (10/12 cada)** repetem a tendência da etapa 4: Q6 um pouco acima de Q4, sem significância. O UD-Q6_K_XL foi mais rápido e gastou menos prompt que o Q6_K_L.
- **UD-Q4_K_XL (9/12)** ficou empatado com o controle e foi o braço mais rápido.
- Nenhum dos três justifica, sozinho, trocar o controle.

## Recomendação

1. **Adotar a cascata X-think** (4B sem thinking, com escalada para 4B com thinking quando há falha visível) como configuração recomendada de worker. É a única intervenção desta etapa com efeito grande e direto (7 → 11/12), e mantém um único modelo na VRAM.
2. **Não adotar o RTK** neste modelo. Se for retestado, deixar o pytest fora do filtro.
3. **LSP** é neutro a levemente positivo e custa tempo (o T5-lsp teve a maior mediana). Não priorizar a ferramenta `lsp`, que o modelo não usa espontaneamente.
4. **Pesos:** manter Q4_K_M como controle. UD-Q6_K_XL é o candidato se houver VRAM.
5. **Próximo:** replicar X-think e T5-rtk com 3 repetições para confirmar as duas direções fortes, antes de documentar como conclusão.

## Arquivos

- `scratchpad/stage5_detail.py`: matriz por tarefa, IC de Wilson e custos.
- `scratchpad/stage5-detail.txt`: saída da análise.
- `units/<braço>/summary.json`: taxas de primeira tentativa e final, e tempos das cascatas.
- `units/<braço>/<tarefa>-r1/cascade.json` e `model-switches.json`: decisões e trocas de modelo.
