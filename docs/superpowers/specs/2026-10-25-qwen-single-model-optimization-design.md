# Otimização de um único modelo local — Qwen3.5-9B

Estado: escopo ampliado pelo usuário em 25/10/2026: comparar todos os harnesses
históricos, inclusive excluídos, e atualizar ambientes/bibliotecas/plugins antes
de começar os testes. Atualização isolada autorizada; nova inferência aguarda a
conclusão das atualizações e dos gates de compatibilidade. Referência: America/Sao_Paulo.

## Intenção

Otimizar um agente completo para a máquina do usuário, usando somente o Qwen3.5-9B
local como modelo gerador. A meta é maximizar correção e conclusão, admitindo mais
tempo/contexto. Passar em todas as tarefas de desenvolvimento é uma meta de ajuste;
a confirmação exige problemas novos, critérios fixos e registro de todas as falhas.
Não é possível garantir antecipadamente que um modelo resolverá qualquer tarefa.

A unidade otimizada é o stack (modelo + runtime + parâmetros + ferramentas +
workflow + memória), não a capacidade isolada dos pesos. Serão publicados sucesso
na primeira tentativa, sucesso assistido dentro do orçamento, custo total e tipo
de assistência. Não haverá promoção silenciosa de uma falha antiga a sucesso.

## Escolha do modelo e escopo

Modelo escolhido pelo agente: Qwen3.5-9B Q4_K_M, arquivo já instalado,
5.680.522.464 bytes, SHA-256
`03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`.
É a melhor opção geral provisória pelo equilíbrio entre cobertura e custo; o
Bonsai 27B tem sinais melhores em alguns problemas difíceis, mas não será usado
como modelo auxiliar nesta otimização de um só modelo.

O trabalho inclui corrigir falhas confirmadas do harness, tornar os parâmetros
efetivos auditáveis, ampliar capacidade dentro do hardware, adaptar ferramentas
e comparar integrações. Não inclui trocar GPU, mexer em clocks/drivers, interromper
aplicações do usuário, reiniciar WSL nem baixar outra quantização automaticamente.

## Máquina observada e envelope

- Ryzen 5 5600X: 6 núcleos/12 threads; WSL expõe 8 processadores lógicos.
- RAM física: 31,92 GiB; na inspeção havia 3,72 GiB disponíveis no Windows.
- WSL Ubuntu-24.04: cap 8 GB, swap 4 GB; 7,8 GiB visíveis e 38 GiB livres em ext4.
- RTX 3070: 8.192 MiB; na inspeção 6.621 MiB usados e 1.397 MiB livres, com jogo
  e outras aplicações. Não há capacidade para carregar o modelo agora preservando
  o piso existente de 7.000 MiB livres. Não fechar processos automaticamente.
- O GGUF declara Qwen35 híbrido: 32 blocos, full attention a cada quatro blocos,
  contexto nativo 262.144, 4 heads KV de dimensão 256. O template real contém
  chamadas de ferramenta e chave `enable_thinking`.

262K é capacidade declarada do modelo, não um tamanho já validado nesta GPU.
O limite prático depende dos pesos residentes, KV, estados recorrentes, buffers
de computação, ferramentas e uso do Windows. Capacidade será medida, não presumida.
Modificar o cap WSL para uma sessão dedicada poderá ser uma opção posterior,
dependendo de pressão de memória medida e autorização para reiniciar WSL.

## Base atual e causas já demonstradas

O perfil medido usa contexto 16.384, saída 4.096, KV K/V Q4_0, temperatura 0,2,
top_p 0,95, um slot, batch 512/ubatch 256 e `--reasoning off`. O help do binário
congelado confirma que esse flag desabilita pensamento, separadamente de
`--reasoning-format`. Não se deve dizer que o perfil atual só oculta pensamentos.
Um log Qwen registrou 4 threads; não há ajuste explícito de threads nesse launcher.

O broker atualmente não admite `top_k`, `repeat_penalty` nem kwargs arbitrários de
template. Há tetos 4K no broker, no perfil OpenCode e nos limites do modelo. Alterar
apenas a interface não ampliaria o orçamento real e pode resultar em rejeição.
`skill`, subtarefas e perguntas estão negados. A integração de plugins exige um
perfil novo, compatível com os nomes de ferramenta que o Qwen efetivamente recebe.

Três reparos anteriores à GPU continuam obrigatórios: ranking/recomendação devem
consumir a vista qualificada de avaliação; término/cleanup devem ter precedência
também no ramo de importação do candidato; recusas de comandos compostos precisam
de atribuição baseada em evidência. Não afrouxar proteções para fazer um teste passar.

## Abordagens

1. **Evolução incremental do OpenCode existente — recomendada e assumida enquanto
   não houver outra preferência.** Reusa isolamento, transcripts e oráculos;
   mede separadamente parâmetros, workflow e compressão. Menor mudança inicial.
2. **Comparação OpenCode/Qwen Code antes de escolher.** Qwen Code é um harness
   oficial da família e admite endpoints locais OpenAI-compatible. É um braço
   válido, mas implica mapear permissões, testes e integrações novamente.

O usuário substituiu essa preferência por uma comparação ampla desde o início.
O catálogo histórico inclui Pi, OpenCode, Codex, Claude Code, Hermes, Mistral Vibe,
TrueForge e DeepSeek Harness. Qwen Code será incluído; Aider/OpenHands recebem
screening como harnesses citados na metodologia, sem alegação de medição anterior.
Todos começam por versões atuais isoladas e os mesmos GGUF, endpoint e limites
efetivos. Depois da comparação nativa entram os braços de plugins otimizados.

## Parâmetros candidatos — não são ótimos já medidos

| Perfil | Contexto total | Saída máxima | KV candidato | Pensamento |
|---|---:|---:|---|---|
| Controle reproduzível | 16K | 4K | Q4_0 | off |
| Precisão | 32K | 8K–16K | F16, se couber; Q8_0 comparador | on/off explícito |
| Qualidade principal | 64K | 16K, depois 32K se justificado | Q8_0, se couber | on |
| Horizonte longo | 128K | 16K–32K | Q8_0 ou Q4_0 conforme capacidade/qualidade | on |

O total inclui entrada, schemas, histórico e geração reservada. Nunca declarar
64K de entrada utilizável mais 32K de saída dentro de um contexto total de 64K.
Com thinking habilitado, sondar orçamentos internos de pensamento de 4K/8K dentro
do teto total de geração, preservando espaço para código e chamadas de ferramenta.
Uma cadeia que consome toda a saída pensando não conta como ganho de qualidade.
O suporte real a reasoning_content, tags e tool calls será testado no caminho
Qwen → llama.cpp → broker → SDK → OpenCode. Guardar a evidência bruta sem reinjetar
automaticamente raciocínios antigos; validar a política de histórico do template.
Sondar 16/32/64/128K; manter somente configurações que carreguem, não paginem
excessivamente e passem testes de continuidade/recuperação, além do caso curto.
Não usar YaRN apenas para aumentar o número anunciado.

Presets de geração a comparar:
- Controle com parâmetros efetivos completos, inclusive defaults hoje implícitos.
- Thinking/código preciso oficial: T=0,6, top_p=0,95, top_k=20, min_p=0,
  presence_penalty=0, repetição=1.
- Non-thinking geral oficial: T=0,7, top_p=0,8, top_k=20, min_p=0,
  presence_penalty=1,5, repetição=1.

O cartão oficial contém duas recomendações divergentes para non-thinking/reasoning;
esse preset ambíguo não será copiado como verdade única. Presets são comparações
de pacote; alegar causalidade de uma opção exige isolá-la num braço próprio.
O mapeamento de nomes das penalidades será confirmado no servidor/API local,
não assumido a partir dos nomes usados por transformers/vLLM.

Também serão sondados cache de prompt, threads 4/6/8 e batch/ubatch viáveis.
Primeiro fixar correção e memória; depois otimizar throughput/TTFT. Cache de
execução de prompts não é cache semântico de respostas: o segundo fica desligado
nas medições, evitando reutilizar soluções entre tentativas.

Orçamento operacional inicial proposto para tarefas difíceis: até 120 gerações
principais, 8 compactações, 1 título e 20 metadados, com prazo absoluto de 30 min.
É um teto experimental amplo, não alvo de consumo nem recomendação já calibrada.
Todas as classes e tentativas serão contadas, incluindo revisões/subagentes.
Repetição sem progresso, falta de espaço, OOM e erro não atribuído continuam tendo
encerramento finito e evidência. A regra atual de revisão após erros comprovados
não será alterada de forma implícita para obter aprovação.

## Ferramentas e workflow

Fluxo proposto: compreender contrato → plano curto → editar por conteúdo atual →
testes visíveis e regressão → revisão → entrega. Uma etapa determinística confere
as entregas obrigatórias antes de permitir o encerramento; a fala do modelo não
comprova aprovação. O verificador oculto permanece inacessível ao agente.

Ferramentas genéricas úteis: edição com validação sintática e hash do arquivo,
test runner com retorno estruturado, navegação de código, checkpoints e paginação
com cursores/IDs auditados. Temporários ficam sob `/workspace/.tmp` e os arquivos
protegidos continuam protegidos. Helpers podem reduzir trabalho mecânico, mas
não conter respostas, fixtures privadas ou regras específicas para decorar o
benchmark. Toda assistência integra o resultado do stack e seu custo.

Subtarefas/revisores, se usados, continuam no mesmo Qwen9B, com sessões separadas
e execução sequencial; um slot de GPU. Revisão pelo mesmo modelo não é evidência
independente. Uma política limitada de reparo pode integrar um episódio novo,
com teto explícito; publicar primeira tentativa e resultado assistido, sem apagar
tentativas fracassadas nem repetir records antigos até obter um acerto.

## Superpowers

Candidato: release 7.0.1; pesquisa observou commit
`2ce8aa15d05bd57213e6f746f953aafb7ded7a8b`. A documentação distingue plugin V1
e V2 e informa precedência diferente de skills no V1. O OpenCode congelado é
1.19.4; compatibilidade exata será testada com modelo simulado antes da GPU.

Começar com skills de testes, debugging e verificação; registrar o pacote e a
licença de adaptações. A documentação do plugin mapeia algumas operações para
`apply_patch`, mas o inventário Qwen observado tem `write`/`edit`; o bootstrap
precisa refletir o inventário real. Não editar a instalação global do Codex.

Haverá modos distintos de uso humano e campanha: tarefas ambíguas podem exigir
pergunta em uso normal; tarefas completas de avaliação têm seu escopo autorizado
previamente. Não injetar um workflow que pare inevitavelmente pedindo aprovação
ou invoque subtarefas indisponíveis no teste automatizado.

## Headroom

Projeto pesquisado: `headroomlabs-ai/headroom`, metadata de pacote 0.41.0;
commit observado `3fef15d376d9899f77a28464e2e91f8b99514930` (24/10) inclui correção
de egress de importações em modo offline. Não assumir que um release publicado
contém esse commit; fixar versão/ref e qualificar seu comportamento local.

Primeiro braço: integração host-side pelo modo biblioteca/compressão estrutural
conservadora, com encaminhamento um-para-um. Código editável, critérios, schemas,
call IDs, cursores, versões, recibos e valores funcionais críticos não serão
descartados. Comparar economia real de tokens e qualidade, não porcentagem de
compressão publicitária. Headroom não substitui a capacidade de raciocínio.

Segundo braço opcional: CCR com originais recuperáveis. Testar recuperação exata
e isolamento por tentativa antes de habilitar memória. Não permitir re-driving
automático de chamadas LLM que burle o contador de gerações; ou ele fica desligado,
ou todo egress é medido no gateway autoritativo posterior ao proxy.

O `wrap` oficial muda provider/modelo/configuração e pode escolher upstream de
nuvem por padrão. Portanto não executá-lo cegamente no perfil pessoal: endpoint
e alias Qwen locais serão explícitos, configuração isolada por experimento,
sem modelo remoto ou fallback. Beacon/update/telemetria externa e dependências
que buscam dados no import serão desabilitados e testados. O tráfego efetivo
antes/depois da compressão será preservado.

Não ativar `learn --apply`, memória entre episódios, compressão AST de código,
Serena, embeddings ou compressor com pesos auxiliares automaticamente. Cada
recurso só entra com hipótese de ganho, footprint e prova de compatibilidade.
As melhorias locais poderão ser úteis no uso diário, mas memória de avaliações
conhecidas nunca entra na confirmação reservada.

## Método de otimização e encerramento

1. Reproduzir a base atual e reparar a fundação em CPU, com hashes novos.
2. Sondar capacidade e parâmetros efetivos sem mudar o arquivo do modelo.
3. Triagem limitada de perfis em tarefas de desenvolvimento Python/JS/MCP e
   continuação. Máximo de oito perfis de parâmetros; falhas são preservadas.
4. Comparar baseline, Superpowers, Headroom e combinação nos mesmos casos/seeds,
   com os parâmetros escolhidos. Só promover braços que melhorem qualidade ou
   custo sem regressões materiais. Qwen Code é comparação adicional se escolhida.
5. Congelar o melhor stack e avaliar em pelo menos seis tarefas novas com duas
   seeds, reservadas antes do tuning. Não corrigir o stack durante essa medição.

Critérios: validade da execução; artefato correto; fluxo completo; regressão
autoral quando exigida; respeito a permissões; uso/custo de todas as gerações;
qualidade após contexto longo; latência, memória e encerramento limpo.
Passar no desenvolvimento não encerra o projeto se falhar a confirmação. Nesse
caso, registrar limitação e decidir novo ciclo separado, sem enfraquecer testes.

Todos os novos perfis usam protocolo, saída e manifesto próprios. As coleções
seladas e os resultados anteriores continuam preservados. Não retomar v9 antigo
com fontes novas. O trabalho termina com perfil operacional, launcher, rollback,
manifesto de dependências e relatório da confirmação, incluindo falhas/reviews.

## Fontes primárias consultadas

- [Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B): presets por modo,
  contexto nativo, seleção de pensamento e cuidado com histórico de raciocínio.
- [Superpowers / OpenCode](https://github.com/obra/superpowers/blob/2ce8aa15d05bd57213e6f746f953aafb7ded7a8b/docs/README.opencode.md).
- [Headroom / OpenCode](https://github.com/headroomlabs-ai/headroom/blob/main/docs/content/docs/opencode.mdx).
- [Headroom architecture](https://docs.headroomlabs.ai/docs/architecture) e
  [proxy](https://docs.headroomlabs.ai/docs/proxy): modos, encaminhamento, CCR e offline.
- [Headroom offline fix observado](https://github.com/headroomlabs-ai/headroom/commit/3fef15d376d9899f77a28464e2e91f8b99514930).
- [Qwen Code providers](https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/model-providers.md).
- Fontes locais: GGUF real, help do llama-server congelado, logs v9,
  `benchmark/model_broker.py`, `practical_runtime_v2.py`, `practical_policy.py` e
  pareceres `model-selection-decision-20261024` / `model-profiles-20261025`.
