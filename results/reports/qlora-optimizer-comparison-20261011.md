# QLoRA optimizer comparison: Qwen2.5-Coder-7B-Instruct

This is a paired local experiment on the RTX 3070 8 GB using the pinned 7B model, NF4 double quantization, rank 8, alpha 16, sequence length 192, batch 1, eight optimizer steps, seed 42, and the same eight-row training fixture. Storage is WSL ext4 on C: (SSD). One warm-up was excluded; each optimizer has three measured repetitions.

| Optimizer | Median train (s) | Mean ± SD (s) | Median total (s) | Peak allocated VRAM (MiB) | Sampled VRAM peak (MiB) | Held-out success | Tests passed | Median reference NLL | Adapter hashes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| adamw32 | 5.54 | 5.5413 ± 0.0042 | 26.354 | 7678.4 | 7835.0 | 100% (15 runs) | 54/54 | 0.236144 | 1 |
| adamw8bit | 5.674 | 5.6747 ± 0.006 | 26.909 | 7649.7 | 7813.0 | 100% (15 runs) | 54/54 | 0.236379 | 1 |

The 8-bit optimizer uses bitsandbytes AdamW8bit with `min_8bit_size=4096`; tensors below that threshold retain 32-bit states by default, so this is not a claim that every optimizer state is quantized. See [official bitsandbytes optimizer documentation](https://huggingface.co/docs/bitsandbytes/main/optimizers).

These short smoke runs establish compatibility and a directional resource comparison, not convergence quality or a general training-speed ranking. The held-out fixture is small and synthetic; passing it does not establish broad coding capability.

## Provenance

Model revision: `c03e6d358207e414f1eca0bb1891e29f1db0e242`; train dataset SHA-256: `4ff85d0585fc875f41b0506e0a890feadcbb892fcb63a78e1c767e14283f2193`; seed: `42`; steps: `8`; sequence length: `192`; storage: `ssd-wsl-ext4-c`.

Raw JSONL inputs are named in the CSV-generation command and retained under `results/raw/`.

The earlier 32-bit run `20261011T191434Z` is retained as preliminary raw evidence but excluded because its storage profile was not recorded; all figures above use the corrected `ssd-wsl-ext4-c` series.
