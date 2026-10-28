# Limites, manual e avaliação — limits-skills-v1

## Recuperação v8

O launcher passa `--recover-from` à tentativa v7 e usa a saída separada
`practical-agent-limits-skills-v8-recovery`. A cadeia preserva a origem v5 com 42
concluídos; v6 e v7 pararam sem concluir novos episódios. A seleção contém somente B2 r3 de
Qwen 9B, Bonsai 27B e Bonsai 9B: um episódio em revisão e dois pulados. As 42
execuções concluídas, inclusive falhas reais dos modelos, não são repetidas. O
manifesto registra hashes dos registros e manifesto de origem; protocolos alheios
na origem são recusados. Não tratar a recuperação parcial como novo benchmark
homogêneo de 45 episódios nem somar sucessos de versões diferentes sem ressalva.

A política v8 analisa lexicalmente a primeira operação do comando e reconhece
escritas literais comprovadamente proibidas fora de `/workspace`, incluindo
`mkdir`, cópia de testes e redirecionamento heredoc. Recusas ambíguas continuam
sob revisão. A agenda selecionada tem ordem determinística registrada no manifesto. O driver usa
locale POSIX disponível com UTF-8 explícito para Python, eliminando avisos de
locale que intercalavam stderr/stdout e alteravam a comparação de repetições. O avaliador
B2 passou a testar ids fracionários, registros não-objeto, associação correta da
linha e saída multilinha. Não houve alteração do prompt nem dos critérios M1.
O arquivo `results/reports/review-all-v6.json` contém inventário e 74 pareceres
adicionais sobre snapshots salvos, sem sobrescrever pontuações originais.

O monitor mostra o avanço da recuperação como 0–3 episódios, não 0–45. A campanha
v5 continua disponível como histórico. Os comandos antigos abaixo descrevem a
matriz completa; o launcher padrão agora prepara/executa a recuperação selecionada.

A versão 2 corrigiu o prazo operacional no supervisor, débito de rejeições locais,
contagem de chamadas encaminhadas, recuperação por fase, hashes do oráculo e
exportações interrompidas. A campanha parou com três ferramentas do modelo
classificadas como não atribuídas. Evidência bruta confirmou erros do modelo:
tentativas de escrever testes protegidos e um cursor MCP com aspas extras. A versão
3 os classifica no episódio, sem suspender a tarefa compartilhada. A campanha v3
revelou mais dois erros de modelo: nome de ferramenta inventado e tentativa de
leitura fora de `/workspace`, ambos bloqueados pelo sandbox. A versão 5 os
classifica no episódio com verificações específicas de ferramenta, mensagem e
caminho. Saídas v1–v4 e registros ficam preservados; v5 usa nova saída.

## Estado e comandos

O launcher sem argumento ou com `--prepare` não inicia inferência. A automação
de acompanhamento foi cancelada a pedido do usuário em 23/10/2026; a recuperação
direta autorizada continua independente dela.

```powershell
& 'D:\Usuario\Downloads\LLM\.worktrees\practical-agent-v2\scripts\Start-LocalLLMRound.bat' --prepare
& 'D:\Usuario\Downloads\LLM\.worktrees\practical-agent-v2\scripts\Start-LocalLLMRound.bat' --operational-prepare
```

`--execute` e `--operational-execute` são entradas explícitas de inferência. A
recuperação foi iniciada após autorização e validação; os testes de engenharia
usaram respostas simuladas. Não há atualização
diária ou instalação automática nesse novo launcher. As versões da fonte congelada
precisam corresponder ao runtime presente. Mudanças exigem protocolo/saída próprios.

Saída do launcher: `/home/foxtrot/local-llm-benchmark/results/practical-agent-limits-skills-v8-recovery`.
A matriz completa de referência contém B2, C2 e M1, cinco modelos e três repetições
(45 episódios); somente três pendências dessa matriz estão na recuperação atual.
O modo operacional, a condição core-only e os multiplicadores de calibração usam
identificadores de protocolo e saídas distintos.

## Orçamentos independentes

| Classe | Principal | Título | Compactação | Prazo total |
|---|---:|---:|---:|---:|
| Básica | 20 | 1 | 2 | 180 s |
| Cotidiana | 30 | 1 | 2 | 300 s |
| Média | 45 | 1 | 3 | 480 s |
| Difícil | 60 | 1 | 4 | 720 s |

Esses valores são um controle inicial local, não um padrão universal nem limites
já calibrados para capacidade. Título e compactação não consomem a coluna principal.
Metadados têm dez requisições independentes. Tentativas e admissões ficam separadas;
a requisição recusada não é uma geração realizada. O teto de saída por geração é
4096 tokens. Ausência de usage permanece indisponível, nunca vira zero.

O relógio do broker é compartilhado entre requisições. No modo operacional, cada
extensão exige uma nova mudança de arquivo registrada pelo plugin de runtime ou
uma página/versão/recibo novo observado na resposta real de MCP; o
modelo não pode conceder orçamento por afirmar que progrediu. Existem duas extensões
de 50%, até 2x, também limitadas pelo prazo absoluto do driver. MCP tem timeout local
de 10 s, shell de 60 s; o driver acompanha início/fim das ferramentas e interrompe
uma ferramenta estagnada. Verificações e snapshot compartilham o prazo da tarefa.

O perfil gerado para OpenCode 1.19.4 usa somente o plugin local, sem dependências npm.
`--pure` não é usado: a versão desabilita plugins externos com esse parâmetro.
Plugins padrão, configuração de projeto e skills externas ficam desabilitados.
O teste de integração confirma que o plugin foi carregado e bloqueou a repetição;
inspeção de config sozinha não estabelece isso.

## Erros e progresso

Chamadas equivalentes são comparadas por nome, argumentos normalizados, resultado
e estado dos arquivos. Descrição e timeout de shell não mudam sua semântica. A
terceira chamada idêntica sem progresso é bloqueada antes do efeito. Ciclos curtos
de duas/três chamadas também são reconhecidos entre turnos. Releitura/teste após
alteração real é permitido. Não existe polling ilimitado implícito neste perfil.

Seis erros atribuídos acumulados encerram o episódio, não a tarefa para outros
modelos. Falhas desconhecidas, de contrato ou infraestrutura exigem revisão. A
liberação antiga de M1 foi uma migração explícita após conferir as seis entradas
brutas idênticas, com backup do registro e relatório; não foi um apagamento do erro
nem declaração de que o Qwen passou. O launcher não libera registros por conta própria.

Resultados distinguem correção funcional, autonomia e causa de encerramento:
`budget_exhausted`, `model_no_progress`, `model_tool_error`, `contract_error`,
`tool_timeout` e infraestrutura. Um teto atingido não prova incapacidade intrínseca.
Antes da atribuição, a integridade callID/result é verificada nos requests salvos.

## Evidência e métricas

`native.jsonl`, `broker/` e snapshots são evidência. `execution.json` registra o
contrato e resultado da execução; `evaluations/<hash-do-grader>/<id>.json` contém
pareceres derivados, hashes das fontes e data. Regrade adiciona um parecer e preserva
trajetória e pontuação original; não inicia modelo. Índices de resumo podem ser
recalculados, mas os pareceres identificados não são sobrescritos.

Cobertura exige igualdade exata entre identidades planejadas e concluídas, sem
duplicatas ou episódios inesperados. Falha de probe é fatal para a execução, incluindo
Bonsais fora de um catálogo legado. Não publicar classificação geral com cobertura
incompleta. Relatar denominadores, falhas de infraestrutura e métricas condicionais
separadamente; três tarefas não sustentam uma conclusão geral sobre programação.
Repetições de uma tarefa não são tarefas independentes. Média de sucesso e sucesso
em todas as repetições são métricas diferentes; best-of-three não é Pass@1.

## Manual e experimentos

O pacote em `agent-manual/` mantém um núcleo e até três módulos selecionados por
tarefa, idênticos para todos os modelos. O modo `--skills off` mantém o núcleo e
retira módulos; não retira regras de segurança. O texto não contém soluções ocultas.
TASK.md, testes existentes e configuração .opencode são protegidos por mounts
somente leitura, inclusive contra tentativas via shell. A política não depende
do modelo obedecer às instruções. Schemas MCP descrevem campos reais, têm validação
de saída e structuredContent. Relatórios finais equivalentes podem corrigir uma
submissão anterior; sequências únicas só são exigidas quando pertencem à tarefa.

`benchmark/configs/limits-skills-experiments-v1.json` prepara as condições de
calibração, ablação de skills e diagnóstico de precisão/cache. Elas não foram
executadas com GPU. A CLI aceita `--budget-multiplier 1|2|4` somente em benchmark;
o multiplicador altera principal e tempo, preservando o teto de compactação da classe.
Não combinar multiplicador com extensões operacionais.

## Prontidão e limites

- `engineering_ready`: verificações CPU aprovadas e fontes/ativos atuais íntegros.
- `execution_capacity_ready`: capacidade livre agora; sua ausência permite preparar
  a fila parada, mas bloqueia `--execute`. A admissão repete o teste antes de cada carga.
- `comparison_ready=false`: resultados reais de inferência/cobertura ainda pendentes.
- `inference_smoke_pending=true`: modelos não foram carregados nesta implementação.

A evidência CPU é invalidada se qualquer fonte relevante ou manual mudar. Seed fixa
não garante bitwise determinism entre kernels, modelos ou runtimes. Adaptações de
reasoning, template, KV, cache e especulação são contratos próprios. O DeepInfer
consultado exige SM100/Ascend 950; não foi instalado na RTX3070. Sua separação de
geração/avaliação e controle de cobertura foram usados como referências metodológicas.

## Contratos de tarefa e M1 independente

Os contratos de tarefa têm ids estáveis. `historical-v2` preserva o perfil efetivo
das bases históricas; `m1-independent-copy-v1` é o novo perfil M1: cada objeto plain
e cada array do retorno é uma cópia independente de defaults e de overrides em
qualquer profundidade, inclusive objetos dentro de arrays; propriedades novas vivem
só na cópia; mutar o resultado não altera entradas e mutar as entradas após a
chamada não altera o retorno; undefined mantém o default e os valores falsey
sobrevivem; round-trip JSON não é cópia geral porque perde undefined; ciclos,
Date, Map, Set e classes especiais ficam fora do escopo desta rodada. O TASK.md do
perfil novo traz o enunciado explícito publicado antes de medir; o oráculo estrito
é um suplemento com ids de caso estáveis, e as duas referências independentes mais
os dois mutantes do perfil novo rodam no mesmo runtime de aceitação.

Regrade resolve o contrato pelo id explícito do record; legado sem id usa um
mapa auditado de hashes do record, evidências e manifesto. Prefixo de protocolo
não comprova origem; ausência ou divergência nesse mapa exige revisão, sem
adivinhar pelo nome da tarefa. Override incompatível só produz avaliação de
sensibilidade (`verdict_profile: sensitivity`, `correct: null`, nunca veredito
principal); os contratos do record e do regrade ficam registrados no parecer
append-only com hashes dos graders. Os 65 snapshots antigos de M1 continuam
mensuráveis apenas como sensibilidade separada, sem reprovação retroativa e sem
novo score principal. O manual e este documento mudam com a publicação; hashes de
manual e de fontes mudam junto, e a evidência CPU correspondente é revalidada
antes da próxima medição.

## Testes próprios e sucesso verificado

A qualidade dos testes submetidos é medida por corrida separada, além das
contagens mecânicas de presença. Em uma cópia temporária do snapshot da fase,
as fontes originais do seed são restauradas e os testes ficam exatamente como
submetidos; a mesma suíte então roda no mesmo sandbox limitado em que o
avaliador autoral rodou no candidato. O `input` original do episódio nunca é
tocado; o parecer append-only guarda o hash do snapshot e um hash por arquivo
restaurado.

Vocabulário: `regression_detected` exige que a suíte submetida tenha passado no
candidato e falhado, com evidência por teste do runner (`not ok` em TAP, ou
linhas `FAIL:`/`ERROR:` do unittest), no seed restaurado. `weak` marca suítes
que também passam no bug original — o caso Gemma M1 r3: presença de testes sem
prova de que detectam a regressão. `not_applicable` marca linguagem MCP sem
suíte autoral e envios sem testes além do baseline. `unverified` cobre
infraestrutura, timeout, snapshot ausente ou inseguro, falha de import/setup
(inclusive `_FailedTest` contado pelo unittest), suíte do candidato que não passou, e falha do
seed sem evidência por teste — nenhum desses casos comprova cobertura de
regressão. O diagnóstico detecta a regressão semeada nomeada na tarefa; não
prova cobertura total, e o número de assertions que falham no seed não é
ranking de qualidade. O agregado por episódio é conservador: uma fase não
verificada limita o episódio a `unverified`; valores fora do vocabulário
também.

`verified_success` é métrica nova, distinta dos resultados mecânicos antigos
(sem renomeação silenciosa): exige execução elegível, veredito funcional
observado, fluxo autônomo, e qualidade verificada (`regression_detected` ou
`not_applicable`). Linhas sem campo de qualidade (registros antigos, caminhos
de infraestrutura) ficam sem valor — nunca falsificadas. Agregados de resumo
só afirmam taxa verificada em células em que todas as observações mediram
qualidade; taxas parciais não existem nesses totais. Os critérios acima
estão publicados no manual `code-and-tests` antes da próxima medição.

## Preparação M1 v9 e fronteira de julgamento

A próxima agenda é `practical-agent-limits-skills-v9-m1-independent`: somente
M1, cinco modelos congelados, seeds 101/202/303, quinze episódios pontuados,
baseline 16K e cache desativado. O contrato é `m1-independent-copy-v1` e a
política `limits-skills-v2`: main 45, title 1, compaction 3, metadata 10,
480 segundos e reserva final de 25 segundos. Sondas de compatibilidade (até
cinco, uma por modelo/perfil) e warmups pertencem à preparação de execução,
ficam fora dos quinze episódios e não rodam com `--prepare`. Sondas aprovadas
são reaproveitadas no mesmo manifesto congelado. A tarefa nova não herda
completions históricos. B2/C1 corrigidos são reavaliados em CPU, sem nova inferência.

O avaliador confiável não importa código do candidato em seu processo.
Python e JavaScript executam o candidato em outro processo e trocam apenas
dados, preservando referências e mutações para testar o contrato. Landlock ABI
4 ou superior e restrições de inspeção de processos/rede são obrigatórios;
ausência desse isolamento reprova a preparação. Eventos de aprovação e saída
do runner só são aceitos do processo confiável. Encerramento abrupto, saída
forjada ou resposta inválida do candidato nunca aprovam um teste não executado.

Reavaliações com snapshot ausente, fases incompletas ou avaliador inválido
recebem `correct: null`, revisão e inelegibilidade. Isso preserva a distinção
entre erro do modelo e impossibilidade de avaliar. Execuções com causa
desconhecida/configuração inválida também não pontuam. Qualidade de testes
autoriais é um diagnóstico contra o seed conhecido, não uma prova de cobertura.

O pretty-print de B2 conserva a verificação histórica de saída multiline.
Indentação estrutural completa permanece diagnóstico: uma quebra de linha
sozinha não comprova boa formatação, e o score não afirma essa propriedade.
Não se impõe retroativamente dois espaços, quatro espaços ou tabs.

A calibração B2 do arquivo de experimentos é apenas proposta separada:
Qwen 9B/Bonsai 27B × compactação 2/4, quatro episódios, um protocolo/saída por
braço e demais tetos fixos. Não usar multiplicador global nesse estudo,
nem executar ou elevar tetos até obter aprovação. O BAT continua em preparo
por padrão; nenhuma automação ou inferência acompanha a entrega de engenharia.

O BAT com `--execute` ativa `--continue-model-blocks`: falha de probe ou
bloqueio de um episódio interrompe somente aquele modelo na passagem atual.
Os demais modelos são tentados uma vez, com seus próprios controles de
capacidade e limpeza; o manifesto conserva `model_blocks` com causa e identidade.
Concluídos não se repetem, erros reais do modelo permanecem concluídos e
quarentenas/contratos inválidos nunca são ignorados. Um servidor órfão impede
novas cargas, mas cada modelo restante recebe o diagnóstico do bloqueio.
Não há loop infinito: nova tentativa de episódio bloqueado exige
`--retry-blocked` e preserva as tentativas anteriores. Bloqueios globais de
admissão, integridade ou runtime inválido encerram a execução antes de qualquer
carga. Para retomada manual robusta após corrigir infraestrutura, usar
`scripts\Start-LocalLLMRound.bat --execute --retry-blocked`.
