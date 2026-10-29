# Máquina, versões e armazenamento

Este documento descreve o ambiente em que as etapas 1 a 3 rodaram, entre 28 e 29 de outubro de 2026. Qualquer mudança de versão ou de hardware exige uma nova linha de base, porque os números dependem do ambiente.

## Host

| Item | Valor |
|---|---|
| Sistema operacional | Windows 10 Pro 22H2 (build 19045) |
| CPU | AMD Ryzen 5 5600X |
| Memória | 32 GB |
| GPU | NVIDIA GeForce RTX 3070, 8 GB (8 192 MiB), arquitetura Ampere (`sm_86`) |
| Driver NVIDIA | 610.62 (Windows) |
| Compartilhamento da GPU | o desktop do Windows usa a mesma GPU |

## WSL2

| Item | Valor |
|---|---|
| Distribuição | Ubuntu 24.04 |
| Memória | limite de 8 GB, configurado no `.wslconfig` |
| CUDA Toolkit | 13.0 (`nvcc` 13.0.88) |
| Diretório do laboratório | `~/local-llm-benchmark` (ext4 do WSL) |

## Software

| Componente | Versão | Observação |
|---|---|---|
| llama.cpp (`llama-server`) | v0.8.0, commit `8642541b255bfb5dc39cd351a178be09013a55d6` | `llama-server 0.8.0-dev`, build 1. SHA-256 do binário em `benchmark/configs/qwen-4b-opencode-baseline.json`. |
| Compilação do llama.cpp | `Release`, `GGML_CUDA=ON`, `GGML_NATIVE=ON`, `CMAKE_CUDA_ARCHITECTURES=86` | Compilado no WSL com o `nvcc` 13.0. A versão anterior, v0.7.0 (commit `620d222`), foi usada só na pré-verificação da F0. |
| OpenCode | 1.19.5 | SHA-256 do binário em `benchmark/configs/qwen-4b-opencode-baseline.json`. |
| bubblewrap | 0.9.0 | Em `/usr/bin/bwrap`. |
| Node.js | v25.5.0 | Instalado pelo NVM. O caminho está no config. |
| Python | 3.12.3 | Ambiente `lab-validation-20261028`. |
| pytest | 9.1.1 | Mesmo ambiente. |
| ruff | 0.17.3 | Atualizado de 0.15.17 em 28/10/2026. Não há configuração de ruff no repositório. |
| git (WSL) | 2.43.0 | Versão do git no WSL. Não faz parte do benchmark. |

## Pesos (GGUF)

Os pesos não estão no repositório. Os hashes abaixo são a verificação de integridade do runner.

| Rótulo no config | Quantização | Quantizador | Tamanho (bytes) | SHA-256 (início) | Onde fica |
|---|---|---|---:|---|---|
| `q4` (controle) | Q4_K_M | bartowski | 3 013 027 808 | `13c16f42…` | ext4 do WSL |
| `q6` | Q6_K | unsloth | 3 525 956 768 | `fdedd781…` | disco D: (lido por `/mnt/d`) |
| `q8` | Q8_0 | unsloth | 4 482 403 488 | `10cc391b…` | disco D: (lido por `/mnt/d`) |
| `q4_unsloth` | Q4_K_M | unsloth | 2 740 937 888 | `00fe7986…` | ext4 do WSL |

O runner confere o SHA-256 de cada GGUF antes de cada execução (função `manifest()` de `benchmark/opencode_baseline.py`), e para se o hash divergir. O Q4_K_M de unsloth tem revisão `e87f176479d0855a907a41277aca2f8ee7a09523`.

## Armazenamento

- **Regra do laboratório.** Benchmarks rodam a partir do ext4 do WSL, que fica em SSD. Os discos D: e E: são usados para arquivo e checkout. Essa regra está registrada na documentação anterior do laboratório, de 11/10/2026.
- **Desvio conhecido.** Os braços `B-q6` e `B-q8` leem os GGUF de D:, pelo caminho `/mnt/d`. O carregamento acontece antes de cada episódio medido, e o efeito sobre as métricas não foi medido. Os demais braços leem do ext4 do WSL.
- **Resultados brutos.** Ficam em `~/local-llm-benchmark/results/`, fora do repositório.

## Medições de sistema

- **VRAM.** Amostrada por `nvidia-smi` a cerca de 1 Hz. O valor é do dispositivo inteiro, e não da memória do processo do `llama-server`. Quando o desktop usa a GPU, o valor inclui esse uso.
- **Memória e CPU do WSL.** Lidas de `/proc` a cada amostra.
- **Memória do Windows.** Lida por interoperabilidade (PowerShell) em thread separada, com timeout. Pode ficar indisponível.

As amostras brutas ficam em `resource_samples` de cada `result.json`, fora do repositório.
