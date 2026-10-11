# Local LLM Lab

Reproducible experiments for local inference, quantization, fine-tuning, and agent harnesses on this Windows 10 + WSL2 host. The machine audit is stored under `results/system-audit/`; run results must be recorded separately from upstream claims.

## Machine facts that constrain this lab

- Windows 10 Pro 22H2, Ryzen 5 5600X, 32 GiB physical RAM, RTX 3070 8 GiB, NVIDIA driver 610.62.
- Ubuntu 24.04.5 in WSL2, kernel 6.18.40.1, CUDA device visible through `nvidia-smi`.
- The current user `.wslconfig` sets WSL to 8 GiB RAM, 8 processors, 4 GiB swap, and a 70 GB default virtual disk. The existing Ubuntu VHD was separately expanded from 70 to 90 GB; the previous config is backed up outside the repository.
- Free VRAM has varied from about 4.6 GiB during the first audit to 3.2–3.4 GiB while other WSL and Windows workloads were active; the desktop shares this GPU.
- The Ubuntu virtual disk is 90 GB (88 GiB filesystem), stored on the C: Samsung 970 EVO Plus SSD; it had 38 GiB free after staging the current model, runtime, and SSD checkout. D: and E: are HDDs. All new experiments run from SSD-backed WSL ext4 on C:, including active model/runtime copies, logs, resource samples, and raw output. E: is archival storage for verified models and historical data; D: holds the Git checkout and receives completed result files only after an SSD run finishes. No new HDD performance tests are planned. Current free space changes, so check before downloads/builds.
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

## Tier 0 baseline (historical)

The first Tier 0 target was IBM Granite 4.1 3B in GGUF Q4_K_M, served locally by llama.cpp. Its pinned model remains archived on E: and verified against SHA-256 in `versions.lock`. A CLI smoke test and a clean-source three-repeat 2K-context server baseline completed; the clean baseline is in `results/raw/tier0-final.jsonl`, consolidated results are in `results/csv/summary.csv`, and a human-readable summary is in `results/reports/tier0-summary.md`. These are short-run throughput tests; model quality and larger-context behavior remain untested.

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

## Pi context compaction stress

The Pi SDK stress runner uses an isolated agent directory and scratch workspace on the C:-hosted WSL SSD; it does not use the user's Pi settings. Four local trials exercised a 16K Qwen3.5-9B Q4_K_M session with automatic compaction and a continuation task. Compaction occurred, but no trial passed the full independent quality contract: the transcripts showed skipped archive files, failed continuation, or context overflow. One apparent pass had only read 7 of 32 files. The stricter probe adds per-file fingerprints and test checks so future results cannot pass on a plausible summary alone. See [Pi compaction results](results/reports/pi-context-stress.md) and raw attempts in `results/raw/pi-context-stress*.jsonl`.

## Local coding-harness comparison

Pi 1.1.0, OpenCode 1.19.0, and Mistral Vibe 2.26.1 each ran one warm-up and three measured repeats against the same deterministic coding task and local Qwen3.5-9B Q4_K_M endpoint. The server used llama.cpp `d81235049`, 16K context, Q4_0 KV, and the WSL-native SSD. All nine valid measured runs passed the five unit tests, independent behavior probe, and change-scope check; each harness passed 3/3.

Pi had the lowest measured context overhead and shortest median wall time for this task: 1,709 first-prompt tokens, 13,875 total prompt tokens, and 19.92 s median. OpenCode used 7,550 first-prompt tokens and 50,580 total, with 46.13 s median. Vibe used 8,088 first-prompt tokens and 53,490 total, with 45.02 s median. Peak VRAM stayed around 6.1 GiB; Pi used the least RAM in these runs. These results support Pi as the leanest harness for this particular single-agent coding workload. All three had the same task success, and the experiment did not test subagents, MCP, long-context compaction, or general coding ability. The consolidated report excludes legacy rows without Git provenance.

Reproduce with llama-server already running at `http://127.0.0.1:8080` against the pinned Qwen3.5-9B Q4_K_M GGUF and the three isolated harness installs present: `./scripts/19_benchmark_harnesses.sh --harness all --warmup`, followed by `./scripts/19_benchmark_harnesses.sh --harness all --repeat 3`. Generate the consolidated files with `python3 benchmark/summarize_harness_results.py`. Raw per-run output, quality checks, and hardware samples are stored under `results/raw/harness-run-summary.jsonl` and the SSD-side run directories listed in each record; two early OpenCode setup-invalid records remain preserved and are excluded from the CSV and Markdown summary. See `results/reports/harness-evaluation.md`.

TrueForge 0.178.0 is installed and its isolated local UI returned the exact expected text from the same llama.cpp endpoint. This was a text-only smoke: the UI exposed zero tools, and startup reported that the local sandbox fallback needs `bubblewrap` and `socat`. No coding/tool result is claimed for TrueForge; see `results/raw/trueforge-smoke.jsonl`.

## SSD-only context and KV follow-up

Context/KV runs use `scripts/20_benchmark_context_kv.sh`. The pinned Qwen3.5-9B GGUF, llama.cpp executable, active JSONL, resource samples, and server logs stay on the C:-hosted WSL ext4 filesystem for the whole run. After every requested configuration completes, JSONL and sampler files are copied into `results/raw/` in this checkout for Git history; they are not read back from D: or E: during inference. A deterministic exact-recall probe at 16K also returned the same invented fact in 3/3 measurements for q4_0, q8_0, and f16 KV; this is one narrow probe, not a general quality result. The initial interrupted attempts are preserved under `results/raw/exploratory-invalid/` and excluded from analysis. See [context/KV throughput results](results/reports/ssd-context-kv.md), [long-context recall results](results/reports/context-recall.md), and the [consolidated CSV](results/csv/ssd-context-kv.csv).

