# Auditoria histórica do defeito de caminhos `/workspace`

**Data:** 28/10/2026  
**Escopo:** tentativas `development` dos protocolos `qwen-quant-harness-optimization-final` e `qwen-quant-harness-optimization-final-oom-v2`.

## Conclusão

A versão de `benchmark/qwen_workloads.py` registrada nos dois manifestos contém o mesmo defeito de F1: `safe_path()` rejeita caminhos absolutos por `PurePosixPath(value).is_absolute()` e retorna `path must stay inside /workspace`, enquanto o prompt diz que os caminhos são relativos a `/workspace`. O SHA-256 do arquivo no worktree indicado pelos manifestos coincide com o hash registrado nos dois protocolos.

O defeito aparece nos dados de `-final-oom-v2`, mas não nas tentativas `development` registradas para `-final`. Em `-final-oom-v2`, contei **101 chamadas de ferramenta emitidas** com `path` começando por `/workspace`; **95 têm resposta registrada com a rejeição exata**. As outras 6 são chamadas emitidas sem resposta de ferramenta correspondente e, portanto, não foram contadas como rejeitadas.

Entre os códigos terminais `model_no_progress` e `budget_exhausted` de `-final-oom-v2`, **duas tentativas 4B terminam com o mesmo padrão de chamada `/workspace` previamente rejeitada**: `python_fix` (`7cfd…`) e `continuation` (`85a9…`). Ambas são `model_no_progress`. Nenhuma tentativa `budget_exhausted` termina nesse padrão. As demais rejeições ocorreram em tentativas com outros desfechos ou antes de ações posteriores; não atribuo esses desfechos ao caminho apenas pela presença de um erro.

No protocolo `-final`, há 9 tentativas registradas, todas 9B, e nenhuma chamada `/workspace`. O estado lista 18 unidades `development` 4B planejadas, mas não há tentativa 4B registrada. Assim, as falhas terminais observadas de `-final` não podem ser explicadas por essa rejeição com base nas evidências disponíveis.

## Escopo e método

- Li `F1-diagnostico.md`, `tentativas.csv`, `resultados-completos.json` e os manifestos/estados relevantes dentro do arquivo bruto. Listei os **8.170 membros** do arquivo, sem extraí-lo por inteiro. Para as tentativas, li seletivamente `client/metrics.json`, `client/request-*.json`, `client/response-*.json`, `messages.json`, `compaction-*.json` e, quando disponível, `episode-progress.json`.
- A chave de tentativa é `(protocolo, unit_id, tentativa)`. O CSV registra 9 tentativas `-final` e 36 tentativas `-final-oom-v2` (18 por modelo). O estado de `-final` mostra 42 unidades `development` programadas: 18 4B e 24 9B; somente 9 tentativas 9B foram executadas/registradas.
- Contei as chamadas uma vez por ID de `tool_call` emitido em `client/response-####.json`. Associei o resultado pelo mesmo ID nas mensagens de ferramenta de `client/request-*.json` e `messages.json`; isso evita contar novamente o histórico que se repete em requests seguintes. Conteúdo de argumento só conta quando o campo `path` começa literalmente por `/workspace`.
- Uma chamada só conta como **rejeitada** se a resposta correspondente contém `path must stay inside /workspace`. A fase é **pré-compactação** se ainda não há geração `kind=compaction` anterior na sequência de `client/metrics.json`; caso contrário, é **pós-compactação**. Os arquivos `compaction-N.json` corroboram esses limites.
- Para o resultado terminal usei `resultado_json.failure` quando preenchido, depois `resultado_json.status`; para tentativas sem `resultado_json`, usei `estado_registrado`. `model_failure` sem campos de causa foi mantido sem atribuição adicional.
- Para “rejeição como último padrão” exigi que a última resposta de modelo emitisse novamente o mesmo par ferramenta/caminho de uma chamada `/workspace` já rejeitada e que o registro terminal fosse `model_no_progress` ou `budget_exhausted`. As duas chamadas finais correspondentes não têm resposta de ferramenta registrada; contam como chamadas emitidas, não como rejeições confirmadas.

## Totais por protocolo, modelo e causa terminal

`Chamadas` e `rejeições` estão somadas em todas as fases. Os detalhes pré/pós estão na tabela seguinte.

| Protocolo | Modelo | Resultado terminal registrado | Tentativas | Chamadas `/workspace` | Rejeitadas | Último padrão de rejeição |
|---|---|---|---:|---:|---:|---:|
| `-final` | 4B | sem tentativa registrada (18 unidades programadas) | 0 | 0 | 0 | — |
| `-final` | 9B | `model_no_progress` | 6 | 0 | 0 | 0 |
| `-final` | 9B | `complete` | 2 | 0 | 0 | 0 |
| `-final` | 9B | interrompida, sem resultado terminal | 1 | 0 | 0 | 0 |
| `-final-oom-v2` | 4B | `model_no_progress`¹ | 8 | 36 | 30 | 2 |
| `-final-oom-v2` | 4B | `budget_exhausted` | 3 | 20 | 20 | 0 |
| `-final-oom-v2` | 4B | `model_failure`, causa não preenchida | 3 | 7 | 7 | 0 |
| `-final-oom-v2` | 4B | `complete` | 4 | 7 | 7 | 0 |
| `-final-oom-v2` | 9B | `model_no_progress` | 9 | 9 | 9 | 0 |
| `-final-oom-v2` | 9B | `budget_exhausted` | 1 | 11 | 11 | 0 |
| `-final-oom-v2` | 9B | `model_failure`, causa não preenchida | 2 | 0 | 0 | 0 |
| `-final-oom-v2` | 9B | `complete` | 4 | 11 | 11 | 0 |
| `-final-oom-v2` | 9B | interrompida, sem resultado terminal | 2 | 0 | 0 | 0 |

¹ Uma das 8 linhas 4B tem `failure=model_no_progress`, mas o campo `error` diz `compaction did not produce a usable text checkpoint`; ela não tem chamadas `/workspace`. As outras 7 trazem `repeated tool result without observable progress`.

| Protocolo | Modelo | Chamadas pré/pós-compactação | Rejeitadas pré/pós-compactação | Total de chamadas | Total rejeitado |
|---|---|---:|---:|---:|---:|
| `-final` | 9B | 0 / 0 | 0 / 0 | 0 | 0 |
| `-final-oom-v2` | 4B | 11 / 59 | 11 / 53 | 70 | 64 |
| `-final-oom-v2` | 9B | 10 / 21 | 10 / 21 | 31 | 31 |
| **`-final-oom-v2` total** | **4B + 9B** | **21 / 80** | **21 / 74** | **101** | **95** |

## Tentativas individuais: `qwen-quant-harness-optimization-final`

Não há tentativas 4B nesse protocolo. Todas as 9 tentativas abaixo são 9B. Nas colunas de contagem, a ordem é pré/pós-compactação.

| Unit ID / tentativa | Tarefa | Chamadas `/workspace` | Rejeições | Terminal registrado | Rejeição como último padrão |
|---|---|---:|---:|---|---|
| `c663a3393ce3d28e8928f987f56373ee427af8a9ca987c952ae2f5e4a424cf73` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `4e2d2b4aadd48be2a438522974b0374a95df4ee7a7eb024a3aab62d96386f9ee` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `dc6ef04b3fd4beea5566b912c9e4f676b41ee29a50f280591e0fbc82ce02eedf` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `3cfb60c19dc994db96869062037cfc29ef84a8fd04423f2f0246736122fbfb43` / 1 | `mcp` | 0 / 0 | 0 / 0 | `complete` | não |
| `5d58644b6eab84b55e884f94ac7fe6b15c52118e8f34a0a0b5d25831bb69fbbb` / 1 | `continuation` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `4244a87c83398469e4d2e53d8bc249410e77f9f20aedacb56aeeb040539d15c2` / 1 | `tool_recovery` | 0 / 0 | 0 / 0 | `complete` | não |
| `c7a9d4f0b4c0687352bf09a5856a4e90b4b26372fefa25a5da54993a7f449f97` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `2e1e6a92fc11b12e4ec11e722b569219d184c14425610c18b7c87a4618fd8876` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `80da3df59c59a32c3d5ecf60fa93719ff76476d0b3d3c7bc4543284ede874254` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | interrompida, sem resultado | — |

## Tentativas individuais: `qwen-quant-harness-optimization-final-oom-v2`, 4B

| Unit ID / tentativa | Tarefa | Chamadas `/workspace` | Rejeições | Terminal registrado | Rejeição como último padrão |
|---|---|---:|---:|---|---|
| `29184ffa562f5ea75cfea53560312fb4dc23cb721c151ac90bedb480605bf084` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress`; erro de checkpoint de compactação | não |
| `885ca74cc7eda3ee2f2779af4f42dcb6dd3e65e490b0b1f7f3ac4650dd861585` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `c5dd4134fab6d48ad4fb98191c2e325023ea3e952a9be672d0f337f96b94b571` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `budget_exhausted` | não |
| `130466244e2bc3f6b8c033a2e2aa8b0280ad2d36bb4a3a297eb791c6b02bf842` / 1 | `mcp` | 2 / 0 | 2 / 0 | `model_failure`, causa não preenchida | não |
| `85a9d834d9ecb05bcadf685a53978dd0e28cd19b40868ea8e8b36f8120ff4c83` / 1 | `continuation` | 0 / 10 | 0 / 9 | `model_no_progress` | sim |
| `eac502b7de41c9b33f769836191dbc6f0746a27e9cafc0a0486faf49e16fc53e` / 1 | `tool_recovery` | 3 / 0 | 3 / 0 | `complete` | não |
| `7cfda498534e8a3c5200b89e6db767e9a5ae816fa71f70f1ed0bc76a0924c428` / 1 | `python_fix` | 0 / 26 | 0 / 21 | `model_no_progress` | sim |
| `9494fb7d8edfb8e0e506d32b76cd48582447ae8f33c4946c244eb0e730c7a1f9` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `19b02efa1097fd9fec45a451462b98a007613259baddf1fe532da6da9959aba0` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `budget_exhausted` | não |
| `7389d876f3f7318dd1fb2c649ad427b2a22334124dd373ce68fad8698e31d77c` / 1 | `mcp` | 2 / 0 | 2 / 0 | `model_failure`, causa não preenchida | não |
| `1a0eb823001b7d26fafd7af9de0c0c41b9ec7a173736c1d1fb35309fde38ce1b` / 1 | `continuation` | 0 / 3 | 0 / 3 | `model_failure`, causa não preenchida | não |
| `8135896cf8c8bfc99778ee1a4982b226f577732f52ef8d4529796d863417c9ab` / 1 | `tool_recovery` | 2 / 0 | 2 / 0 | `complete` | não |
| `a939d858d3931aba4e2472ede2bab6df16065b676a20940dc510cd8b73b5a9e6` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `c2d13ac5732eab19ec26d53bcae952c699deb4a388cf02fac4565c5223bbfc62` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `7c63b9de66f87cb3ad31a87c2dc97de37939ad19087f77e6c8f21bcc84137cc7` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `af9613baf31d6c3d3d244f5c7016b096b4d536bd6b49876d610acc14e530ae30` / 1 | `mcp` | 2 / 0 | 2 / 0 | `complete` | não |
| `81e49412aa3dff3abc8adfef4fce2dc51f5035e5a981f68e510bce303a124765` / 1 | `continuation` | 0 / 20 | 0 / 20 | `budget_exhausted` | não |
| `2345ee5d8817c2feb0c6d2a26bde25b0a25a8addbe722e726d2ce5d4b87fb858` / 1 | `tool_recovery` | 0 / 0 | 0 / 0 | `complete` | não |

## Tentativas individuais: `qwen-quant-harness-optimization-final-oom-v2`, 9B

| Unit ID / tentativa | Tarefa | Chamadas `/workspace` | Rejeições | Terminal registrado | Rejeição como último padrão |
|---|---|---:|---:|---|---|
| `80da3df59c59a32c3d5ecf60fa93719ff76476d0b3d3c7bc4543284ede874254` / 2 | `authored_tests` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `7db0d2b9aa374fb52bae12ab6efba6a0953976c49d43019cfc85d0afdae66f1c` / 1 | `mcp` | 1 / 0 | 1 / 0 | `complete` | não |
| `0b6c4bc61faac6a765960cd037b4c359004a4c90ea975f6a9cec4ac3cf9eabca` / 1 | `continuation` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `4f5326820ccafd4fa286be27e47d62d5318536b90ad8f9745756472a59d32148` / 1 | `tool_recovery` | 1 / 0 | 1 / 0 | `complete` | não |
| `3e2ee894875dac97786a887b1c34305dcb7b6ecb440c450845b27b7a90bb929a` / 1 | `python_fix` | — | — | interrompida, sem resultado; evidência bruta ausente | n/d |
| `3e2ee894875dac97786a887b1c34305dcb7b6ecb440c450845b27b7a90bb929a` / 2 | `python_fix` | 0 / 0 | 0 / 0 | interrompida, sem resultado | — |
| `3e2ee894875dac97786a887b1c34305dcb7b6ecb440c450845b27b7a90bb929a` / 3 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `5464f2b3cb23a7e7d0897212b339e216d929888f530b6b746da565a484f0629b` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `06e404c7c2a9c94f67da7cbed7cb7ad38b3376873dc437c6afde0783d26215a8` / 1 | `authored_tests` | 0 / 9 | 0 / 9 | `model_no_progress` | não |
| `758884e65dc09e4125bc257d24f20144bb7ed66ad536e2b2bfe79e03c5e9bda9` / 1 | `mcp` | 0 / 0 | 0 / 0 | `model_failure`, causa não preenchida | não |
| `365b0c6adcbe525a536a739217ce34260e50700992ea12b0a000cac8b5ee907e` / 1 | `continuation` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `04d4318cb8360a9356da064db269e273f7f7bd83baabdacd9c4ce58dc614cfa6` / 1 | `tool_recovery` | 5 / 1 | 5 / 1 | `complete` | não |
| `10fe7b603175ceeab8d73b76f7cce6ef6ce01f75952c2461fc64afe2d236c0c6` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `440e84728ad0ec6efc120978889acf485d69159e767260c30ceba8c61a320294` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `82638b8722c1fc05c09e98485acc2554de229963f84bb2a8b935442daafe54f1` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `model_no_progress` | não |
| `144383498106e0b6c33acde4772c704990188682ecb369c1701c2a2ac111bb5f` / 1 | `mcp` | 0 / 0 | 0 / 0 | `model_failure`, causa não preenchida | não |
| `c563067a93274300f54490772ef6f022133358aa003f6367310938752e015664` / 1 | `continuation` | 0 / 11 | 0 / 11 | `budget_exhausted` | não |
| `00161c8c1b72d1ba3af4af5167ee988c01887f8d51a39659ca02e93899af7c12` / 1 | `tool_recovery` | 3 / 0 | 3 / 0 | `complete` | não |

## Verificação do código identificado no manifesto

| Protocolo | SHA-256 de `benchmark/qwen_workloads.py` no manifesto | SHA-256 do arquivo atual no worktree indicado | Coincide |
|---|---|---|---|
| `qwen-quant-harness-optimization-final` | `f74a2c1833aa77cfa2ceb76ff46b7aad86750aadb01c65a72824b1be57139087` | `f74a2c1833aa77cfa2ceb76ff46b7aad86750aadb01c65a72824b1be57139087` | sim |
| `qwen-quant-harness-optimization-final-oom-v2` | `f74a2c1833aa77cfa2ceb76ff46b7aad86750aadb01c65a72824b1be57139087` | `f74a2c1833aa77cfa2ceb76ff46b7aad86750aadb01c65a72824b1be57139087` | sim |

Os dois manifestos nomeiam `/mnt/d/Usuario/Downloads/LLM/.worktrees/practical-agent-v2/benchmark/qwen_workloads.py`. No arquivo com esse hash, `safe_path()` (linhas 37–40) testa `path.is_absolute()` e lança `ValueError("path must stay inside /workspace")`; o texto do prompt (“All paths are relative to /workspace”) aparece na linha 310. Portanto, a mesma implementação incompatível foi registrada para os dois protocolos.

## Limites e discrepâncias

- A tentativa `-final-oom-v2`, 9B `python_fix`, unit `3e2ee894…`, tentativa 1, está registrada como interrompida, mas não há diretório bruto correspondente no arquivo. Não foi possível contar suas chamadas nem verificar rejeições ou fase. A tentativa 2 da mesma unidade também está interrompida, mas possui evidência bruta e não contém chamada `/workspace`.
- Três tentativas têm estado exportado `interrupted` e nenhum resultado terminal: `-final` 9B `authored_tests`/1 e `-final-oom-v2` 9B `python_fix`/1 e /2. O snapshot arquivado `state.json` de `-final` ainda mostra a primeira unidade `80da…` como `running`; o CSV/exportação de encerramento a registra como `interrupted`.
- Em 12 tentativas concluídas, `episode-progress.json.tools` fica entre 1 e 5 abaixo do número de chamadas emitidas em respostas do cliente. Isso é compatível com tool calls pendentes no fim do episódio. Por isso, uma chamada emitida sem retorno foi contada como chamada, mas não como rejeição confirmada.
- As causas terminais `model_failure` em cinco tentativas não têm os campos internos `failure`/`error` preenchidos; o resultado agregado não permite atribuí-las ao caminho. As causas registradas como `complete` também podem coexistir com rejeições recuperadas.
- A auditoria cobre somente as tentativas de `development` dos dois protocolos indicados; não atribui causalidade às demais etapas da campanha.

## Fontes consultadas

- `reports/analise-estrategia-4b-2026-10-28/execucao/F1/F1-diagnostico.md`
- `reports/outputs/qwen-final-encerrado/tentativas.csv`
- `reports/outputs/qwen-final-encerrado/resultados-completos.json`
- `reports/outputs/qwen-final-encerrado/evidencias-brutas.tar.gz` — manifestos, snapshots `state.json`/`summary.json` e evidência seletiva sob `qwen-quant-harness-optimization-final/units/` e `qwen-quant-harness-optimization-final-oom-v2/units/`
- `.worktrees/practical-agent-v2/benchmark/qwen_workloads.py`

Nenhum workload foi executado, nenhuma GPU foi usada e nenhum código ou commit foi alterado.
