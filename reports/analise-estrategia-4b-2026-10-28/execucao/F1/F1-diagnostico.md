# F1: diagnóstico interrompido por um defeito do harness

Data: 28/10/2026. Autor: Claude (orquestrador). Status: **interrompida de propósito no episódio 18 de 24**, depois de identificada a causa dominante das falhas.

## Configuração

- Protocolo `qwen-4b-f1-diagnostic`. Runner `benchmark/qwen_f1_diagnostic.py`, commit `8e68478` no branch `feat/4b-worker-v2`.
- Modelo e servidor: Qwen3.5-4B Q4_K_M com KV q4_0, contexto de 16K, llama.cpp v0.8.0.
- Braços:
  - **D1:** thinking on, temperatura 0,6, cache off, `max_tokens` 8192.
  - **D2:** thinking off, temperatura 0, cache on, `max_tokens` 2048.
- Resultados brutos em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-f1-diagnostic/`.

## Resultados até a interrupção

Foram 17 episódios com resultado e **0 sucessos**. As causas registradas pelo runner:

| Tarefa | D1 | D2 |
|---|---|---|
| python_fix s101 | interrompido pelo operador | model_no_progress |
| python_fix s202 | budget_exhausted | model_no_progress |
| javascript_fix s101 | budget_exhausted | model_no_progress |
| javascript_fix s202 | model_no_progress | model_no_progress |
| authored_tests s101 | grader_or_completion_failed | model_protocol_error (JSON da tool call truncado em 2048 tokens) |
| authored_tests s202 | budget_exhausted | model_protocol_error (idem) |
| continuation s101 | model_no_progress | model_no_progress |
| continuation s202 | model_no_progress | model_no_progress |
| mcp s101 | grader_or_completion_failed | interrompido |

## Causa principal: o harness rejeita o próprio caminho que manda usar

O prompt de sistema e o schema da ferramenta `read` dizem: *"All paths are relative to /workspace"*. O modelo então chama `read {"path": "/workspace/TASK.md"}`.

`safe_path()` (`benchmark/qwen_workloads.py:37-40`) rejeita todo caminho absoluto com a mensagem *"path must stay inside /workspace"*. Essa mensagem induz ao erro, porque o caminho pedido **está** dentro de /workspace. O modelo repete a mesma chamada, e o detector de repetição encerra o episódio como `model_no_progress`.

Na janela final de mensagens de cada episódio, ou seja, depois da compactação:

| Episódio | Chamadas `/workspace/...` | Rejeitadas | Desfecho |
|---|---:|---:|---|
| todos os 9 `model_no_progress` com dados, exceto javascript_fix s202 D1 | 2–8 | 1–8 | model_no_progress |
| python_fix s202 D1, javascript_fix s101 D1 | 8 e 6 | 8 e 6 | budget_exhausted |
| mcp s101 D1 | 5 | 5 | grader_or_completion_failed |
| authored_tests (4) | 0 | 0 | outras causas |

O gatilho típico é a **retomada após compactação**: o checkpoint manda "reread TASK.md", e o modelo usa o prefixo `/workspace` sugerido pelo prompt. Isso transforma o mecanismo que o plano antigo descrevia como "plausível" (releitura + detector) num **defeito concreto e reproduzível do harness**. A conta não inclui as mensagens anteriores à compactação.

## Outros achados

- O `max_tokens` de 2048 no D2 é insuficiente para escrever um arquivo de teste inteiro numa única chamada de ferramenta. O llama-server devolve HTTP 500 com o JSON truncado.
- O runner trata `model_protocol_error` como fatal para a campanha inteira. Na F1 isso foi contornado retomando a campanha.

## Auditoria histórica (Luna, 28/10, 23h)

Ver [auditoria-workspace-historico.md](auditoria-workspace-historico.md). O mesmo `safe_path` estava na campanha `-final-oom-v2`. Lá houve 101 chamadas com `/workspace`, das quais 95 foram rejeitadas, quase todas depois de uma compactação.

Mesmo assim, **só 2 das 14 falhas do 4B** (python_fix e continuation) terminam com esse padrão. Outra tentativa teve 20 rejeições e terminou por orçamento esgotado. As demais falhas por repetição **não têm chamadas `/workspace`**.

Isso corrige a hipótese que o orquestrador tinha levantado: o defeito existia, mas **não explica a maior parte do 4/18 histórico**. Na F1 ele dominou, provavelmente porque a configuração mudou (Q4_K_M e a reformulação do checkpoint). A conclusão continua a mesma: o harness próprio tem vários modos de falha, e por isso a linha de base passa a usar OpenCode.

## Consequências

1. Os números da F1 **não medem a capacidade do 4B**: medem esse defeito. O mesmo defeito provavelmente afetou o 4/18 histórico; falta verificar nas evidências brutas da campanha final.
2. O harness próprio deixa de ser a base de medição. A nova estratégia está no PLANO-ESTRATEGICO-v2, seção "Revisão de 28/10, 22h".
