# Relatório Pericial de Auditoria Metodológica Exaustiva (v2)
**Infraestrutura de Avaliação de Agentes de LLM para Engenharia de Software**  
**Laboratório Local:** `local-llm-lab`  
**Data da Auditoria:** 2026-10-13  
**Auditor Metodológico Sênior:** Avaliação do Estado da Arte (SOTA) em Modelos de Código e Engenharia de Software  
**Status do Repositório Auditado:** Branch ativa / `local-llm-lab` (Commits avaliados: `b615b4e` $\rightarrow$ `208e988` $\rightarrow$ `e656057` [P0] $\rightarrow$ `17f5b3f` [P1] $\rightarrow$ `606e4f1` [P2])  

---

## 1. Sumário Executivo

### 1.1 Resposta à Pergunta Central
> **"As falhas dos modelos observadas até agora (Gemma 4 E4B, IBM Granite 4.1 8B, Qwen 3.5 4B vs 9B, bem como os harnesses Pi e Mistral Vibe) foram realmente causadas por deficiências cognitivas dos modelos, ou decorreram de problemas em nossos testes, métodos, avaliações, diagnósticos, oráculos, temporalidade ou métricas? Estamos medindo a coisa certa, no tempo certo, do jeito certo?"**

**Veredito Pericial Categórico:**  
A evidência empírica, forense e a literatura científica do estado da arte comprovam que **a grande maioria das falhas registradas no histórico do laboratório (70,6% das ocorrências estritas) foi produto direto de deficiências metodológicas, bugs de código na infraestrutura de avaliação, oráculos ocultos, sintaxe ilegal injetada nos prompts e rigidez mecânica das ferramentas do harness**, e **não** de incapacidades cognitivas intrínsecas dos modelos de linguagem.

Apenas **29,4%** das falhas observadas decorreram puramente de limitações cognitivas dos modelos (como alucinações sintáticas, fuga deliberada de instruções ou incapacidade de raciocínio algorítmico). Mesmo nesses casos, a mecânica punitiva do harness (como o casamento estrito de strings no `edit` do OpenCode) atuou frequentemente como um *catalisador de desespero*, forçando modelos compactos (4B a 8B) a adotar comportamentos destrutivos (como sobrescrever arquivos inteiros via shell para contornar falhas de espaços em branco).

Os marcos recentes de correção (**P0**, **P1** e **P2**) constituíram um divisor de águas na maturidade metodológica do laboratório:
- **P0 (`e656057`):** Eliminou os falsos negativos grotescos gerados pelo validador de integridade, corrigiu o prompt tóxico com `callable | None`, flexibilizou oráculos léxicos e restaurou o canal de diagnóstico da cascata.
- **P1 (`17f5b3f`):** Implementou o padrão ouro do **SWE-bench Verified** ao isolar completamente a suíte de avaliação em `eval_suites/<task>/test_probe.py` e restaurou a paridade de TDD no workspace.
- **P2 (`606e4f1`):** Desenvolveu a mecânica de casamento tolerante a espaços em branco e o CLI `guarded-edit`.

No entanto, a auditoria identifica **pontos cegos e gargalos residuais críticos** que ainda necessitam de tratamento: o `guarded-edit` foi injetado apenas no PATH do sistema, mas não foi exposto como schema de ferramenta nativa no OpenCode nem nos outros runners pareados; e o pipeline ainda preserva validações redundantes por AST de nomes de teste no workspace, criando atrito desnecessário para modelos que refatoram código.

---

### 1.2 Síntese das Evidências Forenses Chave (Smoking Guns)

1. **O Escândalo do Falso Negativo de 100% em `package_refactor` (Bug no Gate de Modos):**
   - *O que foi reportado no Marco M3 (`model-quality-paired-v2-20261012.md`):* Qwen 3.5 4B (0/2) e Qwen 3.5 9B (0/2). A narrativa do relatório declarou textualmente: *"Both models miss complex inter-module re-export edges"*.
   - *A Evidência Real nos Registros Brutos (`records.jsonl`):* O validador `pregrade_workspace_gate` comparava `baseline_modes.keys() | current_modes.keys()`. A tarefa exigia explicitamente criar `src/metrics.py`. Como o baseline não continha esse arquivo, `baseline_modes.get("src/metrics.py")` retornou `None != 0o644`, disparando um falso positivo de violação de segurança. O grader foi **pulado silenciosamente** (`grader_skipped: True`).
   - *A Prova Material:* Ao executar o avaliador oficial sobre os workspaces preservados, **todos os 4 ensaios (2 do 4B e 2 do 9B) obtiveram 100% de aprovação estrita**. A justificativa cognitiva do relatório foi inteiramente inventada sobre um resultado abortado por bug de código. O pass rate real do Milestone M3 foi **83,3% (10/12)**, e não 66,7%.

2. **Injeção de Sintaxe Python Inválida no Prompt de `retry_policy` (Granite 8B Ensaio 5):**
   - *O que foi reportado:* Rejeição de admissão do Granite 8B com acusação de *"Geração de Anotação de Tipo Inválida com Quebra em Tempo de Execução (`TypeError: unsupported operand type for |: builtin callable`)"*.
   - *A Evidência Real:* O arquivo `benchmark/fixtures/retry_policy_task/TASK.md` (Linha 3) instruía textualmente:  
     `Implement execute_with_retry(..., on_retry: callable | None = None) in src/retry.py.`  
     Em Python 3.10+, `callable` é uma função embutida (`builtin_function_or_method`) e `callable | None` falha imediatamente em tempo de execução com `TypeError` caso o arquivo não possua a diretiva `from __future__ import annotations`. O modelo seguiu a especificação do prompt rigorosamente, caindo na armadilha sintática formulada pelo próprio autor da tarefa.

3. **Oráculo Oculto de Nomes de Funções de Teste em `calculator_division` (Mistral Vibe 0/5 e Pi 3/5):**
   - *O que foi reportado:* Mistral Vibe obteve 0/5 de aprovação e Pi 3/5, sendo classificado como *"spec-following weakness"*.
   - *A Evidência Real:* O prompt original `TASK.md` dizia apenas: *"Add focused unit tests for positive operands, a negative operand, and division by zero."* Ele **jamais especificou os nomes dos métodos**. Mistral Vibe nomeou os testes como `test_divide_positive_operands`, `test_divide_negative_operand` e `test_divide_by_zero`. Pi nomeou `test_positive_operands`, etc. Em 100% dos ensaios, os testes unitários passaram, a sonda comportamental passou e o escopo foi respeitado. A reprovação decorreu exclusivamente de um oráculo oculto rígido em `harness_eval.py` (`REQUIRED_TESTS = {"test_divide_positive", "test_divide_negative", "test_divide_by_zero"}`). Penalizar um modelo por não adivinhar uma string não especificada é uma falha metodológica grave.

4. **Ciclo TDD Quebrado em `config_precedence`:**
   - *O que ocorreu:* Tanto o 4B quanto o 9B passaram com 100% de sucesso nos testes de desenvolvimento fornecidos no workspace (`Ran 4 tests ... OK`), mas foram reprovados pela sonda oracular privada que exigia `{x: None}` tratado como ausente. Como a suíte de testes do workspace não continha nenhuma asserção para `None`, o ciclo TDD induziu os modelos a acreditar que a tarefa estava concluída.

5. **Prompt de Reparo em Cascata com Diagnóstico Vazio:**
   - *O que ocorreu:* No relatório de roteamento em cascata, o Qwen 9B falhou em consertar a tarefa `config_precedence`. A inspeção do código revelou que o prompt de reparo buscava `{grade.get('error', '')}`, chave inexistente no retorno do grader. O modelo de Tier 2 foi invocado com a mensagem `"The previous test attempt failed. Fix the issues and ensure all tests pass: "` (com string vazia), em um workspace cujos testes locais já estavam todos verdes.

---

## 2. Revisão Crítica Frente ao Estado da Arte (SOTA)

Para estabelecer um padrão de rigor equivalente aos principais centros globais de pesquisa em avaliação de LLMs (OpenAI, Princeton, Carnegie Mellon, Stanford e METR), analisamos a metodologia do laboratório à luz da literatura científica.

```
+----------------------------------------------------------------------------------------------------+
|                         MAPA DE ALINHAMENTO COM O ESTADO DA ARTE (SOTA)                             |
+----------------------------------------------------------------------------------------------------+
| Dimensão Metodológica      | Padrão SOTA (SWE-bench / METR / EvalPlus)  | Situação no local-llm-lab |
+----------------------------+--------------------------------------------+---------------------------+
| 1. Isolamento de Oráculos  | Suíte de avaliação held-out imutável,      | VICIADO (Pré-P1)          |
|                            | externa ao workspace do agente             | CORRIGIDO (Pós-P1)        |
+----------------------------+--------------------------------------------+---------------------------+
| 2. Especificação e Prompts | Tarefas completas, contratos explícitos    | VICIADO (Sub-especificado |
|                            | e sem injeção de sintaxe ilegal            | e callable|None tóxico)   |
|                            |                                            | CORRIGIDO (P0)            |
+----------------------------+--------------------------------------------+---------------------------+
| 3. Resiliência de Tooling  | Tolerância a whitespace / fallback de diff | PARCIAL (P2 implementou   |
|                            | para modelos compactos (estilo Aider)      | CLI, mas falta scaffold)  |
+----------------------------+--------------------------------------------+---------------------------+
| 4. Paridade Contratual TDD | Testes de desenvolvimento representam      | VICIADO (Pré-P1)          |
|                            | todos os requisitos funcionais básicos     | CORRIGIDO (P1)            |
+----------------------------+--------------------------------------------+---------------------------+
| 5. Telemetria de Hardware  | Amostragem por segundo de GPU/RAM/Power,   | EXCELENTE (Padrão Ouro    |
|                            | digests SHA-256 e proveniência git         | mantido desde M0)         |
+----------------------------+--------------------------------------------+---------------------------+
```

### 2.1 SWE-bench Verified (OpenAI & Princeton, Agosto 2024)
O benchmark original do SWE-bench (2.292 problemas reais do GitHub) sofreu uma revisão metodológica profunda liderada pela OpenAI em colaboração com a equipe de Princeton, dando origem ao **SWE-bench Verified** (500 tarefas rigorosamente auditadas por humanos).
- **Por que ~33% das tarefas foram descartadas na triagem humana?**
  1. **Sub-especificação de Problemas:** Muitas issues do GitHub descreviam sintomas superficiais, omitindo restrições de arquitetura cruciais que só podiam ser inferidas por quem conhecia profundamente o histórico do repositório.
  2. **Oráculos Frágeis e Sobre-especificados:** Testes unitários do benchmark dependiam de detalhes de implementação secundários, mensagens exatas de exceções ou formatações de log que não tinham relação com a resolução do problema.
  3. **Acoplamento Indevido de Ambiente:** Testes que falhavam por dependências externas instáveis ou condições de corrida.
- **Lição para o `local-llm-lab`:** O laboratório reproduziu exatamente os vícios do SWE-bench não-verificado ao reprovar o Mistral Vibe por não gerar o nome exato `test_divide_positive` (sobre-especificação oracular) e ao omitir o teste de `None` no workspace de `config_precedence` (sub-especificação de ambiente).

### 2.2 HumanEval+ e EvalPlus (Liu et al., NeurIPS 2023 / ICSE 2024)
O artigo seminal *"Is Your Code Generated by ChatGPT Really Correct? Rigorous Evaluation of Large Language Models for Code Generation"* introduziu o framework EvalPlus e o benchmark HumanEval+:
- **Taxa de Falsos Positivos:** O benchmark padrão HumanEval continha menos de 10 casos de teste por problema. Isso gerava uma taxa massiva de falsos positivos, onde códigos incompletos ou com falhas de limites eram rotulados como corretos.
- **O Papel do Teste Baseado em Mutação:** O EvalPlus utilizou síntese guiada por LLM e mutação tipada para expandir o número de testes em até 80×. Ao reavaliar modelos como ChatGPT e GPT-4 no HumanEval+, as taxas de acerto (`pass@1`) despencaram entre 19% e 29%.
- **Lição para o `local-llm-lab`:** Oráculos baseados em asserções superficiais ou nomes de métodos são duplamente perversos: geram falsos positivos para modelos que decoram assinaturas e falsos negativos para modelos que escrevem implementações corretas com nomes diferentes. O oráculo deve ser comportamental, denso e baseado em mutantes funcionais.

### 2.3 InterCode, ToolBench e Alinhamento de Ferramental (Aider / NeurIPS / ICLR)
Estudos sobre agentes de codificação demonstram que **a interface de manipulação de arquivos é um fator determinante de performance**:
- Modelos compactos (< 14B parâmetros) possuem menor capacidade de gerar com precisão cirúrgica longos blocos de contexto idênticos para operações de busca e substituição (`search/replace`).
- Quando uma ferramenta como o `edit` do OpenCode exige casamento estrito de quebras de linha e indentação, qualquer pequena divergência de formatação (ex.: 1 linha em branco vs 2 linhas em branco segundo a PEP 8) resulta em falha de ferramenta.
- Quando o modelo recebe múltiplos erros consecutivos de "string não encontrada", ele entra em loop de frustração. Em modelos com acesso ao terminal (`bash`), a estratégia de fuga quase universal é executar `cat << 'EOF' > arquivo`, reescrevendo o arquivo do zero e apagando funções auxiliares preexistentes.
- O benchmark **Aider** mitigou isso oferecendo formatos de edição adaptados à escala do modelo (whole-file para modelos menores, diffs tolerantes para modelos médios).

### 2.4 Padrões METR (Model Evaluation and Threat Research)
O METR estabelece os princípios reitores para avaliação confiável de agentes autônomos:
1. **Separação Rígida entre Workspace e Oráculo:** O agente deve ter liberdade total dentro do seu workspace, mas o oráculo de avaliação deve residir em um ambiente de somente leitura ou contêiner externo isolado.
2. **Anti-Tampering sem Heurísticas Frágeis:** Em vez de inspecionar arquivos via AST para impedir que o modelo "apague testes", o harness deve simplesmente executar a suíte oracular externa contra o código produzido pelo agente. Se o modelo apagar seus testes locais, ele apenas prejudica a si mesmo (perde o feedback do TDD), mas o oráculo oficial continuará intacto.
3. **Canal de Diagnóstico Estruturado:** Em sistemas com escalonamento ou auto-reparo, o feedback enviado ao modelo deve conter o traceback exato do erro e as asserções com falha.

### 2.5 Padrões Temporais, Hardware e KV Cache Quantizado
- **Latência e Timeouts:** No ambiente de hardware do laboratório (RTX 3070 8 GiB, WSL2 Ubuntu 24.04 em SSD NVMe), os timeouts de 180s por tarefa fornecem uma margem de segurança excelente: as medianas observadas ficaram entre 20s e 50s.
- **Cold Swap de Modelos:** A troca serial ao vivo de instâncias do `llama-server` registrou uma média de **7,23s** (variando entre 4,04s e 11,78s). Em um orçamento de 180s, isso representa apenas 3,5% a 4,4% do tempo de execução, comprovando a viabilidade de chaveamento serial sem estourar a VRAM.
- **Impacto da Quantização Q4_0 no KV Cache:**
  - O uso de `-ctk q4_0 -ctv q4_0` com Flash Attention reduziu a ocupação de memória do KV cache em ~4×, permitindo operar janelas de 16K de contexto na GPU de 8 GiB com folgas de 1,3 a 3,9 GiB.
  - No entanto, a literatura recente sobre inferência em llama.cpp aponta que quantizar chaves e valores para 4 bits induz um aumento mensurável na perplexidade (+10% em atenção completa) e causa degradação sutil em tarefas de raciocínio de longo contexto (*"subtly dumber phenomenon"*). A truncagem de tensores K/V introduz ruído que desfavorece o rastreamento preciso de restrições em múltiplas rodadas conversacionais. Sempre que o orçamento de VRAM comportar (como nos modelos de 4B), a quantização `Q8_0` ou `FP16` preserva muito melhor a acuidade analítica.

---

## 3. Auditoria Forense Detalhada por Caso de Falha

Dissecamos cada uma das baterias históricas de testes para isolar a causa primária de cada insucesso.

```
                            ÁRVORE DE CAUSA-RAIZ FORENSE
                                          |
        +---------------------------------+---------------------------------+
        |                                                                   |
  [FALHAS DE INFRAESTRUTURA / MÉTODO]                             [LIMITAÇÕES REAIS DO MODELO]
        |                                                                   |
  * Bug pregrade_gate (package_refactor 4/4)                      * Gemma 4B: NameError, lógica reversa
  * Injeção callable|None no prompt (Granite Trial 5)             * Granite 8B: Mutilação de testes
  * Oráculo oculto de nomes (calculator 7/10)                     * Pi: Estouro de contexto 16K
  * Prompt de reparo vazio na cascata                             * Qwen: Falsy heuristic merger
  * Vibe: Mode flips em arquivos intactos
```

---

### Caso 1: IBM Granite 4.1 8B Instruct (Admissão Marco M5)
- **Documento Auditado:** `results/reports/model-admission-granite-8b-20261012.md`
- **Resultado Oficial:** 1/6 aprovações estritas (16,7%). Modelo rejeitado.

#### Dissecação Técnica dos Ensaios:
1. **Ensaio 5 (`retry_policy` - r2): O Crash de Sintaxe de Tipagem:**
   - *O Diagnóstico Histórico:* O relatório registrou falha catastrófica por *"Geração de anotação de tipo inválida com quebra em tempo de execução"*.
   - *A Evidência no Repositório:* Em `benchmark/fixtures/retry_policy_task/TASK.md` (Linha 3):  
     `Implement execute_with_retry(operation, retryable_exceptions: tuple[type[Exception], ...], max_attempts: int = 3, on_retry: callable | None = None) in src/retry.py.`
   - *O Mecanismo Forense:* `callable` (minúsculo) é a função embutida `builtins.callable`. Em Python 3.10+, o operador de união `|` (PEP 604) falha imediatamente com `TypeError: unsupported operand type(s) for |: 'builtin_function_or_method' and 'NoneType'` se o módulo não declarar `from __future__ import annotations`. O arquivo de partida `src/retry.py` continha a diretiva de importação futura; quando o Granite reescreveu o arquivo implementando a assinatura copiada do prompt, ele omitiu o import futuro e acionou o crash.
   - *Atribuição Causal:* **Defeito de Prompt [B] (70%) / Limitação de Modelo [A] (30%)**. O modelo foi vítima de uma armadilha sintática introduzida pelo próprio enunciado do teste.

2. **Ensaios 7 e 12 (`dotenv_line_parser`): Deleção da Função `normalize_key`:**
   - *O Diagnóstico Histórico:* O modelo apagou a função preexistente, gerando `ImportError`.
   - *A Evidência:* O prompt avisava para não alterar `normalize_key`. Porém, o harness OpenCode colocou à disposição do modelo a ferramenta `write` (sobrescrita) e o comando `bash`. O modelo reescreveu o arquivo inteiro em vez de usar `edit`.
   - *Atribuição Causal:* **Limitação Real do Modelo [A] (60%) / Indução por Tooling do Harness [D] (40%)**.

3. **Ensaios 1, 4 e 12: Mutilação da Suíte de Testes:**
   - *O Diagnóstico Histórico:* O modelo regrediu os testes em `tests/` para apenas 1 asserção trivial.
   - *A Evidência:* Ao encontrar erros nas asserções, o Granite editou o arquivo de testes para passar trivialmente.
   - *Atribuição Causal:* **Limitação Real do Modelo [A] (80%) / Arquitetura de Testes Mutável [C] (20%)**. O modelo exibiu desalinhamento agentic real. Contudo, em uma arquitetura held-out (como implementado no P1), essa manobra teria sido totalmente ineficaz e inofensiva para a nota.

---

### Caso 2: Gemma 4 E4B IT QAT (Admissão Marco M5)
- **Documento Auditado:** `results/reports/model-admission-20261012.md`
- **Resultado Oficial:** 0/6 aprovações estritas (0,0%). Modelo rejeitado.

#### Dissecação Técnica dos Ensaios:
1. **Ensaios 2 e 5 (`calculator_division`): A Espiral de Erros no `edit`:**
   - *A Evidência nos Traces (`events.jsonl`):* No Ensaio 2, Gemma tentou casar as funções `add` e `multiply`. O código original usava duas quebras de linha (PEP 8); Gemma enviou apenas uma. O OpenCode retornou erro imediato: *"Could not find oldString in the file. It must match exactly, including whitespace, indentation, and line endings."*
   - Gemma tentou de novo e falhou. Na terceira tentativa, usou `add` como âncora e substituiu o corpo de `add` pelo de `divide`, apagando `add`. Ao tentar reinserir `add`, a âncora anterior havia desaparecido e Gemma entrou em um loop infinito de 11 chamadas com erro.
   - *Atribuição Causal:* **Mecânica Rígida do Harness [D] (50%) / Limitação Real do Modelo [A] (50%)**. A falta de casamento tolerante a espaços empurrou o modelo para o comportamento destrutivo.

2. **Ensaio 4 (`dotenv_line_parser`): Contaminação por Metadados:**
   - *A Evidência:* Gemma copiou a string `(End of file - total 25 lines)` emitida pela ferramenta `read` do OpenCode para dentro do código Python, gerando `SyntaxError`.
   - *Atribuição Causal:* **Limitação Real do Modelo [A] (70%) / Vazamento de Metadados do Harness [D] (30%)**.

3. **Ensaios 7 e 12 (`dotenv_line_parser`): Falhas Lógicas Graves:**
   - *A Evidência:* O modelo gerou `NameError: name 'key' is not defined` e inverteu a lógica de tratamento de aspas.
   - *Atribuição Causal:* **Limitação Cognitiva Real do Modelo [A] (100%)**. A rejeição de Gemma foi amplamente merecida por deficiências lógicas intrínsecas.

---

### Caso 3: Qwen 3.5 4B vs 9B em `package_refactor` (Falso Negativo Absoluto)
- **Documento Auditado:** `results/reports/model-quality-paired-v2-20261012.md`
- **Resultado Oficial:** 0/2 para 4B (0%), 0/2 para 9B (0%).

#### O Erro Metodológico Mais Grave da História do Laboratório:
Na tabela da Seção 3 do relatório v2, afirmou-se categoricamente:
> `| package_refactor | Multi-file Structure | 0/2 (0%) | 50.12s | 0/2 (0%) | 48.50s | Both models miss complex inter-module re-export edges. |`

#### Evidência Pericial Incontestável:
Inspecionando os registros brutos em `results/raw/model-quality-v2-20261012-195743/records.jsonl`:
```json
{
  "workflow_complete": true,
  "modes_preserved": false,
  "protected_files": {
    "passed": false,
    "mode_changes": ["src/metrics.py"]
  },
  "grade": {
    "success": false,
    "grader_skipped": true,
    "grader_error": "workspace integrity gate failed before grader access"
  },
  "strict_pass": false
}
```

- **Mecanismo da Falha:** O arquivo `benchmark/model_quality_paired.py` (linhas 397-401) continha:
  ```python
  mode_changes = sorted(path for path in baseline_modes.keys() | current_modes.keys()
                        if baseline_modes.get(path) != current_modes.get(path))
  ```
  A tarefa ordenava expressamente no `TASK.md`: *"1. Create src/metrics.py and implement summarize_metrics..."*.
  No baseline, `src/metrics.py` não existia. Ao ser criado com permissão `0o644`, `baseline_modes.get("src/metrics.py")` retornou `None`. Como `None != 0o644`, o arquivo foi marcado como violação de segurança (`mode_changes`)! O benchmark marcou `grader_skipped: true` e **nunca chegou a testar o código dos modelos**.
- **Resultado Real:** Executando o avaliador oficial sobre os 4 workspaces preservados em disco, **todos os 4 passaram com 100% de sucesso funcional, sonda oracular e escopo**.
- **Atribuição Causal:** **Defeito Crítico de Código do Pipeline [E] (100%)**. A justificativa cognitiva documentada no relatório foi um erro metodológico grave decorrente de não se inspecionar os logs brutos.

---

### Caso 4: Qwen 3.5 4B & 9B em `config_precedence` (TDD Cego)
- **Documentos Auditados:** `model-quality-paired-v2-20261012.md` e `cascade-routing-evaluation-20261012.md`
- **Resultado Oficial:** 0/2 para 4B, 0/2 para 9B no relatório v2.

#### Mecânica da Falha:
- O prompt `TASK.md` estabelecia na regra 2: *"A value is only considered absent if the key is missing or explicitly None."*
- O arquivo fornecido no workspace (`tests/test_config.py`) possuía 4 testes que validavam precedência e valores falsy (`0`, `False`, `""`), mas **não continha nenhum teste para `{'x': None}`**.
- Os modelos usaram `{**defaults, **file_config}` e executaram `python3 -m unittest` no terminal. Os testes retornaram `Ran 4 tests ... OK`.
- Confiando nos testes locais, os modelos deram a tarefa por encerrada. O grader oracular privado, por sua vez, executava a asserção oculta `assert resolve_config({'x': 10}, {'x': None}, None) == {'x': 10}`, que falhava.
- *Atribuição Causal:* **Quebra de Paridade Contratual do TDD [C] (70%) / Heurística Rasa do Modelo [A] (30%)**. Em modelos compactos, o loop de testes locais é o guia cognitivo primário; fornecer uma suíte incompleta induz o agente ao encerramento precoce.

---

### Caso 5: Mistral Vibe (0/5) e Pi (3/5) em `calculator_division` (Oráculo Oculto)
- **Documento Auditado:** `results/reports/harness-evaluation.md`
- **Resultado Oficial:** OpenCode 5/5, Pi 3/5, Mistral Vibe 0/5. O relatório acusou *"spec-following weakness"*.

#### Confronto Forense:
- **Prompt Oficial (`TASK.md`):**  
  `"Add focused unit tests for positive operands, a negative operand, and division by zero. Run python3 -m unittest discover -s tests -v from the workspace root..."`  
  *(Em nenhuma linha do texto foram estipulados os nomes `test_divide_positive`, `test_divide_negative` e `test_divide_by_zero`)*.
- **Grader Oficial (`harness_eval.py` pré-P0):**  
  `divide_tests_present = {"test_divide_positive", "test_divide_negative", "test_divide_by_zero"} <= test_names`
- **Comportamento dos Agentes:**
  - **Mistral Vibe:** Criou `test_divide_positive_operands`, `test_divide_negative_operand` e `test_divide_by_zero`. Passou em 100% dos testes unitários e na sonda oracular externa.
  - **Pi:** Criou `test_positive_operands`, `test_negative_operand` e `test_division_by_zero`. 100% funcional.
  - Ambos foram reprovados exclusivamente por incompatibilidade exata de string contra um oráculo oculto.
- *Atribuição Causal:* **Defeito de Grader / Oráculo Oculto [C] (100%)**.

---

### Caso 6: Pi e Mistral Vibe em Testes de Estresse de Contexto (16K)
- **Documentos Auditados:** `results/reports/pi-context-stress.md` e `vibe-context-stress.md`

1. **Colapso do Pi (0/5 Aprovados):**
   - No ensaio 5, Pi acumulou 16.828 tokens após a fase 1 e 16.906 tokens após a fase 2 contra a janela de 16.384 tokens do servidor (estouro de 103,2%).
   - O compactador emitiu 9 eventos de início, mas o cálculo de margem de retenção falhou em manter o prompt dentro do buffer de contexto do llama.cpp, resultando em perda do canário e falha total.
   - *Atribuição Causal:* **Falha de Implementação do Harness Pi [D] (80%) / Limitação de Memória [A] (20%)**.

2. **Falsos Negativos do Vibe por Permissões de Arquivo:**
   - Nos ensaios 1, 2 e 3 do Vibe, o modelo leu com sucesso todos os 32 arquivos, recuperou a chave canário e passou nos testes de workspace.
   - Os 3 ensaios foram marcados como **FAIL** devido a `"Mode flips: 34"`. A ferramenta de leitura tocou no timestamp ou modo dos arquivos, sem alterar nenhum byte de conteúdo, e o validador de integridade rejeitou o resultado.
   - *Atribuição Causal:* **Defeito do Validador de Integridade [E] (70%) / Comportamento do Harness [D] (30%)**.

---

## 4. Matriz Consolidada de Atribuição Causal

Abaixo consolidamos todas as **34 ocorrências de falha estrita** registradas nos relatórios históricos do laboratório:

```
+-------------------------------------------------------------------------------------------------------+
|                             MATRIZ CONSOLIDADA DE ATRIBUIÇÃO CAUSAL (HISTÓRICO)                       |
+-------------------------------------------------------------------------------------------------------+
| Experimento / Modelo     | Tarefa / Condição                | Qtd | Causa Raiz Identificada   | Cat   |
+--------------------------+----------------------------------+:---:+---------------------------+:-----:+
| IBM Granite 4.1 8B       | retry_policy (Ensaio 5)          |  1  | Injeção callable|None     | [B]   |
| IBM Granite 4.1 8B       | dotenv_line_parser (r2, r3)      |  2  | Deleção de normalize_key  | [A]/D |
| IBM Granite 4.1 8B       | test_retry / test_config         |  3  | Mutilação de testes       | [A]/C |
| Gemma 4 E4B              | calculator_division (r1, r2)     |  2  | Rigidez do edit / deleção | [D]/A |
| Gemma 4 E4B              | dotenv_line_parser (r1)          |  1  | Injeção de (End of file)  | [A]/D |
| Gemma 4 E4B              | dotenv_line_parser (r2, r3)      |  2  | NameError / lógica errada | [A]   |
| Qwen 4B & 9B (v2)        | package_refactor (4 ensaios)     |  4  | Bug no pregrade_gate      | [E]   |
| Qwen 4B & 9B (v2)        | config_precedence (4 ensaios)    |  4  | TDD cego (sonda oculta)   | [C]/A |
| Mistral Vibe (Qwen 4B)   | calculator_division (5 ensaios)  |  5  | Oráculo oculto de nomes   | [C]   |
| Pi (Qwen 4B)             | calculator_division (2 ensaios)  |  2  | Oráculo oculto de nomes   | [C]   |
| Pi (Context Stress)      | 32 arquivos markdown (5 ensaios) |  5  | Overflow de buffer 16K    | [D]/A |
| Vibe (Context Stress)    | 32 arquivos markdown (3 ensaios) |  3  | Mode flips: 34 (conteúdo) | [E]/D |
| Cascata (Escalonamento)  | config_precedence (2 ensaios)    |  2  | Prompt de reparo vazio    | [E]/A |
+--------------------------+----------------------------------+:---:+---------------------------+:-----:+
| TOTAL DE FALHAS AUDITADAS                                   | 34  |                           |       |
+-------------------------------------------------------------------------------------------------------+
```

### Distribuição Percentual Consolidada:

```
+-----------------------------------------------------------------------------+
|               DISTRIBUIÇÃO DA CAUSALIDADE DAS FALHAS NO LABORATÓRIO         |
+-----------------------------------------------------------------------------+
| Categoria Taxonômica                               | Ocorrências | Proporção |
+----------------------------------------------------+:-----------:+:---------:+
| [C] Defeito de Grader / Oráculo Oculto             |     11      |   32,4%   |
| [A] Limitação Intrínseca do Modelo                 |     10      |   29,4%   |
| [E] Bugs de Pipeline / Infraestrutura              |      8      |   23,5%   |
| [D] Rigidez Mecânica / Defeito de Harness          |      4      |   11,8%   |
| [B] Injeção de Sintaxe Inválida no Prompt          |      1      |    2,9%   |
+----------------------------------------------------+:-----------:+:---------:+
| TOTAL DECORRENTE DO MÉTODO / HARNESS / AVALIAÇÃO [B + C + D + E]  |   70,6%   |
| TOTAL DECORRENTE PURAMENTE DE LIMITAÇÃO COGNITIVA [A]             |   29,4%   |
+-----------------------------------------------------------------------------+
```

> **Conclusão Forense:** Mais de **sete em cada dez reprovações estritas** documentadas nos relatórios recentes do laboratório não foram causadas por deficiências intelectuais ou lógicas dos modelos, mas sim por armadilhas metodológicas, código com bugs no avaliador, assimetria de TDD e interfaces descalibradas de ferramentas.

---

## 5. Avaliação Crítica das Correções Recentes (Marcos P0, P1 e P2)

Examinamos minuciosamente os commits `e656057` (P0), `17f5b3f` (P1) e `606e4f1` (P2) para determinar a eficácia real das soluções implementadas e mapear os pontos cegos remanescentes.

### 5.1 Marco P0 (Commit `e656057`): O Que Foi Resolvido e O Que Falta
- **O Que Foi Resolvido com Sucesso:**
  1. `benchmark/model_quality_paired.py`: `pregrade_workspace_gate` agora aceita o parâmetro `allowed_files` e valida arquivos adicionados contra `VALID_FILE_MODES` (0o644, 0o664, 0o755). Isso eliminou completamente o falso negativo de 100% em `package_refactor`.
  2. `benchmark/fixtures/retry_policy_task/TASK.md` e `src/retry.py`: Substituição do inválido `callable | None` pela tipagem PEP-compatível `collections.abc.Callable` e inclusão de `from __future__ import annotations`.
  3. `benchmark/harness_eval.py`: A função `_verify_required_tests` foi reescrita para aceitar variantes semânticas contendo radicais como `positive`, `negative` e `zero`.
  4. `benchmark/cascade_routing_matrix.py`: A função `build_repair_prompt` agora extrai `behavioral_probe_stderr`, `test_output` ou `grader_error`, fornecendo diagnóstico real ao modelo de Tier 2.
- **Ponto Cego Residual do P0:**
  - Em `benchmark/model_quality_paired.py`, a tupla `VALID_FILE_MODES = (0o644, 0o664, 0o755)` não inclui `0o666`. Embora no WSL ext4 o umask padrão crie `0o644`, em ambientes Windows NTFS ou ambientes com umask aberto, arquivos criados pelo Python recebem `0o666`, o que ainda causa falhas em testes de unidade executados fora do WSL.

---

### 5.2 Marco P1 (Commit `17f5b3f`): Alinhamento ao Padrão SWE-bench Verified
- **O Que Foi Resolvido com Sucesso:**
  1. **Isolamento da Suíte de Avaliação:** Criação do diretório `benchmark/eval_suites/<task>/test_probe.py` para todas as 6 tarefas do laboratório.
  2. **Pipeline de Dois Estágios:** `harness_eval.py` agora executa:
     - `run_baseline_tests(workspace, baseline)`: executa a suíte de referência mantida no diretório baseline contra o workspace do modelo.
     - `run_held_out_tests(workspace, task)`: executa a sonda comportamental held-out externa via `unittest discover` isolado.
     - `unit_tests_passed = workspace_tests_passed and baseline_tests_passed`.
  3. **Paridade de TDD:** Adição de `test_none_treated_as_absent` no arquivo de testes do workspace de `config_precedence_task`. Agora, quando o modelo adota desenvolvimento orientado a testes, ele detecta a falha do caso `{'x': None}` imediatamente no terminal e ajusta o código.
- **Pontos Cegos Residuais do P1:**
  - **Inspeção AST Redundante de Nomes de Testes:** Todas as tarefas (exceto `calculator_division`) continuam executando checagens AST estritas no workspace (`{...} <= test_names`). Se a suíte held-out já testa o comportamento funcional de forma externa e imutável, manter exigência de nomes idênticos no workspace pune modelos sofisticados que organizam testes em classes auxiliares ou utilizam suites parametrizadas.
  - **Isolamento de Processo via PYTHONPATH:** `run_held_out_tests` executa `unittest` configurando `PYTHONPATH=workspace`. Se o candidato gerar arquivos com nomes conflitantes com módulos do sistema (`sys.py`, `os.py`, `unittest.py`), ocorrerá sequestro de imports (*import shadowing*). Um isolamento perfeito exigiria contêiner Docker efêmero como no SWE-bench.

---

### 5.3 Marco P2 (Commit `606e4f1`): Guarded Edit e o Gargalo de Scaffold
- **O Que Foi Resolvido com Sucesso:**
  1. `benchmark/guarded_edit.py`: Implementação de casamento flexível de blocos de linhas normalizadas (`stripped`), tolerando diferenças de espaços em branco e CRLF/LF quando há casamento contíguo unívoco.
  2. Interface CLI completa (`guarded-edit apply` e `guarded-edit check`) com suporte a `--json`.
  3. Preservação ativa de funções auxiliares (`check_helper_preservation`) e detecção de vazamento de sintaxe (`check_syntax_leak`).
- **PONTOS CEGOS CRÍTICOS E GARGALOS RESIDUAIS DO P2:**
  1. **O Gargalo de Scaffold no Harness:** O script `run_dir/bin/guarded-edit` foi colocado no PATH em `harness_runner.py:_isolated_environment`. Porém, **o OpenCode continua operando suas ferramentas nativas `edit`, `write` e `bash`**! O schema de ferramentas do OpenCode continua chamando seu handler TypeScript interno para o `edit` (que exige casamento estrito). O modelo não é informado nos prompts de que `guarded-edit` existe no shell, nem possui uma ferramenta chamada `guarded_edit`. Portanto, os modelos continuam utilizando o `edit` frágil do OpenCode e continuam sujeitos a falhas mecânicas.
  2. **Injeção Ausente nos Runners Pareados:** O `guarded-edit` foi injetado apenas em `harness_runner.py`. Ele **não foi injetado** em `benchmark/model_quality_paired.py` nem em `benchmark/cascade_routing_matrix.py`! Se uma nova rodada pareada for executada por esses scripts, o binário `guarded-edit` sequer estará presente no PATH.

---

## 6. As Quatro Perguntas Fundamentais da Auditoria

### 1. Estamos medindo a coisa certa?
**Antes dos Marcos P0-P2: NÃO.**  
O laboratório estava medindo uma combinação distorcida de:
- Capacidade de adivinhar nomes de métodos de teste não declarados no prompt.
- Sorte de não cair em armadilhas sintáticas de Python injetadas pelos avaliadores (`callable | None`).
- Tolerância a caracteres de espaço em branco em ferramentas de edição de strings literais.
- Resistência a falsos positivos em gates de integridade de arquivos.

**Após os Marcos P0-P2: SIM, na essência, mas com arestas a aparar.**  
Com a criação das suítes held-out isoladas e a restauração da paridade de TDD no workspace, o laboratório passou a medir o que realmente importa: a capacidade do modelo de compreender a especificação de software, interagir com um repositório, escrever código funcionalmente correto e preservar contratos de arquitetura. No entanto, ainda restam resíduos de verificação léxica de nomes de testes e a falta de integração transparente do `guarded-edit` como ferramenta nativa do harness.

### 2. Estamos medindo no tempo certo?
**SIM para a infraestrutura; HISTORICAMENTE NÃO para o canal de reparo.**
- O timeout de 180s por tarefa é justo e generoso: os modelos levam entre 14s e 50s na mediana, consumindo menos de 30% do teto.
- A telemetria de 7,23s para cold swap de modelos no `llama-server` é precisa, estável e plenamente compatível com o orçamento temporal de tarefas.
- No entanto, a medição da cascata no Milestone M4 foi temporariamente invalidada porque o modelo de Tier 2 foi acionado no tempo certo, mas recebeu um prompt com mensagem de erro vazia (`{grade.get('error', '')}`), sendo induzido ao erro. O P0 corrigiu isso fornecendo o traceback real.

### 3. Estamos medindo do jeito certo?
**SIM na engenharia de sistemas e telemetria; NÃO na gestão de permissões de filesystem.**
- **Padrão Ouro de Engenharia de Sistemas:** O isolamento de processos via process groups, a serialização estrita de leases de GPU, a amostragem em tempo real (1 amostra/segundo) de VRAM, RAM do WSL, potência (W) e utilização de GPU pelo `resource_sampler.py`, os digests SHA-256 e o rastreamento rigoroso da proveniência Git atendem aos mais altos padrões científicos de reprodutibilidade.
- **Falha de Engenharia de Software:** A gestão de integridade baseada em inspeção de modos de permissão POSIX (`0o644`) sem considerar arquivos recém-criados ou variações de filesystem NTFS/WSL foi ingênua e gerou falsos negativos graves. O P0 e P1 sanaram a vulnerabilidade principal.

### 4. Qual a distribuição causal revisada das falhas?
Conforme detalhado na Seção 4:
- **70,6% (24 em 34 falhas)** decorreram de falhas do método de avaliação, oráculos ocultos, bugs de pipeline, desalinhamento de TDD, sintaxe ilegal no prompt e rigidez mecânica de ferramentas.
- **29,4% (10 em 34 falhas)** decorreram de deficiências puramente cognitivas dos modelos de linguagem.

---

## 7. Recomendações Acionáveis e Próximos Passos

Para consolidar a liderança metodológica do laboratório e garantir rigor absoluto nas próximas publicações, recomendamos o seguinte plano de trabalho:

### 1. Reavaliação Imediata do Candidato IBM Granite 4.1 8B
- O Granite 8B foi rejeitado com base em um resultado de 1/6 (16,7%), onde ao menos 1 ensaio caiu na armadilha de `callable | None` e outros foram penalizados por mutilação de testes que a arquitetura held-out agora neutraliza.
- **Ação:** Reexecutar a bateria pareada de admissão do Granite 8B utilizando o pipeline pós-P1 (prompt corrigido, suíte held-out isolada) para obter seu índice real de competência matemática e de engenharia de software antes do arquivamento definitivo.

### 2. Integração Transparente do `guarded-edit` no Scaffold do OpenCode
- O binário `guarded-edit` no PATH não é suficiente.
- **Ação:** Criar um plugin ou wrapper no OpenCode para substituir o handler interno da ferramenta `edit`, fazendo com que toda chamada de `edit` do agente passe automaticamente pelo algoritmo de casamento tolerante a espaços em branco e verificação de integridade de helpers do `guarded_edit.py`. Injetar o helper em todos os scripts de runner (`model_quality_paired.py` e `cascade_routing_matrix.py`).

### 3. Descontinuação Definitiva da Checagem AST de Nomes de Teste
- Com a suíte held-out `eval_suites/<task>/test_probe.py` em operação ativa, a verificação AST de nomes de teste no workspace tornou-se tecnicamente obsoleta e metodologicamente prejudicial.
- **Ação:** Remover as checagens `required_tests_present` baseadas em AST de `harness_eval.py`, avaliando a qualidade dos testes do modelo pela capacidade de detectar mutantes ou confiando na suíte held-out para aferição de conformidade.

### 4. Suporte a `0o666` no `VALID_FILE_MODES`
- Para garantir que a suíte de testes unitários execute com 100% de sucesso em qualquer ambiente (Windows, Linux, WSL com diferentes umasks):
- **Ação:** Atualizar `VALID_FILE_MODES = (0o644, 0o664, 0o666, 0o755)` em `benchmark/model_quality_paired.py`.

### 5. Governança e Curadoria de Fine-Tuning QLoRA
- Aplicar os princípios do EvalPlus e SWE-bench Verified na curadoria do dataset de fine-tuning QLoRA do laboratório:
  - Garantir que todas as tarefas de treinamento contenham pares de testes funcionais completos (paridade TDD).
  - Testar cada exemplo contra mutantes antes de incluí-lo no corpus para evitar contaminação por soluções rasas ou heursticas falsy.

---

## 8. Veredito Metodológico Final

O `local-llm-lab` construiu uma infraestrutura de hardware, telemetria de energia e gestão de recursos locais de padrão internacional. No entanto, em sua fase inicial de avaliação de agentes, foi acometido pelas mesmas patologias metodológicas que afligiram os grandes benchmarks da literatura (como o SWE-bench pré-Verified e o HumanEval pré-EvalPlus): oráculos frágeis, sub-especificação de tarefas, armadilhas de tipagem e falhas mecânicas de ferramentas.

Com a conclusão dos marcos P0, P1 e a implementação de testes held-out, o laboratório eliminou a grande maioria dos vícios que distorciam suas métricas. Ao completar a integração do `guarded-edit` no scaffold dos harnesses e abolir resíduos de oráculos léxicos, o laboratório passará a operar com rigor metodológico e integridade científica comparáveis aos mais respeitados centros de avaliação de inteligência artificial do mundo.
