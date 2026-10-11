# ExLlamaV3 EXL3 inference on the C: SSD

Run date: 2026-10-11. All active model/runtime reads and inference ran from WSL ext4 backed by the C: Samsung SSD. No HDD was used for benchmarking.

## Reproduction

The model is `turboderp/Qwen3.5-9B-exl3`, revision `d35e580c801b276c4d5ff97f27bd0fa79a0ef3b3`, 2.50 bpw, weight SHA-256 `19e38d592d439a19205469aba6f477355aaa17d81f1f516b222a2abc7ba76d23`. The isolated runtime is ExLlamaV3 `1.6.1+cu128.torch2.10.0` with PyTorch `2.10.0+cu128`, Python 3.12, CUDA 12.8, and an RTX 3070. The pinned wheel digest and model download verification are in `versions.lock` and `results/raw/model-downloads-exl3.jsonl`.

Each row below used one warm-up followed by three measured runs, greedy decoding, seed 1234, and a fixed prompt. Results are grouped from `results/raw/exllama-qwen35-9b.jsonl`; paired system samples are in `results/raw/exllama-qwen35-9b-resources.jsonl` and the reproducible consolidated table is `results/reports/tier0-summary.md` / `results/csv/summary.csv`.

| Context | Actual prompt | K/V cache | Output cap | Generation median (range) | TTFT median | Prompt processing median | Peak sampled total VRAM | Mean sampled power |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 2,048 | 148 tokens | fp16 | 32 | 56.78 tok/s (55.68–58.76) | 168 ms | 980 tok/s | 4,100 MiB | 130 W |
| 8,192 | 7,171 tokens | fp16 | 64 | 55.22 tok/s (53.36–56.52) | 2,793 ms | 2,584 tok/s | 5,098 MiB | 223 W |
| 16,384 | 14,340 tokens | 4-bit | 32 | 53.72 tok/s (51.36–54.21) | 5,838 ms | 2,466 tok/s | 5,713 MiB | 221 W |
| 16,384 | 14,340 tokens | 8-bit | 32 | 52.59 tok/s (51.28–53.82) | 6,386 ms | 2,252 tok/s | 6,115 MiB | 212 W |

All measured rows succeeded and each deterministic series returned the same text. The process-reserved CUDA peak was 4,956 MiB in the 8-bit run. The larger system sampled VRAM includes the Windows desktop and other GPU users, so it is not a model-only allocation figure. Matched samples around measured runs show WSL RAM peaks near 3.5 GiB; the 8-bit run reached 346 MiB of swap, while the 4-bit run reached 2 MiB.

At the same 16K prompt and generation cap, 8-bit K/V was about 2% slower in median generation rate than 4-bit K/V, had roughly 0.55 s higher median TTFT, and showed 402 MiB more sampled system VRAM. The 8-bit series also used up to 346 MiB of WSL swap, so memory pressure may contribute to its slower result. These are separate short runs rather than alternating trials; Windows desktop contention and small-sample variance can affect the gap. No quality or recall difference was measured, so this run provides no evidence that 8-bit K/V earns the additional observed resource use.

## Interpretation and limits

This establishes that the pinned EXL3 model and current ExLlama wheel load and generate on this RTX 3070 from SSD at 2K, 8K and 16K. The 16K K/V comparison covers 4-bit and 8-bit; 2K and 8K use fp16 K/V. Throughput falls modestly as measured prompt length rises, while TTFT grows with prefill length. These short deterministic prompts do not establish semantic recall, coding quality, tool use, quantization quality retention, or behavior beyond 16K. The 2K output cap is also too small for a broad quality comparison. Previous ExLlama JSONL records had no storage-path provenance, so they were preserved under `results/raw/archive/` and excluded from this SSD summary.

The first attempt used the model's parent directory and failed before loading; it was corrected to the verified snapshot directory. An initial sampler run also lacked GPU fields because the isolated PATH omitted WSL's `nvidia-smi`; the sampler now checks `/usr/lib/wsl/lib/nvidia-smi`, and the final traces contain GPU utilization, memory, temperature, clock and power. The valid final records have `source_tree_dirty=false` and source commit `c0de1d9b9385152512f235c59f65667501398189`.

After these runs, the model already archived at `E:\local-llm-models\exllama\Qwen3.5-9B-exl3-2.5bpw` was verified against the pinned weight SHA-256. The active C:-SSD copy was removed to free benchmark space; no weight files were added to Git.

No broad winner between ExLlamaV3 and llama.cpp is claimed: the model quantizations and tested prompts differ. Next useful comparisons are a matched same-family prompt, 8-bit versus 4-bit K/V at 16K, and a semantic long-context recall suite.
