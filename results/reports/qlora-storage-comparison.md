# QLoRA storage comparison — 2026-10-11

This compares the same pinned Qwen2.5-Coder-7B NF4 QLoRA smoke on the RTX 3070. The HDD series has three clean-source repetitions; the SSD series has three clean-source repetitions. All use the same model revision, eight-row dataset and SHA-256, seed 42, rank 8, sequence length 192, batch 1, and eight optimizer steps. One earlier dirty-source HDD run remains a separate diagnostic row in the grouped summary.

| Storage | Runs | Imports median (s) | Model load median (s) | Training median (s) | Total median (s) | Peak sampled VRAM (MiB) | Peak RAM (MiB) |
|---|---:|---:|---:|---:|---:|---:|---:|
| E: HDD through /mnt/e | 3 | 140.080 | 273.348 | 9.542 | 591.779 | 7,897 | 2,383 |
| C: SSD through WSL ext4 | 3 | 15.436 | 14.992 | 7.603 | 51.969 | 7,850 | 2,335 |

Across these three-repeat series, the SSD-backed imports were 9.1x faster at the median, model loading was 18.2x faster, and total elapsed time was 11.4x faster. The ranges did not overlap for imports (SSD 5.489–19.088 s; HDD 98.602–161.158 s), model load (SSD 14.660–17.092 s; HDD 265.939–545.383 s), or total time (SSD 34.557–54.088 s; HDD 450.332–708.629 s). This is a strong local storage effect for this workload. The WSL VHD and active assets were on the C: Samsung SSD; the HDD model snapshot remained on E: as the archive.

Median training time was 7.603 s on SSD and 9.542 s on HDD, but training itself is short and the HDD series contains a 96.541 s outlier under GPU contention. Do not attribute that small median difference to storage. The dominant and reproducible savings came from Python imports and loading the 15.24 GB weight snapshot.

All six clean runs completed 8/8 steps without OOM and produced the same loss trace and deterministic add-function probe. That probe already passed before training, so these results validate capacity, repeatability, and storage impact, not adapter quality. Peak sampled GPU use remained close to the RTX 3070's 8 GiB limit on both disks.

The SSD model, training environment, cache, adapters, and QLoRA outputs are under /home/foxtrot/local-llm-benchmark, outside Git. The original verified model and training environment on E: remain untouched. The first SSD record's storage profile was annotated after the run from the recorded paths; the two later runs captured QLORA_STORAGE_PROFILE directly. Raw run records, paired one-second resource samples, and concise logs are in results/raw/qlora-7b-smoke.jsonl, results/raw/qlora-7b-smoke-resources-ssd1.jsonl through results/raw/qlora-7b-smoke-resources-ssd3.jsonl, and logs/qlora-7b-ssd1.log through logs/qlora-7b-ssd3.log. Summary CSV and table are in results/csv/qlora-7b-summary.csv and results/reports/qlora-7b-summary.md.
