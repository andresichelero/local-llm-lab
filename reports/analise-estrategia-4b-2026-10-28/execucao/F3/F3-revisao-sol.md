# F3 — revisão adversarial de f2970ca

Data: 2026-10-28. **Veredito: REPROVAR o commit como gate da F3 para a F4 até corrigir os quatro achados e repetir as verificações.** Há dois achados de severidade alta e dois média; nenhum crítico confirmado. A suíte verde não cobre os casos reproduzidos abaixo.

## Escopo e execução

- Worktree: `D:/Usuario/Downloads/LLM/.worktrees/4b-worker-f3`, branch `feat/4b-worker-f3`, HEAD `f2970caab86e541210541ffb896c9977828b17f8`; comparação `git diff a459b11 f2970ca`.
- Lidos: seção F3/F4 de `PLANO-ESTRATEGICO-v2.md`, `execucao/F3/F3-implementacao.md`, os quatro módulos alterados e testes associados. Leitura complementar do llama.cpp local para conferir o contrato de tokenização.
- Revisão somente leitura do código. Sem instalação, rede, GPU, inferência, commit, push ou merge. Provas executadas por stdin com arquivos descartáveis exclusivamente em `/tmp` do WSL e bytecode desligado. Este relatório é a única escrita de entrega; o worktree continuou limpo.
- Resultados abaixo são reproduções offline. Não se afirma que já contaminaram uma execução científica ou que algum servidor real foi validado.

## Achados, em ordem de severidade

### 1. ALTO — Interrupção na finalização grava dois terminais contraditórios

**Local:** `benchmark/worker_runner.py:81`, `:82` e `:176`.

`finalize()` persiste o terminal por `_record()` antes de atribuir `self.result`. O SIGALRM permanece armado durante essa operação. Se o prazo expira depois de persistir `accepted`, mas antes de atribuir o resultado, o `except Exception` de `_run()` chama outra finalização, agora `infrastructure_error`: `self.result` ainda é `None`.

**Entrada → saída errada reproduzida:** pacote `py_range`, limite de 1 segundo, patch válido de `x = 1\n` para `x = 2\n`, verificação visível aprovada e oráculo `True`. Injetado atraso de persistência: `_record` chama sua implementação real e dorme 2 segundos somente depois de registrar `accepted`. O timer interrompe a finalização. O journal real contém:

```text
prepared → generating → candidate → verifying → accepted → infrastructure_error
```

O `RunResult` retornado é `infrastructure_error`, com motivo `TimeoutError`, para o mesmo `attempt_id` que já possui `accepted` persistido. O atraso é uma simulação de finalização/I/O lenta, não uma modificação dos callbacks de avaliação. Existe uma janela real equivalente entre persistência e atribuição do resultado, mesmo sem essa injeção.

**Impacto:** o histórico deixa de representar uma máquina com um único terminal. Consumidores que usam o evento de aceite e consumidores que usam o último terminal produzem contagens diferentes. A repetição simples de `finalize()` após uma execução concluída é idempotente, mas essa transição interrompida não é.

**Correção sugerida:** verificar o prazo antes do commit terminal e proteger sua conclusão da entrega do SIGALRM do runner; encerrar o timer como parte dessa transição. Definir uma política explícita para erro de persistência e impedir que o tratamento externo grave outro terminal depois de um terminal já persistido. Apenas inverter `self.result` e `_record()` troca a falha por outra em caso de I/O e não resolve o protocolo sozinho.

**Lacuna de teste:** `tests/test_worker_runner.py:35` chama a finalização novamente somente depois do sucesso completo. Acrescentar a interrupção entre registro terminal e atribuição, exigindo um terminal e concordância entre journal e resultado.

### 2. ALTO — Prazo expirado no oráculo privado pode terminar como aceite incorreto

**Local:** `benchmark/worker_runner.py:163` até `:169`.

Há checagem de relógio após geração e após verificação visível, mas não após `private_oracle()`. O SIGALRM entrega um `TimeoutError` apenas uma vez. Um wrapper de avaliação que captura `Exception` pode absorver esse sinal e devolver um booleano; o runner aceita esse retorno mesmo com o prazo já expirado.

**Entrada → saída errada reproduzida:** mesmo pacote/patch válido, `wall_seconds=1`, verificação visível aprovada e este callback privado:

```python
def private_oracle():
    try:
        time.sleep(2)
        return True
    except Exception:
        return False
```

Resultado observado após aproximadamente 1,01 s:

```json
{"state":"accepted","oracle_passed":false,"reason":""}
```

A exceção capturada pelo callback foi `TimeoutError`. O desfecho deveria registrar expiração, sem atribuir uma nota privada de incorreção ao patch. O callback não precisa ser hostil nem conhecer o mecanismo de timer: captura genérica de exceções num wrapper de teste basta. A ausência de sandbox, já documentada, não explica a ausência da checagem de prazo que o próprio runner faz nas etapas anteriores.

**Impacto:** uma expiração da avaliação vira a métrica científica de “aceito incorreto”. Na F4, que exige zero aceitos incorretos, isso pode mudar diretamente o gate da hipótese.

**Correção sugerida:** checar o relógio imediatamente após o callback privado e antes de interpretar/persistir seu retorno; propagar a expiração pelo caminho de timeout/infraestrutura, sem `oracle_passed=False`. Considerar também uma marca persistente de expiração no handler para não depender de a exceção atravessar todos os callbacks.

**Lacuna de teste:** `tests/test_worker_runner.py:131` exercita o bloqueio no verificador visível; `:144` testa tipo não booleano. Nenhum exercita prazo privado capturado internamente. Acrescentar o cenário acima e exigir ausência de terminal `accepted`.

### 3. MÉDIO — Busca com ocorrências sobrepostas é aceita como única

**Local:** `benchmark/guarded_edit.py:468` até `:472`.

`str.count(search)` conta ocorrências não sobrepostas. Isso não demonstra que existe exatamente uma posição válida para aplicar SEARCH.

**Entrada concreta:** arquivo permitido `a.py`, SHA-256 correto e conteúdo:

```python
a = 1
a = 1
a = 1
```

Resposta do modelo:

```text
FILE: a.py
<<<<<<< SEARCH
a = 1
a = 1
=======
a = 2
>>>>>>> REPLACE
```

**Saída errada observada:** `status=applied`, com conteúdo `a = 2\na = 1\n`. A busca tem duas posições possíveis, offsets 0 e 6; a segunda foi ignorada por `count()`. O contrato exige rejeição `multiple_occurrences` e nenhuma escrita.

**Impacto:** o aplicador escolhe silenciosamente a primeira entre duas edições possíveis. Uma resposta ambígua entra na verificação como candidata válida, contrariando o guard determinístico exigido pela F3.

**Correção sugerida:** localizar a primeira ocorrência e procurar uma segunda a partir de `primeira + 1`, incluindo sobreposição. Só aplicar quando não houver segunda posição.

**Lacuna de teste:** `tests/test_guarded_edit.py:537` cobre repetições disjuntas. Acrescentar a repetição de duas linhas em três linhas idênticas e verificar status e bytes originais.

### 4. MÉDIO — AST válida não garante Python compilável; lote grava erro de sintaxe

**Local:** `benchmark/guarded_edit.py:479`.

O lote usa somente `ast.parse()`. O parser constrói AST para certas instruções cujo contexto é rejeitado na compilação; portanto esse gate não assegura a sintaxe executável exigida.

**Entrada → saída errada reproduzida:** arquivo permitido `a.py` com `value = 1\n`, hash correto, SEARCH exato desse conteúdo e substituição `value = 2\nreturn\n`. O lote retorna `applied` e grava a substituição. Em seguida:

```python
compile(target.read_text(), str(target), 'exec')
# SyntaxError: 'return' outside function (a.py, line 2)
```

**Impacto:** código não compilável ultrapassa uma rejeição que deveria acontecer antes de qualquer escrita e chega à verificação, podendo consumir o único reparo. Se a verificação visível importa o módulo, ela provavelmente detectará a falha; não se está afirmando que o runner necessariamente aceitará esse código. O defeito demonstrado é o aceite e a gravação pelo aplicador como sintaticamente válido.

**Correção sugerida:** compilar o candidato em memória, por exemplo com `compile(content, str(target), 'exec', dont_inherit=True)`, sem executá-lo, antes de escrever. Manter as demais validações e retornar `invalid_syntax` para a exceção.

**Lacuna de teste:** `tests/test_guarded_edit.py:540` usa um parêntese aberto, já rejeitado por `ast.parse()`. Incluir `return` e `break` fora do contexto permitido, exigindo arquivo original intacto.

## Verificado sem achados adicionais

- **Fronteira privada:** no fluxo padrão inspecionado, o builder utiliza metadados da tarefa, teste visível, stub público e snippets exatos de arquivos permitidos. Não foi confirmado carregamento de `corpus/oracles` nem de `reference.patch` para pacote/prefixo. O runner só chama o callback privado depois do sucesso visível e não o chama na primeira fase de continuação. O valor booleano vai para a nota; o texto da exceção privada não é registrado, apenas seu tipo. Não foi observado stderr privado entrando no pacote, no reparo ou no journal implementado pelo runner.
- **Limite dessa evidência:** os adaptadores reais de execução dos verificadores e o isolamento de processos ainda estão pendentes conforme o relatório da implementação. O teste `tests/test_worker_runner.py:35` não executa um oráculo real nem injeta stderr privado; sua sentinela é armazenada numa lista externa. Os testes de ausência de conteúdo privado em `tests/test_worker_contract.py:8` e `:65` comparam textos integrais: sozinhos não detectariam vazamento de um fragmento. A conclusão acima também depende da leitura do fluxo, não desses asserts isoladamente. Não se certifica isolamento de stdout/stderr do futuro executor F4.
- **Parser e escopo:** não encontrado fallback aproximado no modo lote. Cercas/prosa, marcadores embutidos e saída incompleta são rejeitados; a saída original permanece no resultado. Allowlist, hash antigo, proteção dos testes upstream existentes e de caminhos `oracles`, travessia externa e componentes symlink têm verificações úteis. A exceção dos testes novos permite repará-los na mesma tentativa. A ambiguidade sobreposta é a exceção confirmada no achado 3.
- **Lote e rollback:** validação precede escrita. Os testes exercitam falha na segunda substituição, exceção inesperada e interrupção imediatamente após rename, com restauração. Não encontrado novo caso de lote parcialmente persistido nessas falhas ordinárias. Atomicidade contra queda do processo/energia, falha do próprio rollback e troca hostil concorrente de caminhos não está demonstrada e já é uma limitação explícita; não foi convertida em achado novo.
- **Reparo e continuação no caminho normal:** builder limita `repairs` a 0 ou 1; fluxo permite no máximo duas gerações. Reparo exige diagnóstico visível não vazio e ausente do pacote inicial. A liberação pública de follow-up exige aceite do mesmo runner e tarefa de primeira fase; não foi demonstrada liberação precoce nesse caminho. A finalidade dupla simples é idempotente; o achado 1 cobre sua interrupção assíncrona.
- **Infraestrutura no caminho normal:** exceção do cliente e indisponibilidade do verificador sintático não viram rejeição sintática do modelo. Não foi observado timeout de geração diretamente convertido em aceite. O achado 2 é o caso diferente em que o timer é absorvido dentro da avaliação privada. Não foi alegada validação causal dos futuros adaptadores de testes.
- **Prefixo/tokenização:** prefixo comparado byte a byte com o arquivo congelado do host, identificado por SHA-256, conferido novamente pelo runner e enviado primeiro em mensagem de sistema. Os testes entre tarefas verificam bytes iguais. `/apply-template` e geração recebem as mesmas mensagens e `enable_thinking=false`; a geração deste cliente não envia tools, e a evidência de stub integra o corpo contado. Sem divergência estática confirmada para esse fluxo textual.
- **Conferência primária local:** raiz `/home/foxtrot/local-llm-benchmark/tools/llama.cpp-v0.8.0-8642541b2`. Em `tools/server/server-context.cpp:5997` e `:6345`, chat completions e apply-template usam `oaicompat_chat_params_parse`; `:5347` tokeniza geração com `true,true`, coerente com `add_special=true, parse_special=true` de `:6372`/`:6376`. Em `tools/server/server-common.cpp:1448`, `add_generation_prompt` tem padrão `true`, e `:1481`/`:1491` aplicam kwargs e desativação de thinking. Isso é evidência de código da versão local, sem servidor real, GPU, medição de cache ou confirmação de outra configuração implantada.
- **Node:** revisão do resolvedor e seus testes sem defeito confirmado; precedência do override, PATH e versões numéricas NVM exercitada.

## Verificações executadas

Comandos principais, com cwd no worktree, no WSL:

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -p no:cacheprovider -q tests/test_corpus_validate.py tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py tests/test_worker_contract.py tests/test_worker_runner.py
96 passed in 20.00s

PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/worker_contract.py benchmark/worker_runner.py corpus/validate_corpus.py tests/test_guarded_edit.py tests/test_worker_contract.py tests/test_worker_runner.py tests/test_corpus_validate.py
All checks passed!

PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python corpus/validate_corpus.py
RESULT: PASS (12 tasks)
```

O validador retornou `PASS bug/oracle/visible/original=(1, 0, 0, 0)` para cada tarefa. `git diff --check a459b11 f2970ca` também passou. Não há gate de typecheck definido para esta F3, conforme o plano; nenhum foi inventado. Execuções auxiliares dos revisores repetiram subconjuntos sobrepostos, portanto não foram somadas ao total de 96 testes.

As quatro provas adicionais produziram:

```text
overlap: offsets=[0, 6], status=applied, actual='a = 2\na = 1\n'
compile: status=applied, actual='value = 2\nreturn\n', SyntaxError="'return' outside function"
oracle_deadline: state=accepted, oracle_passed=false, elapsed≈1.01s, captured=TimeoutError
finalize_deadline: result=infrastructure_error/TimeoutError, journal=[prepared,generating,candidate,verifying,accepted,infrastructure_error]
```

## Veredito e gate de reavaliação

**REPROVAR para a entrada na F4 neste estado.** Corrigir os quatro cenários demonstrados e incluir regressões que comprovem: um terminal por tentativa; expiração privada sem aceite/nota de incorreção; rejeição de busca sobreposta; rejeição de Python não compilável antes de escrever. Reexecutar os mesmos testes, ruff e validador do corpus. As limitações já declaradas de isolamento e integração F4 continuam separadas desses defeitos e precisam de validação própria antes de inferência.
## Re-revisão de b296ad6

Data: 2026-10-28. **Novo veredito: APROVAR COM CORREÇÕES**, com a correção do teste de privacidade descrita abaixo exigida antes de usar essa cobertura como gate da F4. Os quatro cenários originais foram corrigidos. Não foi confirmado novo defeito no fluxo de produção alterado; foi confirmado um novo falso negativo no teste de fragmentos privados. Este veredito refere-se a `b296ad6`; a reprovação acima fica preservada como histórico de `f2970ca`.

### Escopo e preservação

Revisado `git diff f2970ca b296ad6` no mesmo worktree e branch, com HEAD confirmado como `b296ad6e25cd2a52f77f84958a134e90d568d7dd`. Lida também a política de persistência acrescentada ao relatório de implementação. Código e testes permaneceram intactos; nenhuma instalação, rede, GPU, inferência, alteração Git ou commit. As provas rodaram por stdin no WSL, com arquivos descartáveis somente em `/tmp` e `PYTHONDONTWRITEBYTECODE=1`. Esta seção foi acrescentada ao final do relatório, sem substituir seu conteúdo anterior.

### 1. Reexecução das quatro provas originais

Mesmas entradas, orçamentos e injeções da revisão anterior. O observador da prova de compilação foi apenas adaptado para aceitar a possibilidade de o arquivo original continuar intacto; ele não pressupõe mais que necessariamente haverá `SyntaxError` ao recompilar o arquivo persistido.

**Prova original 1 — interrupção na finalização:** pacote `py_range`, patch `x = 1\n` → `x = 2\n`, orçamento de 1 s, verificação visível e privada aprovadas; `_record` real seguido de `sleep(2)` somente para `accepted`. Saída real:

```json
{"proof":"finalize_deadline","result":{"attempt_id":"5da0354e67624c31ae94fa097b889112","state":"accepted","input_tokens":10,"oracle_passed":true,"reason":""},"elapsed":2.001397736996296,"states":["prepared","generating","candidate","verifying","accepted"]}
```

**Resultado:** corrigido o defeito de dois terminais. Há exatamente um `accepted`, coerente com o resultado retornado. O retorno em 2,00 s para orçamento de 1 s é real: a implementação desarma o timer antes da persistência terminal. A política agora documentada permite concluir persistência iniciada dentro do prazo sem interrupção. Isso não comprova um limite rígido de tempo ponta a ponta; o tempo de persistência deve integrar a medição de custo/latência da F4. Não foi tratado como nova ocorrência do defeito antigo, pois a decisão e seu único registro terminal foram iniciados dentro do prazo, e a extensão ocorre na persistência protegida.

**Prova original 2 — oráculo privado absorve timeout:** mesmo patch/orçamento, callback com `try: sleep(2); return True` e `except Exception: return False`. Saída real:

```json
{"proof":"oracle_deadline","result":{"attempt_id":"aa35fbb3b6614d15b4800de3db0868ae","state":"infrastructure_error","input_tokens":10,"oracle_passed":null,"reason":"TimeoutError"},"elapsed":1.0073366690048715,"oracle_errors":["TimeoutError"],"states":["prepared","generating","candidate","verifying","infrastructure_error"]}
```

**Resultado:** corrigido. A marca de expiração e a checagem após `private_oracle()` impedem aceite e nota privada falsa, mesmo com a exceção absorvida pelo callback.

**Prova original 3 — busca sobreposta:** conteúdo `a = 1\na = 1\na = 1\n`, busca de duas linhas `a = 1\na = 1\n`, substituição `a = 2\n`, hash correto e arquivo permitido. Saída real:

```json
{"proof":"overlap","offsets":[0,6],"status":"multiple_occurrences","actual":"a = 1\na = 1\na = 1\n","original_unchanged":true}
```

**Resultado:** corrigido. As duas posições são detectadas e nenhum byte do alvo muda.

**Prova original 4 — Python não compilável:** conteúdo `value = 1\n`, substituição `value = 2\nreturn\n`, hash correto e arquivo permitido. Saída real:

```json
{"proof":"compile","status":"invalid_syntax","actual":"value = 1\n","persisted_compiler_error":null,"rejection_error":"'return' outside function (a.py, line 2)"}
```

**Resultado:** corrigido. A rejeição vem de `compile()` antes da escrita. `persisted_compiler_error=null` significa que o arquivo original preservado continua compilável; não significa que a substituição tenha passado.

### 2. Novo achado — MÉDIO: lista circular de linhas públicas mascara contaminação do teste visível

**Arquivo:linha:** `tests/test_worker_contract.py:101`, com exclusão aplicada em `:106`.

O teste define `public_lines` a partir de `package.readonly_context['visible_test']`, isto é, da própria saída do builder que deveria fiscalizar. Se um bug de montagem acrescentar uma linha privada a esse campo e ao Markdown, a linha ganha automaticamente status de pública e sai da comparação. O `checked > 0` global continua satisfeito pelas outras linhas/tarefas.

**Cenário concreto reproduzido, somente com mutação em memória:** substituir temporariamente o símbolo `build_package` usado pelo módulo de testes por um wrapper que chama o builder original e, somente para `py_range`, usa `dataclasses.replace` para acrescentar a linha abaixo tanto ao `readonly_context['visible_test']` quanto ao `markdown`:

```python
assert list(bottle.parse_range_header('bytes=0-0,5-99,-2', 8)) == [(0, 1), (5, 8), (6, 8)]
```

A linha foi lida do oráculo privado e **não existe** em `corpus/tasks/py_range/visible.py`. Com essa saída contaminada, executei as funções reais `test_packages_exclude_nontrivial_private_oracle_lines()` e `test_all_corpus_packages_exclude_private_files()`. Ambas passaram. Como controle, a mesma injeção só no Markdown, sem contaminar o campo usado como lista pública, fez o novo teste falhar corretamente.

Saída real da prova principal:

```text
fragment: assert list(bottle.parse_range_header('bytes=0-0,5-99,-2', 8)) == [(0, 1), (5, 8), (6, 8)]
fragment_in_frozen_visible: False
new_fragment_test_with_leak_in_visible_test_and_markdown: PASS (leak undetected)
old_full_content_test_with_same_leak: PASS (leak undetected)
control_fragment_test_with_leak_in_markdown_only: FAIL as expected
```

**Impacto:** esse teste pode ficar verde justamente quando o builder publica um fragmento privado dentro do contexto que chama de visível. As verificações antigas de arquivo inteiro não compensam essa lacuna. Trata-se de falso negativo de teste demonstrado por mutação, não de afirmação de que o builder atual esteja vazando essa linha. O diff não altera o builder de produção, e não foi encontrado esse vazamento no fluxo atual.

**Correção sugerida:** construir a lista de linhas públicas diretamente do arquivo público congelado da tarefa (`visible.py` ou `visible_phase1.py`, conforme a fase), independentemente do pacote produzido. Acrescentar um teste negativo em que o resultado do builder contamine o `visible_test` com uma linha exclusiva do oráculo: a auditoria deve rejeitar essa saída. Excluir uma linha verdadeiramente já pública é legítimo; a circularidade está em usar a saída fiscalizada como fonte dessa decisão.

### 3. SIGALRM, persistência e regressões procuradas

Além das quatro provas, injetei falhas no stream retornado por `Path.open` exclusivamente no append do journal. O método `_record` original continuou executando, inclusive seu `except OSError`; isso evita o falso conforto de testar somente um mock que pula o wrapper real.

| Entrada da prova de I/O | Saída real | Terminais completos persistidos |
|---|---|---|
| `OSError` antes de escrever bytes do terminal | `JournalPersistenceError: terminal append failed; no retry is safe` | nenhum |
| Metade da linha terminal escrita, seguida de `OSError` | `JournalPersistenceError: journal cannot be read unambiguously` | nenhum |
| Linha terminal completa, seguida de `OSError` no fechamento | `accepted`, `oracle_passed=true` | um `accepted` |
| Escrita terminal dorme 1,2 s com orçamento de 1 s | `accepted`, `oracle_passed=true`, tempo real 1,202796875993954 s | um `accepted` |

Em todas as quatro provas, ao retornar ou propagar a exceção, a máscara de sinais ficou vazia e o timer retornou `(0.0, 0.0)`. Nos três casos com `OSError`, `_journal_failed=true`; no caso de linha completa, a recuperação retornou o terminal já persistido sem novo append. Os testes existentes também verificam que a tentativa inconclusiva não pode ser finalizada novamente com um append inseguro.

A política distingue conclusão recuperável de persistência inconclusiva: falha parcial/sem terminal pode levantar exceção e deixar zero terminais, em vez de fabricar `infrastructure_error` no mesmo journal. O executor F4 precisará preservar esse caso como inconclusivo; não deve convertê-lo em erro do modelo nem repetir a tentativa sobre o workspace já alterado. Essa exigência está explicitada no relatório de implementação e não foi descoberta uma contradição com a execução observada.

Não foi confirmado outro defeito no tratamento alterado de SIGALRM, prazo, compilação ou sobreposição. A espera de sinal pendente é não bloqueante, a marca de expiração sobrevive à captura da exceção pelo callback e o timer fica desarmado na persistência terminal. Permanecem as limitações previamente declaradas de POSIX/thread principal, I/O fora do limite rígido de relógio na finalização, callbacks confiáveis e ausência de sandbox do SO.

**Vazamento no reparo:** o novo teste que emite fragmento em stderr comprova que esse fragmento não entra no prompt de reparo nesse fluxo; ele também constata sua presença em stderr capturado pelo pytest. Isso não certifica isolamento do stderr do futuro executor nem ausência de vazamento num journal externo que misture stdout/stderr. Não foi confirmado vazamento para o JSONL implementado pelo runner nesta re-revisão.

### 4. Verificações executadas contra b296ad6

No WSL, cwd do worktree, sem bytecode nem cache pytest:

```text
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -p no:cacheprovider -q tests/test_corpus_validate.py tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py tests/test_worker_contract.py tests/test_worker_runner.py
108 passed in 24.23s

PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/worker_contract.py benchmark/worker_runner.py corpus/validate_corpus.py tests/test_guarded_edit.py tests/test_worker_contract.py tests/test_worker_runner.py tests/test_corpus_validate.py
All checks passed!

PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python corpus/validate_corpus.py
RESULT: PASS (12 tasks)
```

As 12 tarefas retornaram individualmente `PASS bug/oracle/visible/original=(1, 0, 0, 0)`. A seleção de 108 é a suíte F3 pedida, não todos os arquivos de testes do repositório. `git diff --check f2970ca b296ad6` passou; worktree limpo e HEAD inalterado após as verificações. Não há gate de typecheck definido pelo plano. Execuções auxiliares de subconjuntos não foram somadas aos 108.

### 5. Novo veredito

**APROVAR COM CORREÇÕES.** Os quatro achados de `f2970ca` estão encerrados para os cenários concretos reexecutados. Corrigir a fonte da lista de linhas públicas e adicionar a prova negativa de contaminação antes de considerar o teste de fragmentos um gate satisfeito para a F4. Não há novo vazamento de produção confirmado nem aprovação de isolamento, servidor real, GPU ou inferência nesta revisão.