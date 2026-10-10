# Execution status — 2026-10-10

## Researched

- Read official llama.cpp build/release material, ExLlamaV3 repository and current releases, and model cards for Qwen3.5/3.6/3.8, IBM Granite 4.1, Phi-4-mini, Gemma 3, Qwen2.5-Coder, and Bonsai 2 quant documentation.
- Confirmed three new 2026 candidates against official model repositories: Qwen3.8-27B, Qwen3.6-35B-A3B, and IBM Granite 4.1 3B. Their upstream quality and hardware claims remain unverified locally.
- Marked requested Qwen3.9 as unverified/not found in the official lookup. Do not download by guessing a repo name.
- Found a material Bonsai 2 compatibility warning: PQ2_0 needs a specialized activation transform; stock llama.cpp may load it and emit gibberish silently.
- Added recent third-party RTX 3070 reports to the source ledger as leads only.
- Rejected Ubuntu's nvidia-cuda-toolkit package after a simulation showed Linux NVIDIA driver packages in its dependency plan. NVIDIA's current WSL guide specifies its dedicated WSL repository and warns that an in-distro Linux driver can break the host-provided WSL driver. No packages from the rejected plan were installed.

## Audited

- Host: Windows 10 Pro 22H2 build 19045, Ryzen 5 5600X, 34.3 GB physical RAM, RTX 3070 8192 MiB, driver 610.62, reported CUDA API 13.3.
- WSL: Ubuntu 24.04.5, kernel 6.18.40.1, 8 visible vCPUs, 5.8 GiB RAM, 4 GiB swap, GPU visible in nvidia-smi.
- User .wslconfig sets memory=6GB, processors=8, swap=4GB. Not changed.
- WSL root filesystem: 49 GiB total, initially about 13 GiB free and now about 5 GiB after the CUDA toolkit install and clearing downloaded apt archives. E: about 109 GiB free at the latest check; F: about 157 GiB free during the initial audit.
- WSL Python 3.12.3, pip 24.0, CMake 3.28.3, GCC 13.3, Git 2.43.0. WSL Node is unavailable. Windows Node/npm/pnpm/Git and Python were detected.
- WSL GPU visibility was checked with nvidia-smi. This does not establish that a CUDA inference backend or model works.

## Installed / downloaded

- Installed CUDA Toolkit 13.0 from NVIDIA's WSL repository, including compiler 13.0.88 and g++-12. The package plan contained no Linux NVIDIA driver packages. The host-provided driver remains 610.62.
- Downloaded IBM Granite 4.1 3B GGUF Q4_K_M (2,099,501,664 bytes) to `E:\local-llm-models` and verified SHA-256 `662b0626cd58f443baea23559b469df6576a81d349649c59413b36a9fb32eb29`. Model remains outside Git.
- Built llama.cpp v0.6.0 tag at commit `d81235049384534c167caea52b85a694f6103d14`; `llama-cli` and `llama-server` report build `0.6.0-dev`. CUDA 13.0, GNU 13.3, host compiler g++-12, architecture sm_86. Incremental target build completed with no compile errors; GNU Make continues to warn about clock skew on the Windows-mounted D: volume.

## Executed / measured

- CLI smoke test loaded the model with 99 GPU layers at 2K context and returned exactly `READY`; its console-reported short-run generation was 53.3 tokens/s. Log: `logs/tier0-smoke.log`.
- Preliminary server series completed: one warm-up plus 3 measured calls at 2K context, f16 KV, Flash Attention on, 99 GPU layers. TTFT median 13.01 ms (12.40–13.36), prompt processing median 2,990 tok/s (2,947–3,059), server-reported generation median 127.27 tok/s (125.67–127.79), sampled VRAM use 3,146 MiB. Fixed 25-token prompt, 22 generated tokens per call. These are short-run throughput measurements, not a quality ranking; records were created before the instrumentation checkpoint and have the prior Git HEAD.

## Current constraints and next steps

- The 6 GiB WSL memory cap and approximately 5 GiB free root space make full PyTorch, QLoRA, and 14–35B hybrid work uncertain. Those tiers remain untested; the WSL cap was not changed.
- Free VRAM varied substantially with other Windows and WSL workloads: 4.6 GiB at first audit, 3.2–3.4 GiB during installation, and 7.2 GiB immediately before the successful smoke test.
- Next: checkpoint source and preliminary artifacts on `feat/tier0-runtime`, repeat the Tier 0 series from a clean commit, test quantized KV and context sizes, then decide whether ExLlamaV3/training stacks fit storage and memory constraints. Harnesses, multiagent, router API tests, MoE and fine-tuning have not been installed or benchmarked.
