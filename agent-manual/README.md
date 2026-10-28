# Manual comum — limits-skills-v1

Pacote portátil no formato Agent Skills. O texto canônico é o mesmo para todos os
modelos; o adaptador só muda a serialização e a forma de carregamento. O laboratório
injeta CORE.md e até três módulos selecionados por tarefa, evitando turnos extras
de descoberta. Referências ficam em disco. Nenhuma configuração pessoal é instalada.

## Aplicação e permissões

CORE.md é o contrato mínimo. Os módulos não substituem TASK.md nem os schemas.
Permissões são impostas pelo sandbox e pelo adaptador, nunca por promessas do
modelo ou pelo campo experimental allowed-tools de um SKILL.md. Runtime, manual,
grader e arquivos de política ficam fora da área gravável do candidato. O agente
não pode editar TASK.md, testes existentes ou configuração .opencode.

| Situação | Procedimento | Encerramento |
|---|---|---|
| Edição sem correspondência | Ler região atual e corrigir o patch | Mesmo erro repetido: falha do episódio |
| Página MCP | Usar cursor exato até null | Repetição sem avanço: interromper |
| Versão obsoleta | Ler estado atual, manter chave | Não inventar nova transação |
| Resultado de mutação incerto | Conciliar estado/recibo; replay só se idempotente | Origem incerta pede revisão |
| Teste do programa falha | Corrigir código conforme evidência | Não confundir com transporte |
| Transporte indisponível | Retry de leitura transitória limitado | Revisão de infraestrutura |
| Contexto compactado | Revalidar checkpoint e TASK.md | Não repetir efeito já confirmado |
| Orçamento termina | Preservar artefatos e motivo | Não provar incapacidade intrínseca |

## Benchmark e uso operacional

O benchmark fixa limites iguais por classe de tarefa. O perfil operacional permite
duas extensões de 50%, até 2x, apenas mediante progresso de ferramentas observado
pelo runtime; uma afirmação textual do modelo não é progresso. O total de tempo,
tokens e tentativas permanece registrado. Nenhum retry esconde o resultado inicial.

Os detectores procuram chamadas idênticas e ciclos curtos entre turnos. Uma nova
alteração verificável permite reler ou testar de novo. Polling não é implicitamente
permitido nos exercícios locais: integrações que realmente precisam dele devem
declarar intervalo, prazo e estado observável em uma nova política. As exceções de
M2 são específicas da sequência da tarefa, ferramenta, argumentos e erro.

## Integração portátil

1. Mantenha CORE.md e skills/ como pacote somente leitura.
2. Selecione os módulos adequados pelo tipo de tarefa, não pelo nome do modelo.
3. Injete o mesmo conteúdo canônico com o template nativo do modelo.
4. Aplique permissões reais e confirme round-trip de ferramenta e persistência.
5. Preserve hashes da política, manual, módulos, template, pesos e runtime.
6. Avalie ganho por tarefa com/sem módulos; não pressuponha que mais texto ajuda.

O pacote não fornece respostas dos graders nem instala dependências. Exemplos
devem usar identificadores e dados genéricos. Não incorporar automaticamente skills
geradas por um modelo ou provenientes de uma fonte externa.

## Referências e limites de interpretação

- Agent Skills: https://agentskills.io/specification
- DeepInfer, geração separada de avaliação e cobertura: https://github.com/deepseek-ai/DeepInfer/blob/main/eval/README.md
- DeepInfer, determinismo/batch e hardware SM100/Ascend 950 (não RTX3070): https://github.com/deepseek-ai/DeepInfer
- DeepSeek, estado de reasoning é específico do adaptador: https://api-docs.deepseek.com/guides/thinking_mode/
- Inspect, limites independentes: https://inspect.aisi.org.uk/reference/inspect_eval.html
- mini-SWE-agent, limites e erros consecutivos: https://mini-swe-agent.com/latest/reference/agents/default/
- Harbor, retries por exceção: https://github.com/laude-institute/harbor/blob/main/src/harbor/models/job/config.py
- tau2-bench, estado final em vez de trajetória única: https://github.com/sierra-research/tau2-bench/blob/main/docs/evaluation.md
- SkillsBench v4: https://arxiv.org/html/2602.12670v4
- Avaliação de AGENTS.md v3: https://arxiv.org/html/2602.11988v3
- Ruído de infraestrutura: https://www.anthropic.com/research/infrastructure-noise

Essas fontes motivam o desenho; os números locais de limites são escolhas iniciais
de engenharia e precisam de calibração. Seed fixa não garante igualdade bit a bit
entre runtimes, quantizações, kernels ou modelos. O manual reduz ambiguidade; ele
não garante ausência de alucinações. Artefatos e efeitos precisam de verificação.
