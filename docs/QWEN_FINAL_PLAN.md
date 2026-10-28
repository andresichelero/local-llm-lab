# Campanha Qwen final — 27/10/2026

Objetivo: comparar quantizações de Qwen3.5 4B e 9B na RTX 3070 8 GiB, priorizando correção, velocidade, contexto útil e responsividade da máquina.

- Somente modelos-base, sem fine-tuning, e conversões Unsloth, com mais de 4 bits por peso e arquivos abaixo de 7,5 GB decimais; Q4 nominal só quando a média efetiva ultrapassar 4 bits.
- 4B Unsloth: Q5_K_S, Q5_K_M, UD-Q5_K_XL, Q6_K e Q8_0.
- 9B Unsloth: Q4_K_M, Q5_K_S, Q5_K_M, UD-Q5_K_XL e Q6_K. O Q4_K_M foi explicitamente autorizado como exceção nominal: a inspeção local dos 427 tensores mediu 5,0656 bits por elemento, incluindo diferentes tipos de tensor.
- EXL3 2–4 bits foram excluídos pelo piso acima de 4 bits; os EXL3 5–6 bits do catálogo ultrapassam 7,5 GB. Não há EXL3 4B no catálogo. Outros formatos entram apenas após comprovar compatibilidade e cumprir os mesmos limites.
- O tamanho do arquivo não comprova que a inferência caberá na VRAM: pesos, cache KV, contexto, workspace e demais aplicativos contam. A campanha exige carregamento integral na GPU e reserva de 512 MiB; se não couber, registrar bloqueio de capacidade, não usar spillover e não classificar como falha do modelo.
- Protocolo: `qwen-quant-harness-optimization-final`; saída: `/home/foxtrot/local-llm-benchmark/results/qwen-quant-harness-optimization-final`. Os artefatos do catálogo anterior não selecionados não devem entrar automaticamente.
- Preservar repositório, revisão, hash, tokenizer e template de cada artefato. A qualificação exige 10/12 verificações; as demais etapas medem contexto, desempenho e tarefas reais. Comparar harnesses e perfis de raciocínio em protocolos controlados próprios. Não repetir falhas de modelo concluídas para conseguir sucesso.
- Resultados históricos selecionados serão conservados como referência rastreável, sem misturar protocolos no ranking final quando a equivalência não estiver comprovada.
- Execução serial; aguardar capacidade e não fechar aplicativos, alterar drivers/clocks ou modificar o sistema.

## Atualização: execução até OOM

A pedido do usuário em 27/10/2026, a política de 512 MiB foi retirada no protocolo `qwen-quant-harness-optimization-final-oom-v2`: o runner tenta carregar e executar com todas as camadas solicitadas à GPU, sem bloquear apenas porque sobram menos de 512 MiB. OOM confirmado pelo servidor ou falha real de execução é registrado separadamente das falhas de raciocínio. Persistem as verificações de disco e RAM; não se fecham aplicativos do usuário. Essa mudança pode ocupar a VRAM inteira e provocar lentidão ou paginação do driver; não é uma garantia de ausência de spillover.

Os dez bloqueios causados exclusivamente pela antiga reserva são reencaminhados em saída nova. As demais conclusões permanecem com protocolo de origem, dados e logs originais preservados. Uma comparação que misture os protocolos exige revisão, sem transformar os resultados antigos em novos.
