# F0 — corpus do piloto

Status: **12 tarefas implementadas e validadas offline**, sem inferência, GPU ou llama-server. Branch `feat/4b-worker-v2`. Commits: `ce7d44a` (Ruff preliminar), `c6c8ff6` (snapshots) e `a459b11` (corpus, validador e preservação dos bytes de um arquivo do snapshot).

## Hospedeiros e procedência

- **Bottle 0.13.2**, MIT, https://github.com/bottlepy/bottle, tag `0.13.2`, commit `ab49e0c22491f8acfcb02e4a7b8c648843268233`. É um framework real de um módulo, com testes próprios executáveis sem dependências nativas. SHA-256 do arquivo não comprimido produzido por `git archive --format=tar HEAD`: `6cb77dbe442edec538ebc9af0b4cb3d9c22fb3b8e262d4ecfb0e064a2e28ea44`. Seu `LICENSE` e testes estão no snapshot. Os testes originais no snapshot inicial produziram **355 passed**.
- **ms 2.1.3**, MIT, https://github.com/vercel/ms, tag `2.1.3`, commit `1c6264b795492e8fdecbc82cb8802fcfbfc08d26`. Não tem dependências de runtime e hospeda as duas tarefas JavaScript. SHA-256 do `git archive --format=tar HEAD`: `8320d0029c9cd17cb89f5f5d2509a14373d3e2efc6f4824907237f63475d882b`. Os testes originais executados pelo adaptador `node:test`, sem alterar o arquivo upstream de testes, produziram **49 passed**. O adaptador substitui as três formas de asserção usadas por esses testes; não é uma execução do Mocha original.
- Estimativa de código de produção: `bottle.py` tem **180.178 caracteres Unicode** e `index.js` tem **3.024**, total **183.202 / 3,5 = 52.343 tokens estimados**. Método: leitura UTF-8, contagem de caracteres, sem testes/documentação; não é tokenização do modelo. Bottle sozinho: aproximadamente 51.479 tokens. O prefixo Bottle com linhas de referência ocultadas tem 179.962 caracteres, aproximadamente 51.418 tokens.
- Os metadados Git dos clones e os arquivos tar gerados ficaram preservados localmente em `corpus/provenance/`, ignorados pelo Git; os snapshots versionados não contêm `.git`. O manifesto registra SHA-256 de cada arquivo dos snapshots, tarefas, oráculos, stubs, suporte e prefixos. Os 325 arquivos de corpus no índice foram comparados byte a byte com o worktree por hash de objeto Git, sem divergências.

## Tarefas

A dificuldade abaixo é estimativa, não medida com modelo. Os dois oráculos de testes autorados executam os testes de referência no Bottle correto e em dois mutantes distintos. As tarefas MCP/recuperação usam stubs locais determinísticos e editam Bottle; não simulam o protocolo MCP completo.

| ID | Classe | Arquivo alterável | Dificuldade | O que discrimina |
|---|---|---|---|---|
| py_range | python_fix | bottle.py | média | fim inclusivo, limites e faixas inválidas |
| py_query | python_fix | bottle.py | média | espaços, escapes e repetição em query strings |
| js_sign | javascript_fix | index.js | média | durações negativas, frações e unidades |
| js_plural | javascript_fix | index.js | média | limiar de plural e números negativos |
| tests_query | authored_tests | test/test_tests_query.py | média | detecta mutantes de decodificação e ordem |
| tests_range | authored_tests | test/test_tests_range.py | média | detecta mutantes de limite e sufixo |
| cont_quote | continuation | bottle.py | média | escape de caracteres HTML e controles após follow-up |
| cont_path | continuation | bottle.py | média | deslocamentos nos dois sentidos e barra final |
| mcp_header | mcp | bottle.py | média | saída do stub e normalização de nome de cabeçalho |
| mcp_params | mcp | bottle.py | média | saída do stub e normalização de parâmetros |
| recover_date | tool_recovery | bottle.py | média | diagnóstico do stub e conversão de fuso |
| recover_decode | tool_recovery | bottle.py | média | diagnóstico do stub e política de erro Unicode |

## Validação real

O validador foi executado duas vezes, sequencialmente, com `python -u corpus/validate_corpus.py --node /home/foxtrot/.nvm/versions/node/v25.5.0/bin/node`, com `PYTHONDONTWRITEBYTECODE=1` e o Python `/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python`. As duas saídas foram comparadas com `cmp` e eram idênticas. Cada tupla representa respectivamente bug/oráculo, referência/oráculo, teste visível e testes originais: o bug precisa falhar por asserção (1) e os demais precisam passar (0). O validador também verifica o manifesto, escopo de escrita, prefixos, duas execuções de cada stub, amostra do stub no bug e na solução, e os dois mutantes por tarefa autorada.

```text
cont_path: PASS bug/oracle/visible/original=(1, 0, 0, 0)
cont_quote: PASS bug/oracle/visible/original=(1, 0, 0, 0)
js_plural: PASS bug/oracle/visible/original=(1, 0, 0, 0)
js_sign: PASS bug/oracle/visible/original=(1, 0, 0, 0)
mcp_header: PASS bug/oracle/visible/original=(1, 0, 0, 0)
mcp_params: PASS bug/oracle/visible/original=(1, 0, 0, 0)
py_query: PASS bug/oracle/visible/original=(1, 0, 0, 0)
py_range: PASS bug/oracle/visible/original=(1, 0, 0, 0)
recover_date: PASS bug/oracle/visible/original=(1, 0, 0, 0)
recover_decode: PASS bug/oracle/visible/original=(1, 0, 0, 0)
tests_query: PASS bug/oracle/visible/original=(1, 0, 0, 0)
tests_range: PASS bug/oracle/visible/original=(1, 0, 0, 0)
RESULT: PASS (12 tasks)
```

`DETERMINISM: identical output in both runs`

- Pytest focado: `tests/test_corpus_validate.py`, `tests/test_guarded_edit.py`, `tests/test_qwen_engines.py`, `tests/test_qwen_workloads.py` e `tests/test_prefix_cache_paired.py`: **64 passed in 13.35s**. Na etapa preliminar separada, os quatro testes existentes indicados produziram **43 passed in 9.74s**.
- Ruff 0.17.3: `All checks passed!` nos módulos corrigidos na etapa preliminar e, separadamente, em `corpus/validate_corpus.py`, `corpus/oracles`, `corpus/tasks`, `corpus/stubs`, `corpus/support/*.py` e `tests/test_corpus_validate.py`. O código upstream vendorizado não foi reformatado.
- Não há typecheck configurado para este projeto, conforme o plano F3; nenhum resultado de typecheck é alegado.

## Riscos e pendências para as fases seguintes

- As alterações de referência são pequenas e algumas tarefas podem ser fáceis ou saturadas; as dificuldades não foram calibradas com inferência. Algumas tarefas compartilham funções ou conceitos. O corpus é piloto e não é uma confirmação inédita.
- O prefixo Bottle oculta as linhas originais alteradas, mas código vizinho e testes upstream ainda podem revelar comportamento. O snapshot íntegro, patches de bug/referência, gerador e oráculos não podem ser entregues ao trabalhador. A separação de arquivos por si só não impõe esse isolamento: o runner F3 precisa aplicá-lo e testá-lo.
- As fases de continuação têm materiais separados, mas o estado inicial já satisfaz o teste da primeira fase; o runner deve liberar o follow-up apenas após a primeira entrega. Não se avaliou uma sequência real com modelo.
- Os stubs comprovam execução determinística e coerência dos exemplos, mas não medem descoberta, histórico de chamadas, retries ou idempotência de um servidor MCP real.
- O prefixo do pequeno hospedeiro JavaScript, isoladamente, não tem 40 mil tokens; a comparação WL para essas duas tarefas requer uma decisão explícita de contexto. A seleção de uma tarefa por classe para F1 e a execução das fases com GPU permanecem fora desta entrega e exigem o planejamento/autorização correspondentes.