# LoRA vs QLoRA held-out probe

Both methods used `Qwen/Qwen2.5-Coder-0.5B-Instruct` revision `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`, the same held-out dataset (`be9e00ec5f448770d890be38576e1e77bdca2b80925df023b5de1f386a1dfbd3`), seed 42, rank 8, 16 update steps, and three greedy evaluation repeats on NVIDIA GeForce RTX 3070 using `ssd-wsl-ext4-c`.

LoRA kept the base weights in FP16; QLoRA used bitsandbytes NF4 with double quantization. Thus this is a practical method/precision comparison, not a controlled isolation of one algorithmic variable.

| Method | Phase | Base precision | Task runs passed | Cases passed | Median reference NLL | Median reference perplexity | Median generation (s) |
|---|---|---|---:|---:|---:|---:|---:|
| QLORA | base_nf4 | NF4 | 15/15 | 54/54 | 0.2665 | 1.3054 | 0.5627 |
| QLORA | qlora_adapter | NF4 | 15/15 | 54/54 | 0.0848 | 1.0885 | 0.7201 |
| LORA | base_fp16 | FP16 | 12/15 | 39/54 | 0.3005 | 1.3505 | 0.6647 |
| LORA | lora_adapter | FP16 | 15/15 | 54/54 | 0.0696 | 1.0721 | 0.5251 |

The 5-task deterministic fixture is deliberately narrow. LoRA and QLoRA adapters both passed all 15 generated task runs (54 individual cases); the FP16 base missed the inclusive-range task because its output exceeded the generation cap, while the NF4 base passed this fixture. Median reference NLL fell after training in both runs, but it scores only one fixed reference implementation per prompt. Repeated greedy runs are timing/robustness repetitions, not independent quality samples. These observations do not establish a general quality advantage for either method.

Raw QLoRA: `qlora-quality-heldout-20261011T185205Z.jsonl`. Raw LoRA: `lora-quality-heldout-20261011T185257Z.jsonl`.
