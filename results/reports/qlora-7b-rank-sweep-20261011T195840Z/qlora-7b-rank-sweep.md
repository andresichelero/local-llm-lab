# QLoRA 7B rank capacity sweep (SSD only)

Pinned Qwen2.5-Coder-7B-Instruct, NF4/double quantization, AdamW32, seed 42, sequence length 192, batch 1, gradient checkpointing, and the same eight-row training fixture. Ranks use alpha = 2 × rank; each requested rank has one warm-up and three measured trainings. Complete ranks are evaluated against the base and final adapter on five deterministic held-out function tasks over three repeats.

All active model, runtime, cache, log, and result I/O used the C:-backed WSL ext4 SSD. HDDs were not used for measurements. The held-out tasks are synthetic and the base model already performs strongly; this is a narrow capacity/configuration comparison, not a broad coding-quality benchmark.

| Rank / alpha | Training | Trainable params | Adapter MiB | Train seconds median ± SD | Torch VRAM peak MiB | Sampled system VRAM peak MiB | Quality | Base tests | Adapter tests | Median reference NLL base → adapter | Failure |
|---:|:---|---:|---:|---:|---:|---:|:---|---:|---:|---:|:---|
| 8 / 16 | complete | 5,046,272 | 19.28 | 7.160 ± 0.921 | 7678.4 | 7868.0 | complete | 54/54 | 54/54 | 0.519531 → 0.236144 |  |
| 16 / 32 | complete | 10,092,544 | 38.53 | 10.522 ± 0.013 | 7748.9 | 7868.0 | complete | 54/54 | 54/54 | 0.519531 → 0.223301 |  |
| 32 / 64 | complete | 20,185,088 | 77.03 | 13.831 ± 0.005 | 7901.5 | 7868.0 | complete | 54/54 | 54/54 | 0.519531 → 0.203885 |  |

Source commit: `0fc6c258574c69b4130b99f0142526224d21566d`; pinned model revision: `c03e6d358207e414f1eca0bb1891e29f1db0e242`; dirty source rows: 0.
Training JSONL, one-second resource samples, quality JSONL, and failure events remain the source of truth. Incomplete ranks are reported but excluded from any complete-configuration ranking.
