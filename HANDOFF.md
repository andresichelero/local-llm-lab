# Resume point — 2026-10-11

## Current objective

Continue the reproducible RTX 3070 / WSL2 lab. The immediate experiment is an SSD-backed repeat of the Qwen2.5-Coder-7B NF4 QLoRA capacity smoke, compared with three clean-source HDD-based runs.

## Host and storage state

- Windows 10 Pro 22H2, Ryzen 5 5600X, 32 GiB RAM, RTX 3070 8 GiB.
- Ubuntu-24.04 WSL2, 8 GiB RAM limit, 8 vCPUs, 4 GiB swap, 90 GiB virtual disk (88 GiB filesystem). The WSL VHD is under `C:\Users\Andre\AppData\Local\wsl`, on the Samsung 970 EVO Plus SSD.
- Current Linux filesystem free space is about 34 GiB after staging. Recheck before copying any more assets.
- Docker, containerd, snapd, Immich and other nonessential services remain stopped/disabled for this test window.
- C: is the SSD; E: is a 1 TB HDD. Keep the source/archive model on E:; run active tests from WSL-native ext4 on C:.

## QLoRA evidence

- Pinned model: `Qwen/Qwen2.5-Coder-7B-Instruct`, revision `c03e6d358207e414f1eca0bb1891e29f1db0e242`.
- Four HDD-backed runs passed 8/8 steps (one preliminary dirty run, three clean-source runs). Clean-series median load 273.348 s, median total 591.779 s, median training 9.542 s, sampled VRAM max 7,897 MiB. They are capacity smokes using an eight-row synthetic dataset and do not measure adapter quality.
- Raw records: `results/raw/qlora-7b-smoke.jsonl`; per-run hardware samples include the `*-rep2/rep3/rep4.jsonl` files. Grouped outputs are `results/csv/qlora-7b-summary.csv` and `results/reports/qlora-7b-summary.md`.
- The 15.24 GB model copy is at `/home/foxtrot/local-llm-benchmark/models/Qwen2.5-Coder-7B-Instruct`; all four safetensor shard hashes match the pinned manifest.
- The 7.75 GB isolated training environment is at `/home/foxtrot/local-llm-benchmark/envs/training`. The copied venv prefix is valid; Torch 2.10.0+cu128, Transformers 5.19.0, PEFT 0.21.2, bitsandbytes 0.50.2 import successfully and CUDA tensor execution on the RTX 3070 passed. Import time was 5.997 s on SSD versus 98.6–161.2 s on HDD.
- A new helper, `scripts/16_stage_benchmark_to_ssd.sh`, stages E: assets to the WSL ext4 filesystem without deleting sources. It supports `--dry-run` and path overrides.

## Next actions

1. Run one same-config QLoRA repeat with `TRAINING_ENV_DIR=/home/foxtrot/local-llm-benchmark/envs/training`, `TRAINING_MODEL_DIR=/home/foxtrot/local-llm-benchmark/models/Qwen2.5-Coder-7B-Instruct`, and output root under `/home/foxtrot/local-llm-benchmark/results/qlora`.
2. Record the SSD run and resource samples in the repository, regenerate the grouped report, and compare HDD versus SSD import/load/total time without mixing them into the same storage group.
3. Commit/push the verified checkpoint on the existing feature branch. Never add model weights, adapters, environments, or other large assets to Git.
4. Continue with carefully selected inference and harness experiments; large downloads remain opt-in and must be size-checked first.
