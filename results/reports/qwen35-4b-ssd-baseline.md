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

The throughput rows record the clean source revision `e4793e6e7e50c794c0ed4f45bc17bcf9ddb6f065` and runtime commit. At this context, the model fits comfortably within 8 GB VRAM. Long-context scaling, CPU offload, comparative model quality, and repeated functional-quality trials remain untested.
