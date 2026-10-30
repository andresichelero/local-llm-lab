# Machine, versions, and storage

This document describes the environment in which stages 1 through 3 ran, between October 28 and 29, 2026. Any version or hardware change requires a new baseline because the numbers depend on the environment.

## Host

| Item | Value |
|---|---|
| Operating system | Windows 10 Pro 22H2 (build 19045) |
| CPU | AMD Ryzen 5 5600X |
| Memory | 32 GB |
| GPU | NVIDIA GeForce RTX 3070, 8 GB (8 192 MiB), Ampere architecture (`sm_86`) |
| NVIDIA driver | 610.62 (Windows) |
| GPU sharing | the Windows desktop uses the same GPU |

## WSL2

| Item | Value |
|---|---|
| Distribution | Ubuntu 24.04 |
| Memory | 8 GB limit, configured in `.wslconfig` |
| CUDA Toolkit | 13.0 (`nvcc` 13.0.88) |
| Laboratory directory | `~/local-llm-benchmark` (WSL ext4) |

## Software

| Component | Version | Notes |
|---|---|---|
| llama.cpp (`llama-server`) | v0.8.0, commit `8642541b255bfb5dc39cd351a178be09013a55d6` | `llama-server 0.8.0-dev`, build 1. Binary SHA-256 in `benchmark/configs/qwen-4b-opencode-baseline.json`. |
| llama.cpp build | `Release`, `GGML_CUDA=ON`, `GGML_NATIVE=ON`, `CMAKE_CUDA_ARCHITECTURES=86` | Built in WSL with `nvcc` 13.0. The previous version, v0.7.0 (commit `620d222`), was used only in the F0 preflight. |
| OpenCode | 1.19.5 | Binary SHA-256 in `benchmark/configs/qwen-4b-opencode-baseline.json`. |
| bubblewrap | 0.9.0 | At `/usr/bin/bwrap`. |
| Node.js | v25.5.0 | Installed through NVM. The path is in the config. |
| Python | 3.12.3 | `lab-validation-20261028` environment. |
| pytest | 9.1.1 | Same environment. |
| ruff | 0.17.3 | Updated from 0.15.17 on 28/10/2026. There is no ruff configuration in the repository. |
| git (WSL) | 2.43.0 | WSL git version. Not part of the benchmark. |

## Weights (GGUF)

The weights are not in the repository. The hashes below are used by the runner for integrity verification.

| Config label | Quantization | Quantizer | Size (bytes) | SHA-256 (prefix) | Location |
|---|---|---|---:|---|---|
| `q4` (control) | Q4_K_M | bartowski | 3 013 027 808 | `13c16f42…` | WSL ext4 |
| `q6` | Q6_K | unsloth | 3 525 956 768 | `fdedd781…` | D: drive (read via `/mnt/d`) |
| `q8` | Q8_0 | unsloth | 4 482 403 488 | `10cc391b…` | D: drive (read via `/mnt/d`) |
| `q4_unsloth` | Q4_K_M | unsloth | 2 740 937 888 | `00fe7986…` | WSL ext4 |

The runner checks each GGUF's SHA-256 before each run (the `manifest()` function in `benchmark/opencode_baseline.py`) and stops if the hash differs. The unsloth Q4_K_M has revision `e87f176479d0855a907a41277aca2f8ee7a09523`.

## Storage

- **Laboratory rule.** Benchmarks run from WSL ext4 on an SSD. The D: and E: drives are used for archives and checkouts. This rule was recorded in the laboratory's earlier documentation, dated 11/10/2026.
- **Known deviation.** Arms `B-q6` and `B-q8` read the GGUFs from D: through `/mnt/d`. Loading takes place before each measured episode, and its effect on metrics was not measured. The other arms read from WSL ext4.
- **Raw results.** Stored in `~/local-llm-benchmark/results/`, outside the repository.

## System measurements

- **VRAM.** Sampled by `nvidia-smi` at approximately 1 Hz. The value covers the entire device, not just the `llama-server` process memory. It includes any GPU use by the desktop.
- **WSL memory and CPU.** Read from `/proc` at each sample.
- **Windows memory.** Read through interoperability (PowerShell) in a separate thread, with a timeout. It may be unavailable.

Raw samples are in `resource_samples` in each `result.json`, outside the repository.
