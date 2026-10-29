# T3a — preparação da etapa 5, sem GPU

Data: 29/10/2026. Runner `benchmark/baseline_stage5.py`, configuração `benchmark/configs/qwen-4b-opencode-stage5.json`, resultados futuros em `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-stage5-v1`. A etapa 5 não foi executada. O runner e a configuração da etapa 4 e o corpus não foram alterados.

## Matriz e limite de download

Sete braços habilitados, 12 tarefas e uma repetição: **84 unidades**. Controle herdado: Q4_K_M bartowski, KV q4_0, 65536, cache ligado, thinking desligado, temperatura zero e 40 passos. Q5-Q6KL e Q5-UDQ6XL trocam os pesos; T5-lsp habilita LSP; T5-lsp-tool acrescenta a ferramenta experimental; T5-rtk habilita o plugin RTK; X-think e X-9b são cascatas. Não há braço de controle adicional: para comparação, usar o controle compatível da etapa 4 com o cuidado estatístico apropriado.

**Q5-UDQ4XL está desabilitado**. Os três arquivos solicitados somam 11.016.974.624 bytes, acima de 10 GB e de 10 GiB; buscas nos caches de `/home/foxtrot` e `D:/Usuario/Downloads/LLM` não encontraram cópia. Os dois Q6 somam 8.104.864.896 bytes transferidos. Pacotes npm e o arquivo RTK (6.844.596 bytes) são adicionais; o tráfego exato npm não foi medido. O diretório LSP instalado ocupa aproximadamente 71 MiB; tamanho instalado não é medição de tráfego. A soma dos três modelos por si só impede completar os downloads sob o teto autorizado.

| Modelo | Estado | Bytes | Revisão | SHA-256 |
| --- | --- | ---: | --- | --- |
| [bartowski Q6_K_L](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF/resolve/4168f45a16a1290d65a4ec0fa312ae917a4c15d6/Qwen_Qwen3.5-4B-Q6_K_L.gguf) | baixado e conferido | 3.959.316.448 | `4168f45a16a1290d65a4ec0fa312ae917a4c15d6` | `0d7931a7f143ccfdf675c0d84d542c387cd9255af94ee9c8fb5fa6f6df7c08a0` |
| [unsloth UD-Q6_K_XL](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-UD-Q6_K_XL.gguf) | baixado e conferido | 4.145.548.448 | `e87f176479d0855a907a41277aca2f8ee7a09523` | `87f58d94410b81429268d8389a3d686e6c6bffecf7852772720fbea059cbbb9d` |
| [unsloth UD-Q4_K_XL](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-UD-Q4_K_XL.gguf) | **não baixado**; hash publicado no LFS, não verificado localmente | 2.912.109.728 | `e87f176479d0855a907a41277aca2f8ee7a09523` | `b252c5610a42ca82d20fe2a12813e9d069eed89292907e26c783eeb0bc961bc7` |

Os dois downloads estão em `/home/foxtrot/local-llm-benchmark/models/gguf/qwen3.5-4b/`. O Q4_K_M 9B já existente é [Unsloth](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-Q4_K_M.gguf), não bartowski: 5.680.522.464 bytes, SHA-256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`, revisão `3885219b6810b007914f3a7950a8d1b469d598a5`. Um 9B Q6_K também foi encontrado em `/home/foxtrot/local-llm-benchmark/state/qwen-hot/active/`; não é usado.

## Ferramentas: provas offline

O prefixo `/home/foxtrot/local-llm-benchmark/envs/lsp-tools-20261029` contém pyright 1.1.414, typescript-language-server 6.0.2 e TypeScript 5.9.3. O bwrap monta somente `node_modules` read-only em `/opt/lsp/node_modules`, com Node do runner em `/opt/node`. `opencode debug config` aceitou `lsp: true` no sandbox com `--pure`. Com `opencode debug lsp diagnostics /workspace/test.py`, o Pyright retornou diagnóstico real de atribuição de string a `int`, identificado por `source: Pyright`; um wrapper no HOME registrou sua chamada. Evidência: `/tmp/stage5-tool-proof-20261029/lsp.out` e `home/pyright-start.log`. Os wrappers por episódio registram tentativas de inicialização em `home/lsp-starts.log`, e `lsp.log` conserva linhas do log do OpenCode. `lsp_started: null` expressa que o log de chamada isoladamente não confirma prontidão; diagnósticos/eventos são necessários para comprová-la. `lsp_tool_calls` conta eventos `tool_use` da ferramenta `lsp`.

O servidor TypeScript está instalado e acessível, mas diagnósticos de arquivos TS/JS retornaram `{}` e uma configuração explícita expirou; o funcionamento para JS não foi comprovado. Isso não deve ser contado como prova de início ou de diagnóstico.

RTK 1.1.0 está em `/home/foxtrot/local-llm-benchmark/envs/rtk-tools-20261029/rtk`; SHA-256 do binário `f4d2f533d4e82e797cad3fbcd8d4a4f85351c4871d49a6202f5bc7a3e8c5c568`. O plugin foi gerado com `rtk init -g --opencode` em HOME isolado. O runner copia apenas o plugin para o HOME do episódio e monta apenas o binário read-only em `/opt/rtk/rtk`. Como `--pure` impede plugins externos, o braço RTK executa sem essa opção; isso é parte necessária da intervenção. OpenCode 1.19.5, bwrap e provedor falso local, sem inferência, produziram um evento bash `input.command: "rtk git status"`, `status: completed`, `metadata.exit: 0`; evidência `/tmp/stage5-tool-proof-20261029/rtk.out` e `rtk.err`. `rtk hook opencode 'git status'` retornou `{"command":"rtk git status"}`. Essas provas não medem ganho ou qualidade do filtro em episódios reais.

O manifesto da etapa 5 fixa hashes dos arquivos do runner, configuração, modelos, dependências LSP, binário e plugin RTK, além das verificações herdadas do runner. Evidências em `/tmp` são temporárias; os resultados de cada episódio conservarão seus próprios logs e eventos.

## Cascatas, métricas e limites

A decisão usa falha de verificação visível, inclusive fase 1, ou falha identificada do modelo. Falha apenas do oráculo não escala; falhas de servidor e de harness não viram falhas de modelo. Exceções do grader privado são registradas como infraestrutura sem apagar o resultado visível. A segunda tentativa recebe diretório de workspace e HOME novos. X-think reinicia o servidor com reasoning on e sampling 0,6/0,95/20. X-9b usa o modelo existente, KV q4_0 e experimenta contextos 65536, 49152, 32768, 16384 e 8192, em ordem, exigindo pelo menos 500 MiB livres na carga e na amostragem do episódio; OOM comprovado ou folga insuficiente permite tentar o próximo contexto. Em 8192, o limite de saída é reduzido de 8192 para 4096 para deixar espaço de entrada. Uma falha genérica não é chamada de OOM. O comportamento real, a estabilidade, o contexto viável e o pico ainda não foram medidos em GPU.

As tentativas mantêm os `result.json`, eventos, diffs e métricas do T1. `cascade.json` registra as duas tentativas lógicas, decisão, tempos, amostras e trocas; tentativas adicionais por OOM ficam em diretórios separados. `summary.json` por braço contém taxa da primeira tentativa, taxa final, escalonamentos, tempo total e tempo extra. Os logs de carga e `model-switches.json` registram contextos, evidência de OOM e tempos de unload/load; a amostragem de VRAM é do dispositivo inteiro e em aproximadamente 1 Hz, podendo perder picos breves. A análise herdada `baseline_report` seleciona tentativas por sua própria política e não substitui o resumo de cascata da etapa 5.

## Verificação e execução futura

Testes com componentes falsos cobrem isolamento das tentativas, decisão sem oráculo, queda de servidor, troca de contexto, logs anteriores, OOM, wrappers e resumo. A suíte focada `tests/test_baseline_stage5.py tests/test_opencode_baseline.py tests/test_baseline_report.py` passou: **60 testes**, com `PYTHONDONTWRITEBYTECODE=1` e `-p no:cacheprovider`; Ruff nos dois arquivos Python novos: **All checks passed**. O dry-run listou 84 unidades habilitadas. Não há configuração de typecheck no projeto. Uma suíte geral não foi executada durante a campanha ativa, pois inclui outros launchers e processos que não foram todos auditados para esta restrição.

Após o término da etapa 4 e liberação da GPU, o comando abaixo executa somente os **84 episódios habilitados**, não o braço Q5-UDQ4XL:

```sh
cd /mnt/d/Usuario/Downloads/LLM/.worktrees/4b-worker-v2
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.baseline_stage5 --dry-run --stage 5
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.baseline_stage5 --stage 5
```

O runner recusa iniciar se já houver `llama-server`. Uma unidade interrompida com tentativas parciais exige revisão manual; seus arquivos não são sobrescritos automaticamente.

## Atualização do orquestrador (29/10, 06h)

O Codex atingiu o limite de uso antes do commit. O orquestrador baixou o UD-Q4_K_XL (2.912.109.728 bytes, sha256 `b252c561…961bc7`, igual ao `x-linked-etag` do Hugging Face na revisão `e87f1764`) e habilitou o braço **Q5-UDQ4XL**. A etapa 5 passa a ter **96 episódios**. `tests/test_baseline_stage5.py`: 22 testes passam; `--dry-run` lista 96 unidades.
