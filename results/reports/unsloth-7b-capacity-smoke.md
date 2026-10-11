# Unsloth QLoRA 7B capacity smoke — RTX 3070 SSD

Three successful 8-step runs of `Qwen/Qwen2.5-Coder-7B-Instruct` revision `c03e6d358207e414f1eca0bb1891e29f1db0e242` completed on the RTX 3070 with Unsloth 2026.10.3, bitsandbytes NF4/double quantization, FP16 compute, rank 8 / alpha 16 on q/k/v/o, sequence 192, batch 1, learning rate 2e-4, seed 42, and the same eight-row synthetic dataset (SHA-256 `4ff85d0585fc875f41b0506e0a890feadcbb892fcb63a78e1c767e14283f2193`). LoRA dropout was 0.05. Every run completed all steps with finite losses and the deterministic `add(a,b)` AST probe passed before and after training.

The 15,231,271,864-byte sharded model, Python runtime, dataset, cache, adapter outputs and active benchmark records were on the C:-hosted WSL ext4 filesystem. The archived E: source was only used to stage the verified SSD working copy; no timed work ran from E:. Peak swap use was 1 MiB and peak sampled WSL RAM was 2,909 MiB.

| Metric | Median (3 runs) | Range |
|---|---:|---:|
| Model setup/load (s) | 12.232 | 11.802–12.350 |
| 8-step training (s) | 6.431 | 3.688–6.615 |
| Total process wall time incl. imports (s) | 35.830 | 29.132–36.706 |
| Imports (s) | 13.013 | 10.677–14.027 |
| PyTorch peak allocated VRAM (MiB) | 5,640.3 | 5,640.3–5,640.3 |
| PyTorch peak reserved VRAM (MiB) | 5,772 | 5,772–5,772 |
| Sampled system GPU VRAM peak (MiB) | 6,705 | 6,705–6,705 |
| Sampled WSL RAM peak (MiB) | 2,877 | 2,483–2,909 |

The existing PEFT QLoRA SSD smoke for this same model, revision and dataset completed three 8-step runs with a 7.603 s median training time and 7,678.4 MiB peak Torch allocation. Unsloth's three-run median here was 6.431 s and 5,640.3 MiB, about 26.5% less allocated VRAM. Treat the timing comparison cautiously: the runs were not paired and the PEFT rows did not capture dropout metadata consistently. Both paths demonstrate that 7.62B parameters can complete this short NF4 QLoRA smoke on this RTX 3070; they do not establish a useful adapter, robust quality, or the absolute maximum trainable model size.

Unsloth reported that `lora_dropout=0.05` skips its fused LoRA kernels for the patched layers. No OOM occurred. One single measurement was recorded before two additional repeats; there was no separate warm-up series. The third training time was notably lower, so the median and range are more informative than a single headline number.

Run-level metrics are in `results/csv/unsloth-7b-summary.csv`; raw records are in `results/raw/unsloth-7b-qlora-smoke.jsonl`; one-second resource traces are `results/raw/unsloth-7b-rep-1-resources.jsonl` and `results/raw/unsloth-7b-repeat-rep-1-resources.jsonl` through `rep-2`; logs are under `logs/unsloth-7b*`. Adapter outputs were copied to `E:\\local-llm-results\\unsloth-qwen2.5-coder-7b-20261011` and SHA-256 verified. The SSD model copy can be restored with `scripts/25_stage_qwen25_coder_7b_to_ssd.sh`.

Storage audit correction: the initial launcher kept its working directory on the D: checkout, so Unsloth created a small 2.28 MB compiled cache there during these runs. We moved that generated cache to C: and corrected the launcher to run from the SSD storage root. All model shards, environment, training data, adapters, and measured logs/results were on C:; this small cache write is the only known D:-backed exception. No HDD speed measurement was made.

The later storage-path verification smoke completed on the 0.5B fixture after the fix, and no cache was recreated in the D: checkout.


## Clean provenance repeat — 2026-10-11

After fixing the dirty-tree check to exclude generated , a fresh one-warm-up/three-measurement series completed from the SSD-backed WSL ext4 clone. Source revision was ; every record has  and . The pinned 7B model, Unsloth environment, dataset, cache, adapters, and active logs/results all lived under  on C:. E: was used only as the source/archive location for staging and post-run storage; there was no HDD benchmark.

All three measurements completed 8/8 steps, had finite loss, and passed the deterministic post-training  AST probe. They produced the same adapter SHA-256 (), consistent with the fixed seed and tiny deterministic dataset. This is a pipeline/capacity smoke, not an adaptation-quality result; the base model already solved this toy probe before training.

| Metric | Median (3 runs) | Range |
|---|---:|---:|
| Total wall time incl. imports (s) | 28.853 | 28.570–29.140 |
| Imports (s) | 10.143 | 10.110–10.194 |
| Model load (s) | 13.532 | 13.071–13.611 |
| 8-step training (s) | 3.385 | 3.314–3.414 |
| Torch peak allocated / reserved VRAM (MiB) | 5,640.3 / 5,772 | unchanged across runs |
| Sampled system VRAM peak (MiB) | 6,723 |  |
| Sampled WSL RAM peak (MiB) | 2,858 |  |
| Sampled swap peak (MiB) | 16 |  |
| Peak GPU temperature (C) | 45 |  |

The sampler ran at one-second intervals (127 samples total); its mean GPU utilization was 13.15% and mean board power 59.88 W across setup, loading, training, and probe phases, so those averages should not be interpreted as training-only utilization. The 16 MiB peak swap reading is negligible relative to the 4 GiB configured swap.

The prior warm-up plus interrupted repetition with invalid provenance is preserved but explicitly excluded from all summaries in . The clean JSONL, one-second traces, and logs are stored in  and . A post-run archive, including one representative adapter (all four adapter hashes matched), was stored on E: and checksummed.

## Clean provenance repeat — 2026-10-11

After fixing the dirty-tree check to exclude generated results/**, a fresh one-warm-up/three-measurement series completed from the SSD-backed WSL ext4 clone. Source revision was dcb2abc4541fc38b70a043209e4feb84afa0daa3; every record has source_tree_dirty=false and storage_profile=ssd-wsl-ext4-c. The pinned 7B model, Unsloth environment, dataset, cache, adapters, and active logs/results all lived under /home/foxtrot/local-llm-benchmark on C:. E: was used only as the source/archive location for staging and post-run storage; there was no HDD benchmark.

All three measurements completed 8/8 steps, had finite loss, and passed the deterministic post-training add(a, b) AST probe. They produced the same adapter SHA-256 (28e2b3e464aa29f7d5ffb5e5d00495e9dcc4993c6c40e41fb2040ff49a31c858), consistent with the fixed seed and tiny deterministic dataset. This is a pipeline/capacity smoke, not an adaptation-quality result; the base model already solved this toy probe before training.

| Metric | Median (3 runs) | Range |
|---|---:|---:|
| Total wall time incl. imports (s) | 28.853 | 28.570–29.140 |
| Imports (s) | 10.143 | 10.110–10.194 |
| Model load (s) | 13.532 | 13.071–13.611 |
| 8-step training (s) | 3.385 | 3.314–3.414 |
| Torch peak allocated / reserved VRAM (MiB) | 5,640.3 / 5,772 | unchanged across runs |
| Sampled system VRAM peak (MiB) | 6,723 |  |
| Sampled WSL RAM peak (MiB) | 2,858 |  |
| Sampled swap peak (MiB) | 16 |  |
| Peak GPU temperature (C) | 45 |  |

The sampler ran at one-second intervals (127 samples total); its mean GPU utilization was 13.15% and mean board power 59.88 W across setup, loading, training, and probe phases, so those averages should not be interpreted as training-only utilization. The 16 MiB peak swap reading is negligible relative to the 4 GiB configured swap.

The prior warm-up plus interrupted repetition with invalid provenance is preserved but explicitly excluded from all summaries in results/raw/archive/qlora7b-provenance-invalid-20261011/. The clean JSONL, one-second traces, and logs are stored in results/raw/qlora7b-clean-20261011* and logs/qlora7b-clean-20261011-*.log. A post-run archive, including one representative adapter (all four adapter hashes matched), was stored on E: and checksummed.

CSV per-measurement summary: `results/csv/unsloth-7b-clean-20261011.csv`. E: archive: `E:\LocalLLMLabArchive\2026-10-11\qlora7b-clean-20261011\qlora7b-clean-20261011.tar.gz`; SHA-256 `261def338918489d65e4e04812f87951e9a0950ea87904fe1c4221fa67c267cb`. The tar contains raw records, traces, logs, this report snapshot, and one representative adapter; its adapter weight SHA-256 matches the run records.


## Dropout-zero comparison — 2026-10-11

A matched one-warm-up/three-measurement run changed only `lora_dropout` from 0.05 to 0.00, keeping the pinned model, dataset, seed, sequence length, rank, batch, optimizer, and 8-step count fixed. Unsloth logged that the 0.05 configuration skipped fused QKV/O LoRA kernels; at 0.00 it patched all 28 QKV and 28 O layers with fused kernels. Both configurations completed all runs and passed the same deterministic code probe. All measured rows have clean source provenance and identify the C-backed WSL ext4 SSD.

| Dropout | Median total (s) | Median training (s) | Torch allocated VRAM (MiB) | Torch reserved VRAM (MiB) | Sampled system VRAM peak (MiB) |
|---:|---:|---:|---:|---:|---:|
| 0.05 | 28.853 | 3.385 | 5,640.3 | 5,772 | 6,723 |
| 0.00 | 28.714 | 3.289 | 5,663.0 | 5,768 | 6,728 |

On this eight-step smoke, dropout zero was 2.8% faster for the training segment and 0.5% faster end-to-end, while using 22.7 MiB more Torch-allocated VRAM. These small differences do not establish a meaningful speed advantage. Dropout changes regularization, the base model already passed the probe, and no adapter-quality comparison was performed. Raw records/traces are `results/raw/qlora7b-dropout0-20261011*`; the per-run CSV is `results/csv/unsloth-7b-dropout0-20261011.csv`; logs are `logs/qlora7b-dropout0-20261011-*.log`.

E: archive for the dropout-zero comparison: `E:\LocalLLMLabArchive\2026-10-11\qlora7b-dropout0-20261011\qlora7b-dropout0-20261011.tar.gz`; SHA-256 `924fb785e248d0df888f73c71dd51a77e84a7cebebeccea18a0aa24b72e0539a`. The representative adapter hash in that archive matches the dropout-zero JSONL.


## Long-context training capacity — 2026-10-11

The offline fixture generator (`scripts/27_generate_qlora_long_context_fixture.py`) created eight identical deterministic calibration examples with measured prompt and full-sequence lengths. The 512/1,024 configurations used a 1,026-token fixture (dataset SHA-256 `e9a633839e892cb3c944373a24b7b3b5b1c9cb599844da7995eb04d79664dd00`, 357-token prompts); the 2,048 configuration used a separate exact 2,048-token fixture (SHA-256 `010934fac4f4b25015e7262e672fe78c965316bf517e73a29bddfc4436b68b46`). The fixtures and tokenizer-count manifests are checked in under `benchmark/fixtures/`.

All three sequence settings completed one warm-up plus three measured 8-step NF4 QLoRA runs on the RTX 3070. Every row has `success=true`, clean source provenance at `9762d37d8e62dd9333c65d5d75bffa7e9506a2df`, and `ssd-wsl-ext4-c` storage. The post-training deterministic `add(a,b)` probe passed at each length. No run used a CPU/HDD model path.

| Sequence length | Median training (s) | Median total (s) | Torch allocated / reserved peak (MiB) | Sampled total VRAM peak (MiB) | Sampled RAM / swap peak (MiB) | Peak temp (C) |
|---:|---:|---:|---:|---:|---:|---:|
| 512 | 9.055 | 35.765 | 5,752 / 5,830 | 6,792 | 3,019 / 30 | 51 |
| 1,024 | 14.742 | 42.396 | 5,898 / 6,074 | 7,036 | 3,149 / 30 | 55 |
| 2,048 | 22.729 | 49.411 | 6,178 / 6,562 | 7,541 | 3,350 / 30 | 62 |

The 2,048-token configuration fit but left only about 650 MiB of measured VRAM headroom on an RTX 3070 that also drives the desktop. Treat it as the largest sequence length demonstrated in this smoke, not a safe universal ceiling or the maximum possible context; larger lengths, ranks, batches, and real datasets remain untested. Loss falls on the repeated synthetic calibration data and is not a quality metric. Per-run records, one-second traces, logs, and summary CSV are `results/raw/qlora-context{512,1024,2048}-20261011*`, `logs/qlora-context*-20261011-*.log`, and `results/csv/unsloth-7b-context-scaling-20261011.csv`.

The long-context post-run archive is `E:\LocalLLMLabArchive\2026-10-11\qlora-7b-context-scaling-20261011\qlora-7b-context-scaling-20261011.tar.gz` (SHA-256 `7b065d8189df8c95750c213119a5e9fcd1db4e5718d1bbad6ee809205bd97aaf`). It contains the raw rows, traces, logs, fixtures, report snapshot, and one SHA-verified adapter per sequence length; no base-model weights.
