# Revisão crítica da metodologia e das recomendações — 12/10/2026

## Parecer

O laboratório possui uma base útil de reprodutibilidade: versões e hashes, dados brutos, testes independentes, limites de execução, preservação de falhas e armazenamento ativo no SSD. Entretanto, **os testes ainda não sustentam um ranking geral de modelos, um workhorse definitivo, vantagem multiagente ou uma política de roteamento comprovada**. Há defeitos nos validadores e no desenho de admissão que precisam ser corrigidos antes de ampliar a matriz.

Esta revisão é documentação e planejamento. Não modifica os anexos, os protocolos já executados nem suas notas históricas. Nenhuma nova inferência, instalação ou aquisição de pesos foi realizada nesta revisão. O [plano revisado](../../docs/superpowers/plans/2026-10-12-methodology-revised-roadmap.md) define mudanças prospectivas, com novas identidades de experimento.

## Fontes e alcance

- Relatório fornecido: `D:/Usuario/Downloads/Relatório final — laboratório local de LLMs sob restrição de recursos.md`, SHA-256 `5187c4c01e8c3e8fca3701a20a190029227c245364a1d141558f9362b73cc16e`.
- Chat fornecido: `Texto colado.txt`, SHA-256 `8c4a79c62636fa0aeab62c00ba66b3d5c5b79c0fe4cc8356f1f22599596f7ec7`.
- Código publicado: `6efc7a3dae050f7303a01d4bee9584df577da4a6`, branch `feat/audit-opencode-controlled-20261011`. PR35 aberto e três checks CodeQL aprovados na consulta desta revisão. Relatórios/publicação de resultados recentes ainda tinham alterações locais pendentes.
- Snapshot somente leitura da máquina nesta revisão: ext4 com 16.519.012.352 bytes livres (15,38 GiB), WSL com 7.944 MiB totais/7.445 MiB disponíveis e swap 0 de 4.096 MiB; nenhum `llama-server` ativo. Esses valores expiram e devem ser rechecados antes de execução.
- Reabertos: controlador 4B/9B, controlador MTP, smoke JSON/tool, sampler, grader, roteador, plano, relatórios e registros recentes. Resultados históricos foram confrontados com a [auditoria comparativa anterior](audit-continuation-20261011.md); não se afirma reexecução de todo o histórico.
- Revalidação no snapshot SSD do commit acima: **140 testes e 19 subtests passaram**; Ruff 0.15.17 passou em `model_quality_paired.py`, `mtp_paired_probe.py`, `quality_smoke.py` e `provenance.py`. Não há typechecker configurado. Testes verdes não eliminam lacunas sem regressões correspondentes.
- As referências centrais de avaliação, especulação e os candidatos foram consultados em fontes primárias. Esta revisão **não certifica individualmente todas as 133 referências** do relatório externo. As recomendações de aquisição dependem do registro específico de identidade/licença/tamanho, não do número de citações.

## Achados que mudam a decisão

| Prioridade | Achado e evidência | Consequência / correção proposta |
|---|---|---|
| Alta | `quality_smoke.py:124–140` pede `a=19,b=23`, mas aceita outros inteiros cuja soma seja 42. A resposta final passa por uma regex que também reconhece “not 42”. | O gate mede integração básica, não aderência semântica estrita. Exigir argumentos exatos e um contrato final determinístico em uma versão nova; criar regressões adversariais. |
| Alta | `model_quality_paired.py:173–176,557–565,685–701` exige que o modelo acerte um Edit específico para admitir toda a comparação. | Uma falha de comportamento é classificada como incompatibilidade e impede observar as tarefas seguintes. Separar funcionamento do ambiente/parser/handler de acerto do modelo. Manter r1d fechado; não reclassificar a falha como passe. |
| Alta | O relatório externo descreve “0/18 tentativas concluídas” e prioriza corrigir “a falha 0/18”. O bruto r1d tem **uma tentativa diagnóstica, zero medições iniciadas**. | Não houve 18 falhas nem estimativa de qualidade 0%. O 9B nem chegou ao diagnóstico. Registrar planejado/tentado/concluído/aprovado separadamente. |
| Alta | Read-before-edit com SHA é apresentado como correção geral do executor. Bash e Write também podem modificar arquivos; o shell autorizado não tem sandbox do sistema operacional. | Um guard de Edit não estabelece uma barreira global. Primeiro testar invariantes e cobertura dos caminhos de escrita; tratar o wrapper como intervenção de harness separada, com custo e resultado próprios. Não prometer sandbox ou holdout inacessível. |
| Média | `mtp_paired_probe.py:117–132` usa três pares em ordem off/on, on/off, off/on, com aquecimento apenas na primeira exposição, embora reinicie seis servidores. | Estado inicial varia entre blocos. Próxima série deve aquecer cada sessão nova, contrabalançar a ordem e registrar carga separada. A série atual permanece exploratória. |
| Média | `mtp_paired_probe.py:760–763` calcula taxa usando tokens/(parede−TTFT). | Chamar de taxa efetiva de streaming, não confundir com decode nativo do servidor. Publicar ambas, TTFT e latência total. A contagem inclui o primeiro token enquanto o denominador exclui sua latência. |
| Média | `resource_sampler.py:29–34,44–55` usa nomes `*_mb`, mas os valores são MiB; RAM é uso agregado do WSL e VRAM inclui desktop. | Corrigir rótulos prospectivamente e explicar dados antigos. Não chamar RAM agregada de RSS do processo, nem VRAM total de alocação exclusiva do modelo. Um sampler de 1 s também pode perder picos de requisições subsegundo. |
| Média | Probe usa `python`, mas o ambiente fornece `python3`. O modelo recuperou o comando antes de errar Edit. | Preflight deve confirmar o executável contratado e o prompt deve usar esse nome. Recuperação pode ser uma tarefa deliberada, mas não um erro acidental do controle. |
| Média | Diagnósticos MTP gravam `git_sha=null` e `source_tree_dirty=true` por defaults do filho. O wrapper externo perdeu o exit code. | Conservar esses registros e usar a proveniência externa verificável; próxima versão deve propagar HEAD/dirty corretos e capturar retorno sem ambiguidade. Artefatos completos não são prova de exit code 0 observado. |
| Média | Relatório MTP ainda contém uma transcrição incorreta do SHA completo do runtime. Dados de publicação MTP ainda não estão fechados. | Corrigir somente a documentação derivada, conferir contra `protocol.json`, gerar novos manifestos e arquivar antes de publicar a rodada. Não alterar JSONL medido. |

Código: [smoke](../../benchmark/quality_smoke.py), [controle pareado](../../benchmark/model_quality_paired.py), [MTP](../../benchmark/mtp_paired_probe.py), [sampler](../../benchmark/resource_sampler.py), [grader](../../benchmark/harness_eval.py), [roteador](../../router/rules.py).

### O que os registros recentes efetivamente dizem

**r1d:** o arquivo existia. O modelo tentou `python`, recebeu erro, usou `python3` e obteve 42; tentou Edit com `oldString="TASK"`, inexistente no conteúdo; leu o arquivo e depois usou Write, produzindo os bytes esperados. Isso é falha no workflow pedido com recuperação parcial, não ausência do fixture. Zero calibrações, zero aquecimentos, zero de 18 linhas medidas tentadas. [Relatório e evidências](model-quality-paired-20261012.md).

**MTP:** 12/12 requisições medidas concluídas e quatro aquecimentos, dois gates JSON/tool aprovados, 270 tokens propostos e 174 aceitos nos seis registros medidos com MTP (64,4%). Reabri os dois registros de ferramenta: ambos usaram exatamente 19 e 23, retornaram 42 e afirmaram a soma corretamente. Portanto, o defeito latente do smoke não foi observado nessas duas chamadas; ele continua precisando de correção.

Na função de divisão, os pares de parede off/on foram 0,4609/0,3429 s; 0,7570/0,4770 s; 0,7410/0,6547 s. Os deltas on−off foram −0,1180; −0,2800; −0,0863 s; mediana **−0,1180 s**. A diferença entre medianas dos braços (0,7410 versus 0,4770 s) é outra estatística. Ambos geraram 35 tokens, mas comprimento igual não prova IDs iguais nem correção funcional. No resumo, foram 54 versus 55 tokens: a latência de configuração pode ser descrita, porém não isola decode para saídas idênticas. Ainda não houve validação de comportamento de programação nem medição agentic de benefício. [Relatório MTP](mtp-paired-probe-r2-20261012-031553-14d31c9a.md).

## Revisão dos seis pilares do relatório externo

| Pilar | Aproveitar | Revisar ou adiar |
|---|---|---|
| Especulação | Acceptance não basta; separar prefill/decode/ferramenta; registrar template, counters e fallback. | Não executar 27 células × 20 pares por variante de saída/cache de uma vez. Aquecer cada sessão; usar contratos de qualidade. Os 512 MiB calculados são KV F16 de oito camadas do alvo; o draft de uma camada observado alocou **64 MiB**, separado dos **144 MiB** do KV Q4 do alvo. Alocação de KV não é pico total de VRAM. |
| Compactação | Manifesto, hashes, cobertura e preservação de permissões são pertinentes às falhas existentes. | Começar com estado mínimo e leitura sob demanda. Não construir simultaneamente AST, grafo, memdir e vários retrievers. Guarded Edit altera o harness; comparar em ablação própria. |
| Quantização/offload | Pesos ativos não são pesos armazenados; medir memória e runtime efetivos. | Tabelas bpw são aproximações, especialmente quantizações mistas. Peso maior que RAM WSL isoladamente não prova impossibilidade de uma divisão CPU/GPU; tampouco somar RAM+VRAM garante viabilidade. O orçamento de disco pode rejeitar o experimento independentemente. `/mnt/c` é SSD Windows, não o ext4 exigido para os controles. |
| Modelos | Verificar licença, revisão, arquivo, parser e template antes de medir. | Não classificar o 9B como superior por tamanho; não transformar avaliação do publisher em ranking local. Distinguir modelo-base, fine-tune, QAT, quantização e draft. |
| Roteamento | Um executor GPU, falha explícita, custos de carga e escalonamento completos. | T0 deve ser claramente lógica determinística ou um modelo, não ambos na mesma conta. Erro de transporte não justifica trocar de modelo. O roteador atual filtra capacidades declaradas; não demonstra qualidade de seleção. |
| QLoRA | Splits por schema/projeto/erro, retenção e comparação com base sem adapter. | Dados sintéticos verificados podem ser úteis; o problema é saturação/vazamento/falta de representatividade. Adiar treino até existir erro recorrente não resolvido pelo harness e conjunto não saturado. Variar um fator por vez; não iniciar a grade rank×LR×época×acumulação×otimizador. |

Outras correções concretas do relatório externo:

- O exemplo `event.search.count(file_before) == 1` está invertido: verificar busca não vazia e `file_before.count(event.search) == 1`; também conferir bytes atuais/hash, caminho e modo. Não executar o pseudocódigo como implementação pronta.
- No contrato OpenAI-compatible, o marcador usual de término de chamada é `tool_calls`, não o literal genérico `tool`. Validar o contrato real do endpoint fixado; eventos de harness têm outra estrutura.
- Tokens nativos como `<tools>` podem ser legítimos no **template interno** de uma família. O erro relevante é receber pseudochamada textual onde o contrato exige `message.tool_calls`. Não banir delimitadores de todos os dados de treinamento sem considerar o template nativo.
- Um teto absoluto de 7,2 GiB ou reserva de 20% não substitui a VRAM livre no instante de admissão e o pico medido do processo/configuração. Margens propostas são políticas experimentais, não garantias físicas.
- Barreiras de caminho no harness não restringem automaticamente comandos Bash arbitrários. Um futuro ambiente isolado precisa de teste próprio de cobertura e custo; hoje não se deve atribuir essa propriedade ao laboratório.

## Estatística e validade externa

O conjunto de três fixtures é útil para regressões, mas não representa o universo de programação. Repetir a mesma tarefa cinco vezes melhora a observação de instabilidade daquela tarefa; não cria cinco problemas independentes. Separar tarefas distintas, repetições, chamadas e casos do grader. Reportar estrito e funcional lado a lado sem apagar requisitos explícitos, como nomes de testes ou escopo.

Mesmo se 15 passes fossem ensaios independentes e representativos, 15/15 daria limite inferior unilateral exato de 95% de aproximadamente 81,9%, não confiabilidade demonstrada de 100%. Nos três fixtures repetidos, essa premissa nem se aplica a um ranking geral. Da mesma forma, 100 observações sem falha não provam ausência de falhas. Intervalos binomiais exigem hipóteses explícitas; para poucos erros a aproximação normal pode ser inadequada. [NIST](https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbici.htm).

Com três pares, apresentar todos os pares, mediana e faixa. Vinte pares não tornam p95 estável; não usar um quantil de cauda como gate decisivo sem planejar tamanho amostral e precisão. Para múltiplas tarefas, reamostrar por tarefa/cluster, preservando braços pareados. Comparações exploratórias de muitas configurações não devem selecionar um vencedor e apresentar seu intervalo como confirmatório; congelar o escolhido e testar em holdout separado.

A distinção entre avaliações de capacidade e regressão, e entre resultados do ambiente e traços do agente, está alinhada ao [guia de avaliações da Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents). Isso apoia ampliar as tarefas com perguntas definidas, não executar a matriz cartesiana inteira.

## Revisão do chat: recomendações úteis, força excessiva

1. **Qwen3.5-4B como primeira opção provisória é defensável** pelo footprint e pelas tarefas já observadas. “Workhorse permanente ideal” e “metade da GPU livre” excedem a evidência: desktop, contexto, runtime e carga mudam a margem.
2. **Pi padrão e OpenCode como escalonamento ainda são hipóteses.** Os números de 1.709 tokens/19,92 s citados vêm do controle 9B em uma tarefa. O 4B tem resultados próprios (OpenCode 15/15, Pi 11/15, Vibe 9/15) e não autoriza transportar a latência do 9B para o 4B. Falhas de workflow também são falhas do produto quando o usuário exige esse workflow.
3. **9B é um candidato de escalonamento**, não um destino comprovadamente mais competente. Falta o pareamento em tarefas com espaço para diferença de qualidade e o custo de troca do servidor.
4. **Granite e Gemma QAT merecem a lista de admissão**, mas não executar todos os customs e quantizações. Tamanhos atualizados, datas e revisões estão na [verificação de modelos](../../research/reviews/model-claims-audit-20261012.md).
5. **Qwen3.8-27B extremo/offload fica adiado**, por custo de armazenamento, integração e ausência de uma necessidade demonstrada. Não alegar impossibilidade matemática de qualquer quantização a partir do tamanho BF16; também não inferir qualidade útil de um relato que apenas carrega.
6. **Ornith não foi descartado como capacidade geral.** A tarefa pequena passou e foi mais lenta; isso só descarta vantagem naquele caso. Testar novamente faz sentido apenas com uma tarefa nova que possa revelar sua especialização.

## Decisão de sequência

Fechar a evidência pendente → corrigir validadores e classificação de falhas → congelar uma pequena suíte discriminante → comparar 4B/9B → medir cache e, se justificado, MTP em tarefa completa → admitir um candidato → continuidade/roteamento → adaptação. O plano detalhado contém contratos, arquivos, regressões, denominadores, limites e critérios de saída. O laboratório segue incompleto; esta revisão torna explícito o que precisa mudar antes de ampliar conclusões.
