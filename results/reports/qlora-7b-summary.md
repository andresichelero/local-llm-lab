# QLoRA 7B capacity smoke summary

Active capacity results are based on the SSD-backed WSL ext4 runs. The older E:-backed rows below are preserved as historical records only; no new HDD performance tests are planned, and those values are not used to rank active configurations.

| Storage | Git revision | Clean source | Runs | Passed | Median load (s) | Median train (s) | Median total (s) | Peak sampled VRAM (MiB) | Peak RAM (MiB) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hdd-e | 4aaf297; a19bd00 | yes | 3 | 3 | 273.3 | 9.5 | 591.8 | 7897 | 2383 |
| ssd-wsl-ext4-c | ac04176; ce33b35 | yes | 3 | 3 | 15.0 | 7.6 | 52.0 | 7850 | 2335 |
| hdd-e | 33663fe | no | 1 | 1 | 250.5 | 11.2 | 420.9 | 7760 | 2222 |

CSV with per-run mean, median, standard deviation, minimum, and maximum: `results/csv/qlora-7b-summary.csv`.
The system sampler records total VRAM at one-second intervals; the Torch allocator's allocated and reserved peaks are separate fields. The first run reported reserved memory above physical VRAM, so use sampled total VRAM for capacity decisions.
All runs use the same seed and eight-row synthetic task. Identical loss traces establish deterministic execution here, not adapter quality or general coding performance.
