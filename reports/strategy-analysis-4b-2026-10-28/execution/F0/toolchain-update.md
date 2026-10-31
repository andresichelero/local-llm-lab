# Toolchain update — 28/10/2026

## State and versions

WSL root: `/home/foxtrot/local-llm-benchmark`. Older installations were preserved. Candidates in parallel paths are not automatically active; the exception is the Ruff link, explicitly changed and reversible. Complete package numbers are in the snapshots, not just the table.

| Component | Before | After | Path and notes |
|---|---|---|---|
| llama.cpp | 0.7.0-dev, `620d222` | 0.8.0-dev, `8642541` (tag `v0.8.0`); build and smoke passed | `tools/llama.cpp-v0.7.0-620d2225c`, `tools/llama-bin-v0.7.0-620d2225c`; new `tools/llama.cpp-v0.8.0-8642541b2`, `tools/llama-bin-v0.8.0-8642541b2`; active link points to the new one |
| CUDA toolkit | 13.0.88 | unchanged | `/usr/local/cuda-13.0/bin/nvcc`; driver NVIDIA 610.62; RTX 3070 8192 MiB |
| lab-validation | pytest 9.1.1; pip 24.0 | pytest 9.1.1; pip 26.2.2 | `envs/lab-validation-20261028`; pytest 9.2.0 available, but pin prevents update |
| mistral-vibe | 3.0.2; pip 24.0 | 3.0.2; pip 26.2.2 | `envs/mistral-vibe-20261028`; version 3.0.3 available, but pin prevents update |
| qwen-engines | exllamav3 1.6.4+cu132.torch2.13.0; pip 26.2.2 | preserved | `envs/qwen-engines-20261028/venv`; exllamav3 1.6.5 available, but CUDA/Torch wheel and Tabby require specific review; no inference test |
| Python refresh: headroom / MCP | 0.41.0 / 1.30.0 | 0.42.0 / 2.3.0 | `envs/python-refresh-20261028/headroom-python-3.14`; MCP changed major version and was not functionally tested |
| Python refresh: uv | 0.13.5 | 0.13.6 | `envs/python-refresh-20261028/bootstrap` |
| Python refresh: Aider / OpenHands | 0.86.2 / 1.16.0 | same; cyclopts 5.3.0 → 5.3.2 | `envs/python-refresh-20261028/`; Vibe 3.0.2 retained by pin; Aider 3.13 and 3.14 venvs, previously without pip, received pip 26.2.2 |
| Ruff | 0.15.17 | 0.17.3 | `~/.local/bin/ruff` → `envs/ruff-tools-20261028/ruff/bin/ruff`; previous installation `~/.local/share/uv/tools/ruff` |
| OpenCode | 1.19.4 | 1.19.5 | `envs/node-harnesses-update-20261028/opencode` |
| pi | 1.4.0 | 1.4.0 | `envs/node-harnesses-update-20261028/pi` |
| trueforge | 0.179.2 | 0.181.0 | `envs/node-harnesses-update-20261028/trueforge`; `--version` is not a valid option |
| Claude Code WSL | 2.1.310 | 2.1.312 | `envs/node-harnesses-update-20261028/claude-code` |
| Codex WSL | 0.164.0 | 0.165.0 | `envs/node-harnesses-update-20261028/codex` |
| Qwen Code | 0.26.1 | 0.26.3 | `envs/node-harnesses-update-20261028/qwen-code`; `npm ls` reports three extraneous packages |
| headroom-opencode | 0.41.0 | 0.42.0 | `envs/node-harnesses-update-20261028/headroom-opencode` |
| DeepSeek dsh | 0.2.1-rc.2 | same | `envs/node-harnesses-update-20261028/deepseek-harness`; `npm ls` reports two extraneous packages |
| Node/npm | Node 24.22.1 / npm 11.19.1 in previous runtime | Node 25.5.0 / npm 11.8.0 in new prefixes | NVM runtime; versions not changed globally |
| Codex CLI Windows | 0.165.0 | 0.165.0 is the `latest` queried on npm | Windows npm installation; not updated |

Node candidates were installed without activating paths used by the project. OpenCode, pi and trueforge have versions pinned in `versions.lock`; different versions are not an update to the pinned protocol. OpenCode, pi, Qwen, Claude and Codex Linux responded to `--version`; installation and `npm ls` details are in the `*-after.*` files of the new prefixes.

## llama.cpp build

The previous cache records `Release`, `GGML_CUDA=ON`, `GGML_NATIVE=ON`, shared libraries and `/usr/local/cuda/bin/nvcc`; `flags.make` confirms `compute_86,sm_86`. The latest release queried on the GitHub API was [v0.8.0](https://github.com/ggml-org/llama.cpp/releases/tag/v0.8.0), published on 28/10/2026, commit `8642541b255bfb5dc39cd351a178be09013a55d6`.

```bash
cd /home/foxtrot/local-llm-benchmark/tools
git clone --branch v0.8.0 --depth 1 https://github.com/ggml-org/llama.cpp.git llama.cpp-v0.8.0-8642541b2
cmake -S llama.cpp-v0.8.0-8642541b2 -B llama.cpp-v0.8.0-8642541b2/build \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_NATIVE=ON \
  -DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DCMAKE_RUNTIME_OUTPUT_DIRECTORY=/home/foxtrot/local-llm-benchmark/tools/llama-bin-v0.8.0-8642541b2 \
  -DCMAKE_LIBRARY_OUTPUT_DIRECTORY=/home/foxtrot/local-llm-benchmark/tools/llama-bin-v0.8.0-8642541b2
cmake --build llama.cpp-v0.8.0-8642541b2/build --parallel 3
# Interrupted by us to raise parallelism; incremental resume:
cmake --build llama.cpp-v0.8.0-8642541b2/build --parallel 6
```

The project's CMake resets output directories to `build/bin`, regardless of the options above. The complete build finished with exit code zero; files were copied with `cp -an .../build/bin/. .../llama-bin-v0.8.0-8642541b2/`. As in the old build, the executable RUNPATH points to the source `build/bin`; retain both the source/build and binaries directory. Logs: `llama-configure.log`, `llama-build.log` in this folder. NCCL was not found; configuration noted that this affects multi-GPU performance. The UI tried the pinned file and used the `latest` fallback; this is an additional unpinned build dependency.

## Smoke, validation and rollback

`llama-server --version` returned `0.8.0-dev (build 1, commit 8642541)`. `--help` included `--cache-prompt`, `--cache-reuse`, `--ctx-checkpoints`, `--cache-ram`, `--slot-save-path`, `--reasoning`, `--cache-type-k` and `q4_0`. The test used the requested local GGUF, `-ngl 99 --ctx-size 16384 --cache-type-k q4_0 --cache-type-v q4_0 --flash-attn on --reasoning off --jinja`, `127.0.0.1:18080` and a single slot. `/tokenize` returned 2,201 tokens for the prefix; `/apply-template` returned a nonempty prompt. Two identical requests with `cache_prompt=true`:

| Request | `timings.prompt_n` | `timings.cache_n` | `timings.prompt_ms` |
|---|---:|---:|---:|
| first | 2220 | 0 | 809,617 |
| second | 4 | 2216 | 76,516 |

Total VRAM used on the GPU: 654 MiB before, 3912 MiB after loading, 3934 MiB after requests, 652 MiB after shutdown; includes usage by other processes. The server was stopped and the port had no listener. Evidence in `llama-smoke.json` and `llama-smoke-server.log`; `version` was empty in JSON because the executable wrote to stderr, but the version was checked separately and the script was corrected to capture it in future runs. The log records unused `nextn`/layer 32 tensors; the smoke demonstrates loading and cache, not model quality or comprehensive functional validation.

After the smoke, `tools/llama-bin` was pointed to the new directory. The previous target is in `llama-bin.previous-link.txt`: `/home/foxtrot/local-llm-benchmark/tools/llama-bin-v0.7.0-620d2225c`. Link rollback, if needed:

```bash
cd /home/foxtrot/local-llm-benchmark/tools
ln -s /home/foxtrot/local-llm-benchmark/tools/llama-bin-v0.7.0-620d2225c llama-bin-rollback
mv -T llama-bin-rollback llama-bin
```

Commands run in worktree `practical-agent-v2`:

```bash
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m pytest -p no:cacheprovider -q tests/test_guarded_edit.py tests/test_qwen_engines.py tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py
/home/foxtrot/.local/bin/ruff check benchmark/guarded_edit.py benchmark/qwen_engines.py benchmark/qwen_workloads.py
```

Pytest: **43 passed in 11.48 s** in the original environment; the same set passed in candidate `lab-validation-20261028` (**43 in 11.22 s**). Ruff 0.17.3: **4 errors** (`I001` in `guarded_edit.py` and `qwen_workloads.py`, `SIM114` in `guarded_edit.py`, `PIE790` in `qwen_engines.py`); log `ruff.log`. Older Ruff 0.15.17 passed the same command. Project code was not edited to make lint pass. The result does not validate the other harnesses or the GPU smoke.

## System

`sudo -n apt-get -o APT::Update::Error-Mode=any update` and `sudo -n apt-get -y upgrade` finished with code 0, 24 packages updated. Version history in `/var/log/apt/history.log` and `/var/log/dpkg.log`. Initially no DNS was configured in `systemd-resolved`; the first attempt returned code zero with resolution failures, so it was not treated as a valid update. DNS was temporarily configured for installation and then reverted with `sudo -n resolvectl revert eth0`; the previous state without DNS returned. Persistent WSL DNS configuration requires user investigation.

Python snapshots: `snapshots-python-20261028/` in this folder, including `*.before.freeze.txt`, `*.after.freeze.txt`, `*.pip.txt`, `*.outdated.json`, logs and `ruff.previous-link.txt`; the two venvs without pip had freeze via `uv pip freeze`. Previous Node snapshots: `/home/foxtrot/local-llm-benchmark/envs/node-harnesses-update-20261028-snapshots/`. Ruff recovery can use the recorded old target; old environments and builds remain in their original directories. Python candidates passed `pip check`, but this does not validate inference or all absolute references in the qwen-engines copy. Transformers 5.20.2 was retained in the Headroom environment out of caution given existing pins for another training context; compatibility of 5.21.0 was not established.
