# Correções após a auditoria e próxima avaliação — desenho

## Objetivo e base

Tornar o resultado verificável, impedir sucesso sem avaliação concluída e separar
correção funcional, conclusão do fluxo, qualidade dos testes e limites de execução.
Base: `results/reports/full-result-audit-20261023/README.md` e `summary.json`.

A auditoria cobre 600 trajetórias v2 e quatro v1. Há 46 flags funcionais positivas
históricas sem sustentação (34 B2, nove C1, três M1), um negativo histórico sem
artefato avaliável e uma desconexão cuja causa não está estabelecida. Na visão
composta atual há 25 funcionais e 20 aprovações mecânicas; uma destas tem teste
próprio fraco. Esses números são pareceres derivados, não substitutos dos logs.

## Restrições confirmadas

- Preservar manifests, records, snapshots, broker e avaliações anteriores.
- Não promover falhas reais dos modelos nem repetir tentativas para obter sucesso.
- Manter os cinco modelos atuais; Qwen 4B fica fora, sem download.
- Todos os subagentes devem ser Luna Max; ownership explícito, sem reverter outros.
- Monitor automático continua cancelado. Planejamento não inicia inferência.
- Não atualizar sistema, OpenCode, modelos, drivers, CUDA ou clocks.
- Não alterar entradas durante medição. Novo contrato, fonte, grader ou limite
  exige protocolo/saída novos; regrades são avaliações adicionais versionadas.
- Piso de capacidade permanece 7.000 MiB de VRAM e 8 GiB livres no WSL.
- Usar dependências já instaladas e o runtime congelado, validado antes de executar.

## Decisões de engenharia propostas

### 1. Contrato de término do avaliador

Manter os testes existentes e acrescentar um coletor de conclusão confiável,
sem reescrever o benchmark inteiro. Status zero sozinho deixa de aprovar.
O veredito exige relatório de conclusão válido, checks esperados efetivamente
executados, zero falhas e encerramento limpo. Saída comum do candidato não é
autoridade para contagens ou término.

Python: launcher/coletor confiável NÃO importa o candidato. Ele inicia um worker
filho isolado que carrega os checks sem executar o footer `unittest.main`, trata
`SystemExit` durante import/execução e executa a suíte via `unittest`. O coletor
sobrevive a `os._exit(0)` no worker; stdout/stderr do filho são dados, separados
do canal de eventos de teste, e não relatórios de conclusão. Ausência de eventos
completos do filho é inválida mesmo com status zero. `_grader_result` continua no
supervisor externo e também exige esse relatório final. Node: reporter confiável
no processo pai do test runner coleta eventos reais, ignorando eventos de
stdout/stderr como prova de teste; manter isolamento por processo. Ambos são montados
somente leitura e entram na proveniência. A API do reporter será fixada por teste
de contrato no Node instalado antes da implementação do adaptador.

Os mutantes `SystemExit(0)`, `os._exit(0)`, `process.exit(0)`, import quebrado,
saída imitando relatório, zero testes e execução parcial devem ser recusados.
Relatório ausente sem causa provada é execução inválida, não `passed` nem
automaticamente erro de raciocínio. O coletor correlaciona uma execução; ele não
constitui prova criptográfica contra uma biblioteca deliberadamente hostil.
Se os testes de falsificação quebrarem o isolamento do coletor, a liberação fica
bloqueada até separar o código candidato do processo de julgamento.

### 2. Classificação e pontuação

Centralizar a elegibilidade usada por ranking, resumos e exportações. Campos novos
de esquema devem distinguir:

- `functional_correct`: observação sobre o artefato, `null` quando não avaliado;
- `execution_valid`: cadeia de execução/evidência válida;
- `workflow_complete`: entregas e testes executados conforme contrato;
- `authored_test_quality`: `regression_detected`, `weak`, `unverified` ou
  `not_applicable`;
- `verified_success`: execução elegível, função e fluxo corretos e qualidade
  verificada ou não aplicável. Não derivar este campo de `correct && autonomous`.

Em execução inválida, limpar as flags usadas pela ordenação e manter a observação
funcional em seu campo próprio. `infrastructure`, contrato inválido, captura
ausente, sinal externo não explicado e transporte não resolvido não viram falha
funcional do modelo por fallback. Erro de ferramenta atribuído ao modelo exige
operação, regra e evidência correspondentes. Mensagem genérica sozinha não basta.

Orçamento e contexto limitados são resultados delimitados por política, não prova
de incapacidade intrínseca. Os limites atuais ficam constantes nesta correção.
Corrigir o caso observado de retries automáticos após esgotar compactação:
quota duradoura da medição deve produzir erro local tipado não retentável, não
um 429 tratado como falha temporária. Main, wall e compactação esgotados encerram
a fase preservando testes/snapshot e o motivo de orçamento; o driver não deve
aguardar sete rejeições para finalizar. Não emprestar saldo de outra categoria,
nem matar o cgroup inteiro antes de exportar o artefato. O comportamento exato do
OpenCode congelado deve ser confirmado em integração simulada.
Essa mudança de semântica usa versão de política nova (`limits-skills-v2`),
mantendo os tetos numéricos atuais; parsers de evidência histórica continuam
reconhecendo a política v1. A primeira causa terminal não é sobrescrita por
timeouts ou rejeições posteriores.

### 3. Retomada operacional

Expor `--retry-blocked` no replay oficial, com padrão falso e autorização limitada
a episódios bloqueados por infraestrutura. Falhas concluídas continuam imutáveis.
Registrar causa, identidades e backup sob lock; encerrar a autorização depois da
tentativa e arquivar o erro antigo quando resolvido. Nunca editar a seção imutável.

Antes de carregar modelo, esperar capacidade por no máximo 120 segundos, com
amostras a cada dois segundos e três amostras consecutivas acima do piso. Essa
espera pertence à preparação e é registrada separadamente do orçamento do modelo.
Ao expirar, bloquear com zero geração, sem loop de inferência nem fechamento de
aplicativos do usuário. É um guard de inicialização, não um monitor agendado.

### 4. Contratos de tarefas

Corrigir oráculos para requisitos existentes: B2 aceita IDs positivos válidos
como 100, 101 e valores acima de 2³¹; C1 aceita itens escalares e rejeita cursor
ausente/inválido; M1 exige substituição por array vazio. Formatação B2 deve aceitar
indentação equivalente de dois/quatro espaços ou tabs, sem igualdade textual
com um formato arbitrário. Número de linha não fica preso a um único idioma.

C2: o fallback efetivo de `page_size` continua 2 e será anunciado no schema;
omissão continua semanticamente válida. Tornar explícita no próximo contrato a
regra de não repetir write confirmado; tentativas rejeitadas antes do sucesso
continuam permitidas. D2 exige exatamente uma chamada bem-sucedida por conta
alterada, como já escrito. M2 mantém exatamente suas recuperações prescritas.
O contrato C2 estrito terá ID `mcp-no-confirmed-replay-v1`; no histórico sem essa
regra explícita, repetição confirmada é diagnóstico de fluxo, não nova reprovação
funcional automática. A próxima agenda pontuada não contém C2.

### 5. M1 independente é contrato novo

Criar `m1-independent-copy-v1`: objetos plain e arrays do retorno não compartilham
referências com defaults ou overrides, inclusive objetos dentro de arrays.
Preservar `undefined` e os valores falsey; verificar mutação nos dois sentidos.
Não ampliar a tarefa para ciclos, Date, Map, Set ou outras classes nesta rodada.

Manter um perfil histórico para reavaliar M1 antigo: merge, não mutação durante
a chamada e arrays de override, incluindo o caso vazio. Não aplicar o requisito
novo de cópia independente aos 65 snapshots históricos como score retroativo.
IDs: `historical-v2` e `m1-independent-copy-v1`. O default de regrade é seleção
pelo contrato explícito do record; quando ausente em legado conhecido, usa o
perfil histórico compatível. Um override incompatível só pode produzir avaliação
de sensibilidade, nunca veredito principal. Perfil e contrato são selecionados por metadados/hashes conhecidos; contrato
desconhecido exige revisão, não adivinhação pelo nome da tarefa.

### 6. Testes próprios

Adicionar diagnóstico de regressão: os testes submetidos devem passar no candidato
e detectar o bug original em uma cópia isolada do seed. Falha de import/setup ou
infraestrutura não comprova cobertura de regressão. Qualidade não verificada fica
distinta de qualidade fraca. Publicar os critérios antes da próxima medição.
Os resultados mecânicos antigos continuam disponíveis, sem renomeação silenciosa.

### 7. Fonte MCP fora da visão do agente

Não tentar esconder fixtures com regex de comandos, chmod ou bytecode. Para as
tarefas MCP, iniciar o servidor confiável fora do namespace do candidato e expor
somente um proxy stdio JSON-RPC sem fixtures. Reutilizar o padrão de socketpair e
framing do sandbox, em um canal dedicado ao MCP, separado do broker do modelo.

O proxy só encaminha initialize/notifications e tools/list/tools/call. O host
registra requests, responses e estado final por episódio. O agente não recebe
o fonte nem o arquivo privado de estado. Grading confronta o journal confiável,
os eventos públicos e o artefato. Falha do canal ou cleanup é infraestrutura.
M1 sem MCP não inicializa esse serviço. Nenhuma conexão externa é adicionada.

## Publicação e próxima medição

Primeiro corrigir, revisar e validar só em CPU/sandbox. Reavaliar as 600 trajetórias
v2 com perfis históricos, gerando nova coleção derivada; reaproveitar as quatro
avaliações v1 apenas se hashes de fonte e evidência forem os mesmos. Atualizar
tabelas de cobertura e elegibilidade sem misturar protocolos ou contar aliases.

B2/C1 e as correções de grading/classificação podem ser comprovadas sobre os
artefatos existentes: não precisam de nova inferência para resgatar resultados.
A primeira nova campanha pontuada proposta é **somente M1 independente**:
cinco modelos × três repetições = 15 episódios, seeds 101/202/303, baseline 16K,
cache off, budgets atuais. Usar protocolo proposto
`practical-agent-limits-skills-v9-m1-independent` e nova saída com o mesmo nome.
M1 novo não é continuação comparável da pontuação histórica da tarefa antiga.
A campanha v9 usa explicitamente `limits-skills-v2`: versão no manifesto e em
cada episódio, com M1 main=45, title=1, compaction=3, metadata=10, wall=480s e
reserva de testes=25s. Resume recusa qualquer divergência. Sondas de
compatibilidade (no máximo uma por modelo/perfil) e warmups do contrato existente
são registrados separadamente dos 15 episódios; não entram em score nem podem
rodar em `--prepare`.

O estudo de limites fica separado e não inicia automaticamente: se autorizado,
quatro episódios exploratórios B2 (Qwen 9B e Bonsai 27B, uma repetição cada,
compactação 2 versus 4), mantendo main=20, title=1, metadata=10, total=180s e
reserva=25s. Não usar esse estudo como ranking ou para elevar limites de M1 sem
evidência própria. Alterações posteriores de limites exigem outro protocolo.
Os dois braços têm saídas/protocolos distintos e duas identidades cada; não usar
o multiplicador global atual, que também mudaria main e prazo. O suporte a esse
estudo é opcional e não bloqueia a preparação da campanha M1 com limites atuais.

## Critérios de liberação

- Referências corretas passam e todos os mutantes confirmados são recusados.
- Grader sem conclusão não aprova; infraestrutura nunca entra na ordenação.
- Histórico de M1 continua histórico e novo perfil exige cópia independente.
- Retry não duplica concluídos nem ignora quarentena; espera de capacidade termina.
- MCP funciona sem fonte/estado privado acessível no namespace do agente.
- Lint, compilação, testes relevantes e integrações WSL reais passam; integrações
  OpenCode rodam isoladas de outra bateria pesada, sem GPU.
- Proveniência inclui coletores, proxy, contrato, limites e fonte de cada avaliação.
- `--prepare` permanece sem inferência; execução nova depende de comando explícito.

As escolhas de implementação acima são propostas de engenharia apoiadas na
auditoria. Não representam alterações já executadas nem novos critérios aceitos
retroativamente pelas campanhas antigas.
