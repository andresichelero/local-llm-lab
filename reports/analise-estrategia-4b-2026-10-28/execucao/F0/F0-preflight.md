# F0 preflight — itens 1–4

Data: 2026-10-28. Escopo executado offline, sem iniciar llama-server, inferência, GPU, downloads, instalações, alterações de código/configuração, branch, checkout, stash ou commit. A única escrita no workspace foi este relatório; o pytest usou temporários em /tmp e bytecode/cache foram desativados.

## 1. Modelo

### Comandos usados

    Get-ChildItem -LiteralPath D:\ -Filter '*.gguf' -File -Recurse -Force -ErrorAction SilentlyContinue -ErrorVariable +errs |
      Where-Object { $_.FullName -match '(?i)4b' }
    Get-ChildItem -LiteralPath E:\ -Filter '*.gguf' -File -Recurse -Force -ErrorAction SilentlyContinue -ErrorVariable +errs |
      Where-Object { $_.FullName -match '(?i)4b' }
    Get-FileHash -LiteralPath 'E:\LocalLLMLabArchive\models\bartowski-Qwen_Qwen3.5-4B-GGUF\4168f45a16a1290d65a4ec0fa312ae917a4c15d6\Qwen_Qwen3.5-4B-Q4_K_M.gguf' -Algorithm SHA256
    Get-FileHash -LiteralPath 'D:\Usuario\Downloads\LLM\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q6-k-1943f53d06a9a1e6\Qwen3.5-4B-Q6_K.gguf' -Algorithm SHA256

As raízes D: e E: estavam acessíveis. A enumeração final retornou código 0 e encontrou cinco arquivos em D: e um em E:. Foram registrados cinco erros de enumeração por acesso negado: D:\$RECYCLE.BIN\S-1-5-18, D:\System Volume Information, duas subpastas de E:\$RECYCLE.BIN e E:\System Volume Information.

### Q4_K_M e variantes encontradas

| Arquivo | Caminho | Bytes | SHA-256 |
|---|---|---:|---|
| Qwen3.5-4B Q4_K_M | E:\LocalLLMLabArchive\models\bartowski-Qwen_Qwen3.5-4B-GGUF\4168f45a16a1290d65a4ec0fa312ae917a4c15d6\Qwen_Qwen3.5-4B-Q4_K_M.gguf | 3.013.027.808 | 13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983 |
| Qwen3.5-4B Q5_K_M | D:\Usuario\Downloads\LLM\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q5-k-m-523af779a39fdf28\Qwen3.5-4B-Q5_K_M.gguf | 3.143.656.608 | não calculado |
| Qwen3.5-4B Q5_K_S | D:\Usuario\Downloads\LLM\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q5-k-s-c290a3d9efc52920\Qwen3.5-4B-Q5_K_S.gguf | 3.024.934.048 | não calculado |
| Qwen3.5-4B Q6_K | D:\Usuario\Downloads\LLM\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q6-k-1943f53d06a9a1e6\Qwen3.5-4B-Q6_K.gguf | 3.525.956.768 | fdedd781c9ce676ab66b018ca247ff78e8a33c98098a822c1e2d5075e7718f66 |
| Qwen3.5-4B Q8_0 | D:\Usuario\Downloads\LLM\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q8-0-8c94708900a06875\Qwen3.5-4B-Q8_0.gguf | 4.482.403.488 | não calculado |
| Qwen3.5-4B UD-Q5_K_XL | D:\Usuario\Downloads\LLM\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-ud-q5-k-xl-1027ef16cfbfd447\Qwen3.5-4B-UD-Q5_K_XL.gguf | 3.250.869.408 | não calculado |

O Q4_K_M confere com o SHA-256 esperado de outubro. O SHA-256 do Q6_K foi calculado conforme solicitado; os demais hashes de variantes não foram calculados.

Busca WSL executada:

    find /home/foxtrot -type f -iname '*.gguf' -printf '%p %s\n' 2>/dev/null | grep -Ei '4b'

Resultado: nenhuma correspondência 4B (grep retornou 1 por não haver matches). prefix_cache_paired.py e cascade_routing_matrix.py declaram models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf relativamente a REPO_ROOT; esse arquivo não existe no root WSL /home/foxtrot/local-llm-benchmark nem nos roots montados em /mnt/d/Usuario/Downloads/LLM/local-llm-lab e /mnt/d/Usuario/Downloads/LLM/.worktrees/practical-agent-v2. qwen_engines.py recebe o artefato por argumento e fixa apenas o root do runtime/binary em /home/foxtrot/local-llm-benchmark.

## 2. Build llama.cpp

Os três runners examinados convergem para um único caminho de execução: /home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server. llama-bin é symlink para tools/llama-bin-v0.7.0-620d2225c/llama-server. Referências no código: benchmark/qwen_engines.py:16,352; benchmark/prefix_cache_paired.py:397,312; benchmark/cascade_routing_matrix.py:939-940. qwen_engines.py existe somente no worktree practical-agent-v2; prefix e cascade foram conferidos em local-llm-lab e practical-agent-v2.

Comandos executados somente no modo informativo:

    /home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server --version
    /home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server --help 2>&1 | grep -E -- '--cache-prompt|--no-cache-prompt|--cache-reuse|--ctx-checkpoints|--swa-full|--cache-ram|--slot-save-path|--reasoning|--cache-type-k'
    /home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server --help 2>&1 | grep -i -E -- 'cache-type-k|q4_0'

Saída de --version:

    version: 0.7.0-dev (build 1, commit 620d222)
    built with GNU 13.3.0 for Linux x86_64

O source local tools/llama.cpp-v0.7.0-620d2225c tem HEAD 620d2225cc436ab0b001e3200e590e3b286ef9ab e git status --short vazio. --help confirmou todos os recursos solicitados:

| Opção | Resultado em --help |
|---|---|
| --cache-prompt / --no-cache-prompt | suportadas |
| --cache-reuse | suportada |
| --ctx-checkpoints | suportada, também aparece como --swa-checkpoints |
| --swa-full | suportada |
| --cache-ram | suportada |
| --slot-save-path | suportada |
| --reasoning | suportada (on, off, auto) |
| --cache-type-k q4_0 | suportada; q4_0 consta na lista de valores permitidos |

Confirmação estática no source local:

- tools/server/server.cpp:290,292: POST /tokenize e POST /apply-template.
- tools/server/server.cpp:303-304: GET /slots e POST /slots/:id_slot.
- tools/server/server-context.cpp:5415-5421: dispatch de action=save e action=restore; os handlers leem filename do corpo.
- tools/server/server-common.cpp:86,88: campos timings.cache_n e timings.prompt_n.

Nenhum servidor foi iniciado; as rotas foram verificadas no código, sem teste HTTP em runtime. Há outros binários llama-server sob tools/, mas os três runners indicados resolvem o symlink acima; não são builds referenciados por esses scripts.

## 3. Base de código

Resumo obtido com git branch --show-current, git rev-parse HEAD e git status --porcelain=v1 --untracked-files=all:

| Worktree | Branch | HEAD | Modificados | Deletados | Não rastreados | Entradas | Raízes de status mais presentes |
|---|---|---|---:|---:|---:|---:|---|
| local-llm-lab | fix/evaluation-oracle-observability-v3 | 4577aeb921587feaee8518c656a32a64d593ea9c | 13 | 0 | 43 | 56 | benchmark:14, results:21, tests:11, research:4, docs:2, scripts:3, versions.lock:1 |
| .worktrees/practical-agent-v2 | feat/practical-agent-v2 | 4577aeb921587feaee8518c656a32a64d593ea9c | 16 | 68 | 326 | 410 | results:221, benchmark:67, tests:63, scripts:25, docs:18, agent-manual:6, research:5 e arquivos de estado/lock |
| .worktrees/qwen-cleanup-r3-r4 | chore/qwen-cleanup-record | f940432b4733d764ac2d3a5406e09067c02d1c7a | 0 | 0 | 0 | 0 | árvore limpa |

git diff --stat entre HEADs, para benchmark/guarded_edit.py, benchmark/prefix_cache_paired.py, benchmark/qwen_engines.py e benchmark/qwen_workloads.py:

- local-llm-lab..practical-agent-v2: vazio; ambos estão no mesmo HEAD.
- local-llm-lab..qwen-cleanup-r3-r4 e practical-agent-v2..qwen-cleanup-r3-r4: guarded_edit.py (206 linhas alteradas) e prefix_cache_paired.py (9 linhas alteradas), total 16 insertions(+), 199 deletions(-).
- qwen_engines.py e qwen_workloads.py não estão no HEAD desses worktrees; existem apenas como arquivos não rastreados em practical-agent-v2. Seus testes e scripts/check_qwen_readiness.py também estão não rastreados ali. Portanto o diff por HEAD não os contabiliza.

Recomendação: usar o commit comum 4577aeb921587feaee8518c656a32a64d593ea9c como base de feat/4b-worker-v2, em um worktree limpo; tomar local-llm-lab/fix/evaluation-oracle-observability-v3 como referência da árvore rastreada, pois tem o mesmo HEAD e menos entradas sujas que practical-agent-v2. A versão atual de guarded_edit.py e prefix_cache_paired.py é idêntica entre essas duas árvores. Se os módulos Qwen não rastreados forem necessários, revisar e levar somente esses arquivos de practical-agent-v2 para a futura branch. qwen-cleanup-r3-r4 é limpo, mas está em HEAD anterior e não contém os módulos Qwen. Nenhum branch foi criado.

## 4. Reuso e estado atual de guarded_edit.py

scripts/check_qwen_readiness.py usa sys.executable, não fixa por si só um interpretador. O foundation.json existente, datado de 2026-10-27, registra /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python; esse caminho foi revalidado ao vivo: Python 3.12.3 e pytest 9.1.1. O /usr/bin/python3 global não tem pytest, então não foi usado.

Comando executado em practical-agent-v2, com temporários em /tmp:

    cd /mnt/d/Usuario/Downloads/LLM/.worktrees/practical-agent-v2
    PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp TMP=/tmp TEMP=/tmp \
      /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m pytest \
      -p no:cacheprovider -q \
      tests/test_guarded_edit.py tests/test_qwen_engines.py \
      tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py

Resultado real:

    ...........................................                              [100%]
    43 passed in 10.22s

O test_qwen_engines.py usa um servidor HTTP falso em 127.0.0.1; não inicia llama-server. Os testes usam tmp_path; não houve inferência/GPU. O resumo do status pós-teste permaneceu em 410 entradas (16 modificados, 68 deletados, 326 não rastreados); não apareceu alteração nova nos arquivos testados.

benchmark/guarded_edit.py já garante (linhas 83-157, 215-373): confinamento ao workspace e rejeição de travessia/symlink; verificação do SHA esperado quando fornecido; rejeição de SEARCH vazio, ausente ou ambíguo; fallback de comparação ignorando espaços finais; detector de vazamento conversacional; validação AST para Python; preservação de nomes de funções/classes existentes; e gravação atômica de um arquivo. A API aplica um único bloco SEARCH/REPLACE por chamada (apply_guarded_edit, linhas 215-224).

Faltas para a F3 do plano (PLANO-ESTRATEGICO-v2.md:82-85):

- não há lote transacional de vários blocos SEARCH/REPLACE por arquivo;
- não recebe nem valida uma allowlist writable_files; workspace-root é apenas um limite amplo;
- não tem regra que proíba especificamente alterações em testes/oráculos;
- o recibo é parcial: EditResult.to_dict() expõe success, status, new_sha256, diff e error_message, mas o sucesso preenche só new_sha256 (o diff fica null); não inclui hash anterior nem caminho do arquivo.

O próprio módulo ressalva que as verificações são guardas da aplicação, não sandbox de sistema operacional, e não impedem troca concorrente de caminho.

## Bloqueios

- O Q4_K_M íntegro foi encontrado no Windows E:, mas não existe na instalação WSL nem nos caminhos relativos de modelo dos runners. Não copiei o arquivo, pois isso excederia as escritas autorizadas; a execução futura em WSL permanece bloqueada até a disponibilidade autorizada do modelo nesse ambiente.
- Não foi possível enumerar o conteúdo de cinco pastas protegidas ($RECYCLE.BIN/System Volume Information) por acesso negado. Os seis resultados reportados cobrem os caminhos GGUF legíveis em D:/E:.
- Endpoints e timings foram confirmados no source correspondente ao commit do binário; seu comportamento em um servidor vivo não foi testado, conforme a proibição de iniciar servidor.
- Os módulos Qwen e seus testes que permitiram o reuso estão não rastreados em practical-agent-v2; o commit base recomendado, por si só, não os contém. Eles precisam de revisão antes de serem incorporados em uma futura branch.
- O item 5 da F0 (corpus de tarefas) não foi avaliado; está fora do escopo solicitado, limitado aos itens 1–4.

## Gate F0 itens 1–4: passou/falhou

1. **Falhou para disponibilidade operacional WSL; passou para integridade do modelo.** O Q4_K_M existe em E: e seu SHA-256 confere, mas o arquivo não está no caminho WSL dos runners.
2. **Passou.** Build usado, opções pedidas e endpoints/campos no source foram confirmados.
3. **Passou.** Estados e diffs dos três worktrees foram registrados; base recomendada sem criar branch.
4. **Passou.** Os quatro arquivos de teste pedidos passaram: 43 testes.

## Revisão do orquestrador (Claude, 28/10/2026)

O relatório foi aceito. Conferências independentes:

- SHA-256 do Q4_K_M em E:: recalculado, confere (`13c16f42…8a983`).
- `llama-server --version`: retorna 0.7.0-dev, commit 620d222. Todas as 5 flags de cache estão presentes no `--help`.
- Espaço livre no WSL: 36 GB, suficiente para copiar o modelo (3,0 GB).

Pendências antes da F1 e da F3, que dependem do aval do usuário:

1. Copiar o Q4_K_M de E: para `/home/foxtrot/local-llm-benchmark/models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf` e conferir o hash após a cópia.
2. Criar o worktree `feat/4b-worker-v2` a partir do commit `4577aeb` e trazer de `practical-agent-v2`, depois de revisá-los, só os módulos Qwen não rastreados de que a F1 e a F3 precisam: `qwen_*.py`, os testes correspondentes e `scripts/check_qwen_readiness.py`.
3. F0 item 5 (corpus de 12 tarefas embutidas num repo de 40–100K tokens): vai para o Terra 6.1 High, depois do item 2.




