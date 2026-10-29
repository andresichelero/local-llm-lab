# Método

Este documento descreve como a linha de base OpenCode mede o agente, o que conta como acerto e como os resultados são analisados. Os números estão em [RESULTS.md](RESULTS.md).

## 1. Pergunta e desenho

A pergunta é quanto cada fator de runtime muda a taxa de acerto e o custo de um agente de programação local: contexto, tipo de KV cache, quantização dos pesos, cache de prompt e modo de raciocínio (thinking).

O desenho é uma matriz de um fator por vez a partir de um controle (B0). Cada braço muda um único fator em relação ao controle. A matriz tem 132 episódios nas etapas 1 a 3, e a etapa 4 foi configurada com mais 168. Cada etapa só começa depois que a anterior passa no gate. A etapa 1 exige pelo menos 3 acertos em 12 no controle, sem falhas de infraestrutura.

## 2. Corpus

O corpus tem 12 tarefas, 2 em cada uma das 6 classes:

| Classe | Tarefas | Arquivo alterável | Host |
|---|---|---|---|
| python_fix | `py_range`, `py_query` | `bottle.py` | Bottle 0.13.2 |
| javascript_fix | `js_sign`, `js_plural` | `index.js` | ms 2.1.3 |
| authored_tests | `tests_query`, `tests_range` | `test/test_*.py` | Bottle 0.13.2 |
| continuation | `cont_quote`, `cont_path` | `bottle.py`, em duas fases | Bottle 0.13.2 |
| mcp | `mcp_header`, `mcp_params` | `bottle.py`, com stub local | Bottle 0.13.2 |
| tool_recovery | `recover_date`, `recover_decode` | `bottle.py`, com stub local | Bottle 0.13.2 |

- **Hosts.** Bottle 0.13.2 e ms 2.1.3 são snapshots de projetos MIT, com commit e SHA-256 do `git archive` registrados em `corpus/README.md`. Cada tarefa parte do host com `bug.patch` aplicado. O `bottle.py` tem cerca de 51 mil tokens, estimados por caracteres, mais os cerca de 7 mil do prompt do OpenCode. Por isso o controle usa 64K.
- **Validação.** `corpus/validate_corpus.py` confere o manifesto de hashes, aplica os patches em cópias descartáveis e exige que o bug falhe por asserção, enquanto a referência, a verificação visível e os testes originais passem. Para as tarefas `authored_tests`, o oráculo também é validado contra o código correto e contra dois mutantes distintos. O correto passa, e os mutantes falham. Na última execução, as 12 tarefas retornaram `PASS`.
- **Stubs.** As tarefas `mcp` e `tool_recovery` leem a saída de um `tool.py` determinístico. Ele simula a evidência externa, mas não é um servidor MCP real.
- **Continuação.** A fase 1 entrega `TASK.md`, `verify_phase1.py` e `visible_phase1.py`. A fase 2 (`followup.json`, `verify.py` e `visible.py`) só é liberada depois que a fase 1 passa na verificação visível, e na mesma sessão do OpenCode.

Os oráculos, os patches de referência e o manifesto nunca são copiados para o workspace do agente. O runner copia só o host com o bug, `TASK.md`, a verificação visível e, quando previsto, o stub.

## 3. Oráculo privado e verificação visível

Cada tentativa tem duas avaliações.

- **Visível.** `verify.py` (ou `verify_phase1.py`) roda no workspace depois do episódio. Serve para o agente, e a falha conta como `model_visible_failed`.
- **Privado.** O oráculo de `corpus/oracles/<tarefa>/oracle.py` roda uma vez, ao final da tentativa, com pytest e o plugin `corpus_probe`. O plugin classifica cada teste que falha: por asserção (ou `pytest.fail`), ou por outro erro. O oráculo passa se nenhum teste falha. Falha do modelo se pelo menos um teste falha por asserção e nenhum falha por outro erro. Qualquer outra combinação, como erro de importação ou de execução, é infraestrutura (`grader_infrastructure`).

O conteúdo e o resultado do oráculo nunca entram no prompt nem no feedback dado ao agente. Um episódio é sucesso quando não há falha de modelo, o oráculo passa e a verificação visível passa.

## 4. Isolamento

Cada `opencode run` roda dentro do bubblewrap 0.9.0. Os argumentos são estes (`bwrap_command` em `benchmark/opencode_baseline.py`):

- `--die-with-parent` e `--unshare-pid`. Sem `--unshare-net`, então a rede não é bloqueada.
- `/usr` somente leitura, com `/bin`, `/lib` e `/lib64` como links para ele.
- `/proc` e `/dev`, com `/tmp` em tmpfs.
- O binário do OpenCode montado somente leitura em `/opt/opencode`, e o Node em `/opt/node`.
- O workspace do episódio em `/workspace` (leitura e escrita), e a home do episódio em `/episode-home` (leitura e escrita). A home persiste entre as duas invocações da continuação.

O repositório, `/mnt/d`, `/home`, os oráculos e os patches de referência não são montados. Antes de cada tentativa, `verify_isolation` roda uma prova negativa com as mesmas opções de montagem. Ela confirma que o workspace é legível e que o oráculo, `/mnt/d` e `/home` não são. O resultado vai para `isolation-probe.json`.

O perfil do OpenCode nega `webfetch`, `websearch`, subagentes (`task`) e acesso a diretórios externos (`external_directory`). Permite `bash` e `edit` no workspace.

**Limites conhecidos.** A rede não é bloqueada. O confinamento do `bash` não foi comprovado para todos os comandos possíveis. A verificação visível e o oráculo rodam pelo supervisor, fora do sandbox, e não são dados ao agente.

## 5. Servidor e amostragem

Cada braço sobe uma instância do `llama-server` com `--parallel 1`, `-ngl 99`, `--fit off`, `--flash-attn on`, `--jinja` e `--no-webui`. O contexto, o KV e o cache de prompt vêm do braço. Os episódios de um braço usam o mesmo servidor, sem reinício. Se o servidor morre, uma nova época começa e o cache anterior se perde.

- **Thinking desligado:** temperatura 0 (`--temp 0`), com `--reasoning off` e `enable_thinking=false`.
- **Thinking ligado:** temperatura 0,6, top_p 0,95, top_k 20.
- **Cache de prompt:** `--cache-prompt` no controle e `--no-cache-prompt` no braço `B-nocache`.

O runner usa um lock de supervisor e recusa começar se `pgrep -x llama-server` encontrar outra instância. Um proxy local entre o OpenCode e o servidor registra cada requisição, o TTFT (tempo até o primeiro conteúdo, reasoning ou chamada de ferramenta) e os timings devolvidos pelo servidor (`prompt_n`, `cache_n`).

## 6. Limites de cada tentativa

- O OpenCode roda com `--format json --pure`, `--agent build` e o modelo `local/local-qwen`.
- Passos: 40 no protocolo v5 e v6. O braço `S-steps80` (etapa 4) usa 80.
- Tempo de relógio: 600 s por tentativa. Desses, 90 s são reservados para a verificação final.
- Saída: 8 192 tokens por resposta.

## 7. Contagem da primeira tentativa

Cada unidade (braço, tarefa, repetição) gera uma tentativa, e a primeira conta. A única exceção é a falha de infraestrutura explícita. São elas: `server_exited`, `server_http_error`, `harness_configuration_error` e `grader_infrastructure`. Essas são repetidas uma vez. Se a segunda também for de infraestrutura, o estágio para.

Falha do modelo nunca é repetida. Essa regra foi corrigida na v6 (ver seção 9). A ferramenta de análise (`baseline_report.py`) seleciona a primeira tentativa, e só usa a segunda quando a primeira tem uma das falhas de infraestrutura acima. A análise usa o campo `failure`, não `category`.

## 8. Classificação das falhas

| Categoria | Rótulo (`failure`) | Rótulo curto nas tabelas |
|---|---|---|
| modelo | `model_oracle_failed` | oráculo |
| modelo | `model_visible_failed` | visível |
| modelo | `model_phase1_incomplete` | fase 1 |
| modelo | `model_wall_timeout` | tempo |
| modelo | `model_cli_failure` | CLI |
| modelo | `model_protocol_error` | protocolo |
| infraestrutura | `server_exited`, `server_http_error`, `grader_infrastructure`, `harness_configuration_error` | servidor, avaliador |
| harness | `harness_missing_session`, `harness_session_mismatch` | sessão |

O código atual também grava uma taxonomia de término com as tags `wall_timeout`, `context_overflow`, `tool_error_loop`, `step_cap`, `no_edit`, `gave_up`, `wrong_file`, `broke_visible` e `oracle_only`. **Nos resultados v5 e v6 essa taxonomia não está preenchida**: o campo `taxonomy` é nulo nas falhas, e os campos de diff e de métricas de requisição não existem, porque foram acrescentados ao runner depois. Por isso as causas das etapas 1 a 3 vêm dos rótulos `failure`, e as tags não aparecem em nenhuma afirmação.

## 9. Histórico de correções

| Revisão | Mudança | Motivo |
|---|---|---|
| bwrap-v2 | perfil de permissões corrigido | o OpenCode recusou a sintaxe das permissões web antes de inferir |
| bwrap-v3 → v4 | classificação corrigida; smokes repetidos | o runner atribuiu `model_protocol_error` a saídas normais de ferramenta |
| v4 → v5 | limite de passos de 20 para 40; `CORPUS_SUPPORT` passado ao oráculo | em v4, um episódio (`tests_query` r2) abortou por falta de `CORPUS_SUPPORT` no ambiente do oráculo, e ficou fora da conta. A troca do limite não mudou a taxa de forma detectável (15 de 23 contra 16 de 24) |
| v5 → v6 | falha do modelo nunca é repetida | em v5, a fase 1 que esgotou os 40 passos foi classificada como infraestrutura e repetida. A segunda tentativa passou, e isso inflava o acerto |

Em v5, o episódio `cont_path` r2 do controle é contado pela primeira tentativa (falha). Essa é a regra da seção 7.

## 10. Métricas

Por episódio, o runner grava:

- resultado do oráculo privado e da verificação visível;
- tempo total, TTFT por requisição, `prompt_n` e `cache_n` por requisição, e tokens de prompt e de geração somados dos turnos do OpenCode;
- VRAM do dispositivo amostrada a cerca de 1 Hz com `nvidia-smi`, com mínimo, máximo e média;
- número de turnos e de chamadas de ferramenta;
- causa de término pelo rótulo `failure`.

As definições de cada métrica agregada estão em [RESULTS.md](RESULTS.md). O TTFT do proxy mede transporte, não latência de geração. A VRAM mede o dispositivo inteiro.

## 11. Análise estatística

- **Taxa e intervalo.** Intervalo de Wilson de 95% para cada taxa. Com 12 episódios, o intervalo é largo.
- **Comparação pareada.** Cada braço é pareado com o controle pelo par (tarefa, repetição). Só os pares com as duas tentativas entram. O teste é o de McNemar exato, bilateral, sobre os pares discordantes.
- **Ruído.** No controle, quatro tarefas trocaram de resultado entre a repetição 1 e a 2. Diferenças de um ou dois episódios não são efeito.

## 12. Reprodutibilidade

`ensure_manifest` grava, na primeira execução, um `manifest.json` com o protocolo, a configuração completa, os hashes de cada arquivo do runner, do corpus, do harness e do próprio manifesto, o cronograma, os hashes do OpenCode, do servidor, do bubblewrap, do Node, do Python e de cada GGUF, e os hashes do cache de dependências do provider. Se o manifesto de um diretório de resultados não bater com o atual, o runner recusa continuar. Assim os resultados de protocolos diferentes não são misturados.

Os resultados brutos (workspaces, logs e JSON por tentativa) ficam fora do repositório. O que entra são os agregados em `results/3070-benchmark/` e os relatórios das etapas em `reports/`.
