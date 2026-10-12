# Relatório de Avaliação Controlada de Admissão de Candidato: Gemma-4-E4B-it-qat (Marco M5 / Tarefa 7)

**Data de Execução:** 2026-10-12  
**Experimento:** `candidate-admission-paired-20261012-m5-20261012-205114`  
**Harness:** OpenCode 1.19.0 (modo `primary`, subagent_depth=0, permissão `bash`+`edit`, max 20 passos)  
**Runtime:** llama.cpp build b5122 (`d81235049384534c167caea52b85a694f6103d14`) com `--cache-prompt`  
**Candidato Avaliado:** Gemma 4 E4B IT QAT GGUF (UD-Q4_K_XL, quantização Unsloth, SHA-256: `df0fd4ee07072c607c29a0a1cb4f98918426cca12f45a2776bdd6ee6d09a4de3`, tamanho: 4.215.695.776 bytes / 3,93 GiB)  
**Modelo de Controle:** Qwen3.5-4B-Q4_K_M (SHA-256: `13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983`)  
**Hardware:** NVIDIA GeForce RTX 3070 (8.192 MiB VRAM), WSL2 Ubuntu-24.04 (8 GiB RAM, 4 GiB swap), partição ext4 SSD NVMe  
**Status do Disco:** 11 GiB livres após aquisição ($\ge 8\text{ GiB}$ estritamente preservados)  
**Status da Rodada:** 12/12 ensaios executados com exit code 0, 0 timeouts, 0 crashes de motor.

---

## 1. Contexto e Pergunta de Admissão

A auditoria metodológica (`research/reviews/model-claims-audit-20261012.md`) pré-selecionou o modelo `Gemma 4 E4B IT QAT GGUF` como o primeiro candidato formal de aquisição externa para o laboratório sob as seguintes condições estritas:
1. Orçamento de armazenamento: arquivo $< 6\text{ GiB}$ e espaço livre no SSD $\ge 8\text{ GiB}$.
2. Pergunta de pesquisa: *O modelo Gemma 4 E4B QAT oferece qualidade útil, estabilidade sintática e respeito a contratos de ferramentas em tarefas de programação agentic locais, justificando sua admissão ao pool operacional?*

---

## 2. Fase 1: Preflight, Integridade e Fit de Memória

### 2.1 Verificação Criptográfica e de Armazenamento
- **Bytes Exatos:** 4.215.695.776 B (3,93 GiB).
- **Digest SHA-256:** `df0fd4ee07072c607c29a0a1cb4f98918426cca12f45a2776bdd6ee6d09a4de3` (100% de coincidência com o registro da auditoria).
- **Reserva do SSD ext4:** `free_before` = 15 GiB $\rightarrow$ download = 3,93 GiB $\rightarrow$ `free_after` = 11 GiB ($\ge 8\text{ GiB}$ mantido).

### 2.2 Diagnóstico Curto em 4K e 16K
- **Fit em 4K Context:**
  - Tempo de carregamento dos pesos para VRAM: **2,26 segundos**.
  - VRAM total alocada (incluindo display do host): **4.003 MiB** (4.015 MiB livres).
  - Sonda JSON estruturada: Aprovada (`{"result": 42, "status": "ok"}`).
- **Fit em 16K Context:**
  - Carregamento de slots: `n_slots = 1, n_ctx_slot = 16384`.
  - VRAM total alocada com KV cache `q4_0`: **4.118 MiB** (3.900 MiB livres, folga de ~48%).
  - Geração de código básica: Aprovada (função `add(a, b)` sintetizada corretamente em prompt isolado).

---

## 3. Fase 2: Matriz Pareada de Avaliação Agentic (12 Ensaios)

O candidato foi submetido à suíte controlada contra o modelo de controle (Qwen3.5-4B) em 2 tarefas não-saturadas com 3 repetições balanceadas (ordens AB, BA, AB), operando no harness real OpenCode com execução de ferramentas `bash` e `edit`.

### Tabela de Ensaios Medidos (12/12)

| Ensaio | Tarefa | Modelo | Repetição | Tempo de Parede (s) | Passagem Estrita | Classe de Falha Observada | Pico VRAM (MiB) |
|:---:|:---|:---:|:---:|:---:|:---:|:---|:---:|
| 1 | `calculator_division` | `qwen3.5-4b` | 1 | 21,247s | **PASS** | Nenhuma (100% correto) | 4.510,0 |
| 2 | `calculator_division` | `gemma-4-e4b` | 1 | 27,565s | **FAIL** | Scope Violation (`unchanged_helpers: false`, apagou `add`) | 4.135,0 |
| 3 | `dotenv_line_parser` | `qwen3.5-4b` | 1 | 21,194s | **PASS** | Nenhuma (100% correto) | 4.491,0 |
| 4 | `dotenv_line_parser` | `gemma-4-e4b` | 1 | 21,268s | **FAIL** | Syntax Contamination (vazou `(End of file)` no código) | 4.123,0 |
| 5 | `calculator_division` | `gemma-4-e4b` | 2 | 30,726s | **FAIL** | Scope Violation (apagou funções preexistentes) | 4.136,0 |
| 6 | `calculator_division` | `qwen3.5-4b` | 2 | 21,317s | **PASS** | Nenhuma (100% correto) | 4.499,0 |
| 7 | `dotenv_line_parser` | `gemma-4-e4b` | 2 | 40,444s | **FAIL** | Behavioral Assertion Error | 4.123,0 |
| 8 | `dotenv_line_parser` | `qwen3.5-4b` | 2 | 21,142s | **PASS** | Nenhuma (100% correto) | 4.487,0 |
| 9 | `calculator_division` | `qwen3.5-4b` | 3 | 21,172s | **PASS** | Nenhuma (100% correto) | 4.494,0 |
| 10 | `calculator_division` | `gemma-4-e4b` | 3 | 60,298s | **FAIL** | Contract Breach / Test Failure | 4.698,0 |
| 11 | `dotenv_line_parser` | `qwen3.5-4b` | 3 | 20,102s | **PASS** | Nenhuma (100% correto) | 4.480,0 |
| 12 | `dotenv_line_parser` | `gemma-4-e4b` | 3 | 22,317s | **FAIL** | Behavioral Assertion Error | 4.444,0 |

---

## 4. Síntese Comparativa Agregada

| Métrica | `calculator_division` (Qwen3.5-4B) | `calculator_division` (Gemma-4-E4B) | `dotenv_line_parser` (Qwen3.5-4B) | `dotenv_line_parser` (Gemma-4-E4B) |
|---|:---:|:---:|:---:|:---:|
| **Taxa de Sucesso Estrita** | **3/3 (100,0%)** | **0/3 (0,0%)** | **3/3 (100,0%)** | **0/3 (0,0%)** |
| **Tempo Mediano (Parede)** | **21,247 s** | 30,726 s | **21,142 s** | 22,317 s |
| **Tempo Mínimo** | 21,172 s | 27,565 s | 20,102 s | 21,268 s |
| **Tempo Máximo** | 21,317 s | 60,298 s | 21,194 s | 40,444 s |
| **Pico VRAM Máximo** | 4.510,0 MiB | 4.698,0 MiB | 4.491,0 MiB | 4.444,0 MiB |
| **Taxa Geral da Suíte** | **6/6 (100,0%)** | **0/6 (0,0%)** | - | - |

---

## 5. Taxonomia e Diagnóstico das Falhas do Candidato

Embora Gemma-4-E4B tenha apresentado excelente eficiência de carregamento e baixo uso de VRAM (pico de apenas 4.698 MiB), o modelo demonstrou **incompatibilidade comportamental severa com a operação agentic multi-turn**:

1. **Violação de Escopo e Deleção Destrutiva (`calculator_division`):**
   - Ao ser instruído a implementar a função `divide(a, b)`, o modelo sobrescreveu integralmente o arquivo `src/calculator.py`, eliminando as funções auxiliares `add` e `multiply`.
   - Consequência: `ImportError: cannot import name 'add' from 'src.calculator'`. O validador adversarial `unchanged_helpers` reprovou imediatamente a tentativa.

2. **Contaminação Sintática por Artefatos Conversacionais (`dotenv_line_parser`):**
   - Ao editar o arquivo de testes, o modelo copiou literalmente os comentários de metadados do harness (ex: `(End of file - total 25 lines)`) para dentro do código-fonte Python.
   - Consequência: `SyntaxError: invalid syntax. Perhaps you forgot a comma?`. O código tornou-se inválido antes mesmo da execução dos testes.

---

## 6. Veredito e Decisão de Governança

- **Critério de Admissão:** Zero regressões catastróficas e taxa de sucesso compatível com o controle de referência ($\ge 50\%$).
- **Resultado Observado:** **0/6 (0% de sucesso)** contra **6/6 (100% de sucesso)** do controle.

**Decisão Formal:**
1. **REJEIÇÃO DE ADMISSÃO:** O modelo `Gemma-4-E4B-it-qat-UD-Q4_K_XL` é **formalmente rejeitado** para operação no pool de roteamento do laboratório agentic.
2. **Governança de Armazenamento:** Para preservar o orçamento estrito de SSD ext4 e evitar acúmulo de modelos não-operacionais, o arquivo de pesos temporário é elegível para arquivamento no Drive E (`E:\LocalLLMLabArchive\models\`) ou remoção após a publicação das evidências.
3. **Controle Mantido:** `Qwen3.5-4B-Q4_K_M` e `Qwen3.5-9B-Q4_K_M` permanecem como os únicos modelos admitidos e calibrados no laboratório.
