# SSD long-context exact-recall probe

Each series uses the same invented maintenance code, placed once at the midpoint of a deterministic report. The tokenizer sized the user prompt to 14,011 tokens; llama.cpp reports 14,023 prompt tokens after chat formatting. One warm-up and three measured repetitions were run per KV format at 16K context, temperature 0, seed 1234, with prompt caching disabled.

| KV K/V | Exact matches | TTFT median ms | Wall median s | Sampler VRAM peak MiB | RAM peak MiB | GPU utilization mean % |
|---|---:|---:|---:|---:|---:|---:|
| f16/f16 | 3/3 | 7055.32 | 7.305 | 6472.0 | 1090.0 | 87.13 |
| q4_0/q4_0 | 3/3 | 7106.82 | 7.359 | 6134.0 | 1108.0 | 80.53 |
| q8_0/q8_0 | 3/3 | 7154.53 | 7.407 | 6260.0 | 1104.0 | 87.77 |

All three formats retrieved this single synthetic fact exactly in all measured repeats. This narrow probe does not establish general long-context recall or quantization quality. Resource samples are one-second system-wide observations and include server startup and idle intervals.

Raw JSONL and resource samples are under `results/raw/`; consolidated data is in `results/csv/context-recall.csv`. Model revision `3885219b6810b007914f3a7950a8d1b469d598a5`, runtime commit `d81235049384534c167caea52b85a694f6103d14`, source revision `671cab747a8138126ce19d48fa79be83b2d04cfb`.
