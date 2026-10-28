# Ampliação da avaliação para outras famílias e pós-treinos — 2026-10-15

**Estado:** análise e proposta; nenhum modelo foi carregado, adquirido ou treinado nesta revisão.
**Fonte examinada:** `4577aeb921587feaee8518c656a32a64d593ea9c`, com documentação local da campanha v2 ainda não commitada.
**Pergunta:** a confiabilidade do avaliador e o funcionamento do sistema atual se mantêm com modelos diferentes? Quais experimentos permitem responder sem misturar integração, capacidade e efeito de pós-treino?

## 1. Conclusão e retorno ao objetivo original

Ainda não há demonstração de transferência para outras famílias no executor seguro atual. A campanha v2 contém dois tamanhos da mesma família Qwen, seis tarefas públicas e quatro repetições por modelo/tarefa. Cinco tarefas passaram em todas as repetições dos dois modelos; a normalização de whitespace distinguiu 4B (1/4) de 9B (4/4). São 48 medições, mas somente seis problemas distintos. Esses números não medem o ganho causado pelas correções do harness em comparação com versões antigas.

Há duas perguntas diferentes: se os controles/oráculos continuam corretos quando recebem formatos e estilos diferentes; e se cada novo modelo consegue concluir tarefas pelo sistema atual. A primeira requer positivos, negativos e replays seguros de dados. A segunda requer inferência controlada por família. Para afirmar que uma melhoria do harness beneficia várias famílias, será necessário um ensaio posterior que varie apenas essa melhoria entre duas configurações igualmente seguras.

O [roadmap inicial](../../docs/superpowers/plans/2026-10-12-methodology-revised-roadmap.md) já previa referências e mutantes antes dos modelos, seleção exploratória separada da confirmação, admissão de um candidato por vez e confirmação em **24 tarefas distintas** (seções Tarefas 4, 5 e 7). A [auditoria metodológica](../../results/reports/methodology-review-20261012.md) advertia que repetições de fixtures não representam diversidade de problemas. Portanto, ampliar a avaliação retoma o plano original; não exige começar outro laboratório.

| Objetivo original | O que existe agora | O que falta demonstrar |
| --- | --- | --- |
| Validadores, oráculos e isolamento verificáveis | Controles sintéticos, avaliação restrita e evidência preservada na liberação atual | Cobertura de respostas, templates e soluções válidas de outras famílias |
| Comparar qualidade e recursos | Campanha v2 concluída para 4B/9B | Diversidade de famílias e de tarefas, sem saturação dominante |
| Admitir um candidato por vez | Admissões históricas de Gemma e Granite | Nova admissão no caminho seguro; os launchers antigos foram aposentados |
| Avaliar cache, MTP e continuidade | Há experimentos históricos próprios | Transferência dos benefícios para cada configuração atualmente liberada |
| Avaliar routing e adaptação | Há propostas e evidência histórica limitada | Destinos validados, sinais disponíveis em produção e custo total de troca |

A fundamentação de governança e observabilidade segue útil, mas precisa resultar em critérios verificáveis: estado final do workspace, escopo, comportamento funcional, orçamento, registros e encerramento. Complexidade cognitiva, estilo e aparência de planejamento não substituem correção. Qualidade dos testes gerados continua não medida na v2; não deve ganhar uma nota implícita por presença de nomes. A distinção entre regressão e capacidade também está no [guia de avaliações de agentes da Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

### Releitura do relatório de fundamentação de 12/10

Também foram relidas as páginas 1–2, 15–20 e 27–28 de `D:/Usuario/Downloads/Relatório final — laboratório local de LLMs sob restrição de recursos.pdf`. Seu Pilar 4 já exigia templates nativos, respostas brutas e separação entre resultados do fornecedor e edição real; as prioridades incluíam Granite3B, Qwen4B/9B e só depois a matriz de modelos. Isso reforça a ordem proposta aqui. Algumas prescrições precisam conservar as correções da auditoria posterior:

- O r1d teve zero medições iniciadas após falhar o gate, e não 18 reprovações funcionais dos modelos.
- O literal `finish_reason=tool` da página 19 não é um contrato universal; o endpoint OpenAI-compatible normalmente sinaliza `tool_calls`. Validar o protocolo efetivamente usado, incluindo os formatos nativos antes da conversão.
- A ressalva da página 2 contra dataset sintético é excessiva. Dados sintéticos podem ser úteis quando verificados e separados da avaliação por tarefa/projeto/erro; o problema é vazamento ou saturação, não a origem sintética por si só.
- Os 50 prompts × duas temperaturas × cinco seeds por modelo e as 24 issues em quatro linguagens da página 19 constituem uma expansão grande. O executor atual só admite o subconjunto Python restrito: preservar a pergunta experimental, mas não transplantar essa matriz nem executar código de outras linguagens pelo grader atual.
- Chamar um resultado de “não inferior” exige margem e desenho estatístico definidos. Um pequeno smoke ou 100% em um conjunto finito não demonstram equivalência geral nem ausência de falhas de segurança.

## 2. O histórico impede tratar candidatos antigos como inéditos

O inventário abaixo verifica presença e tamanho dos arquivos, sem recalcular os hashes de vários GiB nesta revisão. Cada futura carga exige nova verificação criptográfica, recursos atuais e staging em ext4. Tamanho do GGUF não é pico de VRAM.

| Configuração | Situação local observada | Evidência e interpretação |
| --- | --- | --- |
| Qwen3.5-4B Q4_K_M | Ativo em ext4; 3.013.027.808 bytes | 21/24 na v2; controle pequeno |
| Qwen3.5-9B Q4_K_M | Ativo em ext4; 5.680.522.464 bytes | 24/24 na v2; controle contemporâneo para comparações novas |
| Granite 4.1 3B Q4_K_M | Arquivo em `E:/local-llm-models/`; 2.099.501.664 bytes | Primeira opção de outra família sem aquisição; não confundir com Granite 4.2 do PDF |
| Gemma 4 E4B QAT UD-Q4_K_XL | Arquivado em `E:/LocalLLMLabArchive/models/gemma-4-e4b/`; 4.215.695.776 bytes | Já teve 0/6 no protocolo antigo; QAT e quantização diferente integram a configuração |
| Granite 4.1 8B Q4_K_M | Arquivado em `E:/LocalLLMLabArchive/models/granite-4.1-8b/`; 5.347.914.400 bytes | Já teve 1/6 no protocolo antigo e diagnóstico de encaixe em 16K; não é validação do executor atual |
| Ornith 1.0 9B Q4_K_M | Arquivado em `E:/LocalLLMLabArchive/2026-10-11/ornith-pi-harness/`; 5.629.108.704 bytes | Variante Qwen com ensaios históricos; não acrescenta família independente |

Fontes locais: [registro de versões](../../versions.lock), [cadastro de modelos](../../config/models.yaml), [admissão Gemma](../../results/reports/model-admission-20261012.md), [admissão Granite 8B](../../results/reports/model-admission-granite-8b-20261012.md), [resultado v2](../../results/reports/campaign-v2-results-20261015.md).

Os documentos de pesquisa de 12/10 foram escritos antes de algumas admissões daquele mesmo dia. Seus rótulos “não instalado” são históricos. Rejeições antigas também não são uma reprovação permanente de toda uma família. Não combinar os 0/6 ou 1/6 antigos com as 48 linhas da v2 nem reclassificá-los retroativamente.

## 3. Leitura crítica da conversa anexada

Foi lida a transcrição de 38 páginas e foram renderizadas cinco páginas, com inspeção visual dos gráficos das páginas 5 e 16. Fonte: `D:/Usuario/Downloads/LLM/.codex-remote-attachments/01a136a1-8b74-7c43-84c6-f15e1db328f8/84153b33-5bbf-4c38-9cf7-9ab46396609a/1-Conversa_completa_LLMs_15-10-2026.pdf`. SHA-256: `d093ab3b018397b26c10df7b52789a0f7204160f0487e220ccc8c8ac98250b4d`.

| Ideia na conversa | Aproveitar | Correção necessária |
| --- | --- | --- |
| Capacidade por memória, parâmetros armazenados e ativos; pp. 2–13 | Selecionar candidatos por mais de uma dimensão | Peso em disco, RAM residente, VRAM e parâmetros ativos são medidas distintas. Encaixe exige observar o sistema completo, não uma conta de bits |
| Pareto com pesos Q4 e Intelligence Index; pp. 5 e 14 | Mapa exploratório para escolher o que investigar | A transcrição não demonstra que cada score foi medido naquele GGUF Q4, runtime, orçamento e contexto. O gráfico não constitui uma fronteira empírica de desempenho Q4 local |
| Quantizações do K2; pp. 10–16 | Há uma tabela primária de quantização que corresponde aos valores apresentados | O próprio cartão limita essa bateria GGUF a tarefas não agentic. Médias próximas não provam equivalência em ferramentas, agentes ou português |
| K2 exige fork; p. 12 | Conferir arquitetura do runtime antes da aquisição | O cartão atual já informa suporte mainline em `b11454`. A compatibilidade com nosso pin `d81235049…` ainda não foi demonstrada; não recomendar um fork automaticamente |
| mmap e execução “apenas em memória”; pp. 9–10 | Separar CPU, GPU e offload | mmap não fixa páginas nem garante ausência de swap ou I/O. Verificar paginação e swap observados; não confundir memória disponível com residência demonstrada |
| Modelo pequeno com ferramentas versus flagship; pp. 28–29 | Medir o sistema completo que resolve uma tarefa | Diferenças de ferramentas, retries e computação também fazem parte do tratamento. Não atribuir todo ganho aos pesos |
| Mesmo aluno, professores diferentes; pp. 29–38 | Comparação muito útil de checkpoints pós-treinados | Mesmo aluno não controla dados, tamanho do treino, mistura de professores, otimizador, template, quantização ou reasoning. O delta mede efeito do checkpoint/configuração, não efeito causal puro do professor |
| “Destilação real” exige logits; pp. 33–35 | Distinguir transferência por distribuições e por respostas | Destilação por sequências/respostas também é uma forma válida de destilação. Não é necessário extrair raciocínio privado para estudar comportamentos observáveis |
| Pequenos modelos de decisão como candidatos; pp. 29–30 | Podem interessar a um futuro componente de classificação | `yev0-4b` declara geração livre e julgamento de trajetórias de segurança fora de escopo. Não é substituto direto de um agente de código ou de um grader de segurança |
| 27B e GPUs de 24–32 GB; pp. 8, 23 e 31 | Horizonte futuro separado | Não é a próxima tranche da RTX 3070. Offload pode ser estudado em perfil próprio; não inferir impossibilidade geral a partir dos 8 GiB de VRAM |

Verificação documental atual: [K2 GGUF](https://huggingface.co/IFM/K2-Horizon-7B-GGUF), [cartão yev0](https://huggingface.co/choyiny/yev0-4b), [Jackrong 9B](https://huggingface.co/Jackrong/Qwen3.5-9B-Claude-4.6-Opus-Reasoning-Distilled). Este último declara dados adicionais do Qwen3.5-27B, reforçando que o nome do professor não define uma intervenção isolada. Não foram auditados individualmente todos os números de rankings proprietários do PDF; eles não são usados como pontuação do laboratório.

## 4. Ordem recomendada de modelos

| Ordem | Configuração a investigar | Pergunta respondida | Condição antes de executar |
| --- | --- | --- | --- |
| 1 | Granite 4.1 3B já arquivado, contra Qwen3.5-9B | O caminho seguro e seus oráculos funcionam com outra família e menor footprint? | Hash, template/parser, ferramentas e KV no runtime fixado |
| 2 | Gemma 4 E4B QAT já arquivado, contra o mesmo controle | A transferência também ocorre para uma segunda família e outra receita de quantização? | Nova admissão; preservar rejeição histórica e manter MTP desligado |
| Reserva local | Granite 4.1 8B ou Ornith 9B | Efeito de escala dentro de Granite ou de uma variante Qwen | Somente se houver pergunta adicional; não acrescentam ambas a mesma diversidade que uma nova família |
| Primeiro novo candidato | MiniCPM5-2B GGUF oficial | Um modelo menor orientado a uso de ferramentas oferece boa qualidade por recurso? | Confirmar tradução XML → `tool_calls` no runtime escolhido; download ainda não realizado |
| Pós-treino pareado | Qwen3.5-4B original versus Jackrong 4B Claude-distilled | O checkpoint pós-treinado melhora tarefas sob orçamento definido? | Mesmo tamanho e quantização comparáveis; template e raciocínio registrados. Começar em 4B reduz pressão de memória |
| Tranche CPU/reasoning | LFM2.5-2.6B | Qualidade/latência numa família híbrida e uso em CPU/PT-BR | Sempre pensa e usa formato nativo próprio de ferramentas; requer perfil de raciocínio compatível |
| Tranche de integração | K2 Horizon 3.7B; 7B depois se justificado | Nova arquitetura é útil neste sistema local? | Verificar suporte do runtime fixado e parser antes de considerar upgrade isolado |

Documentação primária consultada em 15/10/2026: [MiniCPM5-2B](https://huggingface.co/openbmb/MiniCPM5-2B), [GGUF oficial](https://huggingface.co/openbmb/MiniCPM5-2B-GGUF), [LFM2.5-2.6B](https://huggingface.co/LiquidAI/LFM2.5-2.6B), [Jackrong 4B](https://huggingface.co/Jackrong/Qwen3.5-4B-Claude-4.6-Opus-Reasoning-Distilled), [K2 3.7B GGUF](https://huggingface.co/IFM/K2-Horizon-3.7B-GGUF). São candidatos condicionais, não vencedores locais. As URLs `main` são mutáveis; revisão, licença, arquivo, hash e dependências terão de ser fixados na admissão.

MiniCPM recomenda parâmetros de geração diferentes dos nossos e um parser próprio; LFM injeta raciocínio no template. Aplicar cegamente `temperature=0`, `reasoning=off` e 1.024 tokens a todas as famílias não cria uma comparação universalmente neutra. Devemos separar: **perfil de política comum**, que pergunta quem atende às mesmas restrições do produto, e **perfil nativo**, que pergunta qual configuração admitida oferece melhor compromisso entre qualidade e custo. Se uma opção não existe numa família, registrar incompatibilidade com o perfil, sem inventar equivalência. Os dois perfis não serão somados num ranking único.

## 5. Mudanças mínimas necessárias no código

A expansão ainda não é uma edição de cadastro. [safe_campaign.py](../../benchmark/safe_campaign.py) fixa os dois Qwen e ABBA × 2 nas linhas 48–49; `_load_config` (linha 63) rejeita outro conjunto/ordem e exige o registro legado. [campaign_readiness.py](../../benchmark/campaign_readiness.py), `_model_bundle_audit` (linha 700), audita todos os modelos daquele registro. [model_quality_paired.py](../../benchmark/model_quality_paired.py), `build_profile` (linha 514) e `_server_command` (linha 721), também contêm escolhas específicas.

Proposta de implementação posterior, sem reativar os launchers aposentados:

1. Extrair um pequeno registro de identidades/perfis para o executor seguro, mantendo o perfil histórico reproduzível. Nome proposto: `benchmark/model_registry.py`; ainda não existe como resultado deste trabalho.
2. Permitir campanhas **pareadas** explícitas, com controle e candidato fixados. Manter ABBA e as validações; não construir agora um scheduler arbitrário para dezenas de modelos.
3. Fazer o pré-voo validar os modelos selecionados. Incluir no resumo de entradas seus manifests, template e parser efetivos, geração, runtime/bibliotecas e controles. Pesos continuam com hash próprio verificado antes da carga.
4. Usar esquema fechado de configuração. Não aceitar argumentos livres de shell, endpoints arbitrários, código remoto do cartão ou flags que desliguem barreiras como forma de “suportar” um modelo.
5. Acrescentar testes de modelo desconhecido, hash/template errado, resposta streaming fragmentada, argumentos exatos, `reasoning_content` separado de conteúdo, pseudochamada textual, contabilização de linhas interrompidas e cleanup. Conservar os testes das 48 medições/56 registros históricos em `tests/test_safe_campaign.py`.
6. Revalidar os vinte controles, testes relevantes, Ruff, compilação e sintaxe antes de nova liberação. Verificador de tipos ausente continua declarado como ausente. Uma nova seleção/configuração recebe identidade de campanha e digest próprios; mudança de tarefa/prompt/grader/cap/cache exige protocolo próprio.

Mantêm-se ext4 ativo no SSD, um servidor/modelo por vez, broker local limitado, avaliação restrita, negação de rede externa ao agente, orçamento, integridade e isolamento. O mínimo atual de 7.168 MiB livres não deve ser reduzido silenciosamente para admitir um candidato. Encaixe de contexto/KV precisa ser demonstrado, mesmo que o arquivo seja pequeno.

## 6. Experimentos em etapas

### E0 — Robustez do avaliador e dos adaptadores, sem modelos

Validar implementações equivalentes com estilos diferentes dentro do contrato Python restrito e mutantes semanticamente errados. Reproduzir formatos reais de transcrição como dados, sem executar código nativo produzido pelos candidatos. Distinguir defeito do grader de sintaxe fora do contrato. Aumentar o subconjunto de Python, se necessário, é outra mudança de protocolo e revisão de segurança.

**Saída:** referências passam, mutantes falham pelo motivo previsto, fixtures iniciais falham e não há feedback do oracle reservado ao modelo. Estas verificações estabelecem invariantes; não estabelecem taxa de acerto dos modelos.

### E1 — Admissão individual e observável

Verificar identidade/licença/arquivo, copiar um artefato por vez do arquivo E: para ext4 e comparar hashes. Validar runtime e template efetivos, modo de raciocínio, formato/parser de ferramentas, tool-result → continuação, streaming, limites e encerramento. Fazer diagnóstico curto antes do contexto-alvo de 16K; se só 8K for viável, controle e candidato precisam de uma série própria em 8K.

Não exigir que o candidato acerte as tarefas de código para ser admitido mecanicamente. Publicar todos os candidatos solicitados, admitidos e bloqueados, com motivo. Erro de transporte/parser é integração; não é automaticamente incapacidade do modelo. Falhas semânticas dentro de uma campanha admitida permanecem no denominador. Nunca repetir a admissão até esconder uma falha ou converter tentativa não iniciada em evidência de qualidade.

### E2 — Ponte entre famílias com as seis regressões atuais

Manter tarefas, prompts, grader e limites atuais, alterando somente os contratos necessários de modelo e integração. Primeiro par: Qwen9B × Granite3B. Segundo par: Qwen9B × Gemma E4B QAT. Usar um controle contemporâneo em cada par; as 24 linhas antigas do Qwen9B não substituem esse controle.

Por par: **6 tarefas × 2 modelos × 4 repetições = 48 medições**, oito sessões ABBA × 2 e oito aquecimentos excluídos. Duas comparações somam **96 medições e 16 aquecimentos**; executá-las sequencialmente, só depois de cada admissão. Registrar carga/encerramento e custos de preparação separados da tarefa, além do custo operacional total. O teto externo deve comportar 56 episódios de até 240 s e oito cargas de até 180 s: só esses máximos somam 248 min, antes das demais fases; congelar orçamento e política de interrupção antes de iniciar.

**Pergunta respondida:** estas configurações operam e passam as regressões no sistema atual? Não se trata ainda de generalização para programação inédita ou de prova causal da superioridade do novo harness. Sintaxe não suportada e falhas de contrato ficam visíveis. Interrupção de infraestrutura torna a campanha incompleta e não autoriza comparação de capacidade a partir de linhas não tentadas.

### E3 — Confirmação em tarefas distintas

Retomar as 24 tarefas distintas já previstas no plano inicial, para no máximo dois finalistas e uma tentativa por modelo/tarefa: **48 tentativas pareadas**. Reservar as tarefas e seus oráculos antes das respostas, com split separado do desenvolvimento e da admissão. Distribuir funções, módulos e classes de erro diferentes; 24 paráfrases de whitespace não bastam.

Começar dentro da linguagem já admitida: transformação de texto, valores-limite/configuração, coleções sem mutação indevida, validação/erros, transições locais limitadas e refatoração/API entre módulos. Essas são categorias propostas; as 24 fixtures, referências e mutantes ainda precisam ser construídos e revisados. Uma divisão possível em oito sessões é AB/BA/AB/BA, seis tarefas novas por par de sessões: cada tarefa aparece uma vez em cada modelo, em vez de repetir seis tarefas quatro vezes. Exige um scheduler de tarefas por bloco diferente do atual e outro protocolo.

O conjunto será **reservado do desenvolvimento do laboratório**, sem alegação de ausência de contaminação no pré-treino. Depois de usado para ajustar um candidato, passa a ser regressão e perde o papel confirmatório. Oráculos ficam fora do workspace e suas mensagens privadas não voltam ao agente como feedback.

### E4 — Pós-treino, causalidade e otimizações

O contraste original versus distilled estima `score(checkpoint_pós_treinado, perfil) − score(checkpoint_original, perfil)` nas tarefas pareadas. Para atribuir um efeito especificamente ao professor seria necessário controlar a receita de treinamento; isso não está identificado por checkpoints públicos distintos. Registrar também raciocínio disponível, truncamento, chamadas, reparos e custo total. Estilo “parecido com Claude” não é critério de sucesso funcional.

Para verificar uma melhoria do harness, definir H0/H1 igualmente seguros e variar uma única intervenção em cada família, com tarefas e orçamento pareados. Sem essa ablação, descrever somente o desempenho do sistema atual. Cache, MTP, quantizações alternativas, CPU/offload, roteamento e QLoRA continuam intervenções separadas; não executar o produto cartesiano modelo × quantização × harness × hardware × raciocínio.

## 7. Relato e critério de conclusão

Publicar identidade de configuração, status de admissão, tentativas planejadas/iniciadas, aquecimentos, sucesso estrito e cada um dos cinco critérios, falhas por categoria, truncamento, reparos e recursos. Distinguir conteúdo observado no broker de eventos declarados pelo agente. Amostragem global de GPU/RAM não é atribuição perfeita a um processo e pode perder picos; métricas indisponíveis não viram zero.

Comparar pares por tarefa, preservando as observações individuais. Repetições estimam instabilidade da tarefa; tarefas relacionadas continuam agrupadas. Não prometer p95, significância ou “100% confiável” a partir de poucos casos. Uma seleção exploratória precisa de confirmação nova; se os finalistas empatarem nas tarefas cobertas, declarar empate/inconclusão e considerar o custo observado.

Os gráficos novos deverão combinar **qualidade medida naquela configuração**, tempo total, pico amostrado e tamanho dos pesos, com contexto/quantização/perfil visíveis. Comparações CPU-only e GPU/offload ficam em coortes próprias. Não converter tokens/s de tokenizadores diferentes ou índices externos em uma unidade universal de eficiência. Energia por solução só entra se houver medição adequada do sistema e do tempo; potência GPU isolada não mede consumo total do PC.

**Próxima entrega executável recomendada:** tornar a admissão pareada segura independente dos nomes Qwen, acrescentar os controles de contrato e preparar Granite3B contra Qwen9B. A primeira nova aquisição sugerida é MiniCPM5-2B após comprovar o caminho de ferramentas; a primeira comparação de pós-treino sugerida é Qwen4B original versus Jackrong4B, em série própria. Esta revisão entrega fundamentação e sequência; não implementou esses adaptadores nem iniciou essas campanhas.

### Verificações desta análise

A proposta recebeu revisão independente de leitura sobre código, contagens, orçamento, separação de protocolos, causalidade e links locais, sem achado material. O revisor não repetiu a inspeção dos pesos, do PDF ou das fontes externas; essa revisão do plano não equivale a admissão nem a auditoria independente de novos resultados. A validação desta entrega documental inclui links locais existentes e ausência de whitespace final; nenhuma nova suíte de testes ou inferência foi executada.
