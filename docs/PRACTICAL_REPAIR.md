# Rodada corrigida — 22/10/2026

Entrada principal no Windows, a partir de qualquer pasta:

```powershell
& 'D:\Usuario\Downloads\LLM\.worktrees\practical-agent-v2\scripts\Start-LocalLLMRound.bat' --prepare
& 'D:\Usuario\Downloads\LLM\.worktrees\practical-agent-v2\scripts\Start-LocalLLMRound.bat' --execute
```

Sem argumento, somente verifica. `--execute` atualiza o ambiente uma vez no dia de São Paulo antes de criar uma campanha, executa os fluxos de integração sem GPU e então carrega os modelos. Repetir `--execute` retoma a mesma saída com versões congeladas. Ctrl+C interrompe a execução em primeiro plano; não há supervisor que repita falhas de infraestrutura indefinidamente.

Protocolo: `practical-agent-selection-7bplus-corrected-v3`.
Saída: `/home/foxtrot/local-llm-benchmark/results/practical-selection-7bplus-corrected-v3`.
Origem histórica somente leitura: `practical-selection-7bplus-v1`.

## Matriz

| Etapa | Tarefas | Modelos | Repetições | Episódios |
|---|---|---|---:|---:|
| Baseline corrigida | B2,C2,M1,M2,D2 | Cinco atuais | 3 | 75 |
| Cache ligado,16K | D2 | Dois finalistas recalculados | 3 | 6 |
| Contexto32K,cache vencedor | D2 | Mesma dupla | 3 | 6 |
| Confirmação,perfil escolhido | H2 | Mesma dupla | 3 | 6 |

Máximo93 episódios. Cada etapa é congelada quando seus finalistas/perfis estão conhecidos. B1,C1,D1 históricos são identificados como herdados; não são uma medição nova. A classificação da baseline mantém líder básico/médio mais alternativa difícil. Os perfis são comparados somente em D2. H2 não valida H1: a recomendação permanece limitada, sem proclamar vencedor definitivo com um único holdout. Não há novos pesos ou treinamento.

A atualização diária fornece versão exata do OpenCode e commit do llama.cpp; a campanha mede hashes de binários e bibliotecas e exige os mesmos valores na retomada. Os Bonsais continuam usando o Prism explicitamente identificado. Drivers e CUDA não são alterados pela rotina diária.

## Erros e revisão

O controle decodifica erros de `state.error`, saídas e envelopes MCP, incluindo strings JSON reais do OpenCode. As duas falhas intencionais de M2 são reconhecidas por ferramenta, argumentos e mensagem; cada uma é isenta uma única vez. Erros normais dos testes do programa não são falhas de transporte.

No sexto erro atribuível ao modelo, o episódio é interrompido e a tarefa fica suspensa para todos os modelos, perfis e repetições. Falhas de ferramenta desconhecidas ou de infraestrutura também pedem revisão, sem culpa do modelo. Problemas compartilhados do runtime interrompem a rodada sem repetir automaticamente a tarefa.

Registro persistente: `/home/foxtrot/local-llm-benchmark/results/task-review-registry.json`. Não apagar evidências. Depois da análise, marcar a entrada como `active:false` e preencher `review_reason`. A retomada libera os episódios pendentes somente se fontes, protocolo e versões ainda corresponderem ao contrato congelado. Se a correção alterar fontes, usar novo protocolo/saída; a execução antiga permanece histórica.

O monitor mostra `review_required`, episódios `skipped_review` e os motivos. Tarefas suspensas ficam excluídas da comparação para todos os modelos. Chamadas principais, título e compactação aparecem separadas como diagnóstico; os orçamentos20/30/45/60 contam POSTs ao modelo, não ferramentas.

## Validação

Antes de usar GPU, exigir os quatro fluxos reais de harness/MCP com modelo simulado: paginação, recuperação, JavaScript e continuidade, além dos controles do guard. Um marcador diário completo não comprova integração: ela é executada após atualizar e antes de criar a campanha. Cada perfil recebe ainda a verificação curta existente de carregamento e chamada real MCP, sem repetir uma tarefa inteira como aquecimento.

Resultados brutos anteriores e seus manifests não são regravados. Não interpretar pontuação composta como comparação homogênea dos pesos: runtimes, quantizações, compactação e versões fazem parte da configuração testada.
# Atualização limits-skills-v1

A entrada padrão do launcher prepara a nova política descrita em
[LIMITS_SKILLS.md](LIMITS_SKILLS.md), sem inferência. Os protocolos e resultados
abaixo são históricos e não devem ser retomados com as fontes atuais. Há modos
benchmark e operacional independentes; a fila nova fica preparada e parada.

