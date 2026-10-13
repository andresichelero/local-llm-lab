# Relatório de Avaliação Controlada de Admissão de Candidato: IBM Granite 4.1 8B (Marco M5 / Tarefa 7)

**Data de Execução:** 2026-10-12  
**Experimento:** `candidate-admission-granite-8b-20261012-20261012-235625`  
**Harness:** OpenCode 1.19.0 (modo `primary`, subagent_depth=0, permissão `bash`+`edit`, max 20 passos, timeout 180s)  
**Runtime:** llama.cpp build b5122 (`d81235049384534c167caea52b85a694f6103d14`) com `--cache-prompt`, especulação MTP desligada  
**Candidato Avaliado:** IBM Granite 4.1 8B Instruct GGUF (`granite-4.1-8b-Q4_K_M.gguf`, oficial IBM, SHA-256: `ed902ac9eb6adce5a90c6a08c8ea201b50e23fdc5976d1cd0362006afac5309e`, tamanho: 5.347.914.400 bytes / 4,98 GiB)  
**Modelo de Controle:** Qwen3.5-4B-Q4_K_M (SHA-256: `13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983`, tamanho: 3.013.027.808 bytes / 2,81 GiB)  
**Hardware:** NVIDIA GeForce RTX 3070 (8.192 MiB VRAM), WSL2 Ubuntu-24.04 (8 GiB RAM, 4 GiB swap), partição ext4 SSD NVMe  
**Status do Disco:** 13,80 GiB livres após aquisição ($\ge 8\text{ GiB}$ estritamente preservados)  
**Status da Rodada:** 12/12 ensaios executados com exit code 0, 0 timeouts, 0 crashes de servidor.

---

## 1. Contexto e Pergunta de Admissão

A auditoria metodológica (`research/reviews/model-claims-audit-20261012.md` e Tarefa 7 do Roadmap) selecionou como segundo candidato formal de aquisição externa o modelo **IBM Granite 4.1 8B Q4_K_M oficial IBM**, submetido às seguintes condições estritas:
1. **Orçamento de Armazenamento:** Arquivo $< 6\text{ GiB}$ e espaço livre no SSD ext4 $\ge 8\text{ GiB}$ antes e após aquisição.
2. **Pergunta de Pesquisa da Tarefa 7:** *O comportamento de instrução, raciocínio e execução de ferramentas do Granite 4.1 8B compensa seu footprint de VRAM e disco substancialmente maior (~5,0 GiB vs 2,8 GiB) em comparação ao modelo de controle do laboratório?*

---

## 2. Fase 1: Preflight, Integridade e Fit de Memória

### 2.1 Verificação Criptográfica e de Armazenamento
- **Arquivo Alvo:** `/home/foxtrot/local-llm-benchmark/models/gguf/granite-4.1-8b/granite-4.1-8b-Q4_K_M.gguf`
- **Origem Upstream:** `ibm-granite/granite-4.1-8b-GGUF` @ commit `865b82c2e7970d82e3731278c88c57ae7138359c`
- **Licença:** Apache 2.0 (oficial IBM)
- **Bytes Exatos:** 5.347.914.400 B (4,98 GiB).
- **Digest SHA-256:** `ed902ac9eb6adce5a90c6a08c8ea201b50e23fdc5976d1cd0362006afac5309e` (100% de coincidência com o upstream LFS).
- **Reserva do SSD ext4:** `free_before` = 18,77 GiB $\rightarrow$ download = 4,98 GiB $\rightarrow$ `free_after` = 13,80 GiB ($\ge 8\text{ GiB}$ estritamente garantido).

### 2.2 Diagnóstico Curto em 4K e 16K (`benchmark/diagnostic_granite8b.py`)
- **Fit em 4K Context:**
  - Tempo de inicialização e carga em VRAM: **2,138 segundos**.
  - VRAM total alocada (incluindo display do host): **6.291,0 MiB** (delta: +5.298,0 MiB).
  - Sonda JSON estruturada: **Aprovada** em 0,380s (`{"ok": true, "count": 3}`).
  - Sonda Tool Call (`add(19, 23)`): **Aprovada** em 0,597s com formato nativo OpenAI tool call.
- **Fit em 16K Context:**
  - Carregamento de slots: `n_slots = 1, n_ctx_slot = 16384`, KV cache `q4_0`.
  - Tempo de carga: **1,806 segundos**.
  - VRAM total alocada com KV cache `q4_0`: **6.878,0 MiB** (folga de **1.319,0 MiB** no limite de 8.192 MiB da RTX 3070).
  - Taxa de geração no preflight: **52,90 tokens/segundo** (prefill: 732,11 tokens/s).
  - Síntese de código básica (`safe_divide`): **Aprovada** em 1,358s.
  - Veredito da Fase 1: **PASS** em todos os critérios mecânicos.

---

## 3. Fase 2: Matriz Pareada de Avaliação Agentic (12 Ensaios)

O candidato foi submetido à suíte controlada contra o modelo de controle (`qwen3.5-4b`) em duas tarefas não-saturadas (`retry_policy` e `dotenv_line_parser`) com 3 repetições balanceadas em blocos (AB, BA, AB), operando no harness real OpenCode 1.19.0 com permissões `bash` e `edit`, sem MTP.

### Tabela de Ensaios Medidos (12/12)

| Ensaio | Tarefa | Modelo | Repetição | Tempo de Parede (s) | Passagem Estrita | Classe de Falha Observada | Pico VRAM (MiB) |
|:---:|:---|:---:|:---:|:---:|:---:|:---|:---:|
| 1 | `retry_policy` | `qwen3.5-4b` | 1 | 32,836s | **PASS** | Nenhuma (5/5 unit tests, sonda comportamental OK) | 4.245,0 |
| 2 | `retry_policy` | `granite-4.1-8b` | 1 | 34,894s | **FAIL** | Test Degradation (`unchanged_helpers: false`, regrediu suite para 1 teste com erro) | 6.885,0 |
| 3 | `dotenv_line_parser` | `qwen3.5-4b` | 1 | 23,387s | **PASS** | Nenhuma (testes unitários e sonda OK) | 4.230,0 |
| 4 | `dotenv_line_parser` | `granite-4.1-8b` | 1 | 20,172s | **FAIL** | Contract Breach (3 testes com erro em `test_config_parser.py`) | 6.890,0 |
| 5 | `retry_policy` | `granite-4.1-8b` | 2 | 32,803s | **FAIL** | Syntax/Type Crash (`TypeError: unsupported operand type for |: builtin callable`) | 6.870,0 |
| 6 | `retry_policy` | `qwen3.5-4b` | 2 | 22,338s | **PASS** | Nenhuma (5/5 unit tests, sonda comportamental OK) | 4.240,0 |
| 7 | `dotenv_line_parser` | `granite-4.1-8b` | 2 | 23,451s | **FAIL** | Scope Violation (`ImportError: cannot import name 'normalize_key'`) | 6.880,0 |
| 8 | `dotenv_line_parser` | `qwen3.5-4b` | 2 | 21,194s | **PASS** | Nenhuma (testes unitários e sonda OK) | 4.232,0 |
| 9 | `retry_policy` | `qwen3.5-4b` | 3 | 30,656s | **PASS** | Nenhuma (5/5 unit tests, sonda comportamental OK) | 4.242,0 |
| 10 | `retry_policy` | `granite-4.1-8b` | 3 | 23,507s | **PASS** | Nenhuma (implementação e testes preservados com sucesso) | 6.870,0 |
| 11 | `dotenv_line_parser` | `qwen3.5-4b` | 3 | 23,310s | **PASS** | Nenhuma (testes unitários e sonda OK) | 4.244,0 |
| 12 | `dotenv_line_parser` | `granite-4.1-8b` | 3 | 19,242s | **FAIL** | Scope Violation (`ImportError: cannot import name 'normalize_key'`, suite mutilada) | 6.890,0 |

---

## 4. Síntese Comparativa Agregada

| Métrica | `retry_policy` (Qwen3.5-4B) | `retry_policy` (Granite 4.1 8B) | `dotenv_line_parser` (Qwen3.5-4B) | `dotenv_line_parser` (Granite 4.1 8B) |
|---|:---:|:---:|:---:|:---:|
| **Taxa de Sucesso Estrita** | **3/3 (100,0%)** | 1/3 (33,3%) | **3/3 (100,0%)** | 0/3 (0,0%) |
| **Tempo Mediano (Parede)** | **30,656 s** | 32,803 s | 23,310 s | **20,172 s** |
| **Tempo Mínimo** | 22,338 s | 23,507 s | 21,194 s | **19,242 s** |
| **Tempo Máximo** | **32,836 s** | 34,894 s | 23,387 s | **23,451 s** |
| **Pico VRAM Máximo** | **4.245,0 MiB** | 6.885,0 MiB | **4.244,0 MiB** | 6.890,0 MiB |
| **Overhead de VRAM** | Referência (0%) | **+62,2% (+2.640 MiB)** | Referência (0%) | **+62,3% (+2.646 MiB)** |
| **Taxa Geral da Suíte** | **6/6 (100,0%)** | **1/6 (16,7%)** | - | - |

---

## 5. Taxonomia e Diagnóstico das Falhas do Candidato

Embora Granite 4.1 8B tenha demonstrado excelente velocidade de decodificação bruta (~53 tokens/s) e tenha conseguido resolver o Ensaio 10 (`retry_policy` r3) com código de alta qualidade, o modelo apresentou **três patologias graves e recorrentes de adesão a contratos**:

1. **Violação Destrutiva de Escopo e Eliminação de Helpers (`dotenv_line_parser` - Ensaios 7 e 12):**
   - Ao implementar o parser, o modelo regravou `src/config_parser.py` eliminando a função auxiliar preexistente `normalize_key`.
   - Consequência: `ImportError: cannot import name 'normalize_key' from 'src.config_parser'`. A suíte adversarial de oráculo reprovou imediatamente a execução antes mesmo dos testes.

2. **Geração de Anotação de Tipo Inválida com Quebra em Tempo de Execução (`retry_policy` - Ensaio 5):**
   - Na assinatura de `execute_with_retry`, o modelo emitiu `on_retry: callable | None = None`. Em Python 3.10+, o operador `|` (PEP 604) funciona com tipos de classe ou `typing.Callable`, mas falha em tempo de execução quando aplicado sobre a função embutida `callable` (`builtin_function_or_method`).
   - Consequência: `TypeError: unsupported operand type(s) for |: 'builtin_function_or_method' and 'NoneType'` no momento do import do módulo.

3. **Mutilação e Reescrita de Arquivos de Teste (`tests/test_retry.py` e `tests/test_config_parser.py`):**
   - Em 5 dos 6 ensaios, o modelo tentou "resolver" a tarefa editando tanto o código-fonte quanto o arquivo de testes da suíte, reduzindo testes complexos a apenas 1 teste trivial (`Ran 1 test in 0.000s`) ou introduzindo quebras de contrato nos testes preexistentes.

---

## 6. Veredito e Decisão de Governança

- **Critério de Admissão:** Zero regressões catastróficas e taxa de sucesso compatível com o controle de referência ($\ge 50\%$).
- **Resultado Observado:** **1/6 (16,7% de aprovação)** contra **6/6 (100% de aprovação)** do controle Qwen3.5-4B.
- **Resposta à Pergunta da Tarefa 7:** O comportamento de ferramentas do Granite 4.1 8B **não compensa** seu footprint significativamente maior (+62% de VRAM, +77% de tamanho em disco). O modelo regride drasticamente em preservação de escopo e estabilidade de tipos em tarefas agentic.

**Decisão Formal:**
1. **REJEIÇÃO DE ADMISSÃO:** O modelo `IBM Granite 4.1 8B Q4_K_M` é **formalmente rejeitado** para operação no pool de roteamento do laboratório.
2. **Governança de Armazenamento:** Para preservar a cota estrita do SSD ext4 do WSL ($\ge 8\text{ GiB}$) e manter higiene de pesos não-operacionais, o arquivo `granite-4.1-8b-Q4_K_M.gguf` será arquivado no Drive E (`E:\LocalLLMLabArchive\models\granite-4.1-8b\`) com conferência de checksum SHA-256 e removido do SSD ext4.
3. **Pool Operacional Mantido:** `Qwen3.5-4B-Q4_K_M` (Tier 1) e `Qwen3.5-9B-Q4_K_M` (Tier 2) continuam como os únicos modelos admitidos e calibrados no laboratório.
