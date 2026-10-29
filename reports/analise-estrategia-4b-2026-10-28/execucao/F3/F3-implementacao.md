# F3 — contrato, aplicador e runner do trabalhador

Data: 2026-10-28. Trabalho offline no worktree `D:/Usuario/Downloads/LLM/.worktrees/4b-worker-f3`, branch `feat/4b-worker-f3`, base `a459b11`. Commit `f2970caab86e541210541ffb896c9977828b17f8`. Sem push, merge, GPU, llama-server real ou inferência. Os arquivos reservados à F1 não foram alterados.

## Arquitetura e arquivos

- `corpus/validate_corpus.py`: resolução de Node na ordem `CORPUS_NODE`, PATH e versões numéricas de `~/.nvm/versions/node/*/bin/node`, escolhendo a mais recente. Override inválido e ausência produzem mensagem clara. `--node` continua disponível.
- `benchmark/guarded_edit.py`: mantém `apply_guarded_edit` e seu fallback antigo; adiciona `apply_edit_batch` com allowlist obrigatória, SHA-256 esperado, correspondência exata, validação antes de qualquer escrita, arquivos temporários e rollback. Recibo por arquivo inclui caminho relativo, hashes, diff unificado e cada bloco de busca/substituição. Rejeições são tipadas; o resultado retém a saída original. Python usa AST; JavaScript usa `node --check` offline. Falha ao localizar/executar o verificador é classificada como infraestrutura pelo runner.
- Testes upstream existentes e oráculos são protegidos. A exceção para as tarefas `authored_tests` é um arquivo de teste explicitamente permitido, ausente no início da tentativa: pode ser criado e reparado nessa tentativa. Isso é necessário para `tests_query` e `tests_range` do corpus.
- `benchmark/worker_contract.py`: dataclasses e schemas JSON fechados para metadados e resultado; corpo Markdown separado. O construtor lê `task.json` e teste visível, aceita somente trechos exatos de arquivos relevantes do workspace e, nas tarefas que têm stub, acrescenta a saída JSON do stub local. Não lê oráculos ou patches de referência para construir o pacote. Prefixo WL deve ser o arquivo congelado do respectivo host; `prefix_id` é seu SHA-256.
- `benchmark/worker_runner.py`: cliente HTTP mínimo injetável, runner e journal JSONL. Cada runner tem UUID; cada registro contém ID, estado e, quando pertinente, número da geração, saída original ou recibos. Tokenização chama `/apply-template` e `/tokenize` com `add_special=true` e `parse_special=true`, alinhados ao código local do llama.cpp v0.8.0; geração usa cache, temperatura zero, seed fixa e thinking desligado. Essas interfaces foram verificadas no código/documentação local e com cliente falso, não contra servidor executando.

## Gramática de resposta

A resposta de patch é a concatenação de um ou mais blocos, sem prosa ou cercas Markdown. Os marcadores devem ocupar linhas completas terminadas em LF:

```text
FILE: caminho/relativo
<<<<<<< SEARCH
<texto exato a localizar, inclusive suas quebras de linha>
=======
<texto substituto, inclusive suas quebras de linha>
>>>>>>> REPLACE
```

A busca deve ocorrer exatamente uma vez no estado resultante dos blocos anteriores. Uma busca vazia só cria arquivo ausente que esteja na allowlist; buscas vazias em arquivos existentes são rejeitadas. Marcadores reservados dentro do conteúdo, cercas, texto fora dos blocos ou marcador embutido numa linha são rejeitados, sem conserto silencioso. O bloqueio é uma linha `BLOCKED: <motivo>`, com `insufficient_context`, `conflicting_requirements` ou `cannot_safely_edit`.

## Estados, verificação e orçamentos

`prepared → generating → candidate → verifying → accepted | rejected | blocked | infrastructure_error`. Uma verificação visível falha pode retornar ao estado `generating` uma vez, apenas com diagnóstico não vazio e ainda não presente no pacote. O callback privado é chamado somente depois de uma verificação visível aprovada na fase final; o retorno booleano é registrado como nota e não entra no prompt. Na primeira fase de continuação ele não é chamado; o follow-up só é criado pelo runner que aceitou essa primeira entrega. `accepted` com `oracle_passed=false` é possível e representa aceitação visível incorreta, métrica necessária à F4.

A finalização é idempotente. W16 envia pacote; WL envia primeiro a mensagem de sistema com prefixo idêntico por hash, depois o pacote. Ambos usam `cache_prompt=true`. O orçamento padrão reserva 14.336 tokens de entrada e 2.048 de saída para uma janela de 16.384; WL exige orçamento de entrada ajustado à janela escolhida na F2. O limite de relógio é no máximo 300 s por pacote e há no máximo um reparo. Em WSL/POSIX o timer usa `SIGALRM` na thread principal e recusa um timer já ocupado.

## Verificação executada

A suíte integra os cinco arquivos anteriores da F0 (64 testes naquele ponto) e os testes novos do contrato/runner, Node e lote. Abrange estados, bloqueio, saída malformada, limite de entrada, timeout, finalização dupla, reparo com/sem diagnóstico novo, não propagação de diagnóstico privado, contagem de tokens, estabilidade de prefixo entre tarefas, gating de continuação, exclusão de oráculos e referências nos pacotes das 12 tarefas, tool stub, rejeições de edição, verificação de sintaxe JS, recibos e rollback após falha e interrupção logo após rename.

Comando real, no WSL:

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -p no:cacheprovider -q tests/test_corpus_validate.py tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py tests/test_worker_contract.py tests/test_worker_runner.py
........................................................................ [ 75%]
........................                                                 [100%]
96 passed in 19.50s
```

```text
/home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/worker_contract.py benchmark/worker_runner.py corpus/validate_corpus.py tests/test_guarded_edit.py tests/test_worker_contract.py tests/test_worker_runner.py tests/test_corpus_validate.py
All checks passed!
```

O validador completo também foi executado sem `--node`, com `PYTHONDONTWRITEBYTECODE=1`; todas as 12 tarefas retornaram `PASS bug/oracle/visible/original=(1, 0, 0, 0)` e a saída terminou em `RESULT: PASS (12 tasks)`. Na primeira tentativa desta verificação, o manifesto detectou três `.pyc` gerados pelas execuções de testes; esses três arquivos de cache foram removidos individualmente e a verificação foi repetida com bytecode desligado. Não há typecheck configurado neste projeto.

Revisão independente estática por Sol 6.1 High: não restaram achados acionáveis após correções de prefixo, tokens e rollback; o revisor não executou testes nem servidor. A regressão do rollback em caso de interrupção após o rename foi reproduzida falhando e depois passou.

## Limitações e pendências para F4

- O worktree e as verificações de caminho não são sandbox do sistema operacional. O executor deve isolar o workspace e manter o código candidato sem acesso a oráculos, referências, credenciais ou recursos externos. A allowlist não protege contra troca hostil concorrente de caminhos.
- O lote valida antes de gravar e tenta desfazer falhas, inclusive interrupções; vários `rename`s não constituem transação de filesystem contra queda de energia/processo ou falha também no rollback. Se o rollback falhar, backups temporários são preservados e a falha é propagada. Usar workspace descartável e exclusivo.
- O runner recebe callbacks de verificação visível e privada: sua implementação/orquestração confiável e a preparação dos workspaces do corpus para episódios F4 ainda precisam ser conectadas e testadas ponta a ponta. Os testes não provam isolamento contra callbacks que violem esse contrato. Pacotes W16 precisam de trechos úteis escolhidos pelo coordenador; o builder não os seleciona automaticamente. Os stubs são executados localmente como parte da construção, não são uma sessão MCP real.
- O timer depende de POSIX/thread principal e não constitui limite de recursos do SO nem garante encerramento de subprocessos arbitrários iniciados por callbacks. A contagem usa o contrato local do llama.cpp, sem confirmação por servidor real nesta fase.
- Antes da F4: cumprir F1/F2 e gate de revisão do projeto; congelar os pacotes e contabilizar a preparação do coordenador; selecionar janela/orçamento WL, aquecer e medir cache/TTFT e VRAM; implementar coleta de métricas e adaptadores para verificadores e orquestração serial; validar W16/WL/AG/C com o mesmo estado/oráculo; obter autorização explícita para qualquer inferência/GPU. Nenhum resultado de qualidade, desempenho ou cache real é alegado aqui.

## Correções pós-revisão

A revisão adversarial `F3-revisao-sol.md` reprovou o commit `f2970ca`; a afirmação anterior de ausência de achados refere-se somente à revisão anterior e não substitui esse veredito. As correções abaixo estão no commit `b296ad6` do mesmo branch. Esta seção registra a implementação e as verificações, sem alegar que Sol já reavaliou ou aprovou o novo commit.

1. **Finalização e journal:** antes de persistir o terminal, o runner bloqueia `SIGALRM`, desarma o timer e verifica prazo e sinal pendente com espera não bloqueante. Uma finalização já registrada é recuperada do JSONL e retorna resultado coerente, sem outro terminal. O registro `prepared` também está protegido pelo tratamento de timeout. A checagem de prazo ocorre antes de iniciar a persistência terminal: se uma gravação já iniciada antes do prazo for lenta, ela é concluída sem interrupção do timer e o resultado concorda com o registro.
2. **Timeout no oráculo:** o handler guarda a marca de expiração mesmo quando o callback captura `TimeoutError`; após `private_oracle()` o runner verifica a marca e o relógio antes de interpretar o retorno. Expiração termina como `infrastructure_error`/`TimeoutError`, com `oracle_passed=null`.
3. **Busca sobreposta:** depois da primeira posição, busca-se outra a partir de `primeira + 1`; uma segunda ocorrência, inclusive sobreposta, resulta em `multiple_occurrences` sem escrever.
4. **Python compilável:** o lote usa `compile(content, path, "exec", dont_inherit=True)` em memória antes de gravar; `return` e `break` fora de contexto retornam `invalid_syntax`.

**Política de erro de I/O:** uma gravação terminal com linha JSONL completa já presente é recuperada; nenhum segundo terminal é gravado. Se a escrita falhar sem terminal completo ou deixar linha parcial/malformada, o runner levanta `JournalPersistenceError`, marca a tentativa como falha de persistência e não tenta outro append. Nesse caso não há garantia de um terminal durável: pode haver zero terminais completos, e o consumidor deve tratar o journal como inconclusivo e preservá-lo para investigação. A implementação não promete durabilidade contra falha de energia ou processo.

**Fragmentos privados:** os testes agora varrem linhas não triviais dos oráculos correspondentes aos 12 pacotes e verificam trechos do oráculo e uma sentinela emitida em stderr privado contra o prompt de reparo. Algumas linhas de oráculos são literalmente idênticas a asserções já publicadas nos testes visíveis (por exemplo em `mcp_params`); essas linhas públicas compartilhadas são excluídas da comparação de trechos exclusivos. Isso não certifica o isolamento dos futuros adaptadores de processo.

**Regressões RED → GREEN:** antes das correções, os testes que reproduzem exatamente os quatro achados produziram `5 failed` (busca sobreposta, `return`, `break`, finalização interrompida e oráculo que absorve timeout). Após as correções, a mesma seleção produziu `5 passed in 4.17s`. Uma revisão adicional identificou e motivou testes para timeout após `prepared`, registro JSON válido sem LF e política de I/O antes/depois do append; a espera de sinal pendente passou a ser não bloqueante. Esses casos adicionais foram corrigidos antes das verificações finais.

**Verificações finais reais**, no WSL e com bytecode desligado:

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -p no:cacheprovider -q tests/test_corpus_validate.py tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py tests/test_worker_contract.py tests/test_worker_runner.py
........................................................................ [ 66%]
....................................                                     [100%]
108 passed in 22.07s
```

```text
/home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/worker_contract.py benchmark/worker_runner.py corpus/validate_corpus.py tests/test_guarded_edit.py tests/test_worker_contract.py tests/test_worker_runner.py tests/test_corpus_validate.py
All checks passed!
```

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -u corpus/validate_corpus.py
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

A suíte acima é a suíte F3 pedida (os 96 testes anteriores e os novos), não uma alegação de execução dos demais arquivos de teste do repositório. Continuam aplicáveis as limitações de isolamento, callbacks e integração F4 registradas acima. Sem GPU, llama-server real, inferência, push, merge, reset, stash ou rebase.

- Re-revisão de b296ad6: commit 1e9a81c substitui a lista circular de linhas públicas pelos arquivos visíveis congelados e adiciona teste negativo de contaminação do builder (falhou antes e passou depois); pytest: 109 passed in 25.54s; Ruff: All checks passed!; corpus: RESULT: PASS (12 tasks).
