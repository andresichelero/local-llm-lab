# SSD context and KV-cache measurements

Generated from successful, clean-source Qwen3.5-9B Q4_K_M runs. Each row has one warm-up plus three measured repetitions; prompt caching was off, Flash Attention on, all 99 layers on the RTX 3070, temperature 0, seed 1234, and generation capped at 64 tokens. Active model, runtime, logs, and raw measurements were stored on the C:-hosted WSL ext4 SSD.

These are throughput and memory measurements, not a quality comparison. The prompts are deterministic generated text, not a semantic long-context recall test. Sampler peak/mean fields come from one-second external samples and include idle intervals around each server process.

| Context | KV K/V | Prompt tokens | Prefill tok/s median (mean ± sd) | Generation tok/s median (mean ± sd) | TTFT ms median | Wall s median | Sampler VRAM peak MiB | Sampler GPU util mean % | Power mean W | RAM peak MiB | Success |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 16384 | q4_0/q4_0 | 14352 | 1966.5 (1965.0 ± 3.1) | 59.37 (59.24 ± 2.24) | 7307 | 7.75 | 6143.0 | 78.42 | 202.41 | 1118.0 | 3/3 |
| 32768 | q4_0/q4_0 | 28695 | 1811.5 (1811.1 ± 1.8) | 53.18 (53.06 ± 1.03) | 15856 | 16.35 | 6356.0 | 91.98 | 227.96 | 1115.0 | 3/3 |
| 16384 | f16/f16 | 14352 | 1982.4 (1980.9 ± 4.2) | 59.52 (59.98 ± 2.14) | 7248 | 7.69 | 6456.0 | 87.09 | 223.94 | 1094.0 | 3/3 |
| 16384 | q8_0/q8_0 | 14352 | 1939.7 (1937.5 ± 4.1) | 61.99 (61.94 ± 0.16) | 7408 | 7.83 | 6267.0 | 88.12 | 221.35 | 1106.0 | 3/3 |

Interpretation: compare KV formats only at 16K, where prompt size and runtime settings were held constant. The 16K vs 32K Q4_0 rows show the cost of doubling prompt/context size on this setup. Any earlier HDD-backed values remain historical context; no HDD benchmark was run for this report.

Raw JSONL and one-second sampler files are in `results/raw/`; the consolidated CSV is `results/csv/ssd-context-kv.csv`. Source revision `b4125552fe3d8744bf7882b5f2a2dba16efd640e`, llama.cpp `d81235049384534c167caea52b85a694f6103d14`, model revision `3885219b6810b007914f3a7950a8d1b469d598a5`.
