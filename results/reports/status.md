# Execution status — 2026-10-10

## Researched

- Read official llama.cpp build/release material, ExLlamaV3 repository and current releases, and model cards for Qwen3.5/3.6/3.8, IBM Granite 4.1, Phi-4-mini, Gemma 3, Qwen2.5-Coder, and Bonsai 2 quant documentation.
- Added three 2026 candidates: Qwen3.8-27B, Qwen3.6-35B-A3B, and IBM Granite 4.1 3B. Upstream claims remain unverified locally.
- Marked requested Qwen3.9 as unverified/not found in the official lookup. Do not download by guessing a repo name.
- Found a material Bonsai 2 compatibility warning: PQ2_0 needs a specialized activation transform; stock llama.cpp may load it and emit gibberish silently.
- Added recent third-party RTX 3070 reports to the source ledger as leads only.
- Rejected Ubuntu's nvidia-cuda-toolkit package after a simulation showed Linux NVIDIA driver packages in its dependency plan. NVIDIA's current WSL guide specifies its dedicated WSL repository and warns that an in-distro Linux driver can break the host-provided WSL driver. No packages from the rejected plan were installed.

## Audited

- Host: Windows 10 Pro 22H2 build 19045, Ryzen 5 5600X, 34.3 GB physical RAM, RTX 3070 8192 MiB, driver 610.62, reported CUDA API 13.3.
- WSL: Ubuntu 24.04.5, kernel 6.18.40.1, 8 visible vCPUs, 5.8 GiB RAM, 4 GiB swap, GPU visible in nvidia-smi.
- User .wslconfig sets memory=6GB, processors=8, swap=4GB. Not changed.
- WSL root filesystem: 49 GiB total, about 13 GiB free. E: about 111 GiB free; F: about 157 GiB free. GPU had about 4.6 GiB free during the audit.
- WSL Python 3.12.3, pip 24.0, CMake 3.28.3, GCC 13.3, Git 2.43.0. CUDA toolkit compiler and WSL Node were not found. Windows Node/npm/pnpm/Git and Python were detected.
- WSL GPU visibility was checked with nvidia-smi. This does not establish that a CUDA inference backend or model works.

## Installed / downloaded

- No new software or models installed yet. The official WSL CUDA toolkit path is being prepared and pinned to CUDA 13.0; it will be checked for driver packages before installation.

## Executed / measured

- No model inference or throughput benchmark completed yet. The machine audit is not a runtime benchmark.

## Current constraints and next steps

- The 6 GiB WSL memory cap and 13 GiB free root space make full PyTorch, QLoRA, and 14–35B hybrid work uncertain. Start with a small GGUF model, resolve its immutable revision and exact file size, then choose the smallest safe runtime installation.
- At audit time, Windows and the desktop were using the shared GPU; free VRAM was about 4.6 GiB.
- The next checkpoint is the verified audit and research inventory. Then install one runtime, download only a small model tier to a separately configured model directory, and run Tier 0.
