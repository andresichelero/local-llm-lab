# Pesquisa de estado da arte (agente Sonnet, esforço high, 29/10/2026), condensada pelo orquestrador

Fontes primárias consultadas pelo agente:
- llama.cpp: [README do server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [PR #21038](https://github.com/ggml-org/llama.cpp/pull/21038), [PR #22673](https://github.com/ggml-org/llama.cpp/pull/22673), [issue #24055](https://github.com/ggml-org/llama.cpp/issues/24055), [discussão #23470](https://github.com/ggml-org/llama.cpp/discussions/23470);
- model card do [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B);
- repositórios de quantizações: [unsloth GGUF](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF), [unsloth MTP GGUF](https://huggingface.co/unsloth/Qwen3.5-4B-MTP-GGUF), [bartowski](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF);
- OpenCode: [config](https://opencode.ai/docs/config/), [LSP](https://opencode.ai/docs/lsp/), [tools](https://opencode.ai/docs/tools/);
- ferramentas: [Headroom](https://github.com/headroomlabs-ai/headroom), [RTK](https://github.com/rtk-ai/rtk).

Marcações usadas abaixo: **F** é fato em fonte primária, **R** é relato de terceiros, **I** é inferência.

## KV cache
- **F** Tipos de KV aceitos: f32, f16, bf16, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1.
- **F** O build CUDA padrão só compila kernels de flash attention para os pares q4_0-q4_0, q8_0-q8_0, f16-f16 e bf16-bf16. Pares mistos, como K q8_0 com V q5_0, exigem recompilar com `GGML_CUDA_FA_QUANTS`. Sem isso, o servidor cai para f16 com um warning.
- **F** A rotação de Hadamard no KV quantizado foi incorporada em 01/04/2026 (PR #21038). Ela está ativa no nosso build e reduz a perda do q4_0. Para fazer A/B: `LLAMA_ATTN_ROT_DISABLE=1`.
- **R** Na discussão #23470, a chave (K) é bem mais sensível à quantização que o valor (V). O q8_0 com q8_0 fica perto do baseline. O efeito do q4_0 com q4_0 varia muito de modelo para modelo.
- O TurboQuant só existe em forks, não no upstream.
- **I** Os nossos dados (q4_0 67%, q8_0 75%, f16 58%) não mostram diferença. O q8_0 é a escolha "segura", com pouca VRAM a mais.

## Pesos
- Quantizações disponíveis:
  - unsloth: UD-Q4_K_XL (2,91 GB), UD-Q6_K_XL (4,15 GB) e um repositório com MTP;
  - bartowski: Q6_K_L e Q4_K_L, que guardam embeddings e saída em Q8_0.
- **F** Segundo a unsloth, em modelos híbridos os tensores `attn_*` e `ssm_out` são sensíveis à quantização. Isso favorece as variantes XL e _L.
- **R** No benchmark llm-quant-bench (HumanEval de um turno), de Q4 para cima a nota fica entre 57% e 61%, e o UD-Q4_K_XL foi o melhor.
- **I** Os nossos 83% do Q6_K vêm de uma única rodada e de outro quantizador, então ainda é preciso repetir.

## MTP (decodificação especulativa)
- **F** Suportado desde o PR #22673 (16/05/2026), com `--spec-type draft-mtp --spec-draft-n-max 2`. O valor 2 é o ponto de partida; testar de 1 a 6.
- **F** Exige `-np 1`.
- **F** O MTP pode alterar a saída mesmo com temperatura 0, por causa dos kernels dependentes do tamanho do batch (issue #23335).
- **R** Ganhos relatados: de 1,5× a 2,9× em modelos maiores, sem número para o 4B.

## Amostragem oficial (model card do Qwen3.5-4B)
- **Sem thinking:** temperatura 0,7, top_p 0,8, top_k 20, min_p 0, presence_penalty 1,5.
- **Thinking para código:** temperatura 0,6, top_p 0,95, top_k 20, presence_penalty 0.
- O card não proíbe temperatura 0, mas todos os presets usam temperatura acima de 0. O card do Qwen3 desaconselhava decodificação gulosa por risco de loops.
- **I** Verificar se o OpenCode manda `temperature` no corpo da requisição, porque esse valor sobrescreve o do servidor.

## Cache em modelos híbridos
- **F** O `--cache-reuse` fica desabilitado quando a memória não suporta deslocamento ("shift"). O log avisa com "cache_reuse is not supported". **I** Provavelmente não tem efeito no Qwen3.5.
- **F** Parâmetros relevantes: `--ctx-checkpoints` (padrão 32), `--checkpoint-min-step` (padrão 8192) e `--cache-ram`. Recomendação para multi-turno: `-ctxcp 64 -cms 512..1024`.
- **R** Bug aberto (#24055): modelos híbridos às vezes reprocessam o prompt inteiro. **I** No nosso caso, de 91% a 95% dos tokens de prompt vêm do cache, então o problema parece pequeno.

## Tarefas longas
- **F** Compactação no OpenCode: `"compaction": {"auto": true, "prune": true, "reserved": 8192}`, mais `limit.context/input/output` por modelo. A reserva padrão é grande e estoura contextos locais pequenos (#8140).
- **F** Plugins podem trocar o prompt de compactação pelo hook `experimental.session.compacting`.
- **F** O Headroom comprime saídas de ferramentas por proxy (`headroom-opencode` com `proxyUrl`). A telemetria vem ligada por padrão; desligar com `HEADROOM_OFFLINE=1`. Os números divulgados são do próprio fabricante.
- **I** Comprimir a saída de ferramentas pode mudar o prefixo da conversa e quebrar os checkpoints de cache.

## Ferramentas
- **F** O LSP do OpenCode vem desligado por padrão. `"lsp": true` liga, e o pyright precisa estar instalado.
- **F** A ferramenta `lsp` (definição, referências, símbolos) é experimental e se liga com `OPENCODE_EXPERIMENTAL_LSP_TOOL=true`.
- **F** O RTK filtra a saída do bash, por exemplo deixando só as falhas do pytest. Instala com `rtk init -g --opencode`.
- **I** Não há evidência independente de ganho para modelos pequenos. Cada MCP adiciona schemas ao prompt, e filtrar ferramentas tem efeito mais comprovado.

## Prioridades sugeridas (usadas no plano da noite)
1. Repetições: com 12 tarefas, só diferenças de 3 ou mais merecem atenção.
2. KV q8_0.
3. Pesos UD-Q4_K_XL, Q6_K_L e UD-Q6_K_XL.
4. Amostragem oficial contra temperatura 0.
5. MTP com n-max 2.
6. Checkpoints de cache verificados com `-lv 4`.
7. Compactação configurada.
8. LSP e filtro de saída.
9. Notas em disco ou reinício da sessão.
10. Headroom, com prioridade baixa.
