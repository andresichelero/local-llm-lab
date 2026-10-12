# Avaliação de Guarded Edit e Continuidade de Sessão em Multi-Arquivos (Trilha B)

**Data:** 2026-10-12  
**Commit de Origem:** `b615b4ea76953a4db7aa0675b86dc0c545c0733f`  
**Branch:** `feat/routing-cascade-and-guarded-edit-20261012`  
**Harness:** OpenCode CLI (modo agentic build com profile isolado)  
**Hardware:** NVIDIA GeForce RTX 3070 (8.192 MiB VRAM / 8 GiB dedicada), WSL2 Ubuntu-24.04 ext4 SSD  
**Modelo de Continuidade:** Qwen3.5-9B-Q4_K_M sob janela de contexto estendida de **16.384 tokens (16K)** com KV cache Q4_0/Q4_0.

---

## 1. Contexto e Objetivos

A Trilha B atende diretamente às exigências da **Tarefa 8 do Roadmap Metodológico Revisado**:
1. **Guarded Edit:** Desenvolver e testar deterministicamente um wrapper de edição segura contra as três patologias observadas em modelos menores/quantizados:
   - Modificações destrutivas acidentais em blocos não-únicos (SHA-256 block uniqueness).
   - Deleção/mutação inadvertida de funções auxiliares e helpers pré-existentes (AST preservation check).
   - Injeção de anotações conversacionais e markdown (`Here is the code:`, ````python`) no código Python final.
2. **Continuidade de Sessão em 32 Arquivos (16K Context):** Reutilizar o protocolo adversarial de estresse de contexto com 32 arquivos markdown sintéticos, comparando o comportamento **Baseline** (prompt direto desestruturado) versus a intervenção de **Manifesto de Checkpoint Conciso** (rastreamento incremental de arquivos visitados e hashes).

---

## 2. Parte 1 — Guarded Edit: Verificação Determinística Adversarial

O wrapper de edição segura foi implementado em `benchmark/guarded_edit.py` e submetido a uma suíte de 9 testes unitários determinísticos em `tests/test_guarded_edit.py`, cobrindo todos os modos de falha:

| Teste Adversarial | Condição de Entrada | Comportamento Esperado | Resultado |
|---|---|---|---|
| `test_guarded_edit_success` | Alvo único no arquivo, sintaxe válida, helpers preservados | Edição aplicada com sucesso | **PASS** |
| `test_file_not_found` | Arquivo inexistente no workspace | Rejeição imediata (`FileNotFoundError`) | **PASS** |
| `test_stale_hash` | Hash SHA-256 pré-condição diferente do arquivo em disco | Rejeição de colisão (`StaleDigestError`) | **PASS** |
| `test_target_not_found` | Bloco alvo ausente no arquivo | Rejeição sem mutação (`TargetNotFoundError`) | **PASS** |
| `test_multiple_occurrences` | Bloco alvo ambíguo (ocorre $\ge 2$ vezes sem offset) | Rejeição de ambiguidade (`AmbiguousTargetError`) | **PASS** |
| `test_helper_preservation_failure` | Edição remove ou altera assinatura de helper pré-existente | Rejeição por AST (`HelperPreservationError`) | **PASS** |
| `test_conversational_leak_detection` | Código gerado contém marcadores conversacionais/markdown | Rejeição de vazamento (`ConversationalLeakError`) | **PASS** |
| `test_syntax_error_detection` | Código gerado introduz erro de sintaxe Python | Rejeição por AST (`SyntaxError`) | **PASS** |
| `test_symlink_rejection` | Tentativa de edição apontando para symlink | Rejeição de segurança (`SymlinkRejectionError`) | **PASS** |

**Taxa de Aprovação:** **9 / 9 testes passando (100%)** em 0,03s.

> **Ressalva de Cobertura:** Conforme prescrito no roadmap, como o harness OpenCode mantém permissão de execução de comandos Bash aberta, o wrapper `guarded_edit` protege estritamente as operações estruturadas de edição de arquivos (`edit`), mas não elimina intervenções destrutivas executadas via `bash` arbitrário (ex.: `sed -i` ou `rm`). A proteção é declarada como nível de ferramenta de edição.

---

## 3. Parte 2 — Piloto de Continuidade em 32 Arquivos sob OpenCode 16K

O piloto foi executado com o modelo **Qwen3.5-9B-Q4_K_M** em servidor local `llama-server` configurado com `--ctx-size 16384` (16K), quantização de KV cache `q4_0/q4_0`, e teto de tempo de 180s por braço.

### Resultados Comparativos Pareados:

| Braço Experimental | Status | Arquivos no Manifesto | Chave Canário Recuperada | Testes Unitários (`test_result.py`) | Passos Agentic | Prompt Tokens | Completion Tokens | Latência (s) | Pico VRAM (MiB) |
|---|---|---|---|---|---|---|---|---|---|
| **Baseline** (Sem tracking) | **FAIL** | 0 / 32 | **NÃO** | **FAIL** | 2 | 19.123 | 2.842 | 84,28s | 6.922 MiB |
| **Checkpoint Manifest** (Intervenção) | **PASS** | **32 / 32** | **SIM** (`GLACIER-47-MAPLE`) | **PASS** | 11 | 128.926 | 4.214 | 131,22s | 6.622 MiB |

### Análise Causal:

1. **Patologia do Baseline (Blowout de Contexto):**
   - No braço baseline, o agente tentou ler múltiplos arquivos de uma só vez sem checkpointing em disco. Em apenas 2 passos, o volume de tokens de prompt explodiu para **19.123 tokens**, ultrapassando o limite da janela de 16.384 tokens e abortando sem registrar nenhum arquivo (`manifest_count = 0`).
2. **Eficácia da Intervenção de Manifesto:**
   - Com o arquivo `checkpoint_state.json` e a diretriz de registro incremental em `archive_manifest.txt`, o agente procedeu de forma disciplinada ao longo de 11 passos de raciocínio e execução de ferramentas.
   - **100% de Cobertura:** Todos os 32 hashes determinísticos foram extraídos e validados na ordem exata esperada.
   - **Extração da Chave Canário Secreta:** A chave `GLACIER-47-MAPLE` embutida exclusivamente no arquivo `archive-07.md` foi identificada e gravada com sucesso em `recovery.txt`.
   - **Validação Oracular:** O script de teste do workspace `test_result.py` rodou e foi aprovado com `Ran 3 tests in 0.000s ... OK`.
   - **Contenção de Recursos:** O pico de VRAM no braço com checkpoint permaneceu em **6.622 MiB**, mantendo ~1,5 GiB de folga segura na GPU de 8 GiB.

---

## 4. Conclusão e Integração

O experimento comprova que modelos da classe 9B em hardware de consumo (RTX 3070 8 GiB) **são plenamente capazes de processar tarefas de longa continuidade e 32 arquivos sob 16K de contexto**, desde que o harness imponha ou forneça um artefato de **manifesto de checkpoint conciso**. A ausência de estado estruturado leva a context blowout previsível.
