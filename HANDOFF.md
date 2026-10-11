# Resume point — 2026-10-11

## Current objective

Continue the reproducible RTX 3070 / WSL2 lab. The HDD-versus-SSD QLoRA storage comparison is complete; resume the broader inference and harness experiments with active assets on the SSD and model archives on E:.

Latest checkpoint: the pinned Qwen3.5-9B GGUF Q4_K_M was tested from the C:-hosted WSL ext4 filesystem at 2K and 16K, and the llama.cpp runtime bundle was staged to the same SSD. Three 2K startup log measurements showed 4.39 s median on SSD versus 41.47 s on E:, with uncontrolled OS file-cache state. Warm generation remained near 63–66 tok/s. A C-only runtime series completed, but Windows GPU sharing raised VRAM use and reduced throughput; treat it as contention-affected. See `results/reports/ssd-inference-comparison.md`.

## Host and storage state

- Windows 10 Pro 22H2, Ryzen 5 5600X, 32 GiB RAM, RTX 3070 8 GiB.
- Ubuntu-24.04 WSL2, 8 GiB RAM limit, 8 vCPUs, 4 GiB swap, 90 GiB virtual disk (88 GiB filesystem). The WSL VHD is under `C:\Users\Andre\AppData\Local\wsl`, on the Samsung 970 EVO Plus SSD.
- Current Linux filesystem free space is about 34 GiB after archiving the tested Qwen GGUF to E: while keeping the runtime and QLoRA assets on SSD. Recheck before copying more assets.
- Docker, containerd, snapd, Immich and other nonessential services remain stopped/disabled for this test window.
- C: is the SSD; E: is a 1 TB HDD. Keep the source/archive model on E:; run active tests from WSL-native ext4 on C:.
- D: is also a 1 TB HDD; the source checkout/runtime is on D:. `scripts/17_stage_llamacpp_to_ssd.sh` stages the runtime bundle to C: and validates its dependencies. `scripts/18_stage_qwen35_gguf_to_ssd.sh` restages the pinned GGUF from E: after an SSD test copy has been archived. Use `LLAMA_SERVER=/home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server`, `LD_LIBRARY_PATH=/home/foxtrot/local-llm-benchmark/tools/llama-bin`, and `RUNTIME_STORAGE_PROFILE=ssd-wsl-ext4-c` for C:-only llama.cpp runs.

## QLoRA evidence

- Pinned model: `Qwen/Qwen2.5-Coder-7B-Instruct`, revision `c03e6d358207e414f1eca0bb1891e29f1db0e242`.
- Four HDD-backed runs passed 8/8 steps (one preliminary dirty run, three clean-source runs). Clean-series median load 273.348 s, median total 591.779 s, median training 9.542 s, sampled VRAM max 7,897 MiB.
- Three clean SSD-backed repeats passed 8/8 with identical loss traces. Medians: 15.436 s imports, 14.992 s model load, 7.603 s training, 51.969 s total; sampled VRAM max 7,850 MiB. The same synthetic eight-row dataset means this is a capacity/storage result, not an adapter quality comparison.
- Against three clean HDD repeats, SSD medians were 9.1x faster for imports, 18.2x faster for model load, and 11.4x faster overall. See results/reports/qlora-storage-comparison.md.
- Raw records: results/raw/qlora-7b-smoke.jsonl; hardware samples cover HDD rep2/3/4 and SSD ssd1/ssd2/ssd3. Grouped outputs are results/csv/qlora-7b-summary.csv and results/reports/qlora-7b-summary.md.
- The 15.24 GB model copy is at `/home/foxtrot/local-llm-benchmark/models/Qwen2.5-Coder-7B-Instruct`; all four safetensor shard hashes match the pinned manifest.
- The 7.75 GB isolated training environment is at `/home/foxtrot/local-llm-benchmark/envs/training`. The copied venv prefix is valid; Torch 2.10.0+cu128, Transformers 5.19.0, PEFT 0.21.2, bitsandbytes 0.50.2 import successfully and CUDA tensor execution on the RTX 3070 passed. A short import-only check took 5.997 s; the full QLoRA runs recorded median imports of 15.436 s on SSD versus 140.080 s on HDD.
- A new helper, scripts/16_stage_benchmark_to_ssd.sh, stages E: assets to the WSL ext4 filesystem without deleting sources. It supports --dry-run and path overrides.
- benchmark/qlora_smoke.py now records the QLORA_STORAGE_PROFILE environment variable; use ssd-wsl-ext4-c for further runs. The current SSD record was annotated after execution from the recorded paths.

## Next actions

1. Continue the broader lab on the existing feature branch; publish checkpoints after each experiment. Never add model weights, adapters, environments, or other large assets to Git.
2. Resume the broader lab with carefully selected inference comparisons, placing active models, runtimes, caches, environments, and outputs on the SSD and retaining verified originals on E:.
3. Continue with harness, context, MoE, and training experiments only after each runtime/model is researched and its storage requirements are checked.

## Latest checkpoint — paired LoRA and QLoRA

- Code is committed and pushed as `462d6a6` (`bench: add paired LoRA and QLoRA smoke`). The runner now selects `--method lora|qlora`; QLoRA remains the default. Three unit tests for routing, both dry-runs, shell syntax, Python compilation, and the six real training runs passed.
- One warm-up and three measured repeats per method ran with pinned Qwen2.5-Coder-0.5B revision `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`, eight synthetic rows, seed 42, rank 8, sequence 192, batch 1, eight steps, and FP16 compute. All six final runs passed; the static `add(a,b)` probe passed both before and after training.
- Median LoRA / QLoRA values: model load 1.142 / 1.137 s; training 1.637 / 2.214 s; total 9.159 / 10.147 s; Torch allocated VRAM peak 1,109.8 / 886.0 MiB; one-second sampled total VRAM peak 2,951 / 2,500 MiB. This is a capacity/runtime comparison only because the base model already passed the probe and the task data is synthetic.
- Raw results, individual hardware traces, CSV and report: `results/raw/lora-qlora-*.jsonl`, `results/csv/lora-qlora-summary.csv`, and `results/reports/lora-qlora-comparison.md`. Adapter artifacts are archived at `E:\local-llm-results\lora-qlora-20261011`; base model remains at `E:\local-llm-models\Qwen2.5-Coder-0.5B-Instruct`. The temporary SSD model and adapter copies were removed only after checksum/content verification. The training environment remains staged on the SSD for subsequent work.
- Next work returns to the broader benchmark: prioritize current official-source research, harness comparisons, context/compaction instrumentation, and then MoE/hybrid candidates. Continue checking SSD capacity before staging large files.
