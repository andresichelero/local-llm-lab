# Post-Audit Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. All subagents must use Luna Max.

**Goal:** Corrigir a confiança dos resultados e preparar uma campanha M1 independente, preservando integralmente as medições anteriores.

**Architecture:** Endurecer o harness existente com um contrato de conclusão dos graders, classificação central e retomada oficial. Manter perfis históricos separados do novo contrato M1. Endurecimento do transporte MCP constitui uma etapa própria; nenhuma reescrita geral ou nova dependência.

**Tech Stack:** Python 3.12, Node 22.23.3 já instalado, pytest/unittest/node:test, sandbox Linux/WSL e OpenCode congelado.

**Spec:** `docs/superpowers/specs/2026-10-23-post-audit-design.md`.

## Global Constraints

- Subagentes Luna Max; não reverter alterações alheias do worktree já sujo.
- Preservar logs, records, manifests, snapshots e resultados; avaliações append-only.
- Sem inferência, monitor automático, instalações, downloads ou mudanças de sistema nesta implementação de engenharia.
- Não alterar fontes/testes durante uma medição; novo contrato/grader/limite exige protocolo e saída novos.
- Catálogo de cinco modelos; Qwen 4B excluído.
- Capacidade mínima: 7.000 MiB VRAM e 8 GiB WSL livres, sem reduzir os pisos.
- Aprovações históricas e scores antigos não serão sobrescritos ou combinados com o novo M1.
- Não fazer commit/push ou reorganizar alterações preexistentes como parte automática do plano.

## Review Focus

1. Término zero sem checks ou stdout falsificado não deve aprovar (Task 1).
2. Sinal, artefato ausente e transporte não resolvido não devem virar erro funcional por fallback (Task 2).
3. Retry concorrente não pode perder histórico nem repetir um resultado concluído (Task 3).
4. Um perfil novo não pode endurecer silenciosamente M1 histórico (Task 5).
5. A remoção do fonte MCP não pode quebrar paginação, recuperação prescrita ou cleanup (Task 7).

## Ordem e ownership

Sequência crítica: 1 → 2 → 3; tarefas 4 e 5 depois do contrato de grader; 6 depende de 1/5; 7 é um subprojeto isolado de transporte; 8 reúne tudo; 9 só prepara execução.
Não colocar dois agentes editando `practical_runtime_v2.py`, `practical_tasks_v2.py` ou o sandbox ao mesmo tempo. Um executor por ownership, revisão independente somente leitura. Documentação pode avançar em paralelo. O principal coordena e valida.

### Task 1 — Impedir aprovação sem término real do grader (P0)

**Files:** criar `benchmark/practical_grade_contract.py`, `benchmark/practical_python_checks.py`, `benchmark/practical_node_reporter.mjs`; modificar `benchmark/practical_runtime_v2.py` e a proveniência em `benchmark/practical_campaign_v2.py`; testes `tests/test_practical_runtime_v2.py`, novo `tests/test_practical_grade_contract.py` e `tests/test_practical_integration_v2.py`.

**Interfaces:** novo `validate_grade_report(report: dict | None, *, expected_case_ids: set[str], returncode: int | None, cleanup_verified: bool) -> dict`; retorna `passed`, `infrastructure`, `reason`, `checks_completed`, `tests_run` e falhas. `_grader_result(...)` mantém seu formato público e acrescenta esses dados. IDs dos checks vêm do contrato confiável, não de stdout do candidato.

- [x] Criar regressões vermelhas a partir de `grader-resistance.json`: B1 `SystemExit(0)`, B2 `process.exit(0)`, `os._exit(0)`, import quebrado, zero checks, saída imitando JSON/TAP e execução parcial.
- [x] Fixar o contrato do reporter no Node instalado por teste real de eventos. Não presumir que o contador de arquivos corresponde a checks executados.
- [x] Implementar o launcher Python como coletor pai que nunca importa o candidato; executar import e unittest em worker filho, com canal de eventos separado de stdout/stderr. O coletor deve sobreviver a `os._exit(0)` no filho. No Node, manter reporter no pai e checks no worker isolado. Rejeitar relatório ausente, incompleto, repetido, sem correspondência de execução ou com checks faltantes. Não aceitar contagens de stdout.
- [x] Testar PID do coletor distinto do worker; worker imprime relatório falso e encerra abruptamente, mas o pai registra execução inválida. O supervisor externo também deve rejeitar ausência de relatório do coletor.
- [x] Diferenciar exceção capturada do candidato de falha do coletor. Sem causa provada, gerar contrato inválido/revisão em vez de culpar o modelo.
- [x] Acrescentar os novos fontes/hashes aos manifests e às avaliações derivadas.
- [x] Rodar foco e integração com as duas referências de todos os tipos de código. Gate: referências passam e mutantes não aprovam; falsificação de conclusão bloqueia liberação.

### Task 2 — Classificação causal e elegibilidade única (P0)

**Files:** `benchmark/practical_runtime_v2.py`, `benchmark/practical_campaign_v2.py`, `benchmark/practical_evidence.py`, `benchmark/model_broker.py`, `benchmark/practical_driver_v2.py`, `benchmark/practical_policy.py`; testes `test_practical_runtime_v2.py`, `test_practical_campaign_v2.py`, `test_practical_evidence.py`, `test_model_broker.py`, `test_practical_policy.py`, `test_practical_flows_v2.py`.

**Interfaces:** novo `is_scoring_eligible(row: Mapping) -> bool` em `practical_evidence.py`, usado por ranking, resumos e exportações; normalização do novo esquema preserva `functional_correct` separadamente de validade/pontuação. Dados antigos não são regravados.

- [x] Testar explicitamente `failure=infrastructure` com `correct=True/autonomous=True`: contribuição ao ranking e sucesso deve ser zero.
- [x] Testar saída `-15`, oito chamadas, sem snapshot: observação funcional desconhecida, execução inválida; nunca `wrong_result` por ausência de dados.
- [x] Testar APIError de conexão e stream interrompido versus cancelamento por deadline/limite registrado. Preservar causa desconhecida quando não houver evidência suficiente.
- [x] Reproduzir no cliente congelado a repetição automática de compactação após quota. Emitir erro local tipado não retentável para limite terminal de main/tempo/compactação; driver finaliza a fase e captura testes/snapshot, sem esperar novos retries nem matar o cgroup inteiro. Preservar `budget_exhausted:<categoria>` e não converter em configuração/infraestrutura.
- [x] Testar que depois do primeiro limite terminal não há outra geração encaminhada, que tentativas/uso são contados separadamente e que não se empresta saldo entre main/title/compactação/metadata. Não elevar tetos como correção desse bug de retry.
- [x] Versionar a nova semântica como `limits-skills-v2`, sem mudar os tetos atuais; preservar leitura de evidência v1 e a primeira causa terminal. Não reexecutar trajetórias históricas como se tivessem recebido a nova política.
- [x] Implementar ordem causal: infraestrutura/contrato inválido antes de inferir erro funcional; `wrong_result` exige grader concluído; orçamento/contexto planejadamente esgotado fica como resultado delimitado.
- [x] Preservar veredito funcional conhecido em campo próprio, limpar flags de pontuação inválidas e usar a mesma elegibilidade em todos os consumidores.
- [x] Testar referências antigas sem campos novos: não fabricar validade ou qualidade verificada. Exportar estado legado explicitamente.
- [x] Foco passa; comparar resumos sintéticos com o caso latente demonstrado na auditoria, sem modificar registros reais.

### Task 3 — Retry oficial e guard de capacidade (P0 operacional)

**Files:** `benchmark/practical_review_replay.py`, `benchmark/practical_runtime_v2.py`, `scripts/Start-LocalLLMRound.bat`, `scripts/local_llm_snapshot.py`, `scripts/Watch-LocalLLM.ps1`, `docs/LOCAL_LLM_MONITOR.md`; testes replay/launcher/runtime/monitor existentes.

**Interfaces:** adicionar `retry_blocked=False` como parâmetro explícito de `run` e `execute_prepared`, exposto por `--retry-blocked`; não acrescentar à seção imutável como flag permanente de autorização. Guard de capacidade usa espera máxima 120s, polling 2s e três amostras estáveis, antes da geração.

- [x] Testar bloqueado infra + concluídos: sem flag recusa; com flag tenta só o bloqueado, preserva tentativas e nunca repete concluídos/model errors ou ignora quarentena.
- [x] Testar lock negado e duas invocações concorrentes: nenhuma sobrescreve estado/records do dono do lock.
- [x] Implementar backup/auditoria da autorização sob lock e encerrá-la no `finally`. Arquivar erro antigo resolvido; status atual não pode mostrar erro ativo de tentativa anterior.
- [x] Testar relógio/telemetria simulados: capacidade oscila, estabiliza e expira. Sem estabilidade, zero chamadas e motivo de infraestrutura; nunca um loop de inferência.
- [x] Documentar espera como preparação, sem consumir budget do modelo; não fechar apps nem ajustar piso.
- [x] Atualizar snapshot, watcher, testes e docs juntos para mostrar preparação/espera/erro resolvido e denominador da agenda imutável. Não recriar automação.

### Task 4 — Oráculos B2, C1, M1 histórico e MCP (P1)

**Files:** `benchmark/practical_tasks_v2.py`, `benchmark/practical_mcp_grading_v2.py`, `benchmark/practical_mcp_v2.py`; testes `test_practical_tasks_v2.py`, `test_practical_mcp_v2.py`, `test_practical_tool_policy.py`.

**Interfaces:** contratos funcionais históricos permanecem identificáveis; novos casos do grader devem ter IDs estáveis para Task 1. A fonte dos testes é a pasta `results/reports/full-result-audit-20261023/supplemental-checks/` e as contraprovas registradas.

- [x] Regressões B2: IDs 99/100/101 e acima de 2³¹, ordem/duplicação/Unicode, tipos inválidos e linhas físicas após blanks. Testar erro com rótulo inglês/português e evitar aceitar número de id como número da linha.
- [x] Testar pretty-print válido com 2/4 espaços e tabs; rejeitar compactação disfarçada por uma quebra sem exigir igualdade textual arbitrária. Se houver ambiguidade não resolvida, manter esse subcritério como diagnóstico, não inventar falso negativo.
- [x] Regressões C1: `items` com escalares/objetos, página vazia intermediária, cursor opaco, falta de `next_cursor`, booleano/número/lista como cursor e imutabilidade das respostas.
- [x] Regressão M1 histórica mínima: `resolveConfig({tags: []}).tags == []`; preservar testes de falsey/undefined e não impor deep copy futuro neste perfil.
- [x] Remover o corte `[-1:]` da validação C2; anunciar fallback 2 no schema. Para o novo contrato, documentar uma submissão bem-sucedida após paginação, sem rejeitar tentativa anteriormente negada.
- [x] Usar `mcp-no-confirmed-replay-v1` para o novo C2 estrito; histórico sem regra explícita não recebe reprovação funcional nova por replay confirmado. D2 já exige uma chamada por conta no contrato histórico. Testar os dois perfis separadamente.
- [x] Testar D2 com replay idempotente duplicado: um efeito não substitui a exigência de uma chamada confirmada por conta. Preservar exatamente as recuperações M2 deliberadas.
- [x] Referências duas variantes passam; cada mutante da auditoria falha pelo motivo esperado. Nenhuma reescrita de veredito histórico.

### Task 5 — Versão M1 com cópia independente (P1)

**Files:** `benchmark/practical_tasks_v2.py`, `benchmark/practical_runtime_v2.py`, `benchmark/practical_review_replay.py`, `benchmark/practical_evidence.py`, `agent-manual/skills/code-and-tests/SKILL.md`, `docs/LIMITS_SKILLS.md`; testes tasks/runtime/evidence/replay.

**Interfaces:** adicionar keyword `task_contract_id='historical-v2'` a `seed_task`, `checks_source` e `reference_files`, preservando parâmetros atuais; execução e manifesto registram o contrato usado. `regrade_episode(run_dir, *, evaluation_profile=None)` resolve o contrato explícito conhecido do record; legado sem ID usa mapa verificado de hashes para o histórico. Override incompatível só gera avaliação rotulada como sensibilidade. Novo perfil: `m1-independent-copy-v1`. Acrescentar ID/hashes às avaliações append-only.

- [x] Testar que regrade padrão de snapshot antigo NÃO recebe checks de independência futura, e que record novo com ID explícito NÃO cai no perfil histórico. Contrato desconhecido exige revisão; override incompatível não produz score principal.
- [x] Publicar enunciado M1 explícito para cópia profunda de objetos plain/arrays, sem aliases com qualquer entrada. Primitivos/undefined/falsey preservados; ciclos e classes especiais fora do escopo.
- [x] Testar mutação de retorno → entradas e entradas → retorno; objetos dentro de arrays, arrays defaults não sobrescritos, propriedades novas, arrays vazios e defaults/overrides congelados.
- [x] Atualizar duas referências independentes e geradores de casos determinísticos. Não usar roundtrip JSON que perde `undefined` como cópia geral.
- [x] Verificar os 65 snapshots antigos só como sensibilidade separada; resultado esperado de baseline documental é 63 falhas, oito dos oito positivos atuais. Não esperar que modelos antigos tivessem recebido o novo contrato.

### Task 6 — Separar presença de testes e qualidade de regressão (P1)

**Files:** `benchmark/practical_runtime_v2.py`, `benchmark/practical_evidence.py`, novo `benchmark/practical_test_quality.py`; testes runtime/evidence e novo `tests/test_practical_test_quality.py`.

**Interfaces:** `assess_authored_regression(...)->dict` devolve `regression_detected/weak/unverified/not_applicable`, com resultados separados de candidato/seed e proveniência. `verified_success` é métrica nova, distinta dos resultados mecânicos antigos.

- [x] Testar suíte smoke que passa no candidato e no seed bugado, como Gemma M1 r3; não atribuir qualidade verificada.
- [x] Testar caso que falha por assert no bug original e passa no candidato; testar também import/setup ausente, infraestrutura e indisponibilidade do seed, que devem ficar não verificados.
- [x] Restaurar apenas fontes originais em cópia temporária; manter teste submetido e provar hashes de seed/snapshot. Nunca tocar no `input` original.
- [x] Integrar métricas separadas de função, fluxo, quantidade, qualidade e limites. Documentar critérios no manual antes de medir o novo M1.
- [x] O diagnóstico detecta regressão conhecida, não prova cobertura completa. Não transformar a quantidade de mutantes mortos em ranking universal.

### Task 7 — Isolar fixtures/estado MCP do agente (P1, subprojeto próprio)

**Files:** novo `benchmark/practical_mcp_bridge.py`; `benchmark/linux_sandbox.py`, `benchmark/sandbox_bootstrap.py`, `benchmark/practical_driver_v2.py`, `benchmark/practical_runtime_v2.py`, `benchmark/practical_mcp_grading_v2.py`; testes sandbox/MCP/flows e novo `tests/test_practical_mcp_bridge.py`.

**Interfaces:** serviço MCP host-side por episódio, canal dedicado por socketpair e proxy stdio sem catálogo no namespace. Não reutilizar contadores/canal do broker HTTP do modelo como contador MCP. Journal e estado final host-side são a fonte confiável do grading.

- [x] Testar leitura por Bash de `/opt/practical/practical_mcp_v2.py` e do estado privado: dados não devem existir no namespace do candidato.
- [x] Implementar servidor host-side e proxy restrito às operações MCP necessárias; encaminhar IDs/erros sem alterar semântica de paginação ou M2.
- [x] Reconciliar eventos públicos, journal confiável e artefato; rejeitar ausência, divergência, eventos incompletos e fonte de estado fornecida pelo candidato.
- [x] Testar timeout, processo filho encerrado, request parcial, cleanup, repetição e dois episódios sem compartilhamento de estado. Nenhum processo/FD órfão e nenhuma rede externa.
- [x] Integrações C2/M2/D2/H2 reais com respostas de modelo simuladas. M1 sem MCP não cria servidor nem canal extra.

### Task 8 — Reavaliação CPU, revisão e fechamento da engenharia

**Files:** testes e docs anteriores; `results/reports/post-audit-v9/` (novo), `benchmark/practical_evidence.py` e proveniência dos novos componentes.

- [x] Rodar os testes focados de cada tarefa durante sua implementação; regressão vermelha antes de consertar, verde depois.
- [x] Rodar Ruff no código alterado, compilação Python e testes relevantes. Não existe typechecker standalone configurado; não alegar que foi executado.
- [x] Rodar a suíte completa uma vez após integrar; depois executar integrações opt-in WSL isoladamente. Não repetir a experiência de rodar bateria pesada em paralelo ao fluxo OpenCode.
- [x] Com lock e sem servidor de modelo, reavaliar as 600 trajetórias nos perfis históricos apropriados; registrar resultados adicionais com hashes completos. Reusar v1 apenas com hashes idênticos, sem sobrescrever `regrade.json` antigo.
- [x] Confirmar os 46 contraexemplos, publicar diferenças adicionais se existirem e explicar qualquer divergência. Não fixar o resultado dos testes por contagem esperada se a evidência mudar legitimamente.
- [x] Qualificar Qwen 4B C1/SIGTERM e Bonsai 9B D2/transporte em coleção derivada. Não marcar como sucesso nem reincluir 4B.
- [x] Revisão independente Luna Max do diff e das evidências. Gate: zero mutação de fonte histórica e todos os testes obrigatórios verdes. (Executada por DeepSeek-v4.1, família independente — "Luna Max" não existe no catálogo; mensagem registrada no README da coleção de Task 8: G1–G4 PASS; suíte completa final 771 passed/19 skipped; 0 mutações; dívida de endurecimento registrada.)

### Task 9 — Preparação da nova campanha e estudo de limites separado

**Files:** `benchmark/practical_review_replay.py`, `benchmark/configs/limits-skills-experiments-v1.json`, `scripts/Start-LocalLLMRound.bat`, testes replay/round/monitor, `docs/LIMITS_SKILLS.md`.

**Interfaces:** seleção explícita de tarefas e contrato no manifesto; nova campanha proposta `practical-agent-limits-skills-v9-m1-independent`, saída nova com o mesmo nome. `--recover-from` histórico não deve transformar todos os resultados M1 antigos em pendências da nova tarefa.

- [ ] Agenda pontuada M1 somente: cinco modelos × seeds 101/202/303 = 15 episódios, baseline 16K/cache off. Selecionar explicitamente `limits-skills-v2`, com M1 main=45, title=1, compaction=3, metadata=10, wall=480s e reserva=25s; gravar versão e tetos no manifesto e em cada episódio. Tarefa nova não herda completions históricos; resume recusa mudança de contrato/política.
- [ ] Separar sondas de compatibilidade (até cinco, uma por modelo/perfil) e warmups já previstos dos 15 episódios pontuados. Fixar política/proveniência/custo dessas etapas; não duplicar sondas aprovadas em resume e nunca executá-las em `--prepare`.
- [ ] Provar que B2/C1 não entram na agenda só para substituir falsos positivos ou falhas reais: para suas correções de oráculo, a reavaliação CPU é suficiente.
- [ ] `--prepare` valida catálogo, hashes, runtime, capacidade, agenda e testes sem iniciar servidor/GPU. Default do BAT permanece preparo.
- [ ] Gerar readiness report com IDs dos gates e revisão. A implementação termina nesse ponto, sem inferência automática.
- [ ] Proposta opcional de calibração, somente mediante execução explícita posterior: quatro B2 (Qwen 9B/Bonsai 27B × compactação 2/4), demais budgets fixos; um protocolo/saída por braço, duas identidades em cada. Não usar o multiplicador global, que mudaria outras variáveis; suporte opcional não bloqueia M1. Nunca usar como pontuação principal nem aumentar teto até passar.
- [ ] Se a medição M1 for posteriormente autorizada, congelar tudo, executar somente os 15, verificar logs e classificar causas. Não mudar testes enquanto a campanha estiver ativa.

## Comandos de validação conhecidos (WSL, sem GPU)

Executar na raiz do worktree Linux, com o interpretador já instalado:

```text
/home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m pytest -q tests/test_practical_runtime_v2.py tests/test_practical_tasks_v2.py tests/test_practical_campaign_v2.py tests/test_practical_review_replay.py tests/test_practical_evidence.py
/home/foxtrot/.local/bin/ruff check benchmark
/home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m compileall -q benchmark
/home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m pytest -q tests --basetemp /tmp/llm-v9-full
RUN_PRACTICAL_INTEGRATION=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m pytest -q tests/test_practical_integration.py tests/test_practical_integration_v2.py tests/test_practical_flows_v2.py tests/test_practical_launcher_v2.py::test_launcher_dispatches_actual_non_inference_cli_modes --basetemp /tmp/llm-v9-integration
```

Os testes novos citados nas Tasks devem ser incluídos no foco depois de criados.
Usar `/tmp` curto para evitar limite AF_UNIX e a restrição de binds da pasta home.
Não executar suites durante inferência. Não instalar dependências para resolver
uma falha de ambiente sem autorização.

## Entrega esperada

Uma versão de engenharia com os gates verificados e um relatório CPU derivado,
seguida de uma agenda M1 nova preparada. Não haverá nova pontuação fabricada de
históricos, retomada irrestrita, campanha completa repetida ou monitor reativado.
