# Qwen2.5-Coder-7B QLoRA: Transformers/PEFT and Unsloth

Both paths trained the pinned `Qwen/Qwen2.5-Coder-7B-Instruct` revision `c03e6d358207e414f1eca0bb1891e29f1db0e242` on the RTX 3070 from C:-backed WSL ext4. They used the same eight-row arithmetic dataset, NF4 with double quantization, rank 8, alpha 16, dropout 0.05, seed 42, sequence length 192, eight optimizer steps, and AdamW at 2e-4. Unsloth had one warm-up plus three measured runs; the direct Transformers/PEFT quality probe had one training run, so its runtime and peak-memory comparison has no repeat distribution.

| Training backend | Measured training runs | Median training (s) | Median total process (s) | Peak Torch allocation (MiB) | Adapter SHA-256 |
|---|---:|---:|---:|---:|---|
| Transformers + PEFT | 1 | 5.552 | 27.552 | 7,678.4 | `578ca804e866326ca1da16524b65bf0f101aa45da83faa7575a5afb95c3e21e9` |
| Unsloth 2026.10.3 | 3 | 3.116 | 27.637 | 5,640.3 | `28e2b3e464aa29f7d5ffb5e5d00495e9dcc4993c6c40e41fb2040ff49a31c858` |

The three measured Unsloth adapter files had the same SHA-256. The single PEFT run used substantially more of the available VRAM, while total process time was nearly the same. Since PEFT training has only one observation here, do not read the timing or memory difference as a stable performance ratio.

Both adapters were evaluated using the same Transformers + PEFT + bitsandbytes NF4 evaluator, with one warm-up and three greedy repeats on five held-out function tasks (15 generated task runs and 54 individual cases per phase).

| Adapter training backend | Adapter task runs passed | Cases passed | Median reference NLL/token | Median generation (s) |
|---|---:|---:|---:|---:|
| Transformers + PEFT | 15/15 | 54/54 | 0.2361 | 0.8978 |
| Unsloth | 15/15 | 54/54 | 0.2364 | 0.9267 |

Both unadapted NF4 baselines also passed all 15 task runs. The NLL and timing differences are small on this fixed arithmetic fixture and do not establish a quality winner. The adapter evaluation used the same inference runtime, so these results compare training backends, not inference backends.

All model, environment, logs, measurements, adapters, and evaluation stayed on the C:-hosted WSL ext4 SSD. No HDD performance test was run. Adapters and result evidence are archived after measurement on E:; base model weights are not included in Git or the archive.

Raw evidence: `results/raw/qwen25-coder-7b-peft-qlora-ssd-20261011T1858Z.jsonl`, `results/raw/qwen25-coder-7b-peft-qlora-resources-20261011T1858Z.jsonl`, `results/raw/qwen25-coder-7b-unsloth-qlora-20261011.jsonl`, `results/raw/qwen25-coder-7b-unsloth-qlora-quality-20261011T1915Z.jsonl`, and `results/raw/qwen25-coder-7b-unsloth-qlora-resources/`.
