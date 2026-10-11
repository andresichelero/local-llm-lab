# QLoRA rank sweep (SSD only)

Qwen2.5-Coder-0.5B-Instruct, NF4/double quantization, AdamW32, seed 42, 16 steps, sequence length 192, batch 1, gradient checkpointing, and the same eight-row synthetic training fixture. Each rank used alpha = 2 × rank, one warm-up, and three measured trainings. Each final adapter and the base were evaluated on five deterministic held-out function tasks over three repeats.

Source commit: `131eabe84616db25710f28125e0f20246b111328`; pinned model revision: `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`; dirty source rows: 0 of 9 measured training records.
All active model, runtime, cache, log, and result I/O used the C:-backed WSL ext4 filesystem. HDDs were not used for measurements. The held-out tasks are synthetic and the base model already performs strongly; this is a narrow adapter/configuration comparison, not a broad coding-quality benchmark.

| Rank / alpha | Trainable params | Adapter MiB | Train seconds median ± SD | Torch VRAM peak MiB | Sampled system VRAM peak MiB | Base tests | Adapter tests | Base task passes | Adapter task passes | Median reference NLL base → adapter |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 / 16 | 1,081,344 | 4.15 | 3.905 ± 0.011 | 886.0 | 1914.0 | 54/54 | 54/54 | 15/15 | 15/15 | 0.266511 → 0.084842 |
| 16 / 32 | 2,162,688 | 8.27 | 3.935 ± 0.018 | 898.4 | 1932.0 | 54/54 | 54/54 | 15/15 | 15/15 | 0.266511 → 0.068473 |
| 32 / 64 | 4,325,376 | 16.52 | 3.932 ± 0.012 | 923.1 | 1978.0 | 54/54 | 54/54 | 15/15 | 15/15 | 0.266511 → 0.063254 |

The CSV records adapter SHA-256 values and mean/standard deviation. Training-run JSONL and one-second hardware samples remain the source of truth.
