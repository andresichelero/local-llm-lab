# Local LLM Lab

Reproducible experiments for local inference, quantization, fine-tuning, and agent harnesses on this Windows 10 + WSL2 host. The machine audit is stored under `results/system-audit/`; run results must be recorded separately from upstream claims.

## Machine facts that constrain this lab

- Windows 10 Pro 22H2, Ryzen 5 5600X, 32 GiB physical RAM, RTX 3070 8 GiB, NVIDIA driver 610.62.
- Ubuntu 24.04.5 in WSL2, kernel 6.18.40.1, CUDA device visible through `nvidia-smi`.
- The current user `.wslconfig` limits WSL to 6 GiB RAM, 8 processors, and 4 GiB swap. This lab will not change that setting.
- At audit time, roughly 4.6 GiB VRAM was free; Windows desktop processes use the same GPU.
- WSL root has about 13 GiB free. E: has about 111 GiB free and F: about 157 GiB. Keep model storage outside Git and point `MODEL_DIR` to a suitable location before downloads.
- CUDA toolkit compiler (`nvcc`) was not found in WSL. `nvidia-smi` reports the driver CUDA API level; this does not mean the CUDA toolkit is installed.

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

The first Tier 0 target is IBM Granite 4.1 3B in GGUF Q4_K_M, served locally by llama.cpp. It was selected as a small, current, Apache-2.0 model with an upstream GGUF distribution. It should fit more realistically than the 9B+ candidates under the observed 6 GiB WSL memory cap and 4.6 GiB free VRAM. This is a hypothesis until the actual model loads and the benchmark completes.

