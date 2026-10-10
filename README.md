# Local LLM Lab

Reproducible experiments for local inference, quantization, fine-tuning, and agent harnesses on this Windows 10 + WSL2 host. The machine audit is stored under `results/system-audit/`; run results must be recorded separately from upstream claims.

## Machine facts that constrain this lab

- Windows 10 Pro 22H2, Ryzen 5 5600X, 32 GiB physical RAM, RTX 3070 8 GiB, NVIDIA driver 610.62.
- Ubuntu 24.04.5 in WSL2, kernel 6.18.40.1, CUDA device visible through `nvidia-smi`.
- The current user `.wslconfig` limits WSL to 6 GiB RAM, 8 processors, and 4 GiB swap. This lab will not change that setting.
- Free VRAM has varied from about 4.6 GiB during the first audit to 3.2–3.4 GiB while other WSL and Windows workloads were active; the desktop shares this GPU.
- The WSL root filesystem started with about 13 GiB free. After installing the CUDA toolkit and clearing only its downloaded apt package archives, it has about 5 GiB free. E: had about 111 GiB free and F: about 157 GiB at audit time. Current disk space changes; check it before downloads/builds.
- CUDA Toolkit 13.0 was installed from NVIDIA's WSL repository. `nvcc` 13.0.88 is available. The Windows driver remains 610.62; no Linux NVIDIA driver was installed into WSL.

The host, WSL and GPU can change while the lab runs. Re-run the audit before interpreting later benchmarks.

## Quick start

```bash
cd /mnt/d/Usuario/Downloads/LLM/local-llm-lab
bash scripts/00_audit_system.sh
```

The audit is read-only. Model downloads require an explicit tier and check free space before writing:

```bash
MODEL_DIR=/mnt/e/local-llm-models bash scripts/07_download_models.sh --tier small --dry-run
```

Do not use `--tier all` until the model matrix has been reviewed and each download's size is known. Existing model directories are never cleaned by these scripts.

## Experiment status

See `results/reports/status.md` for the current ledger of what has been researched, installed, executed, measured, and deferred. `research/source-ledger.csv` classifies primary evidence separately from community reports. Community throughput claims are leads, not lab measurements.

## Reproducibility rules

- Each run records the git revision, model revision, runtime version, quantization, context, generation limit, and hardware readings when available.
- Keep raw JSONL and logs. Derived CSV/report files can be regenerated.
- Use one warm-up and at least three measured repetitions for comparisons. This lab's initial smoke run is explicitly not a final ranking.
- Keep prompts, seeds, sampling settings, and endpoints fixed within a comparison.
- Do not infer quality from throughput. Coding tasks must include deterministic checks and preserve their test output.
- Never store API keys or credentials in this repository. Cloud work is opt-in and has a conservative spend ceiling.

## Current first experiment

The first Tier 0 target is IBM Granite 4.1 3B in GGUF Q4_K_M, served locally by llama.cpp. The pinned model was downloaded to `E:\local-llm-models` and verified against SHA-256 in `versions.lock`. A CLI smoke test and a clean-source three-repeat 2K-context server baseline completed; the clean baseline is in `results/raw/tier0-final.jsonl`, consolidated results are in `results/csv/summary.csv`, and a human-readable summary is in `results/reports/tier0-summary.md`. These are short-run throughput tests; model quality and larger-context behavior remain untested.

## ExLlamaV3 / EXL3 tier

ExLlamaV3 1.6.0 is installed in an isolated Python 3.12 environment under `/mnt/e/local-llm-envs/exllamav3`; CUDA 12.8 PyTorch detected the RTX 3070. To reproduce the pinned install, run `scripts/04_install_exllamav3.sh`. Qwen3.5-9B EXL3 2.50bpw has been measured through 64K context using chunked prefill and 4-bit K/V cache; see `results/raw/exllama-qwen35-9b.jsonl` and the execution status. Its same-family GGUF Q4_K_M counterpart has now been downloaded and verified for a runtime comparison. The GGUF and EXL3 measurements use different quantization formats and bit budgets, so any speed difference is not attributable to runtime alone.

Reproduce the pinned GGUF download with `scripts/07_download_qwen35_gguf.sh --dry-run`, then omit `--dry-run` to download to `MODEL_DIR` (default `/mnt/e/local-llm-models`). Both downloaders preserve partial files for safe resumption and verify the final checksum. The latest short-prompt comparison shows 67.11 tok/s median for llama.cpp Q4_K_M versus 62.51 tok/s for ExLlamaV3 EXL3 2.50bpw, with respective TTFT medians 62.93 ms and 47.24 ms. These are different quantization formats and serving templates, so treat them as configuration measurements, not a controlled runtime-only ranking. See `results/reports/status.md` and raw JSONL for scope and details.

