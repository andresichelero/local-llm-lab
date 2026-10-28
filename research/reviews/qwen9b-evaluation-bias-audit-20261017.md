# Auditoria do 100% do Qwen3.5-9B — 2026-10-17

## Conclusão

O 24/24 registrado é sustentado pelos artefatos daquele protocolo, mas não demonstra superioridade geral do Qwen. A suíte está saturada: são seis problemas públicos repetidos quatro vezes, não 24 problemas diferentes. Em cinco tarefas, as quatro fontes finais do 9B são idênticas; configuração tem duas variantes. O Ornith também atingiu 12/12 nas mesmas seis tarefas. Não encontrei aprovação condicionada ao nome Qwen no avaliador, nem evidência de que o modelo recebeu as soluções de referência. A neutralidade completa dos pesos, do parser llama.cpp ou das heurísticas internas do OpenCode não foi demonstrada.

Há riscos confirmados de cobertura e de interpretação: o oráculo aceita algumas implementações erradas, a pontuação estrita mistura comportamento do código com conclusão do fluxo, e o subconjunto Python e a política fixa de geração delimitam quais estilos/configurações podem ter sucesso. A suíte serve como regressão local e triagem de integração; já não discrimina suficientemente a qualidade de programação dos candidatos fortes.

## Evidência examinada

Foram auditadas 108 medições preservadas: campanha Qwen v2 (48), Granite 4.2 curto (12), Gemma 12B ampliado (24) e Ornith ampliado (24). Aquecimentos foram examinados à parte. Não houve nova inferência, aquisição de pesos ou execução nativa do código dos candidatos nesta auditoria. As sondas funcionais usaram `benchmark.restricted_python.load_modules`, com limites de execução. Os testes de referência locais validaram previamente a coerência das sondas.

Os arquivos do avaliador, interpretador, fixtures e probes utilizados para a análise coincidem com os do commit `4577aeb921587feaee8518c656a32a64d593ea9c` da campanha Qwen v2 (`git diff` desses caminhos vazio). Isso não implica que todos os outros componentes ou protocolos das campanhas posteriores sejam iguais: seus parâmetros e resultados foram lidos dos próprios registros congelados.

| Campanha / modelo | Código final aprovado pelo avaliador | Aprovação estrita do fluxo |
| --- | ---: | ---: |
| Qwen v2 / Qwen3.5-4B | 21/24 | 21/24 |
| Qwen v2 / Qwen3.5-9B | 24/24 | 24/24 |
| Granite curto / Granite 4.2 8B | 6/6 | 4/6 |
| Granite curto / Qwen3.5-9B | 6/6 | 6/6 |
| Gemma ampliado / Gemma 4 12B QAT local | 12/12 | 10/12 |
| Gemma ampliado / Qwen3.5-9B | 12/12 | 12/12 |
| Ornith ampliado / Ornith 1.0 9B | 12/12 | 12/12 |
| Ornith ampliado / Qwen3.5-9B | 12/12 | 12/12 |

Essa aprovação funcional descreve os testes congelados, não correção exaustiva; as sondas adicionais abaixo encontraram justamente um falso positivo no Ornith. Os aquecimentos do Qwen9B na v2 passaram 4/4. Os quatro aquecimentos reprovados, excluídos da pontuação daquela campanha, pertencem ao 4B; portanto essa exclusão não ocultou reprovações do 9B.

## O que pode favorecer o resultado

1. **Pouca diversidade e muita reutilização.** Cinco das seis tarefas já passaram em todas as repetições de ambos os Qwen na v2. `package_refactor` fornece a fórmula de agregação no próprio prompt; a normalização praticamente especifica `split/join`. A confirmação em tarefas distintas foi planejada, mas as 24 fixtures novas ainda não foram implementadas. Repetir essas mesmas tarefas mede consistência de execução e uma instabilidade do 4B, não diversidade de capacidade. Fontes: [campanha v2](../../results/reports/campaign-v2-results-20261015.md), [plano de ampliação](cross-model-evaluation-20261015.md), [tarefa de refatoração](../../benchmark/fixtures/package_refactor_task/TASK.md).

2. **O código e o fluxo não são a mesma métrica.** `strict_quality_pass` combina o grade com edição, ferramenta, teste bem-sucedido após a última edição, saída final e encerramento. O avaliador recebe workspace e tarefa, sem identidade do modelo; não há ramo que aprove Qwen. Gemma e Granite atingiram aprovação funcional integral no conjunto, mas falharam em duas conclusões do fluxo. Isso é evidência de integração/recuperação sob aquele orçamento, não de que não conseguiram implementar as funções. Fontes: [composição da aprovação](../../benchmark/model_quality_paired.py), [execução e workflow](../../benchmark/safe_campaign.py).

3. **Contrato e orçamento específicos.** O interpretador v2 rejeita sintaxe Python válida, como desempacotamento de dicionários; o caso MiniCPM foi atingido por isso e pelo contexto de 8K. Nomes exatos de testes são exigidos expressamente em várias tarefas, e sua presença participa do grade. Isso mede também conformidade nominal. Temperatura zero, saída de 1.024 tokens, raciocínio desligado e limite fixo de etapas são escolhas de uma configuração local, não garantia de medir o máximo de todas as famílias. As campanhas expandidas Gemma/Ornith e a triagem Granite usaram parâmetros iguais entre seus dois braços, conforme seus protocolos. Fontes: [interpretador](../../benchmark/restricted_python.py), [políticas do avaliador](../../benchmark/pristine_grading.py), [limites do MiniCPM](../../results/reports/minicpm5-2b-five-task-screen-20261017-r2.md).

4. **Exposição e independência limitadas.** As tarefas e seus exemplos já são conhecidos pelo desenvolvimento do laboratório; não há holdout novo e independente. Não encontrei prova de contaminação do treinamento ou de ajuste deliberado para beneficiar Qwen. Aquecimento e medição repetem uma tarefa, mas cada tentativa tem workspace novo e OpenCode `--pure`; não identifiquei aprendizado persistente entre tentativas por esse mecanismo.

## Verificação das entradas e das transcrições

Nos primeiros pedidos de `calculator_division` de cada modelo, em cada uma das quatro campanhas (oito corpos upstream), os hashes de mensagens de sistema, mensagens de usuário, schemas de ferramentas e parâmetros de geração coincidiram dentro do par. O nome do modelo foi conferido separadamente. Isso verifica uma amostra das entradas efetivas, além das configurações; não é uma auditoria de todas as requisições nem dos templates internos do llama.cpp.

Os registros nativos mostram chamadas de unittest em todas as 24 medições do Qwen9B v2, com último teste relatado como `OK` em todas. O runtime congelado monta o Python real no sandbox; um exemplo mostra os três métodos autorados de normalização e o teste de `word_count`, `Ran 4 tests`/`OK`. O campo `grade.candidate_tests_executed=false` pertence ao **avaliador independente**, que não executa testes autorados. Não significa que o agente não os executou no sandbox. Os eventos nativos continuam sendo relatos do processo, não atestação independente de cada comando.

No Gemma, as duas tentativas de divisão executaram uma chamada correta de unittest, que falhou porque `multiply` estava ausente naquele momento. Edições posteriores restauraram a função, mas produziram oito definições de `add` e sete de `multiply`, e não houve novo teste antes do limite de etapas. O código final passou no avaliador. A narrativa anterior de que a recuperação não reparou o workspace foi corrigida: houve recuperação funcional, duplicação de código e ausência de revalidação final. Os escores originais permanecem intactos.

## Sondas adicionais sobre as soluções salvas

Foram construídas 81 verificações diagnósticas para as seis tarefas: divisão com numerador zero e valores fracionários; outras formas de whitespace; aspas isoladas/descasadas; configurações vazias e valores falsy; limites de retry e callback terminal; métricas negativas e identidade de reexportação. As verificações foram aplicadas ao código preservado de todas as medições, sem pedir novas respostas aos modelos.

| Código preservado | Verificações diagnósticas aprovadas |
| --- | ---: |
| Qwen9B na v2 | 324/324 |
| Qwen4B na v2 | 321/324 |
| Qwen9B / Gemma12 na campanha Gemma | 162/162 em cada modelo |
| Qwen9B / Granite4.2 na triagem curta | 86/86 em cada modelo, só três tarefas |
| Qwen9B / Ornith na campanha Ornith | 162/162 / 156/162 |

São verificações repetidas sobre seis problemas e soluções já observados; não são tarefas inéditas, avaliação cega ou novas notas de modelo. As referências vieram do próprio laboratório. Os três erros do 4B reproduzem a falha conhecida em entrada vazia. No Ornith, ambas as soluções de retry chamam `on_retry` também após a última falha, quando nenhuma tentativa resta. O contrato só permite o callback quando restam tentativas; os testes congelados não verificavam callbacks na exaustão. Com `max_attempts=1`, o callback indevido ocorre imediatamente. Fontes: [contrato](../../benchmark/fixtures/retry_policy_task/TASK.md), [implementação preservada do Ornith](../../results/raw/ornith9b-expanded-20261017-r1/runs/block-2-measurement-ornith-1.0-9b-retry_policy-r1/workspace/src/retry.py).

Foi separada uma ambiguidade: `defaults={'unset': None}` é preservado pelos candidatos examinados, enquanto a referência elimina a chave. O texto sobre `None` pode ser lido para todas as camadas, mas os exemplos só desambiguam as superiores. Não contei essa divergência como erro dos modelos; o contrato precisa ser esclarecido antes de usar esse caso para pontuar.

## Controles do avaliador que expõem lacunas

Três implementações deliberadamente incorretas passaram em `grade_pristine_workspace` e falharam nas sondas extras: divisão que retorna `1.0` quando o numerador é zero; retry que valida somente zero e aceita limites negativos; parser que remove aspas externas de tipos diferentes. São exemplos construídos após inspecionar a cobertura, não estimativas de taxa de erro nem defeitos encontrados no Qwen.

O mesmo avaliador aprovou fontes corretas com métodos de teste contendo somente `pass`. Em sentido inverso, testes de normalização com asserções corretas e nomes diferentes dos exigidos passaram funcionalmente e falharam no gate nominal. Este último resultado é coerente com o requisito atual de nomes exatos, portanto não o chamo de falso negativo oculto.

Esses controles chamam **somente o avaliador independente**, não o fluxo completo OpenCode/CPython. Em especial, os stubs dos controles existentes nem herdam `unittest.TestCase`; não demonstram aprovação na execução real de discovery. Demonstram que presença de nomes e aprovação funcional da implementação não medem adequação dos testes autorados.

## Próximo critério de decisão

Antes de usar outro 100% para escolher um modelo, preparar uma pequena seleção nova e congelada de tarefas do uso real, sem calibrá-las primeiro nas respostas do Qwen. Reservar casos para avaliação e separar código funcional, regressão, workflow, tempo e manutenção. Validar múltiplos estilos corretos e mutantes parciais, incluindo os limites expostos aqui; esclarecer contratos ambíguos. A neutralidade de um orçamento fixo pode ser útil para a máquina, mas deve ser relatada como avaliação da configuração modelo+harness. A suíte antiga deve continuar como regressão, sem ser apresentada como evidência de generalização. Nenhuma nova rodada de inferência foi iniciada nesta investigação.

## Artefatos e validação

- [Análise estruturada r2](../../results/system-audit/qwen9b-bias-audit-20261017-r2/audit.json), SHA-256 `05b76cf2f0276ecd304cf001ff4d0380ba26c0dcb3f17fac8051a33a5989088f`.
- [Comparação de pedidos e eventos](../../results/system-audit/qwen9b-bias-audit-20261017-r2/transcripts-audit.json), SHA-256 `5463afa78ff8c454da646568f27d38100383f78cb1bffbb898f3fb3e038c6919`.
- [Manifest de evidências](../../results/system-audit/qwen9b-bias-audit-20261017-r2/evidence-manifest.json), scripts reproduzíveis e cópias dos relatórios anteriores no mesmo diretório. As fontes de candidatos comparadas pelo script são texto normalizado; os hashes dos JSONL e dos pedidos preservados usam seus bytes.
- Originais e saídas finais de CPU em `/home/foxtrot/local-llm-benchmark/results/audits/qwen9b-bias-audit-20261017-r2-final` e nos diretórios de campanha citados no JSON. As saídas r1 e r2 intermediárias foram preservadas; r2 remove uma duplicação de caso diagnóstico de retry. A revisão final removeu apenas um import não utilizado e repetiu a análise de CPU, sem mudar as sondas ou seus resultados.
- Validação focada do projeto: 22 testes e 18 subtestes aprovados em `test_trusted_task_tests.py` e `test_pristine_grading.py`; Ruff aprovado nos scripts da auditoria; execução dos dois scripts concluída; hashes das cópias e da fonte executada conferidos. Não há verificador de tipos configurado no projeto. A revisão de leitura independente apontou e delimitou corretamente o alcance dos controles, a exigência nominal explícita e a ausência de avaliação cega.
