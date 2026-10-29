# Linha de base OpenCode: etapa 2, contexto e KV

Data: 29/10/2026. Autor: Claude (orquestrador).

- Protocolo: `bwrap-v6`, commit `417e96d`.
- Controle: Q4_K_M, KV q4_0, contexto de 64K, cache ligado, thinking desligado, 40 passos. São os 24 episódios do `bwrap-v5`.
- Cada braço muda **um único fator** e roda 1 vez nas 12 tarefas.

| Braço | Acertos | Taxa | Mediana s (sucessos) | TTFT mediano ms | Pico de VRAM do dispositivo, MiB | Fração de prompt vinda do cache | Falhas |
|---|---:|---:|---:|---:|---:|---:|---|
| **Controle** (64K, q4_0) | 16/24 | 67% | 36 | 273 | 4.567 | 0,94 | 5 oráculo, 1 fase 1, 1 tempo, 1 CLI |
| ctx 16K | **3/12** | **25%** | 28 | 437 | 3.858 | 0,87 | **9 contexto excedido** |
| ctx 32K | 9/12 | 75% | 38 | 234 | 4.105 | 0,92 | 3 oráculo |
| ctx 128K | 9/12 | 75% | 38 | 258 | 5.422 | 0,95 | 2 oráculo, 1 tempo |
| KV q8_0 | 9/12 | 75% | 31 | 272 | 5.038 | 0,92 | 2 oráculo, 1 CLI |
| KV f16 | 7/12 | 58% | 32 | 273 | 5.754 | 0,91 | 4 oráculo, 1 tempo |

## Leitura

1. **16K é insuficiente para o OpenCode neste corpus.** Nove episódios morreram com `exceeds the available context size (16384 tokens)`; um pedido chegou a 23.723 tokens. É um limite de capacidade do harness com esse repositório, não erro do modelo.
2. **De 32K a 128K não há diferença detectável de acerto** (75%, 67% e 75%). No controle, 4 tarefas trocaram de resultado entre repetições, então diferenças de 1 a 2 episódios são ruído.
3. **O tipo de KV não muda o acerto de forma detectável** (q4_0 67%, q8_0 75%, f16 58%). O f16 ficou abaixo, mas dentro do ruído. **O KV q4_0 não custa qualidade mensurável** e é o mais barato.
4. **O custo de contexto e KV maiores é pequeno nesta escala de uso real.**
   - Pico de VRAM: 4,1 GiB com 32K, 4,6 GiB com 64K e 5,4 GiB com 128K, todos com q4_0; 5,8 GiB com f16 a 64K.
   - O TTFT ficou entre 230 e 280 ms em todos os braços a partir de 32K. O cache cobre mais de 91% do prompt.
   - Como o agente não enche a janela, o custo de 85 s de prefill a frio medido no needle a 128K não aparece aqui.

## Recomendação para a configuração de uso

- **Contexto: 32K é o mínimo, 64K é a margem confortável.** O 128K funciona e cabe na GPU (5,4 GiB), mas não trouxe ganho neste corpus.
- **KV: q4_0.**
- O controle das etapas seguintes continua **64K com q4_0**.
