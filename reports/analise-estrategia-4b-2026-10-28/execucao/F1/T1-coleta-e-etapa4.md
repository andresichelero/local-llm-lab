# T1 — coleta e preparação da etapa 4

Data: 29/10/2026. Worktree `feat/4b-worker-v2`. Protocolo novo `qwen-4b-opencode-baseline-b-20261029-bwrap-v7`, saída `/home/foxtrot/local-llm-benchmark/results/qwen-4b-opencode-baseline-bwrap-v7`. A etapa 4 não foi executada. A campanha v6 em andamento e seu diretório de resultados não foram acessados.

## Coleta

- `diff_quality` compara o snapshot inicial e o final e registra linhas adicionadas/removidas, arquivos alterados, fora de `writable_files` e de `relevant_files`, arquivos novos, testes apagados e testes potencialmente enfraquecidos. Os arquivos liberados pelo supervisor na continuação são atualizados no snapshot de referência. Se houver arquivo binário alterado, os totais de linhas são `null`.
- Heurística de teste: caminhos com nomes de teste são examinados por expressões `assert*`, `expect(...)` e `should(...)`; redução da contagem ou aumento de asserts triviais (`assert True`, `assert 1` e equivalentes reconhecidos) sinaliza possível enfraquecimento. Não prova equivalência semântica e pode produzir falsos positivos e negativos.
- `tokens_after_last_edit` exige evento de edição concluído com diff da ferramenta que compartilhe alteração com o diff final do mesmo arquivo. Um comando bash posterior, dados de uso incompletos ou falta dessa evidência resulta em `null`; descarta o primeiro `step_finish` após a edição, pertencente à resposta que a solicitou.
- Timings do proxy preservam as requisições; `request_metrics` registra medianas de `prompt_per_second` e `predicted_per_second` e totais de `prompt_n`, `cache_n` e soma dos dois. Total incompleto é `null`, não uma soma parcial. Os valores são somas por requisição, não tokens únicos.
- Amostragem aproximadamente 1 Hz: CPU total do WSL via `/proc/stat`, RAM disponível do WSL via `/proc/meminfo`, RAM disponível do Windows via `Get-CimInstance` em thread independente com timeout, e VRAM do dispositivo via `nvidia-smi`. Guardam-se amostras e mínimo, máximo e média por episódio. A primeira CPU e leituras indisponíveis são `null`; VRAM representa o dispositivo inteiro, não exclusivamente o processo. A RAM do Windows é `null` quando a interoperabilidade falha ou excede o tempo.

## Taxonomia automática

A primeira tag na ordem abaixo é principal e as demais são secundárias. Os sinais são heurísticos; sucesso não recebe tags e um evento ausente não é prova de ausência do comportamento.

1. `wall_timeout`: falha `model_wall_timeout`.
2. `context_overflow`: mensagem de contexto excedido nos eventos ou stderr.
3. `tool_error_loop`: mesma ferramenta e mesmo texto de erro/saída pelo menos três vezes; inclui status `error`/`failed` e saída bash não zero em `metadata.exit`.
4. `step_cap`: pelo menos o limite configurado de eventos `step_finish` em uma fase.
5. `no_edit`: diff final sem arquivos alterados.
6. `gave_up`: sem edição, texto posterior à última ferramenta, encerramento com falha de oráculo/visível/fase 1 e sem `step_cap`.
7. `wrong_file`: pelo menos um arquivo alterado fora dos relevantes.
8. `broke_visible`: verificação visível falhou.
9. `oracle_only`: visível passou e oráculo falhou.

## Análise

`python -m benchmark.baseline_report DIR... --markdown relatorio.md --csv relatorio.csv` gera tabelas por braço, por tarefa/repetição, comparação de braços por tarefa e pares tarefa/repetição. Calcula Wilson 95%, McNemar exato, tempos, TTFT, taxas, VRAM, tokens, desperdício e tags disponíveis. Valores ausentes ficam vazios. Uma única repetição tem estabilidade `insufficient`. Para usar controle de outro protocolo, acrescente `--control-dir DIR_CONTROLE --control B0`; dados de protocolos distintos não são fundidos.

Seleciona a primeira tentativa salvo `server_exited`, `server_http_error`, `harness_configuration_error` ou `grader_infrastructure`, usando `failure`, não `category`. Isso mantém a primeira tentativa incorretamente classificada como infraestrutura no v5. Tentativas exclusivamente de infraestrutura são excluídas e não convertidas em falha do modelo. Resultados antigos sem taxonomia ou timings completos não recebem valores inventados.

Executado somente sobre v5, sem ler v6: B0 **16/24**, taxa 0,6667, Wilson 95% [0,4671; 0,8203]; tempo mediano 42,2508 s; 6.722.306 tokens de prompt, 85.053 gerados e 1.528,6387 s nos episódios malsucedidos. Os totais do servidor ficaram vazios porque nem todas as requisições tinham timings completos. Saídas persistidas ao lado deste relatório: `T1-analise-v5.md` e `T1-analise-v5.csv`.

## Etapa 4

Todos usam Q4_K_M bartowski, KV q4_0/q4_0, contexto 65536, cache ligado, thinking desligado, temperatura 0 e 40 passos, exceto o fator indicado. São 12 tarefas por repetição.

| Braço | Alteração | Repetições | Unidades |
| --- | --- | ---: | ---: |
| C4-q4 | controle | 3 | 36 |
| C4-q6 | Q6_K Unsloth | 3 | 36 |
| S-qwen-sampling | temperatura 0,7; top_p 0,8; top_k 20; min_p 0; presence_penalty 1,5 | 1 | 12 |
| S-steps80 | 80 passos | 1 | 12 |
| S-ctx48 | contexto 49152 | 1 | 12 |
| S-cache-reuse | `--cache-reuse 256 --ctx-checkpoints 16` | 1 | 12 |
| S-mtp | `--spec-type draft-mtp` | 1 | 12 |
| S-q4-unsloth | Q4_K_M Unsloth | 1 | 12 |

O `--help` do servidor v0.8.0 confirma os três nomes de flags; o código `common/speculative.cpp` cria o contexto draft MTP a partir do alvo, e o GGUF de controle contém `qwen35.nextn_predict_layers=1` e tensores `blk.32.nextn.*`. Suporte de interface e metadados não demonstram funcionamento ou ganho em inferência. O model card Unsloth da revisão abaixo confirma os parâmetros non-thinking gerais. O perfil de sampling foi aceito por `opencode debug config` offline.

Modelo Unsloth: `Qwen3.5-4B-Q4_K_M-unsloth.gguf`, 2.740.937.888 bytes, `/home/foxtrot/local-llm-benchmark/models/gguf/qwen3.5-4b/`; revisão `e87f176479d0855a907a41277aca2f8ee7a09523`, SHA-256 `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4`, verificado após download. URL: https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q4_K_M.gguf.

## Verificação e execução futura

No WSL, a partir de `/mnt/d/Usuario/Downloads/LLM/.worktrees/4b-worker-v2`:

```text
$ /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m pytest -q tests/test_opencode_baseline.py tests/test_baseline_report.py tests/test_qwen_f1_diagnostic.py tests/test_opencode_controlled_probe.py
49 passed in 29.81s
$ /home/foxtrot/.local/bin/ruff check benchmark/opencode_baseline.py benchmark/baseline_report.py tests/test_opencode_baseline.py tests/test_baseline_report.py
All checks passed!
$ python -m compileall -q benchmark/opencode_baseline.py benchmark/baseline_report.py tests/test_opencode_baseline.py tests/test_baseline_report.py
exit 0
$ /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.opencode_baseline --dry-run --stage 4
001 stage=4 arm=C4-q4 task=cont_path rep=1
002 stage=4 arm=C4-q4 task=cont_quote rep=1
...
144 stage=4 arm=S-q4-unsloth task=tests_range rep=1
Total: 144
```

O `compileall` acima usou o mesmo Python de validação. A listagem completa está em `T1-etapa4-dry-run.txt` ao lado deste relatório. Não foi identificada configuração de typecheck no projeto; compilação não substitui um verificador de tipos.

Comando para execução posterior, **não executado nesta tarefa**:

```sh
cd /mnt/d/Usuario/Downloads/LLM/.worktrees/4b-worker-v2
/home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.opencode_baseline --stage 4
```
