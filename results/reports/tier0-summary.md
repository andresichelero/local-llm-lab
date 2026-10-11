# Tier 0 summary

Clean-source measured runs: 94 across 31 configurations.
Warm-ups and preliminary or dirty-source records remain in raw JSONL but are excluded from measured-run statistics.

| Experiment | Context | Prompt | Max output | KV K/V | Prompt cache | Reasoning | Runs | TTFT median (ms) | Prompt median (tok/s) | Generation median (tok/s) | Max sampled VRAM (MiB) |
|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|
| exllamav3-qwen35-9b-exl3-2.5bpw-kv-4-prompt-14340 | 16384 | 14340 | 32 | 4/4 | n/a | n/a | 3 | 5837.91 | 2465.50 | 53.72 | 5713 |
| exllamav3-qwen35-9b-exl3-2.5bpw-kv-8-prompt-14340 | 16384 | 14340 | 32 | 8/8 | n/a | n/a | 3 | 6385.98 | 2252.22 | 52.59 | 6115 |
| exllamav3-qwen35-9b-exl3-2.5bpw-kv-fp16-prompt-148 | 2048 | 148 | 32 | fp16/fp16 | n/a | n/a | 3 | 168.16 | 980.09 | 56.78 | 4100 |
| exllamav3-qwen35-9b-exl3-2.5bpw-kv-fp16-prompt-7171 | 8192 | 7171 | 64 | fp16/fp16 | n/a | n/a | 3 | 2793.06 | 2584.35 | 55.22 | 5098 |
| llama-cpp-qwen35-9b-gguf-q4km-2k | 2048 | 29 | 64 | f16/f16 | on | off | 3 | 62.93 | — | 67.11 | 5794 |
| llama-cpp-qwen35-9b-gguf-q4km-2k-nocache | 2048 | 29 | 64 | f16/f16 | off | off | 3 | 64.32 | 462.78 | 64.13 | 5801 |
| llama-cpp-qwen35-9b-gguf-q4km-long-16k-q4kv | 16384 | 14352 | 64 | q4_0/q4_0 | off | off | 3 | 7289.00 | 1971.38 | 61.85 | 5935 |
| llama-cpp-qwen35-9b-gguf-q4km-long-32k-q4kv | 32768 | 28695 | 64 | q4_0/q4_0 | off | off | 3 | 15781.85 | 1820.07 | 54.41 | 6147 |
| llama-cpp-qwen35-9b-gguf-q4km-long-8k | 8192 | 7206 | 64 | f16/f16 | on | off | 3 | 65.39 | — | 64.90 | 5999 |
| llama-cpp-qwen35-9b-gguf-q4km-long-8k-nocache | 8192 | 7206 | 64 | f16/f16 | off | off | 3 | 3474.49 | 2077.56 | 64.98 | 6000 |
| llama-cpp-qwen35-ssd-context-16384-q4_0-kv | 16384 | 14352 | 64 | q4_0/q4_0 | off | off | 3 | 7307.04 | 1966.50 | 59.37 | 6142 |
| llama-cpp-qwen35-ssd-context-32768-q4_0-kv | 32768 | 28695 | 64 | q4_0/q4_0 | off | off | 3 | 15856.39 | 1811.48 | 53.18 | 6356 |
| llama-cpp-qwen35-ssd-context-recall-16384-f16 | 16384 | 14023 |  | f16/f16 | on | auto | 4 | 7056.17 | — | — | 6472 |
| llama-cpp-qwen35-ssd-context-recall-16384-q4_0 | 16384 | 14023 |  | q4_0/q4_0 | on | auto | 4 | 7117.65 | — | — | 6134 |
| llama-cpp-qwen35-ssd-context-recall-16384-q8_0 | 16384 | 14023 |  | q8_0/q8_0 | on | auto | 4 | 7155.50 | — | — | 6260 |
| llama-cpp-qwen35-ssd-kv-16384-f16-kv | 16384 | 14352 | 64 | f16/f16 | off | off | 3 | 7248.50 | 1982.40 | 59.52 | 6456 |
| llama-cpp-qwen35-ssd-kv-16384-q8_0-kv | 16384 | 14352 | 64 | q8_0/q8_0 | off | off | 3 | 7408.30 | 1939.72 | 61.99 | 6264 |
| llamacpp-qwen35-9b-gguf-q4km-2k-sameprompt | 2048 | 29 | 32 | f16/f16 | off | off | 3 | 68.77 | 433.51 | 58.38 | 6086 |
| qwen35_9b_gguf_16k_q4kv_ssd | 16384 | 14380 | 64 | q4_0/q4_0 | off | off | 3 | 7324.97 | 1965.55 | 62.04 | 6191 |
| qwen35_9b_gguf_2k_full_ssd_runtime | 2048 | 29 | 64 | f16/f16 | off | off | 3 | 85.27 | 351.08 | 52.75 | 6700 |
| qwen35_9b_gguf_2k_ssd_profiled | 2048 | 29 | 64 | f16/f16 | off | off | 3 | 71.34 | 418.94 | 65.51 | 6212 |
| qwen35_9b_gguf_2k_ssd_runtime_profiled | 2048 | 29 | 64 | f16/f16 | off | off | 3 | 78.82 | 376.94 | 52.18 | 6658 |
| qwen35_9b_gguf_2k_ssd_startup_repeat | 2048 | 29 | 64 | f16/f16 | off | off | 1 | 85.03 | 352.68 | 57.49 | 6217 |
| qwen35_9b_gguf_ssd_storage | 2048 | 29 | 64 | f16/f16 | off | off | 3 | 69.97 | 429.97 | 63.23 | 6022 |
| tier0-ctx-16k-q4 | 16384 | 25 | 64 | q4_0/q4_0 | on | auto | 3 | 16.62 | — | 125.36 | 3541 |
| tier0-ctx-32k-f16 | 32768 | 25 | 64 | f16/f16 | on | auto | 3 | 12.35 | — | 133.46 | 5721 |
| tier0-ctx-64k-q4 | 65536 | 25 | 64 | q4_0/q4_0 | on | auto | 3 | 17.66 | — | 124.89 | 4729 |
| tier0-ctx-8k-f16 | 8192 | 25 | 64 | f16/f16 | on | auto | 3 | 12.93 | — | 132.46 | 3795 |
| tier0-final-f16 | 2048 | 25 | 64 | f16/f16 | on | auto | 3 | 12.34 | — | 129.13 | 3308 |
| tier0-kv-q4-2k | 2048 | 25 | 64 | q4_0/q4_0 | on | auto | 3 | 17.08 | — | 125.97 | 3202 |
| tier0-kv-q8-2k | 2048 | 25 | 64 | q8_0/q8_0 | on | auto | 3 | 12.92 | — | 127.60 | 3242 |

Per-run means, standard deviations, ranges and approximate p95 values: `results/csv/summary.csv`.
VRAM values in the table are peaks from the paired low-frequency system/GPU time-series samples. The CSV also records the Torch allocator's per-process peak separately where available.
Prompt caching and reasoning mode are separate grouping dimensions. For cold prefill comparisons, use rows with prompt_cache=off; cached-prefix rows have artificially low prompt processing time.
The short prompt does not validate reasoning, tool use or quality under long-context load.
