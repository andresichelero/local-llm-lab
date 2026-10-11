# QLoRA storage comparison — 2026-10-11

This compares the same pinned Qwen2.5-Coder-7B NF4 QLoRA smoke on the RTX 3070. The HDD side has three clean-source repetitions; the SSD side currently has one. Both use the same model revision, eight-row dataset and SHA-256, seed 42, rank 8, sequence length 192, batch 1, and eight steps.

| Storage | Runs | Imports median (s) | Model load median (s) | Training median (s) | Total median (s) | Peak sampled VRAM (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| E: HDD (/mnt/e, clean-source series) | 3 | 140.080 | 273.348 | 9.542 | 591.779 | 7,897 |
| C: SSD (WSL ext4, first repeat) | 1 | 15.436 | 14.992 | 10.526 | 54.088 | 7,840 |

For this first SSD run, import time was 9.1x lower, model loading 18.2x lower, and total elapsed time 10.9x lower than the clean HDD medians. Training time was similar, as expected for an experiment dominated by setup and weight loading. Before treating the speedup as stable, collect two more SSD runs and compare medians and ranges.

The SSD run completed all eight steps without OOM. Its loss trace and deterministic add-function probe matched the HDD runs exactly; the probe already passed before training, so this is a storage and capacity result, not evidence of a quality gain. Peak sampled GPU use was 7,840 MiB, leaving very little VRAM headroom for other desktop workloads.

The model copy, virtual environment, cache, adapter, and benchmark output were on the WSL ext4 filesystem whose VHD resides on C:. The original model and training environment remain untouched on E:. The SSD result was tagged after execution using the recorded model and adapter paths because the runner did not yet emit a storage profile; future runs record QLORA_STORAGE_PROFILE explicitly. Raw per-run data and one-second resources remain in results/raw/qlora-7b-smoke.jsonl and results/raw/qlora-7b-smoke-resources-ssd1.jsonl.
