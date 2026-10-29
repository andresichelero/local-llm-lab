# Atualização do toolchain — 28/10/2026

## Estado e versões

Raiz WSL: `/home/foxtrot/local-llm-benchmark`. As instalações antigas foram preservadas. Candidatos em caminhos paralelos não estão automaticamente ativos; a exceção é o link do Ruff, explicitamente alterado e reversível. Os números de pacotes completos estão nos snapshots, não apenas na tabela.

| Componente | Antes | Depois | Caminho e observações |
|---|---|---|---|
| llama.cpp | 0.7.0-dev, `620d222` | 0.8.0-dev, `8642541` (tag `v0.8.0`); build e smoke passaram | `tools/llama.cpp-v0.7.0-620d2225c`, `tools/llama-bin-v0.7.0-620d2225c`; novo `tools/llama.cpp-v0.8.0-8642541b2`, `tools/llama-bin-v0.8.0-8642541b2`; link ativo aponta para o novo |
| CUDA toolkit | 13.0.88 | inalterado | `/usr/local/cuda-13.0/bin/nvcc`; driver NVIDIA 610.62; RTX 3070 8192 MiB |
| lab-validation | pytest 9.1.1; pip 24.0 | pytest 9.1.1; pip 26.2.2 | `envs/lab-validation-20261028`; pytest 9.2.0 disponível, mas pin impede atualização |
| mistral-vibe | 3.0.2; pip 24.0 | 3.0.2; pip 26.2.2 | `envs/mistral-vibe-20261028`; versão 3.0.3 disponível, mas pin impede atualização |
| qwen-engines | exllamav3 1.6.4+cu132.torch2.13.0; pip 26.2.2 | preservados | `envs/qwen-engines-20261028/venv`; exllamav3 1.6.5 disponível, mas wheel CUDA/Torch e Tabby exigem revisão específica; sem teste de inferência |
| Python refresh: headroom / MCP | 0.41.0 / 1.30.0 | 0.42.0 / 2.3.0 | `envs/python-refresh-20261028/headroom-python-3.14`; MCP mudou de versão principal e não foi testado funcionalmente |
| Python refresh: uv | 0.13.5 | 0.13.6 | `envs/python-refresh-20261028/bootstrap` |
| Python refresh: Aider / OpenHands | 0.86.2 / 1.16.0 | mesmos; cyclopts 5.3.0 → 5.3.2 | `envs/python-refresh-20261028/`; Vibe 3.0.2 retido por pin; venvs Aider 3.13 e 3.14, antes sem pip, receberam pip 26.2.2 |
| Ruff | 0.15.17 | 0.17.3 | `~/.local/bin/ruff` → `envs/ruff-tools-20261028/ruff/bin/ruff`; instalação anterior `~/.local/share/uv/tools/ruff` |
| OpenCode | 1.19.4 | 1.19.5 | `envs/node-harnesses-update-20261028/opencode` |
| pi | 1.4.0 | 1.4.0 | `envs/node-harnesses-update-20261028/pi` |
| trueforge | 0.179.2 | 0.181.0 | `envs/node-harnesses-update-20261028/trueforge`; `--version` não é opção válida |
| Claude Code WSL | 2.1.310 | 2.1.312 | `envs/node-harnesses-update-20261028/claude-code` |
| Codex WSL | 0.164.0 | 0.165.0 | `envs/node-harnesses-update-20261028/codex` |
| Qwen Code | 0.26.1 | 0.26.3 | `envs/node-harnesses-update-20261028/qwen-code`; `npm ls` reporta três pacotes extraneous |
| headroom-opencode | 0.41.0 | 0.42.0 | `envs/node-harnesses-update-20261028/headroom-opencode` |
| DeepSeek dsh | 0.2.1-rc.2 | mesmo | `envs/node-harnesses-update-20261028/deepseek-harness`; `npm ls` reporta dois pacotes extraneous |
| Node/npm | Node 24.22.1 / npm 11.19.1 no runtime anterior | Node 25.5.0 / npm 11.8.0 nos novos prefixos | Runtime NVM; versões não alteradas globalmente |
| Codex CLI Windows | 0.165.0 | 0.165.0 é o `latest` consultado no npm | `C:\Users\<usuario>\AppData\Roaming\npm\codex.ps1`; não atualizado |

Os candidatos Node foram instalados sem ativar os caminhos usados pelo projeto. OpenCode, pi e trueforge têm versões fixadas no `versions.lock`; versões diferentes não são uma atualização do protocolo fixado. OpenCode, pi, Qwen, Claude e Codex Linux responderam a `--version`; os detalhes de instalação e de `npm ls` estão nos arquivos `*-after.*` dos prefixos novos.

## Build llama.cpp

O cache anterior registra `Release`, `GGML_CUDA=ON`, `GGML_NATIVE=ON`, bibliotecas compartilhadas e `/usr/local/cuda/bin/nvcc`; `flags.make` confirma `compute_86,sm_86`. O último release consultado na API GitHub foi [v0.8.0](https://github.com/ggml-org/llama.cpp/releases/tag/v0.8.0), publicado em 28/10/2026, commit `8642541b255bfb5dc39cd351a178be09013a55d6`.

```bash
cd /home/foxtrot/local-llm-benchmark/tools
git clone --branch v0.8.0 --depth 1 https://github.com/ggml-org/llama.cpp.git llama.cpp-v0.8.0-8642541b2
cmake -S llama.cpp-v0.8.0-8642541b2 -B llama.cpp-v0.8.0-8642541b2/build \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_NATIVE=ON \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DCMAKE_RUNTIME_OUTPUT_DIRECTORY=/home/foxtrot/local-llm-benchmark/tools/llama-bin-v0.8.0-8642541b2 \
  -DCMAKE_LIBRARY_OUTPUT_DIRECTORY=/home/foxtrot/local-llm-benchmark/tools/llama-bin-v0.8.0-8642541b2
cmake --build llama.cpp-v0.8.0-8642541b2/build --parallel 3
# Interrompido por nós para aumentar o paralelismo; retomada incremental:
cmake --build llama.cpp-v0.8.0-8642541b2/build --parallel 6
```

O CMake do projeto redefine os diretórios de saída para `build/bin`, independentemente das opções acima. Build completo finalizado com código zero; os arquivos foram copiados com `cp -an .../build/bin/. .../llama-bin-v0.8.0-8642541b2/`. Como no build antigo, o RUNPATH dos executáveis aponta para o `build/bin` da fonte; mantenha tanto a fonte/build quanto o diretório de binários. Logs: `llama-configure.log`, `llama-build.log` nesta pasta. NCCL não encontrado; configuração observou que isso afeta desempenho multi-GPU. A UI tentou o arquivo fixado e usou fallback `latest`; isso é uma dependência adicional não fixada do build.

## Smoke, validação e rollback

O `llama-server --version` retornou `0.8.0-dev (build 1, commit 8642541)`. O `--help` continha `--cache-prompt`, `--cache-reuse`, `--ctx-checkpoints`, `--cache-ram`, `--slot-save-path`, `--reasoning`, `--cache-type-k` e `q4_0`. O teste usou o GGUF local solicitado, `-ngl 99 --ctx-size 16384 --cache-type-k q4_0 --cache-type-v q4_0 --flash-attn on --reasoning off --jinja`, `127.0.0.1:18080` e um único slot. `/tokenize` retornou 2.201 tokens para o prefixo; `/apply-template` retornou prompt não vazio. Duas requisições idênticas com `cache_prompt=true`:

| Requisição | `timings.prompt_n` | `timings.cache_n` | `timings.prompt_ms` |
|---|---:|---:|---:|
| primeira | 2220 | 0 | 809,617 |
| segunda | 4 | 2216 | 76,516 |

VRAM total usada na GPU: 654 MiB antes, 3912 MiB após carga, 3934 MiB após requisições, 652 MiB após desligamento; inclui uso de outros processos. O servidor foi encerrado e a porta ficou sem listener. Evidência em `llama-smoke.json` e `llama-smoke-server.log`; `version` saiu vazio no JSON porque o executável escreveu em stderr, mas a versão foi conferida separadamente e o script foi corrigido para capturá-la em execuções futuras. O log registra tensores `nextn`/camada 32 não usados; o smoke demonstra carregamento e cache, não qualidade do modelo ou validação funcional abrangente.

Após o smoke, `tools/llama-bin` foi apontado para o novo diretório. O alvo anterior está em `llama-bin.previous-link.txt`: `/home/foxtrot/local-llm-benchmark/tools/llama-bin-v0.7.0-620d2225c`. Rollback do link, se necessário:

```bash
cd /home/foxtrot/local-llm-benchmark/tools
ln -s /home/foxtrot/local-llm-benchmark/tools/llama-bin-v0.7.0-620d2225c llama-bin-rollback
mv -T llama-bin-rollback llama-bin
```

Comandos executados na worktree `practical-agent-v2`:

```bash
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m pytest -p no:cacheprovider -q tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py
/home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/qwen_engines.py benchmark/qwen_workloads.py
```

Pytest: **43 passaram em 11,48 s** no ambiente original; o mesmo conjunto passou no candidato `lab-validation-20261028` (**43 em 11,22 s**). Ruff 0.17.3: **4 erros** (`I001` em `guarded_edit.py` e `qwen_workloads.py`, `SIM114` em `guarded_edit.py`, `PIE790` em `qwen_engines.py`); log `ruff.log`. Ruff 0.15.17 antigo passou no mesmo comando. Não houve edição do código do projeto para fazer o lint passar. Resultado não é uma validação dos demais harnesses nem do smoke GPU.

## Sistema

`sudo -n apt-get -o APT::Update::Error-Mode=any update` e `sudo -n apt-get -y upgrade` terminaram com código 0, 24 pacotes atualizados. Histórico de versões em `/var/log/apt/history.log` e `/var/log/dpkg.log`. Inicialmente não havia DNS configurado em `systemd-resolved`; a primeira tentativa retornou código zero com falhas de resolução, portanto não foi tratada como atualização válida. Foi temporariamente configurado DNS para execução das instalações e depois revertido com `sudo -n resolvectl revert eth0`; o estado anterior sem DNS voltou. A configuração persistente do DNS do WSL requer investigação pelo usuário.

Snapshots Python: `snapshots-python-20261028/` nesta pasta, incluindo `*.before.freeze.txt`, `*.after.freeze.txt`, `*.pip.txt`, `*.outdated.json`, logs e `ruff.previous-link.txt`; os dois venvs sem pip tiveram freeze por `uv pip freeze`. Snapshots Node anteriores: `/home/foxtrot/local-llm-benchmark/envs/node-harnesses-update-20261028-snapshots/`. A recuperação do Ruff pode usar o alvo antigo registrado; ambientes e builds antigos permanecem em seus diretórios originais. Os candidatos Python passaram em `pip check`, mas isso não valida inferência nem todas as referências absolutas da cópia de qwen-engines. Transformers 5.20.2 foi mantido no ambiente Headroom por cautela diante de pins existentes para outro contexto de treinamento; a compatibilidade de 5.21.0 não foi estabelecida.
