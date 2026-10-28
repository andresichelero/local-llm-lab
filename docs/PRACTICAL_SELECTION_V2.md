# Seleção prática v2

Implementação do plano aprovado em 18/10/2026 para escolher um agente principal
e uma alternativa para tarefas difíceis na RTX 3070 de 8 GB. O protocolo v1
as campanhas v2-r1 e v2-r2 permanecem como histórico. O protocolo v2-r2 corrigiu
o nome da ferramenta MCP no pré-voo; o v2-r3 também registra a falta de chamada
como diagnóstico de capacidade, sem excluir o modelo das tarefas. Protocolos
diferentes não são combinados na mesma nota.

## Uso

No WSL, a partir deste worktree:

```bash
bash scripts/run-practical-selection-v2.sh --validate-only
bash scripts/run-practical-selection-v2.sh
```

O segundo comando inicia ou retoma a campanha. O diretório padrão de resultados
fica no SSD do WSL:
`/home/foxtrot/local-llm-benchmark/results/practical-selection-v2-r3`.
Uma campanha nova passa primeiro pela atualização diária. A validação isolada
e a reavaliação de resultados preservados não executam atualizações. Uma retomada mantém
as versões congeladas no manifesto e recusa alterações incompatíveis.
O piso padrão de VRAM é 7168 MiB. Uma exceção autorizada pode reduzi-lo até
7000 MiB com `--gpu-free-floor-mib 7000`; o valor é congelado no manifesto e
deve ser fornecido novamente ao retomar.
Se um episódio parar após duas falhas de infraestrutura, corrija a causa e use
`bash scripts/run-practical-selection-v2.sh --retry-blocked`. Esse pedido explícito
libera mais uma tentativa e uma repetição por infraestrutura, preservando tempos,
evidências e tarefas concluídas. Falhas de qualidade não são repetidas por essa opção.

## Trabalho medido

Oito tarefas, três repetições e cinco modelos produzem 120 episódios iniciais.
Há duas tarefas por dificuldade, com limites de 3, 5, 8 e 12 minutos e de
20, 30, 45 e 60 chamadas ao modelo. Python e JavaScript são executados de fato;
TypeScript com checagem de tipos não faz parte desta rodada.

Modelos: Qwen3.5-4B, Qwen3.5-9B, Ornith 9B, Granite 4.2 8B e Gemma 12B QAT local.
O Gemma é identificado pelo hash do arquivo, sem atribuição de origem não verificada.

Baseline: contexto 16K, saída de até 4096 tokens, temperatura 0,2, top_p 0,95,
seeds 101/202/303, KV Q4_0 e cache de prompt desligado. A compactação reserva
6144 tokens. As tentativas começam em conversas e workspaces limpos.

O agente recebe ferramentas locais e MCP real, com dados fictícios. Os testes
de aceitação só ficam disponíveis depois da entrega em outro isolamento.
Os testes escritos pelo agente também são executados e têm resultado próprio.

## Escolha e ajustes

O principal é escolhido pelas tarefas básicas a médias: mais conclusões corretas
e autônomas, depois mais tarefas 3/3, menor tempo total incluindo falhas e menor
pico de VRAM. Uma alternativa deve superar o principal nas difíceis.

Nos dois finalistas, até 24 episódios medem cache de prompt e contexto de 32K.
Outros 12 episódios usam duas tarefas inéditas para confirmação. Comparação,
ajuste e confirmação aparecem separadamente; notas de perfis diferentes não
são somadas como se fossem a mesma configuração.

Falhas do resultado, fluxo, tempo, contexto, configuração e infraestrutura são
distintas. Uma correção do avaliador pode aproveitar snapshots preservados;
uma resposta incorreta do modelo não é transformada em acerto.

O teto principal é de 14 horas e o teto incluindo ajustes e confirmação é de
21h12, além de carregamentos e verificações. São limites, não previsões.

## Verificação

A validação usa as duas soluções de referência por tarefa, erros plausíveis,
testes do agendamento/retomada/classificação e integração real com OpenCode,
MCP, CPython e Node, usando uma API de modelo simulada antes de ocupar a GPU.
O registro de execução do plano contém a evidência final dos testes e da revisão.
