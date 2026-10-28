# Seleção prática do agente local

Objetivo: escolher a configuração que conclui mais tarefas reais corretamente
na RTX 3070 de 8 GB, usando tempo total como desempate. Sem novos downloads.

Execute no WSL: `bash scripts/run-practical-selection.sh`. A atualização diária
ocorre primeiro. O mesmo comando retoma as tarefas restantes após interrupção.
O local padrão dos resultados é
`/home/foxtrot/local-llm-benchmark/results/practical-selection-v1-r1`.

Fila: Qwen3.5 4B, Qwen3.5 9B, Ornith 9B, Granite 4.2 8B e Gemma 12B QAT local.
O Gemma é identificado pelo hash do arquivo, sem atribuir origem ainda não confirmada.
Cada modelo recebe correção de bug, implementação e consulta MCP. Os dois melhores
seguem para recuperação de ferramenta, manutenção e continuação na mesma sessão.
Cada tarefa tem até 300 segundos e 30 chamadas ao modelo, incluindo chamadas
auxiliares do harness. Não há repetição automática nem aquecimento de tarefa.

Todos usam contexto de 16K, saída máxima de 2048 tokens, temperatura zero,
seed 1234, KV Q4_0, um slot, cache de prompt e raciocínio desligados.
Uma consulta MCP curta valida a integração antes das tarefas. Os pesos e o
runtime permanecem fixos durante a rodada; a retomada recusa código de avaliação
alterado. Para uma nova versão do protocolo, use outro diretório de resultados.

O agente usa Python real e o servidor MCP local pelo transporte stdio. A consulta
exige todas as páginas. A recuperação inclui versão desatualizada, falha
temporária e chave de idempotência; o servidor deve aplicar exatamente uma vez.
Os testes de aceitação só são montados em outro sandbox após a execução.
As soluções podem acrescentar arquivos auxiliares e nomes de testes livres.
Os testes escritos no workspace são executados separadamente e seu resultado
fica por fase; a avaliação funcional usa os testes independentes.

`summary.csv` apresenta corretude, conclusão autônoma, tempo total (incluindo
falhas), mediana dos sucessos, erros de ferramentas e picos de VRAM/RAM.
Memória é medida no sistema inteiro, sem atribuição exclusiva ao processo.
`status.json` mostra progresso; `recommendation.json` compara os finalistas e
preserva a triagem de todos os modelos. Comparar somente tarefas comuns: os
eliminados fazem três tarefas e os finalistas fazem seis.

Falha de infraestrutura não vira reprovação de qualidade e pode ser retomada.
As respostas, snapshots e registros por tarefa permitem reavaliar uma saída
sem solicitar nova inferência. O sandbox mantém limites de memória, tempo e
acesso ao host; não há acesso a arquivos pessoais nem serviços externos.

Nas tarefas de código, conclusão autônoma exige também testes do workspace
aprovados com pelo menos um caso adicional ao teste inicial. Não há exigência
de nomes específicos. MCP e recuperação são avaliados pelos resultados e
pelas chamadas observadas, sem exigir testes de código para uma consulta.
Eventos nativos do harness são evidência operacional, sem alegação de atestação
contra um agente deliberadamente malicioso.

Para reavaliar um snapshot sem inferência:
`python -m benchmark.practical_selection --regrade-run CAMINHO_DA_TAREFA`.
Isso escreve uma análise separada e preserva a nota original.

Validação da implementação em 2026-10-17: 44 testes e 31 subtestes passaram,
incluindo dependências de isolamento, broker e atualização diária. Mais dois
testes de integração passaram com CPython isolado, OpenCode real, MCP stdio e
continuação no mesmo identificador de sessão. Ruff passou nos arquivos novos;
não há typecheck configurado no projeto. Revisão independente corrigiu paginação
variável, classificação de artefatos inválidos e avaliação dos testes autorados.

Validação sem GPU: `python -m pytest tests/test_practical_selection.py
tests/test_practical_tasks.py tests/test_practical_mcp.py -q`.
Integração no WSL: `RUN_PRACTICAL_INTEGRATION=1 python -m pytest
tests/test_practical_integration.py --basetemp=/home/foxtrot/local-llm-benchmark/results/practical-integration-NOVO -q`.
Ela usa OpenCode real e servidor de modelo simulado, comprovando MCP stdio,
continuação de sessão e execução CPython isolada antes de gastar GPU.
