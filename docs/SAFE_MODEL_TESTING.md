# Testes controlados dos modelos locais

## Seleção prática atual

A escolha do agente local passa a usar o [pipeline prático](PRACTICAL_SELECTION.md):
seis tarefas novas, ferramentas MCP reais e CPython isolado. A suíte antiga
abaixo permanece como histórico e regressão. Entrada: `scripts/run-practical-selection.sh`.

## Resultado da execução de 2026-10-15

A campanha v2 concluiu 48 medições em oito sessões: Qwen3.5-4B passou em 21/24 e
Qwen3.5-9B em 24/24. As três falhas foram funcionais e ocorreram na normalização de
entrada vazia pelo 4B. Não houve falhas de infraestrutura na campanha corrigida.
Consulte o [relatório com a análise e os limites](../results/reports/campaign-v2-results-20261015.md)
e o [status atualizado](../results/reports/status.md). A execução usou a fonte
`4577aeb921587feaee8518c656a32a64d593ea9c`; os resultados não são evidência de
capacidade geral ou de tarefas inéditas.

A [auditoria de 2026-10-17](../research/reviews/qwen9b-evaluation-bias-audit-20261017.md)
confirmou saturação e lacunas de cobertura nesta suíte. Para selecionar entre
candidatos fortes, use tarefas novas com critérios congelados antes de observar
suas respostas; registre aprovação funcional e conclusão do fluxo separadamente.

## Liberação verificada em 2026-10-15

O código `6133bb6bd2af2daed6c1678b88ff61570df92464` obteve `READY` nos 20
controles obrigatórios, com 389 testes e 70 subtestes aprovados. Nenhum modelo foi
carregado e nenhuma inferência foi realizada durante esta preparação. A liberação
vale para a campanha de regressão de seis tarefas descrita abaixo; as condições de
recursos e as entradas são verificadas novamente antes de executar.

O [relatório e índice de evidências](C:/Users/Andre/.codex/state/plugins/codex-security/scans/local-llm-lab/artifacts-ea8449f477509b0759c670a45dde0c65a4df2fbee8ab7fcf70bac2a42a4c0c38/hardening/safe-model-release-20261015.md)
registra hashes, controles, revisão independente, limitações e tentativas anteriores.
O relatório original está em
`/home/foxtrot/local-llm-benchmark/results/safe-readiness-6133bb6-20261015/readiness-report.json`.

Foram verificados separadamente o ciclo completo simulado da campanha (oito sessões,
48 linhas medidas e oito aquecimentos), uma tarefa pelo caminho nativo completo com
provedor simulado e os contratos do avaliador para as seis tarefas. Esses controles
não são 48 resultados reais dos modelos. Não há verificador de tipos configurado;
Ruff, compilação Python e sintaxe dos 40 scripts passaram como verificações distintas.

## Contrato e alcance

A entrada suportada para a próxima campanha é `python -m benchmark.safe_campaign`.
O modo padrão apenas mostra o plano. `--readiness` verifica os pré-requisitos sem
carregar modelos; somente `--execute` pode iniciar inferência. A execução repete
os controles e recusa evidências antigas ou incompatíveis com os arquivos atuais.

O protocolo `restricted-python-workspace-v2` avalia seis tarefas públicas de
regressão em um subconjunto explícito e limitado de Python. Não mede compatibilidade
geral com CPython, tarefas inéditas, qualidade geral de programação ou ausência de
contaminação de treinamento. Sintaxe não suportada é uma falha separada; não é
descartada da contagem nem aprovada silenciosamente. Resultados anteriores mantêm
seu protocolo original e não são comparáveis diretamente com esta campanha.
O [contrato de linguagem](restricted-python-v2.md) também integra o prompt de cada
tarefa, para que as restrições sejam conhecidas antes da tentativa.

O código produzido pelo agente é dado para o interpretador restrito. Apenas os
testes e as sondas originais, verificados por impressão digital, executam no
avaliador confiável. Os cinco critérios são registrados separadamente: regressão
nos testes originais, funcionalidade nas sondas adicionais, integridade, escopo e
contrato estático de trabalho. A preservação dos auxiliares integra o critério de
escopo. Verificar a presença de testes escritos pelo agente não prova a
qualidade desses testes; essa dimensão continua não medida.

## Ambiente de execução

Use Ubuntu-24.04 no WSL, com fonte, trabalho e resultados ativos em ext4 no SSD C:.
O checkout em D: serve para edição e exportação; E: permanece arquivo frio. Use o
Python já existente em
`/home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python`.

No início de cada dia de execução, atualize primeiro o llama.cpp e os aplicativos
isolados usados como harnesses:

```sh
bash /mnt/d/Usuario/Downloads/LLM/local-llm-lab/scripts/00_update_runtime.sh
```

O atualizador consulta a versão estável mais recente, compila o llama.cpp em uma
pasta separada, preserva o runtime anterior e atualiza OpenCode, Pi, TrueForge e
Mistral Vibe. Registra versões e commit em `versions.lock` e em
`results/system-audit/runtime-updates/`. Ele executa uma vez por dia no fuso de
São Paulo; falha antes de qualquer teste se a atualização não terminar. Não
atualiza driver NVIDIA, CUDA, ferramentas de treino ou modelos.

No estado verificado em 2026-10-17, a campanha segura usa llama.cpp v0.7.0
(commit `620d2225cc436ab0b001e3200e590e3b286ef9ab`) e OpenCode 1.19.3. O
`npm audit` do TrueForge 0.179.2 encontrou oito alertas `high` e nenhum
`critical`; ele fica fora dos testes até revisão dos alertas. O experimento
ativo usa OpenCode.

Inicie cada comando de preparação ou teste com `scripts/daily-run.sh`; ele faz
essa verificação antes de executar o comando solicitado e pula a atualização se
já foi concluída no mesmo dia. Assim, chamadas diretas aos scripts de teste não
devem ser usadas para iniciar uma nova execução.

O pré-voo verifica os dois arquivos GGUF fixados, o conjunto local do llama.cpp,
o OpenCode instalado, portas, memória, armazenamento, GPU e isolamento. Não se
conecta a um servidor de modelos já aberto. Se uma condição não puder ser medida
ou um recurso estiver ocupado, a execução deve falhar antes de carregar o modelo.

O agente executa em namespaces Linux privados, com sistema de arquivos restrito,
runtime somente leitura e limites agregados de memória, swap, CPU, processos,
tempo, saída e armazenamento temporário. O acesso ao modelo passa por um broker
com destino e protocolo limitados. O controlador, o avaliador e os registros ficam
fora do espaço gravável do agente. Os testes de isolamento usam sentinelas
inofensivas e provedores simulados; não leem credenciais reais.

## Preparação sem inferência

No snapshot local final em ext4, execute a preparação pelo wrapper diário:

```sh
cd /home/foxtrot/local-llm-benchmark/repos/safe-model-campaign-20261017
bash /mnt/d/Usuario/Downloads/LLM/local-llm-lab/scripts/daily-run.sh /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m benchmark.safe_campaign --dry-run
bash /mnt/d/Usuario/Downloads/LLM/local-llm-lab/scripts/daily-run.sh /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m benchmark.safe_campaign --readiness --evidence-root /home/foxtrot/local-llm-benchmark/results/readiness-NOVO-ID
```

Use um diretório novo de evidências. Uma preparação válida exige todos os controles
obrigatórios aprovados para o mesmo resumo de entradas. Um rótulo `READY` isolado
em um arquivo não basta. Modificar fonte, testes, configurações ou protocolo exige
nova verificação. Consulte o relatório efetivo da última execução para conhecer o
estado atual; este procedimento não é um certificado permanente.

Os controles incluem as seis referências corretas, seis implementações sem
correção, seis mutantes, alterações indevidas de argumentos, callbacks e identidade
de funções, tentativa de fraude do executor, limites do avaliador, acesso negado
a arquivos e rede, encerramento de descendentes e uso real de ferramentas pelo
OpenCode contra um provedor simulado. A suíte do projeto e o linter também precisam
passar. Ausência de um verificador estático de tipos configurado deve ser registrada
como tal, sem fingir uma verificação equivalente.

## Triagem curta executada: Granite 4.2 8B

A comparação pareada terminou com 4/6 aprovações estritas para Granite 4.2 8B
Q4_K_M e 6/6 para o controle Qwen3.5-9B Q4_K_M. O código final passou no
avaliador em 6/6 nos dois modelos; a diferença estrita veio do fluxo de testes.
Foram três tarefas, duas
repetições por modelo, quatro sessões ABBA e aquecimentos excluídos; contexto 16K,
KV Q4_0, temperatura zero, seed 1234, limite de saída 1.024, OpenCode 1.19.3 e
llama.cpp v0.7.0. As duas falhas do Granite foram classificadas como falhas do
agente em `whitespace_normalization`: ele escreveu expectativas de teste erradas
e não completou a correção antes do limite de etapas. A chamada de testes estava
correta. Não há falhas de infraestrutura, protocolo ou recurso, e não se repetiu
a medição sem alterar as condições.

O resultado é uma triagem preliminar, não admissão final nem ranking preciso. O
relatório, com tempos por tarefa e caminhos para as evidências brutas, está em
[granite-4.2-8b-short-screen-20261017-r1](../results/reports/granite-4.2-8b-short-screen-20261017-r1.md).
O Gemma 4 12B QAT já possui campanha concluída; a procedência do arquivo local
continua sem correspondência com a revisão oficial pretendida, portanto seus
resultados não devem ser atribuídos a essa revisão upstream.

## Campanha pareada completa: Qwen 4B/9B

Depois de concluir a preparação e decidir iniciar a medição:

```sh
cd /home/foxtrot/local-llm-benchmark/repos/safe-model-campaign-20261017
bash /mnt/d/Usuario/Downloads/LLM/local-llm-lab/scripts/daily-run.sh /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m benchmark.safe_campaign --execute --output-root /home/foxtrot/local-llm-benchmark/results/safe-campaign-NOVO-ID
```

Esse comando carrega modelos e realiza inferência. Não faz parte da preparação.
O diretório precisa ser novo. Os caminhos históricos de execução de agentes foram
retirados da campanha suportada; não remova seus bloqueios para reaproveitar uma
linha de comando antiga. Experimentos de treinamento, cache, MTP e novos modelos
precisam de protocolos e liberações próprios.

A comparação repete duas vezes a ordem 4B, 9B, 9B, 4B em oito sessões, com seis
tarefas em ordem determinística derivada da seed e quatro repetições por par
modelo/tarefa: 48 linhas medidas. Cada sessão tem aquecimento excluído do
denominador. Contexto, geração,
orçamento de ferramentas e política do agente são fixados antes da execução.
Falhas de protocolo, linguagem, recursos, agente, avaliação e infraestrutura
permanecem distintas. Não elimine tentativas ruins, repita apenas as favoráveis ou
altere critérios depois de observar os resultados. Quatro repetições oferecem um
controle inicial, não uma estimativa precisa de diferenças pequenas.

## Evidências e interpretação

Preserve protocolo e hashes, prompts, saída nativa, chamadas e resultados de
ferramentas, transcrições limitadas do broker, estados do sandbox, resultado do
avaliador e amostras de recursos externas. Correlacione por execução, fase, agente,
evento e horário. Não trate fala do agente como evidência de que um comando passou.
O fluxo nativo registra os bytes recebidos do processo; ele não é uma atestação
independente de cada ação descrita. A sequência de ferramentas é uma observação
do harness, separada das verificações confiáveis de arquivos e comportamento.

As métricas globais de WSL/GPU incluem outros processos; não são consumo exclusivo
do agente. Amostras periódicas não capturam necessariamente todos os picos.
Latência até o primeiro byte HTTP não equivale a tempo até o primeiro token.
Tokens, cache, compaction e outros campos ausentes devem permanecer explicitamente
indisponíveis. Nunca preencha ausências com zero nem derive desempenho a partir
de um teste com resposta simulada.

Uma interrupção ou erro de infraestrutura exige preservar a evidência parcial e
confirmar o encerramento dos processos próprios. Não encerre processos de outros
experimentos. As verificações reduzem riscos concretos; não constituem prova de
segurança geral do sistema operacional ou do interpretador.
