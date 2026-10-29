# F1 B — runner da linha de base OpenCode

## Etapa 2: isolamento e smokes reais (29/10/2026)

Concluída a qualificação dos dois smokes abaixo; a campanha de 132 episódios não foi iniciada. Protocolo final `qwen-4b-opencode-baseline-b-20261029-bwrap-v4`, resultado bruto em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v4/`. A tabela da etapa 1 abaixo é um registro histórico e suas limitações sobre ausência de sandbox e de smoke não descrevem a etapa 2.

### Isolamento

Cada chamada `opencode run` é lançada por bubblewrap 0.9.0 com `/usr` read-only, symlinks `/bin`, `/lib`, `/lib64`, `/proc`, `/dev`, `/tmp` em tmpfs, namespace PID e `--die-with-parent`. O binário real fica montado read-only em `/opt/opencode`, o Node em `/opt/node`, o workspace em `/workspace` (rw) e a home persistente do episódio em `/episode-home` (rw), fora do workspace avaliado. `HOME` e `XDG_*` apontam para essa home e o comando usa `--dir /workspace`. A mesma home persiste entre as duas invocações da continuação. O repositório, `/mnt/d`, `/home/foxtrot`, oráculos e patches de referência não são montados.

A rede é compartilhada: **o bubblewrap não bloqueia acesso à rede externa nem a outros serviços acessíveis na rede do host**. O perfil nega webfetch/websearch, mas não impede que um comando bash use a rede. O manifesto registra essa limitação e o hash do executável bubblewrap. A avaliação visível e o oráculo ainda são executados pelo supervisor fora do sandbox; não são dados ao OpenCode como feedback.

A prova negativa roda automaticamente usando a mesma função e as mesmas opções de montagem da invocação OpenCode. Ela testa leitura de `/workspace/TASK.md`, tenta `cat` no caminho absoluto real do oráculo, `ls /mnt/d` e `ls /home`, sem exibir o conteúdo privado. Nos dois episódios finais a saída foi:

```text
workspace_readable oracle_denied mnt_d_denied home_denied
returncode=0; --unshare-pid presente; --unshare-net ausente
```

A prova completa, com comando e resultado, está em `isolation-probe.json` de cada tentativa. O teste automatizado executa a mesma verificação, e o `debug config` do OpenCode 1.19.5 foi validado dentro do bubblewrap sem inferência.

### Smokes GPU: resultados finais

Os valores de tokens de prompt são a soma de uso registrada pelos turnos OpenCode, incluindo tokens de cache; não representam tokens únicos. Os intervalos `prompt_n` e `cache_n` vêm dos timings de todas as requisições capturados pelo proxy, inclusive requisições auxiliares. TTFT é mediana das requisições com primeiro conteúdo detectado. Pico de VRAM é amostragem do dispositivo inteiro, não memória exclusiva do processo.

| Medida | B0 `py_query` | B0 `cont_path` |
|---|---:|---:|
| Causa / categoria | `model_oracle_failed` / modelo | `null` / sucesso |
| Teste visível | falhou | passou nas duas fases |
| Oráculo privado | falhou | passou |
| Tempo total | 47,40 s | 106,05 s |
| Turnos do modelo | 20 | 27 |
| Chamadas de ferramenta | 20 | 26 |
| Tokens de prompt (soma, com cache) | 582.381 | 724.104 |
| Tokens gerados | 1.403 | 4.205 |
| Requisições com timings | 21 | 28 |
| `prompt_n` mínimo–máximo | 21–12.558 | 21–21.997 |
| `cache_n` mínimo–máximo | 0–34.720 | 0–31.259 |
| TTFT mediana | 314,8 ms | 251,8 ms |
| Pico VRAM do dispositivo | 5.329 MiB | 5.325 MiB |
| Evidência de OOM no log | não | não |

Na continuação a fase 1 terminou em 57,91 s e a fase 2 em 41,22 s; ambas retornaram código 0 e sessão `ses_e7a21b829ffeMCGvh2KtLxpQOx`. O teste visível da primeira fase passou antes de liberar os arquivos e o objetivo seguintes. `result.json`, `events.jsonl`, `server-segment.log`, `workspace.diff`, `oracle-probe.json` e `isolation-probe.json` estão nos diretórios `smoke/B0/py_query-r1/attempt-01/` e `smoke/B0/cont_path-r1/attempt-01/` do protocolo acima.

Trechos dos eventos OpenCode, sem conteúdo do oráculo, mostram o trabalho no caminho montado:

```text
py_query:  {"command": "cat /workspace/visible.py"}
py_query:  {"command": "sed -n '3051,3100p' /workspace/bottle.py"}
cont_path: {"filePath": "/workspace/bottle.py"}
cont_path: {"filePath": "/workspace/verify_phase1.py"}
cont_path: {"command": "grep -n \"^def \" /workspace/bottle.py | head -30"}
```

Comandos executados no WSL, a partir da raiz do worktree:

```sh
PY=/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python
"$PY" -m benchmark.opencode_baseline --smoke
"$PY" -m benchmark.opencode_baseline --smoke --task cont_path
"$PY" -m pytest -q tests/test_opencode_baseline.py tests/test_qwen_f1_diagnostic.py tests/test_opencode_controlled_probe.py
# 26 passed in 17.59s
/home/foxtrot/.vscode-server/extensions/charliermarsh.ruff-2026.54.0-linux-x64/bundled/libs/bin/ruff check benchmark/opencode_baseline.py tests/test_opencode_baseline.py
# All checks passed!
```

As duas primeiras tentativas de desenvolvimento foram preservadas, sem reclassificação retroativa. Em `bwrap-v2`, OpenCode recusou a sintaxe das permissões web antes de inferir; o perfil foi corrigido e testado com o CLI real. Em `bwrap-v3`, ambos os episódios passaram no oráculo e a continuação manteve a sessão, mas o runner atribuiu indevidamente `model_protocol_error` ao examinar saída normal de ferramentas. Testes reproduziram e corrigiram a classificação; os smokes foram repetidos no `bwrap-v4`. Os resultados variaram entre repetições e não demonstram eficácia estatística.

## Registro histórico da etapa 1 (28/10)

Status histórico da etapa 1 em 28/10/2026: implementação e verificações offline. Nenhum smoke com GPU e nenhuma etapa da campanha foram executados nesta etapa. O runner ainda precisa ser qualificado com o OpenCode e o llama-server reais antes da campanha.

## Arquitetura e contrato

`benchmark/opencode_baseline.py` prepara uma cópia do host de cada tarefa, aplica `bug.patch` e fornece `TASK.md`, teste visível e, quando previsto, `tool.py`. Para continuação, só libera objetivo e teste da fase 2 quando a primeira execução termina, fornece um ID de sessão e passa o teste visível da fase 1; a segunda chamada usa `--session` com o mesmo ID. O oráculo é executado uma vez por tentativa, ao final, sem inserir seu conteúdo ou resultado no prompt. A avaliação usa o contrato de classificação de `corpus/validate_corpus.py`. O snapshot inicial e a alteração final produzem `workspace.diff`.

O runner usa perfil OpenCode e ambiente HOME/XDG isolados, `opencode run --format json --pure`, provider local e cache de dependências do caminho anterior. Um llama-server permanece ativo por braço, sem reinício entre episódios; uma nova invocação ou recuperação de servidor morto cria uma nova época e perde o cache anterior. Um proxy local registra respostas e TTFT por requisição; logs do servidor e timings do proxy preservam `prompt_n` e `cache_n` quando disponíveis. Eventos registram turnos, chamadas de ferramentas e tokens. `nvidia-smi` é amostrado a cada segundo; o pico é do dispositivo inteiro. OOM é marcado apenas quando o log contém evidência correspondente. Cada tentativa tem resultado próprio; infraestrutura é repetida uma vez, e falhas do modelo não interrompem as próximas tarefas. O manifesto fixa protocolo, cronograma, config, hashes do corpus e código, servidor, OpenCode, modelos, Python, Node e cache de provider; divergências impedem misturar resultados.

## Configuração

- Protocolo: `qwen-4b-opencode-baseline-b-20261028-v1`; resultados em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-b-v1`.
- Controle B0: Q4_K_M, KV K/V q4_0, 65536, cache on, thinking off, temperatura 0. Stage 1: 24 episódios, duas repetições das 12 tarefas.
- Stage 2: B-ctx16/32/128 e B-kv8/16, 12 episódios por braço, 60 no total. Stage 3: B-q6, B-q8, B-nocache e B-think, 12 por braço, 48 no total. Total: 132.
- Thinking on: temperatura 0,6, top_p 0,95, top_k 20. Servidor: `--parallel 1`, `-ngl 99`, `--fit off`, flash attention on, `--reasoning` e `enable_thinking` conforme o braço. `--cache-prompt` ou `--no-cache-prompt` conforme o braço.
- Wall 600 s por tentativa, com reserva de até 90 s para a verificação final, e 20 passos OpenCode, mesmo valor do `MAX_PRIMARY_STEPS` de `prefix_cache_paired.py`; 600 s limita o custo por episódio, sem demonstrar que seja suficiente para as 12 tarefas. Saída máxima configurada: 8192 tokens.
- OpenCode `.bin/opencode`: versão 1.19.5, SHA-256 `7df4e4136301f16589b0f30bf91a61380fca5f8ef22dd36570f5ebe1d4ec802c`.
- llama-server: `0.8.0-dev`, build 1, commit `8642541`; SHA-256 `da1068f30d898c10c02c754ebef3b5b877073213989ff5ef9dfb2d4332e265f0`.
- Q4_K_M bartowski: `13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983`; Q6_K unsloth: `fdedd781c9ce676ab66b018ca247ff78e8a33c98098a822c1e2d5075e7718f66`; Q8_0 unsloth: `10cc391b403021dd11c614679d2fd92f611c3681d29e29651b717316965d61e1`. Os três hashes foram calculados nesta etapa.

## Comandos

No WSL, a partir de `/mnt/d/Usuario/Downloads/LLM/.worktrees/4b-worker-v2`:

```sh
PY=/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python
"$PY" -m benchmark.opencode_baseline --dry-run
"$PY" -m benchmark.opencode_baseline --dry-run --arm B0
# Qualificação posterior, ainda não executada:
"$PY" -m benchmark.opencode_baseline --smoke
"$PY" -m benchmark.opencode_baseline --smoke --task cont_path
# Campanha posterior, exclusivamente por decisão do orquestrador:
"$PY" -m benchmark.opencode_baseline --stage 1
"$PY" -m benchmark.opencode_baseline --stage 2
"$PY" -m benchmark.opencode_baseline --stage 3
# Alternativa para um braço:
"$PY" -m benchmark.opencode_baseline --arm B-kv8
```

A etapa 2 depende do gate do plano: pelo menos 3/12 no controle e nenhuma falha de infraestrutura. O runner não automatiza essa decisão; cabe ao orquestrador conferir os resultados antes de iniciar a etapa seguinte.

## Verificações offline executadas

```text
$ python -m pytest -q tests/test_opencode_baseline.py tests/test_qwen_f1_diagnostic.py tests/test_opencode_controlled_probe.py
23 passed in 15.04s
$ ruff check benchmark/opencode_baseline.py tests/test_opencode_baseline.py
All checks passed!
$ python -m benchmark.opencode_baseline --dry-run | tail -n 4
130 stage=3 arm=B-think task=recover_decode rep=1
131 stage=3 arm=B-think task=tests_query rep=1
132 stage=3 arm=B-think task=tests_range rep=1
Total: 132
$ python -m benchmark.opencode_baseline --dry-run --arm B0 | tail -n 2
024 stage=1 arm=B0 task=tests_range rep=2
Total: 24
```

`compileall` dos dois arquivos Python terminou com código 0. A comparação do corpus retornou `320 320 True`; a construção offline do manifesto retornou 132 unidades, 326 hashes de arquivos do repositório e 3657 entradas do cache. Os testes usam CLI e servidor falsos; a continuação simulada preservou a sessão nas duas fases e executou o oráculo real ao fim, com falha esperada por não haver edição. Não há timings reais de inferência ou valores reais de cache_n nesta etapa.

## Limitações e diferenças em relação a outubro

- O perfil limita permissões declaradas do OpenCode, mas bash e rede não têm confinamento de sistema comprovado. O agente pode, em princípio, alcançar arquivos do host, inclusive material privado fora do workspace. Os diretórios do episódio e os ambientes são isolados, mas isso não é uma barreira de segurança; não há credenciais intencionalmente fornecidas ao agente. A decisão do orquestrador aceitou essa limitação para a linha de base.
- Os testes visíveis e o oráculo executam código do workspace sem sandbox de SO comprovado. As saídas privadas ficam fora do workspace e não são enviadas ao modelo, mas a falta de confinamento de bash impede garantir que ele não possa encontrá-las por conta própria.
- O prazo de 600 s limita subprocessos e reserva tempo para verificação, mas cópias e leitura de arquivos não são preemptivas e podem ultrapassar o prazo em I/O lento.
- O TTFT do proxy é o tempo até o primeiro conteúdo, reasoning ou tool call detectado; é uma medição de transporte e pode ficar indisponível. `prompt_n`/`cache_n` dependem do formato efetivamente retornado pelo servidor; listas vazias ou ausência nos timings significam não medido, não zero. O uso por dispositivo não identifica o processo causador do pico.
- O perfil, o provider cache, o CLI atualizado, o proxy, a liberação faseada, o corpus e o oráculo são diferentes dos experimentos de outubro. O processamento real de sampling, streaming, continuação, cache e erro 500 ainda precisa do smoke real; uma passagem offline não prova esses comportamentos em inferência.
- Mudanças do runner ou dos artefatos após a criação do manifesto exigem novo diretório/protocolo; retomadas em outra invocação reiniciam o servidor e não preservam o estado de cache anterior. Erro de classificação entre parser do modelo e erro HTTP de infraestrutura depende das evidências textuais presentes nos logs e eventos.




