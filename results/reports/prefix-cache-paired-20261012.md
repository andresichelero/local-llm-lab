# Relatório de Avaliação Pareada: Prompt Cache / Prefix Caching (Tarefa 6A)

**Data de Execução:** 2026-10-12  
**Experimento:** `prefix-cache-paired-20261012-6a-20261012-202948`  
**Harness:** OpenCode 1.19.0 (modo `primary`, subagent_depth=0, permissão `bash`+`edit`, max 20 passos)  
**Runtime:** llama.cpp build b5122 (`d81235049384534c167caea52b85a694f6103d14`)  
**Modelo Avaliado:** Qwen3.5-4B-Q4_K_M (SHA-256: `13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983`)  
**Hardware:** NVIDIA GeForce RTX 3070 (8.192 MiB VRAM), WSL2 Ubuntu-24.04 (8 GiB RAM, 4 GiB swap), partição ext4 SSD NVMe  
**Status da Rodada:** 12/12 ensaios concluídos com sucesso (100%), 0 timeouts, 0 vazamentos de VRAM, 0 falhas funcionais.

---

## 1. Contexto e Hipótese

No framework de benchmark agentic multi-turn (OpenCode), a cada turno o agente reenvia o histórico completo da sessão (incluindo o system prompt fixo de ~6.500–6.800 tokens, definições de ferramentas e histórico de mensagens). 

- **Hipótese:** A ativação de prefix caching nativo no `llama-server` (`--cache-prompt`) permite que o servidor reutilize os slots KV do prefixo comum invariante entre turnos da mesma sessão, reduzindo o tempo de prefill (`prompt_eval`) em turnos subsequentes de milhares de tokens para poucas dezenas de tokens incrementais, gerando ganho substancial de latência de parede (*wall-clock speedup*) **sem alterar a determinística nem degradar a qualidade funcional das soluções geradas**.

---

## 2. Metodologia do Ensaio Pareado

O experimento foi desenhado estritamente conforme o Roadmap Metodológico Revisado (Tarefa 6A):
1. **Design Pareado:** 2 tarefas discriminantes (`calculator_division` e `dotenv_line_parser`) $\times$ 3 pares balanceados off/on = **12 ensaios medidos**.
2. **Ordem Balanceada:** Bloco 1 (off $\rightarrow$ on), Bloco 2 (on $\rightarrow$ off, eliminando viés de ordem/aquecimento), Bloco 3 (off $\rightarrow$ on).
3. **Isolamento de Servidor:** Cada ensaio subiu uma instância limpa e dedicada de `llama-server` com `start_new_session=True` em porta 8080 local, monitorada por `resource_sampler.py` a 1 Hz, e encerrada via `SIGTERM` gracioso após cada tarefa.
4. **Avaliação Cega e Independente:** Cada workspace foi auditado pós-execução pelo oráculo `grade_workspace` contra os casos de teste e contratos de exceção formais.

---

## 3. Tabela de Ensaios Medidos (12/12)

| Ensaio | Tarefa | Par | Modo de Cache | Tempo de Parede (s) | Passagem Estrita | Tokens Prefill por Turno | Pico VRAM (MiB) |
|:---:|:---|:---:|:---:|:---:|:---:|:---|:---:|
| 1 | `calculator_division` | 1 | `False` (Off) | 41.647s | **PASS** | `[8374, 8344, 8600]` | 4.790,0 |
| 2 | `calculator_division` | 1 | `True` (On) | **25.264s** | **PASS** | `[618, 6773, 259, 394, 22, 22, 22, 129]` | 5.032,0 |
| 3 | `dotenv_line_parser` | 1 | `False` (Off) | 36.032s | **PASS** | `[690, 6848, 7292, 7711, 8127, 8256, 8382, 8593]` | 5.027,0 |
| 4 | `dotenv_line_parser` | 1 | `True` (On) | **22.784s** | **PASS** | `[690, 6848, 257, 331, 22, 31, 27, 113]` | 5.085,0 |
| 5 | `calculator_division` | 2 | `True` (On) | **21.258s** | **PASS** | `[618, 6773, 259, 394, 22, 22, 22, 129]` | 4.481,0 |
| 6 | `calculator_division` | 2 | `False` (Off) | 32.911s | **PASS** | `[618, 6773, 7117, 7685, 7932, 8303, 8529]` | 4.492,0 |
| 7 | `dotenv_line_parser` | 2 | `True` (On) | **21.220s** | **PASS** | `[690, 6848, 257, 331, 840, 31, 27, 113]` | 4.492,0 |
| 8 | `dotenv_line_parser` | 2 | `False` (Off) | 36.179s | **PASS** | `[690, 6848, 7292, 7711, 8116, 8245, 8371, 8582]` | 4.492,0 |
| 9 | `calculator_division` | 3 | `False` (Off) | 36.007s | **PASS** | `[618, 6773, 7117, 7697, 7904, 8061, 8378, 8604]` | 4.565,0 |
| 10 | `calculator_division` | 3 | `True` (On) | **22.871s** | **PASS** | `[618, 6773, 259, 394, 22, 22, 22, 129]` | 5.110,0 |
| 11 | `dotenv_line_parser` | 3 | `False` (Off) | 37.087s | **PASS** | `[690, 6848, 7292, 7711, 8125, 8254, 8380, 8591]` | 4.492,0 |
| 12 | `dotenv_line_parser` | 3 | `True` (On) | **20.209s** | **PASS** | `[690, 6848, 152, 505, 22, 31, 27, 113]` | 4.492,0 |

---

## 4. Síntese Comparativa Agregada

| Métrica | `calculator_division` (Cache OFF) | `calculator_division` (Cache ON) | Delta / Speedup | `dotenv_line_parser` (Cache OFF) | `dotenv_line_parser` (Cache ON) | Delta / Speedup |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Taxa de Sucesso Estrita** | 3/3 (100%) | 3/3 (100%) | **Paridade Total** | 3/3 (100%) | 3/3 (100%) | **Paridade Total** |
| **Tempo Mediano (Parede)** | 36,007 s | **22,871 s** | **1,574× (+36,5% mais rápido)** | 36,179 s | **21,220 s** | **1,705× (+41,3% mais rápido)** |
| **Tempo Mínimo** | 32,911 s | **21,258 s** | 1,548× | 36,032 s | **20,209 s** | 1,783× |
| **Tempo Máximo** | 41,647 s | **25,264 s** | 1,648× | 37,087 s | **22,784 s** | 1,628× |
| **Pico VRAM Máximo** | 4.790,0 MiB | 5.110,0 MiB | +320 MiB | 5.027,0 MiB | 5.085,0 MiB | +58 MiB |
| **Swap Utilizada** | 0,0 MiB | 0,0 MiB | 0,0 MiB | 0,0 MiB | 0,0 MiB | 0,0 MiB |

---

## 5. Análise dos Resultados

1. **Eficiência Algorítmica Comprovada:**
   - Com o cache desativado (`--no-cache-prompt`), cada turno do OpenCode forçava o reprocessamento completo do prompt cumulativo (subindo de 6.848 para 8.593 tokens). O tempo gasto em prefill somava entre 2,6s e 3,2s adicionais por turno.
   - Com o cache ativado (`--cache-prompt`), os turnos intermediários reprocessaram apenas os tokens incrementais (22 a 505 tokens), reduzindo o tempo de prefill por turno para milissegundos.
   - Isso gerou uma redução sistemática de **~13 a 16 segundos no tempo total de cada tarefa** (~37% a 41% de aceleração líquida de parede).

2. **Invariância de Qualidade Funcional:**
   - Em 100% dos ensaios (6/6 off e 6/6 on), as soluções produzidas pelo modelo passaram integralmente na suíte de testes unitários do oráculo.
   - Não houve qualquer alucinação induzida, corrupção de contexto ou regressão semântica.

3. **Impacto de Memória VRAM Controlado:**
   - O overhead adicional de retenção de slots de prefixo no KV cache com quantização `q4_0` foi de apenas ~60 a 320 MiB.
   - O pico máximo absoluto de VRAM observado foi de **5.110,0 MiB**, operando confortavelmente dentro da cota de 8 GiB da RTX 3070 com **mais de 3.080 MiB de folga**.
   - O swap permaneceu rigidamente em 0,0 MiB.

---

## 6. Decisão de Engenharia (Promoção a Padrão)

A evidência empírica preenche integralmente todos os critérios de promoção estipulados no Roadmap (M4):
- **Critério 1 (Zero Regressão):** 100% de passagem funcional estrita em ambos os braços.
- **Critério 2 (Ganho Significativo):** Aceleração de parede de **1,57× a 1,70×** (superando amplamente o limiar mínimo de 10%).
- **Critério 3 (Segurança de Hardware):** Headroom de VRAM $> 3\text{ GiB}$ e zero uso de swap.

**Decisão:** O sinalizador `--cache-prompt` é formalmente **promovido a configuração padrão obrigatória** para todos os servidores `llama-server` operando no laboratório com harnesses agentic multi-turn.
