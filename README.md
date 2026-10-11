# Local LLM Lab

Reproducible experiments for local inference, quantization, fine-tuning, and agent harnesses on this Windows 10 + WSL2 host. The machine audit is stored under `results/system-audit/`; run results must be recorded separately from upstream claims.

## Machine facts that constrain this lab

- Windows 10 Pro 22H2, Ryzen 5 5600X, 32 GiB physical RAM, RTX 3070 8 GiB, NVIDIA driver 610.62.
- Ubuntu 24.04.5 in WSL2, kernel 6.18.40.1, CUDA device visible through `nvidia-smi`.
- The current user `.wslconfig` sets WSL to 8 GiB RAM, 8 processors, 4 GiB swap, and a 90 GiB default virtual disk. The previous file is backed up outside the repository.
- Free VRAM has varied from about 4.6 GiB during the first audit to 3.2–3.4 GiB while other WSL and Windows workloads were active; the desktop shares this GPU.
- The Ubuntu virtual disk is 90 GiB (88 GiB filesystem) with 34 GiB free in the latest check, after archiving the tested Qwen GGUF back to E:. Its VHD is stored on the C: Samsung 970 EVO Plus SSD. D: and E: are HDDs; verified model archives remain on E:, while active models, runtimes, and benchmark outputs go under `/home/foxtrot/local-llm-benchmark` in WSL ext4 on C:. Current free space changes, so check before downloads/builds.
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

Reproduce the pinned GGUF download with `scripts/07_download_qwen35_gguf.sh --dry-run`, then omit `--dry-run` to download to `MODEL_DIR` (default `/mnt/e/local-llm-models`). Both downloaders preserve partial files for safe resumption and verify the final checksum. The cache-controlled short-prompt comparison shows 64.13 tok/s median for llama.cpp Q4_K_M versus 62.51 tok/s for ExLlamaV3 EXL3 2.50bpw, with respective TTFT medians 64.32 ms and 47.24 ms. llama.cpp Q4_K_M completed cold prompts up to 28,695 tokens in 32K context with q4_0 K/V at 1,820 tok/s prefill, 54.41 tok/s generation, and 6,147 MiB sampled VRAM. These are different quantization formats and serving templates, so treat them as configuration measurements, not a controlled runtime-only ranking. Cold-prefill runs set `CACHE_PROMPT=off` (the default). See `results/reports/status.md` and raw JSONL for scope and details.

## QLoRA capacity smoke

The pinned QLoRA downloader supports `scripts/07_download_training_model.sh --profile qwen25-coder-0.5b|qwen25-coder-7b`. It verifies each file's revision, size, and digest before writing a manifest. Qwen2.5-Coder-7B completed four HDD-backed runs and three clean SSD-backed 8-step NF4 QLoRA smokes on the RTX 3070 at sequence length 192. Median model load fell from 273.3 s on E: to 15.0 s on the SSD-backed WSL ext4 filesystem; median total time fell from 591.8 s to 52.0 s. All three runs on each disk used the same synthetic data, seed, and config and passed 8/8 steps. This establishes fit and storage performance, not adapter quality. See `results/reports/qlora-storage-comparison.md` and `results/reports/qlora-7b-summary.md`.

To stage the pinned model and isolated training environment from E: to the SSD-backed WSL Linux filesystem without deleting the archive, run `bash scripts/16_stage_benchmark_to_ssd.sh --dry-run`, then omit `--dry-run`. The destination defaults to ${XDG_DATA_HOME:-$HOME/.local/share}/local-llm-lab; set `BENCH_STORAGE_ROOT` to choose another WSL-native path. The copied virtual environment is checked for relocatability before the script reports the QLoRA command.

The same smoke runner accepts `--method lora` (FP16 base weights) or `--method qlora` (NF4 with double quantization). A controlled comparison on the pinned 0.49B model completed three measured repeats per method after one warm-up, with the same eight-row dataset and training settings. On this machine, median training/total time was 1.637/9.159 s for LoRA and 2.214/10.147 s for QLoRA; QLoRA's Torch-allocated peak was 886 MiB versus 1,109.8 MiB for LoRA. All runs passed the same pre/post static probe. Since the base model already passed and the dataset is synthetic, this is a capacity/runtime result, not a quality comparison. Adapter artifacts are archived on E: and the temporary model copy has been cleared from the SSD. See [the paired report](results/reports/lora-qlora-comparison.md) and [raw JSONL](results/raw/lora-qlora-smoke.jsonl). The script now accepts either method while retaining QLoRA as the default.

## SSD-backed llama.cpp follow-up

The Qwen3.5-9B GGUF Q4_K_M (pinned revision `3885219b6810b007914f3a7950a8d1b469d598a5`, SHA-256 in `versions.lock`) was tested from WSL ext4 on the C: SSD at 2K and 16K context. Three 2K-context startup-log measurements had a median 4.39 s from llama.cpp initialization to model-ready, versus 41.47 s across three prior E:-backed starts. Those historical log timings were collected on different runs without clearing the OS file cache, so treat the ratio as observed storage behavior, not a controlled cold-cache guarantee. Warm inference stayed in a similar range (about 63–66 generated tok/s); prompt and GPU load varied slightly between series.

The 16K run processed a 14,380-token prompt using Q4 K/V with 3/3 successful outputs, 1,966 tok/s median prefill, 62.04 tok/s generation, and 6,191 MiB peak in paired resource samples. Its prior HDD comparison used 14,352 prompt tokens, so it is close but not an identical-prompt test. Raw JSONL, resource samples, startup events, and logs are in `results/raw/` and `logs/`; see `results/reports/ssd-inference-comparison.md`.

After testing, keep the hash-verified archive on E: and remove only the temporary SSD copy when it is no longer needed. Run `bash scripts/18_stage_qwen35_gguf_to_ssd.sh --dry-run`, then omit `--dry-run` to restage it for the next Qwen series.

The benchmark helper `scripts/17_stage_llamacpp_to_ssd.sh` copies the built runtime to WSL ext4 without deleting the D: source, checks that files match, compares the build version, and verifies that llama/ggml libraries resolve from the SSD copy. `scripts/18_stage_qwen35_gguf_to_ssd.sh` restages the pinned GGUF from E: and refuses to overwrite a different destination. `scripts/09_benchmark_inference.sh` now records model/runtime paths, storage profiles, model revision, and server startup-to-ready time. GPU sharing with the Windows desktop produced a later lower-throughput run with higher baseline VRAM use; it is reported separately rather than attributed to the drive.

