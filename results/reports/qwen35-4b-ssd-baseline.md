# Qwen3.5-4B SSD baseline

Run date: 2026-10-11. All benchmark reads and writes used the C:-hosted WSL2 ext4 SSD. No HDD benchmark was performed; E: remains archival storage only.

## Pinned artifacts and setup

- Model: `bartowski/Qwen_Qwen3.5-4B-GGUF`, revision `4168f45a16a1290d65a4ec0fa312ae917a4c15d6`.
- File: `Qwen_Qwen3.5-4B-Q4_K_M.gguf`, 3,013,027,808 bytes; SHA-256 `13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983`.
- Runtime: llama.cpp `d81235049384534c167caea52b85a694f6103d14`, RTX 3070, 99 requested GPU layers, Flash Attention enabled, batch 256 / ubatch 128, seed 1234, temperature 0, reasoning off.
- 2,048-token context; 1 warm-up and 3 measured repetitions per KV mode; each performance prompt was 1,804 actual tokens.

## Measured throughput

| KV K/V | Median TTFT | Median prompt throughput | Median generation throughput | Peak sampled VRAM | Runs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Q4_0 | 729.55 ms | 2,482 tok/s | 85.01 tok/s | 3,927 MiB | 3/3 successful |
| Q8_0 | 742.57 ms | 2,438 tok/s | 84.96 tok/s | 3,943 MiB | 3/3 successful |

The difference at 2K is small and within this short run's variability; this does not establish a general speed or quality advantage for either cache type. Q4_0 used about 16 MiB less peak sampled VRAM in this run.

An additional context sweep measured 4K and 8K with Q4_0 and compared Q4_0/Q8_0 at 8K. Each row below used one warm-up and three measured runs, with a 87.5% context-filling prompt.

| Context / KV K/V | Actual prompt tokens | Median TTFT | Median prompt throughput | Median generation throughput | Peak sampled VRAM | Runs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4K / Q4_0 | 3,604 | 1,408 ms | 2,566 tok/s | 83.87 tok/s | 3,945 MiB | 3/3 successful |
| 8K / Q4_0 | 7,206 | 2,802 ms | 2,577 tok/s | 91.34 tok/s | 3,997 MiB | 3/3 successful |
| 8K / Q8_0 | 7,206 | 2,814 ms | 2,565 tok/s | 81.08 tok/s | 4,061 MiB | 3/3 successful |

At 8K, Q4_0 used 64 MiB less peak sampled VRAM and was faster in generation by about 10 tok/s in these three runs; treat the size and speed differences as preliminary. This confirms an 8K operating point for the pinned 4B quant on this machine, not the upstream 262K context claim.

## Functional smoke checks

- Structured output: exact JSON `{"ok": true, "count": 3}` parsed successfully.
- Function calling: model requested `add(19, 23)`, the harness executed it, and the model reported 42; 1 call, 0 failed calls, 0 retries.
- These are smoke checks, not a broad capability or coding-quality evaluation.

## Raw data and limitations

- `results/raw/qwen35-4b-ssd-baseline-20261011-context-2048-q4_0.jsonl`
- `results/raw/qwen35-4b-ssd-baseline-20261011-context-2048-q4_0-resources.jsonl`
- `results/raw/qwen35-4b-ssd-baseline-20261011-kv-2048-q8_0.jsonl`
- `results/raw/qwen35-4b-ssd-baseline-20261011-kv-2048-q8_0-resources.jsonl`
- `results/raw/qwen35-4b-quality-smoke-20261011.jsonl`
- `results/raw/qwen35-4b-quality-resources-20261011.jsonl`
- `results/raw/qwen35-4b-ssd-contextscale-20261011-context-4096-q4_0.jsonl` and its `-resources.jsonl` companion
- `results/raw/qwen35-4b-ssd-contextscale-20261011-context-8192-q4_0.jsonl` and its `-resources.jsonl` companion
- `results/raw/qwen35-4b-ssd-contextscale-20261011-kv-8192-q8_0.jsonl` and its `-resources.jsonl` companion

The throughput rows record clean source revisions (`e4793e6e7e50c794c0ed4f45bc17bcf9ddb6f065` for 2K and `9b9e2e81ea5433a8526115888aa4e20ce2db66eb` for the 4K/8K sweep) and the runtime commit. At tested lengths through 8K, the model fits comfortably within 8 GB VRAM. Longer-context scaling, CPU offload, comparative model quality, and repeated functional-quality trials remain untested.
