# SSD long-context exact-recall probe

Each series uses the same invented maintenance code, placed once at the midpoint of a deterministic report. Context and prompt token counts are recorded per series in the CSV and table. Each run has one warm-up and three measured repetitions per KV format, temperature 0, seed 1234, with prompt caching disabled.

| Context | Prompt tokens | KV K/V | Exact matches | TTFT median ms | Wall median s | Sampler VRAM peak MiB | RAM peak MiB | GPU utilization mean % |
|---:|---:|---|---:|---:|---:|---:|---:|---:|
| 16384 | 14023 | f16/f16 | 3/3 | 7055.32 | 7.305 | 6472.0 | 1090.0 | 87.13 |
| 16384 | 14023 | q4_0/q4_0 | 3/3 | 7106.82 | 7.359 | 6134.0 | 1108.0 | 80.53 |
| 16384 | 14023 | q8_0/q8_0 | 3/3 | 7154.53 | 7.407 | 6260.0 | 1104.0 | 87.77 |
| 65536 | 57383 | q4_0/q4_0 | 3/3 | 39717.76 | 40.084 | 6853.0 | 1156.0 | 94.87 |
| 65536 | 57383 | q8_0/q8_0 | 3/3 | 40100.00 | 40.420 | 7367.0 | 1150.0 | 94.52 |

This deterministic synthetic probe checks one fact placed at the midpoint. Exact matches do not establish general long-context recall or quantization quality. Resource samples are one-second system-wide observations and include server startup and idle intervals.

Raw JSONL and resource samples are under `results/raw/`; consolidated data is in `results/csv/context-recall.csv`. Model revision `3885219b6810b007914f3a7950a8d1b469d598a5`, runtime commit `d81235049384534c167caea52b85a694f6103d14`. Source revisions represented: `671cab747a8138126ce19d48fa79be83b2d04cfb`, `b81540336fa2aae6b0372c050468dbb02dfc8094`.
All active benchmark I/O was on the C:-hosted WSL ext4 SSD; E: stores historical archives only. No HDD benchmark was run. The 64K recall logs and resource files are archived at `E:\LocalLLMLabArchive\2026-10-11\qwen35-ssd-context-recall-64k-20261011\results.tar.gz` with a SHA-256 sidecar.
