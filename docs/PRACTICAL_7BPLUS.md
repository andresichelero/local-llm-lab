# Fila de inferência — modelos a partir de 7B

Autorizada em 20/10/2026. O usuário confirmou Bonsai 9B + 27B. Qwen4B e Granite saíram da fila; seus resultados históricos e arquivos permanecem preservados.

| Ordem inicial | Modelo | Pesos | Runtime |
| --- | --- | --- | --- |
| 1 | Bonsai 2 27B | PTQ1_0 existente no SSD C: | Prism `73bfe6c`, Linux CUDA 13.3 |
| 2 | Bonsai 2 9B | PQ2_0, revisão `5b2abb02362efbed46bbe204014b02837778b2c2` | Mesmo bundle Prism |
| 3 | Ornith 1.0 9B | Q4_K_M existente | llama.cpp `620d222` |
| 4 | Qwen3.5-9B | Q4_K_M existente | llama.cpp `620d222` |
| 5 | Gemma 12B QAT local | Q4_0 existente; origem ainda não atribuída | llama.cpp `620d222` |

O agendador alterna os modelos por tarefa e repetição para equilibrar a ordem. Esta tabela representa a primeira passagem, não blocos completos por modelo.

Não foi localizado Qwen3.8 **oficial** de 7–12B no [catálogo Qwen](https://huggingface.co/Qwen/models) na consulta de 20/10. O [Empero Qwen3.8-9B-Distill](https://huggingface.co/empero-ai/Qwen3.8-9B-Distill) é comunitário e não foi introduzido como se fosse lançamento oficial. Qwen3.5-9B permanece como controle conhecido.

O catálogo executável e seus hashes estão em [practical-7bplus-v1.json](../benchmark/configs/practical-7bplus-v1.json). Os dois bundles entram no congelamento de versões, incluindo bibliotecas compartilhadas. A preparação baixou o GGUF 9B e o runtime Prism Linux com conferência SHA-256; o 27B não foi baixado novamente.

## Execução e retomada

No WSL, neste worktree:

```bash
bash scripts/run-practical-7bplus.sh --execute
```

O comando retoma o que já terminou. Para liberar uma nova tentativa após corrigir um bloqueio de infraestrutura:

```bash
bash scripts/run-practical-7bplus.sh --execute --retry-blocked
```

Resultados: `/home/foxtrot/local-llm-benchmark/results/practical-selection-7bplus-v1`.
Estado: `status.json`; saída do processo lançado em 20/10: `campaign-console.log`; PID registrado em `campaign.pid`.

### Supervisão de capacidade

Em 20/10, a fila parou após 12 episódios porque a GPU tinha 6728 MiB livres, abaixo do piso congelado de 7000 MiB. Nenhuma chamada ao modelo ocorreu no episódio bloqueado. O NVIDIA Overlay foi encerrado com a autorização anterior do usuário; a inferência de Ornith/C1 foi retomada sem refazer os concluídos.

A supervisão instalada aguarda VRAM suficiente e retoma apenas bloqueios de capacidade, preservando manifesto, resultados e parâmetros. Outros erros exigem investigação. Iniciar ou retomar a supervisão no WSL:

```bash
/home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m benchmark.practical_queue_supervisor
```

Uma trava impede supervisores duplicados. O estado da supervisão fica em `supervisor-state.json` (`running`, `waiting_for_vram`, `complete` ou `needs_attention`); o histórico, em `supervisor-console.log`. Durante uma espera por VRAM, `status.json` preserva o bloqueio anterior até a retomada real. Não confundir esse estado salvo com o encerramento da supervisão.

Os três controles novos de espera/rejeição de erros não relacionados passaram, junto dos seis testes do catálogo; Ruff também passou. O piso continua em 7000 MiB e os 12 episódios encerrados foram preservados.

A rotina diária é executada antes de criar uma nova campanha e usa o marcador do dia. A retomada de um manifesto existente preserva suas versões. Validação isolada: `bash scripts/run-practical-7bplus.sh --validate-only`.

Protocolo: `practical-agent-selection-7bplus-v1`. Oito tarefas por modelo, três repetições, baseline de 16K/4096 tokens de saída, KV Q4_0, Flash Attention, raciocínio e especulação desligados. São 120 episódios iniciais e até 36 episódios de ajustes/confirmacão dos finalistas. Um servidor e um modelo por vez; piso autorizado de 7000 MiB livres antes da carga; ferramentas continuam dentro do isolamento existente.

As tarefas H1/H2 já foram usadas na campanha anterior; nesta comparação repetida são regressões de confirmação, não um conjunto novo ou secreto. Nenhum resultado antigo foi importado como nova medição.

## Verificação da implementação

35 testes focados passaram em 20/10, incluindo propagação do catálogo aos probes, identidade do runtime, protocolo dos agendamentos e retomada de saída alternativa sem atualização. Ruff, compilação Python e sintaxe Bash passaram. Não havia mypy/pyright disponível; compilação não é checagem de tipos. A revisão independente identificou o caso de saída alternativa no launcher; o teste reproduziu a falha e passou depois da correção.
