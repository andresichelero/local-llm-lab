# Tier 0 summary

Clean-source measured runs: 21 across 7 configurations.
Preliminary or dirty-source runs excluded from the table: 9 (all records remain separated by experiment and commit in the CSV).

| Experiment | Context | KV K/V | Runs | TTFT median (ms) | Prompt median (tok/s) | Generation median (tok/s) | Max sampled VRAM (MiB) |
|---|---:|---|---:|---:|---:|---:|---:|
| tier0-ctx-16k-q4 | 16384 | q4_0/q4_0 | 3 | 16.62 | 2947.42 | 125.36 | 3541 |
| tier0-ctx-32k-f16 | 32768 | f16/f16 | 3 | 12.35 | 3093.29 | 133.46 | 5721 |
| tier0-ctx-64k-q4 | 65536 | q4_0/q4_0 | 3 | 17.66 | 2931.86 | 124.89 | 4729 |
| tier0-ctx-8k-f16 | 8192 | f16/f16 | 3 | 12.93 | 3086.42 | 132.46 | 3795 |
| tier0-final-f16 | 2048 | f16/f16 | 3 | 12.34 | 3059.23 | 129.13 | 3308 |
| tier0-kv-q4-2k | 2048 | q4_0/q4_0 | 3 | 17.08 | 2927.06 | 125.97 | 3202 |
| tier0-kv-q8-2k | 2048 | q8_0/q8_0 | 3 | 12.92 | 2902.25 | 127.60 | 3242 |

Per-run means, standard deviations, ranges and approximate p95 values: `results/csv/summary.csv`.
VRAM values are the highest per-request samples. The separate `*-resources.jsonl` files contain low-frequency system/GPU time-series samples.
The short prompt does not validate reasoning, tool use or quality under long-context load.
