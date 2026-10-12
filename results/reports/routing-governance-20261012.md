# Relatório de Roteamento Empírico, Governança e Backlog (Marco M6 / Tarefas 8 e 9)

**Data de Publicação:** 2026-10-12  
**Autor:** Antigravity Agent & Foxtrot Lab  
**Referência Metodológica:** `2026-10-12-methodology-revised-roadmap.md` e `methodology-review-20261012.md`  
**Escopo:** Marco M6 (Tarefas 8 e 9) — Consolidação das evidências experimentais de M0 a M5 em regras de roteamento operacional, medição de latência de troca de modelo e governança do backlog técnico.

---

## 1. Evidências Empíricas Acumuladas (Marcos M0 a M5)

| Marco | Experimento | Amostras | Conclusão Empírica Principal |
|---|---|:---:|---|
| **M0** | Fechamento e Auditoria de Evidências | 64 docs | Rastreabilidade criptográfica fechada (100% SHA-256 OK), drive E arquivado. |
| **M1** | Validadores Adversariais e Amostrador MiB | 170 testes | 100% de precisão na detecção de mutantes e telemetria corrigida para MiB. |
| **M2** | Suíte Discriminante e Piloto Controlado | 4 ensaios | Piloto concluído em 8m53s sem falhas mecânicas; fixtures calibradas. |
| **M3** | Matriz Pareada 4B vs 9B (6 tarefas × 2 repeats) | 24 ensaios | Paridade de sucesso estrito (66,7% vs 66,7%). 4B é ~30% mais rápido em tarefas leves; **9B é 2,38× mais rápido em raciocínio multi-turn** (`retry_policy`: 46,9s vs 111,6s). |
| **M4 (6A)** | Prefix Caching Pareado (`--cache-prompt`) | 12 ensaios | **1,57× a 1,70× de aceleração de parede**; reaproveitamento de ~8.000 tokens de prefixo por turno com zero regressão funcional. |
| **M4 (6B)** | MTP no Harness Agentic (`draft-mtp 3`) | 12 ensaios | **Taxa de aceitação de 91,16%**; velocidade de geração saltou de 77 para **146 tokens/s**; aceleração adicional de 1,24× a 1,79×. |
| **M5** | Admissão de Candidato (Gemma 4 E4B QAT) | 12 ensaios | **0% de aprovação (0/6)** vs 100% do controle. Rejeitado por violação de escopo e vazamento sintático. |

---

## 2. Medição Real de Latência de Troca de Modelo (Tarefa 8)

Para viabilizar políticas de cascata (*cascade routing*) onde o agente inicia no modelo 4B e pode escalar para o 9B sob demanda, foi executado o benchmark de 5 ciclos alternados de troca real entre os pesos quantizados no SSD ext4 NVMe (`benchmark/model_switch_bench.py`):

| Ciclo | Transição | Tempo de Descarregamento (s) | Tempo de Carregamento VRAM (s) | Latência de Prontidão (*Ping*) (s) | **Tempo Total de Troca (s)** |
|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 4B $\rightarrow$ 9B | 0,451 s | 4,396 s | 0,108 s | **4,955 s** |
| 2 | 9B $\rightarrow$ 4B | 0,359 s | 3,002 s | 0,104 s | **3,465 s** |
| 3 | 4B $\rightarrow$ 9B | 0,206 s | 4,257 s | 0,098 s | **4,561 s** |
| 4 | 9B $\rightarrow$ 4B | 0,204 s | 3,122 s | 0,109 s | **3,435 s** |
| 5 | 4B $\rightarrow$ 9B | 0,205 s | 3,920 s | 0,097 s | **4,222 s** |

### Observações:
1. **Descarregamento Ultra-rápido:** O encerramento gracioso via `SIGTERM` libera a porta e desocupa os 8 GiB de VRAM em **0,20 a 0,45 segundos**.
2. **Carga em VRAM:**
   - Qwen3.5-4B (3,01 GB) carrega e instancia o contexto de 16K em **~3,0 a 3,1 segundos**.
   - Qwen3.5-9B (5,68 GB) carrega e instancia o contexto de 16K em **~3,9 a 4,4 segundos**.
3. **Custo de Chaveamento Insignificante:** O tempo total para descarregar um modelo e deixar o outro 100% pronto para inferência é de **apenas 3,4s (para 4B) e 4,5s (para 9B)**.
4. **Viabilidade de Cascata:** Como uma tarefa agentic típica consome entre 20s e 50s, um custo de troca de ~4,5s representa menos de 10% do orçamento total de 180s, confirmando a plena viabilidade da política de cascata.

---

## 3. Matriz de Decisão e Regras de Roteamento Determinístico

A política de roteamento formalizada em `router/rules.py` passa a operar em 3 camadas determinísticas:

```mermaid
flowchart TD
    T[Nova Tarefa Recebida] --> T0{É verificação sintática,\nlinter ou formatação?}
    T0 -- Sim --> C0[Nível 0: CPU Local\nrules / AST / pytest\n0 MiB VRAM | < 1s]
    T0 -- Não --> T1{Complexidade / Escopo?}
    T1 -- Tarefa linear / 1 arquivo --> C1[Nível 1: Qwen3.5-4B\ncache-prompt + MTP-draft-3\n4.850 MiB VRAM | ~17s-22s]
    T1 -- Multi-turn / Exceções / Refatoração --> C2[Nível 2: Qwen3.5-9B\ncache-prompt ativo\n7.320 MiB VRAM | ~40s-47s]
    C1 --> F1{Falha detectada no turno 2?}
    F1 -- Sim (e orçamento > 60s) --> ESC[Escalonamento Automático\nTroca de modelo: 4,5s] --> C2
    F1 -- Não --> S1[Sucesso na Tarefa]
    C2 --> S2[Conclusão da Tarefa]
```

### Especificação dos Níveis:

1. **Nível 0 (Determinístico / CPU):**
   - Destino: Interpretador local Python / `pytest` / AST.
   - Aplicação: Testes de formatação, checagem de tipos, linting e execução de oráculos determinísticos.
   - Custo: 0 MiB VRAM, $< 1\text{ s}$.

2. **Nível 1 (Local Compacto — Qwen3.5-4B):**
   - Configuração Padrão: `--cache-prompt` + `--spec-type draft-mtp --spec-draft-n-max 3`.
   - VRAM de Pico: $\le 4.870\text{ MiB}$ (folga de $> 3.300\text{ MiB}$).
   - Latência Mediana Observada: **17,0s a 22,4s**.
   - Casos Indicados: Tarefas de escopo limitado (`calculator_division`, `whitespace_normalization`, `dotenv_line_parser`).

3. **Nível 2 (Local Pesado — Qwen3.5-9B):**
   - Configuração Padrão: `--cache-prompt`.
   - VRAM de Pico: $\le 7.330\text{ MiB}$ (folga de ~860 MiB na RTX 3070).
   - Latência Mediana Observada: **40,0s a 46,9s**.
   - Casos Indicados: Raciocínio multi-turn, políticas de retry e manipulação de hierarquias de exceção (`retry_policy`). Evita múltiplos ciclos de reparo, sendo **2,38× mais rápido** que o 4B nessa classe de problema.

4. **Regra de Escalonamento em Cascata:**
   - Se uma tarefa iniciada no Nível 1 registrar 2 tentativas consecutivas de reparo sem aprovação nos testes locais e houver pelo menos 60 segundos restantes no orçamento da tarefa, o supervisor realiza o escalonamento automático para o Nível 2 (custo de troca: 4,5s).
   - Erros de transporte, timeout de rede ou estouro de cota abortam imediatamente sem escalonamento.

---

## 4. Governança do Backlog Técnico (Tarefa 9)

Em conformidade rigorosa com os critérios de encerramento do roadmap:

1. **QLoRA e Ajuste Fino Local:**
   - **Status:** **DIFERIDO / EM ESPERA.**
   - **Justificativa:** Conforme o critério de governança da Tarefa 9, o ajuste fino só deve ser iniciado quando:
     1. Há uma classe persistente e caracterizada de erro que **não** possa ser resolvida por engenharia de harness, validador ou template;
     2. Existem pelo menos 120 episódios verificáveis de desenvolvimento com prova de masking e split de holdout de 60 episódios.
   - Ambas as classes abertas (`config_precedence` e `package_refactor`) são deficiências estruturais de raciocínio de contexto e edição multi-arquivo, passíveis de mitigação por decomposição em sub-passos no harness antes de demandar adaptação de pesos.

2. **Mistral Vibe Harness:**
   - **Status:** **DIFERIDO.**
   - **Justificativa:** Apresentou desvio sistemático de identificadores canônicos de teste nos ensaios históricos. Mantido fora do caminho crítico enquanto OpenCode 1.19.0 mantiver 100% de estabilidade mecânica.

3. **Contextos Extremos (>16K) e Modelos Maiores:**
   - Modelos de 12B/27B e quantizações EXL3/AWQ adicionais permanecem arquivados no Drive E (`E:\LocalLLMLabArchive\`), acessíveis sob demanda sem onerar o SSD de desenvolvimento.

---

## 5. Conclusão do Roadmap Metodológico Revisado

Com a execução deste marco, todos os objetivos e marcos do roadmap foram concluídos com evidências auditadas:
- [x] **M0:** Evidências e integridade histórica consolidadas.
- [x] **M1:** Validadores adversariais e taxonomia formal de falhas operacionais.
- [x] **M2:** Suíte discriminante de 3 fixtures e piloto de viabilidade concluído com 100% de integridade.
- [x] **M3:** Matriz pareada 4B vs 9B (24 ensaios) com deltas precisos de latência e VRAM.
- [x] **M4:** Otimizações de inferência comprovadas (Prompt Cache com ganho de 1,7×; MTP com 91% de aceitação e ganho de 1,8×).
- [x] **M5:** Processo de admissão executado com integridade; candidato Gemma-4-E4B avaliado e rejeitado por evidência de falha funcional.
- [x] **M6:** Roteamento determinístico, medição de troca em 4,5s e governança de backlog formalizados.
