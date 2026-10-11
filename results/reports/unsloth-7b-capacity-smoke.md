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
