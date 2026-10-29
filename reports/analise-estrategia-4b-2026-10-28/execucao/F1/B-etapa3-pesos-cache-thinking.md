# Linha de base OpenCode: etapa 3 (pesos, cache e thinking)

Data: 29/10/2026. Autor: Claude (orquestrador).

- Protocolo: `bwrap-v6`.
- Controle: os 24 episódios do `bwrap-v5`, com Q4_K_M (bartowski), KV q4_0, contexto 64K, cache ligado, thinking desligado, temperatura 0 e 40 passos.
- Cada braço muda um único fator e roda as 12 tarefas uma vez.

| Braço | Acertos | Taxa | Tempo mediano dos sucessos (s) | TTFT mediano (ms) | Pico de VRAM (MiB) | Falhas |
|---|---:|---:|---:|---:|---:|---|
| **Controle** | 16/24 | 67% | 36 | 273 | 4.567 | 5 oráculo, 1 fase 1, 1 tempo, 1 CLI |
| Q6_K (unsloth) | 10/12 | 83% | 34 | 290 | 5.162 | 1 oráculo, 1 CLI |
| Q8_0 (unsloth) | 8/12 | 67% | 32 | 320 | 6.033 | 4 oráculo |
| Cache desligado | 9/12 | 75% | **82** | **7.704** | 4.521 | 1 tempo, 1 oráculo, 1 CLI |
| **Thinking ligado** (temperatura 0,6, top_p 0,95, top_k 20) | **11/12** | **92%** | **109** | 200 | 4.535 | 1 oráculo |

## Leitura

1. **Thinking ligado teve a maior taxa até agora: 11 de 12.** Resolveu tarefas difíceis em que o controle falhou. O custo é cerca de **3× o tempo por tarefa** (109 s contra 36 s). Com 12 episódios, a diferença ainda não é estatisticamente firme, mas é o maior sinal da matriz. Por isso a etapa 4 ganhou o braço **C4-think com 2 repetições** para confirmar.
2. **Q6_K com 10/12 e Q8_0 com 8/12.** Mais bits não deu um ganho monotônico. O Q6_K continua promissor, mas pode ser ruído ou efeito do quantizador. A etapa 4 roda 3 repetições do Q6_K e um Q4_K_M do mesmo quantizador (unsloth) para separar os dois efeitos.
3. **O cache não muda o acerto, mas é essencial para a latência.** Sem cache, o TTFT mediano sobe de 0,27 s para 7,7 s e o tempo por tarefa mais que dobra (82 s contra 36 s).
4. Nenhuma falha de infraestrutura.

## Consolidado das etapas 1–3

A configuração de uso provisória, a confirmar na etapa 4, é: **Q4_K_M ou Q6_K, KV q4_0, contexto de 32–64K, cache ligado**. Para thinking:
- **ligado** quando a qualidade importa mais que o tempo;
- **desligado** para respostas rápidas.

O contexto de 16K não serve com o OpenCode.
