# Linha de base OpenCode: etapa 1, controle B0

Data: 29/10/2026. Autor: Claude (orquestrador).

- Runner: `benchmark/opencode_baseline.py`, branch `feat/4b-worker-v2`.
- Controle: Qwen3.5-4B Q4_K_M, KV q4_0/q4_0, contexto de 64K, cache de prompt ligado, thinking desligado, temperatura 0.
- Ambiente: OpenCode 1.19.5 isolado em bubblewrap, llama.cpp v0.8.0, 12 tarefas do corpus com 2 repetições cada.

## Duas rodadas, com uma variável de harness diferente

| Protocolo | Limite de passos do OpenCode | Episódios | Sucessos | Taxa |
|---|---:|---:|---:|---:|
| bwrap-v4 | 20 | 23 (o 24º não rodou por erro do avaliador) | 15 | 65% |
| bwrap-v5 | 40 | 24 | **16** (o runner registrou 17; ver correção abaixo) | **67%** |

**Correções aplicadas aos dados:**

1. **v4, `tests_query` r2:** o avaliador abortou por falta de `CORPUS_SUPPORT` no ambiente do oráculo. Esse episódio não entra na conta. Corrigido em `f3a895d`.
2. **v5, `cont_path` r2:** a fase 1 esgotou os 40 passos e o runner classificou isso como "infraestrutura". Com essa classificação o episódio ganhou uma 2ª tentativa, que passou. **Conta-se a 1ª tentativa, que é falha do modelo.** O bug de classificação foi corrigido em `417e96d`, que é o protocolo v6, usado a partir da etapa 2.

## Por tarefa (v5, após a correção)

| Tarefa | r1 | r2 | Observação |
|---|---|---|---|
| js_plural, mcp_header, mcp_params, recover_decode, cont_quote | ✅ | ✅ | estáveis |
| py_query | ✅ | ✅ | r2 levou 36 passos e 106 s |
| js_sign | ✅ | ❌ | r2 esgotou 40 passos |
| recover_date | ❌ | ✅ | r1 esgotou 40 passos |
| cont_path | ✅ | ❌ | r2 parou na fase 1, no limite de passos |
| tests_range | ❌ (falha do CLI) | ✅ | |
| py_range | ❌ | ❌ | 0/4 somando v4 e v5: a tarefa mais difícil do corpus |
| tests_query | ❌ | ❌ (tempo esgotado, 505 s) | 0/3 avaliáveis somando v4 e v5 |

## Custo operacional (v5)

- Mediana dos episódios com sucesso: **33 s**. TTFT mediano de 200–450 ms por requisição.
- **93,5%** dos tokens de prompt vieram do cache.
- Pico de VRAM do dispositivo nos smokes: ~5,3 GiB.

## Leitura

- **O 4B resolve a maioria das tarefas do corpus** com um harness maduro e configuração de runtime sensata. Isso contrasta com 0/17 no harness próprio na F1, mas nos dois casos as tarefas e os harnesses são diferentes.
- **O limite de 20 ou 40 passos não mudou a taxa de forma detectável** (65% contra 67%, dentro do ruído). A variação entre repetições é alta: 4 tarefas trocaram de resultado entre r1 e r2. Para afirmar diferenças nas etapas 2 e 3, é preciso olhar a magnitude e não tratar 1 ou 2 episódios como efeito.
- O v5 (40 passos) é o controle das etapas seguintes.
