# T2 — robustez em tarefas longas

Status: implementação, verificações offline e dois smokes GPU executados. A campanha não foi executada. As limitações dos oráculos de fase 1 e da integridade adversarial do grader continuam abertas.

## Desenho e limites do corpus

Cada maratona usa uma cópia do Bottle com todos os patches de bug pertinentes aplicados antes da primeira entrega. M1 contém `py_query`, `py_range`, `cont_quote:1`, `cont_quote:2` e `recover_decode`. M2 contém `mcp_header`, `mcp_params`, `recover_date`, `cont_path:1`, `cont_path:2` e `tests_range`: são **seis** objetivos na enumeração solicitada, apesar da referência a cinco no texto do pedido. Os objetivos são liberados em ordem após o término da chamada anterior, sem exigir que ela passe. O máximo é 40 passos por objetivo e 1800 s por maratona, incluindo preparação e avaliação; o supervisor reserva tempo para avaliações e classifica o encerramento por essa reserva separadamente como `supervisor_wall_budget`. No código embutido do OpenCode 1.19.5, o contador `agent.steps` é reiniciado por prompt mesmo ao retomar uma sessão; ele conta iterações do agente, inclusive processamento de compactações, e não necessariamente corresponde ao número de eventos `step_finish`.

O corpus não contém oráculo privado para as primeiras fases de `cont_quote` e `cont_path`. Seus testes visíveis já passam com os bugs aplicados. O resultado privado dessas fases é, portanto, `null`, com `no_private_phase1_oracle`; os testes visíveis são registrados separadamente. Não é correto dizer que todos os objetivos têm oráculo privado nem que todos falham inicialmente. Há oráculos privados para os contratos finais das duas tarefas.

Verificação offline das combinações: todos os quatro oráculos privados de M1 e os cinco de M2 falharam com os bugs combinados e passaram com todas as referências combinadas. Os patches aplicaram sem conflito. `tests_range` tem `bug.patch` vazio; seu oráculo falha inicialmente pela ausência do teste exigido.

## Braços e isolamento

Todos usam Q4_K_M do controle, KV K/V q4_0, cache de prompt ligado, thinking desligado, temperatura 0 e limite de saída do controle. `L-compact` usa uma sessão e contexto 32768; `L-bigctx`, uma sessão e 131072; `L-reset`, contexto 32768 e uma nova sessão por objetivo, com `PROGRESS.md` contendo objetivos anteriores, `git diff --stat` e os resultados visíveis, sem resultado privado. `L-headroom` usa uma sessão, 32768, plugin 0.42.0 montado read-only e proxy local Headroom encadeado ao proxy de métricas. O plugin não carrega com `--pure`, portanto apenas esse braço remove essa opção. O proxy usa `--stateless --no-cache --disable-kompress --no-telemetry --no-subscription-tracking`: desabilitar Kompress evita depender de downloads; outros mecanismos de otimização permanecem habilitados. O cache de prompt do llama-server permanece ligado.

OpenCode 1.19.5 aceita `compaction: {"auto": true}`; o binário informa que o padrão também é verdadeiro. As solicitações de compactação são contadas nas partes `type=compaction` do SQLite da sessão; isso não confirma que o resumo terminou. O fluxo `run --format json` não expõe essas partes. O teste offline com provider falso observou uma parte de compactação, e outro teste com provider falso confirmou o carregamento do plugin e `headroom_retrieve` dentro do bwrap, além de duas requisições encaminhadas e compactação de schemas. Os arquivos temporários dessas provas foram removidos; essa evidência não estabelece compressão de histórico em inferência real.

Uma prova inicial do plugin tentou consultar `models.opencode.ai` e falhou na resolução. O runner define `OPENCODE_DISABLE_MODELS_FETCH=true` para impedir essa consulta. A sandbox do OpenCode compartilha a rede do host, como no baseline; não é uma barreira para chamadas de rede feitas por bash. Os avaliadores visíveis e privados usam outro bwrap, com workspace somente leitura e rede isolada. Seus resultados privados não são entregues ao modelo. Limitação de integridade: o código avaliado e o oráculo compartilham o processo e o namespace do avaliador; código adversarial pode ler o oráculo ou adulterar o relatório do grader. A implementação não fornece isolamento adversarial entre teste e código avaliado.

O runner guarda avaliações depois de cada objetivo já liberado e ao final, regressões após uma aprovação observada, duração, tokens quando disponíveis, compactações solicitadas, resets, evolução de `prompt_n + cache_n` por requisição com tempo observado de conclusão, erros de contexto, amostras de recursos e métricas aplicáveis do baseline. Um valor ausente permanece `null`. O campo principal `compactions` vem do SQLite; o campo aninhado `usage.compactions` é herdado da sumarização dos eventos JSON e não detecta essas solicitações. A amostragem de VRAM é do dispositivo inteiro. Cada maratona inicia um processo de servidor próprio; o manifesto registra essa diferença em relação ao baseline. O lock é compartilhado pelos modos T2 e há checagem de processos baseline/llama antes do início; outros supervisores que não compartilhem esse lock ainda podem introduzir uma corrida de inicialização.

## Execução

O modo `--dry-run` lista as oito unidades, intercalando braços e maratonas. O smoke usa os dois primeiros objetivos de M1 em `L-compact` e `L-reset`. A campanha completa fica para o orquestrador:

```sh
cd /mnt/d/Usuario/Downloads/LLM/.worktrees/4b-worker-v2
/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.long_tasks --dry-run
/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.long_tasks --smoke
# Somente pelo orquestrador, depois de avaliar as limitações acima:
/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.long_tasks --run
```

## Smokes e verificações

A etapa 3 estava ativa na primeira checagem; o loop autorizado de 60 s aguardou até o processo sair. Os dois smokes foram executados depois, sem executar a campanha:

```text
{"unit": {"arm": "L-compact", "marathon": "M1", "repetition": 1}, "failure": "model_oracle_failed", "error": null, "passed_final": 1}
{"unit": {"arm": "L-reset", "marathon": "M1", "repetition": 1}, "failure": "model_oracle_failed", "error": null, "passed_final": 1}
```

| Medida | L-compact | L-reset |
| --- | ---: | ---: |
| Oráculos finais `py_query`, `py_range` | passou, falhou | passou, falhou |
| Verificações visíveis de cada entrega | passaram, passaram | passaram, passaram |
| Tempo das entregas | 24,80 s; 15,37 s | 23,52 s; 21,85 s |
| Tempo total da tentativa | 48,57 s | 54,61 s |
| Tokens de prompt OpenCode / gerados | 217.337 / 1.892 | 249.916 / 1.570 |
| Requisições com timings / total | 18 / 18 | 19 / 19 |
| Solicitações de compactação no SQLite | 1 | 2 |
| Resets | 0 | 1 |
| Pico de VRAM do dispositivo | 4.079 MiB | 4.076 MiB |
| Ocorrências detectadas de contexto excedido / evidência de OOM | 0 / não | 0 / não |

Em ambos, o oráculo de `py_query` passou após a primeira entrega e permaneceu passando depois da segunda; `py_range` falhou na avaliação final apesar de passar no teste visível. Não houve regressão observada. `L-compact` manteve o mesmo ID nas duas chamadas; `L-reset` usou IDs diferentes e o `PROGRESS.md` inspecionado continha o objetivo anterior, o status visível e o diff. As duas provas de isolamento do OpenCode passaram. Os resultados por objetivo não são prova de eficácia estatística.

Artefatos brutos no WSL: `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-long-tasks-20261029-v1/smoke/L-compact-M1-r1/attempt-01/` e `.../smoke/L-reset-M1-r1/attempt-01/`, incluindo `result.json`, `events.jsonl`, avaliações por etapa, `workspace.diff` e prova de isolamento. Os servidores dos smokes foram encerrados.

Verificações finais: `pytest -q tests/test_long_tasks.py tests/test_opencode_baseline.py tests/test_baseline_report.py tests/test_qwen_f1_diagnostic.py tests/test_opencode_controlled_probe.py` com o Python solicitado: **63 passed**. Ruff nos arquivos T2 e nos arquivos do baseline/report cobertos: **All checks passed**. `compileall` terminou com código 0; não foi encontrada configuração de typecheck no projeto, e compilação não equivale a typecheck. O teste existente da agenda do baseline foi atualizado de 276/144 para 300/168 unidades após um commit externo adicionar duas repetições de `C4-think`; os dois arquivos protegidos não foram editados por T2.

A suíte completa `pytest -q` não está verde: **16 failed, 1083 passed, 19 skipped, 187 subtests passed**. A repetição de apenas as falhas confirmou: seis falhas em que o Git do WSL não resolve o caminho Windows no arquivo `.git` deste worktree; oito falhas por manifestos/catálogos de outras campanhas ausentes; e duas por espaço insuficiente para os pisos de testes de download e hot-cache. Na verificação havia aproximadamente 6,7 GiB livres no filesystem Linux. Esses problemas não foram corrigidos com alterações globais, arquivos fabricados ou limpeza de dados. Os 63 testes focados acima passaram independentemente da suíte completa.
