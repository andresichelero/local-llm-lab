# Unsloth QLoRA smoke — RTX 3070, SSD-backed WSL

Executed 2026-10-11 in Ubuntu 24.04 WSL2. Model weights, dataset, Python environment, adapter output, cache, and benchmark JSONL were on the C:-hosted WSL ext4 filesystem (`/home/foxtrot/local-llm-benchmark`). E: was used only as the source archive for staging the model; no HDD-backed files were read during timed runs. The repository itself is on D:, outside the timed model/data/output paths.

## Protocol and result

Pinned `Qwen/Qwen2.5-Coder-0.5B-Instruct` revision `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`; eight fixed synthetic rows (SHA-256 `4ff85d0585fc875f41b0506e0a890feadcbb892fcb63a78e1c767e14283f2193`); NF4 double-quantized base, FP16 compute, rank 8/alpha 16 on q/k/v/o, dropout 0.05, sequence 192, batch 1, AdamW at 2e-4, seed 42, 8 steps. One warm-up and three measured runs all completed with finite losses and the post-training `add(a,b)` probe passed static AST validation in every run. There is one additional preliminary successful measurement before the full protocol; it is retained in raw JSONL but excluded below.

| Metric (median of 3 measured runs) | Result |
|---|---:|
| Model setup/load (s) | 2.985 |
| Training, 8 steps (s) | 2.334 |
| Total process wall time, incl. imports (s) | 17.262 |
| Imports (s) | 9.994 |
| PyTorch peak allocated / reserved (MiB) | 507 / 550 |
| Sampled system GPU VRAM peak (MiB) | 1483 |
| Sampled WSL RAM peak (MiB) | 2936 |
| Sampled GPU power mean (W) | 47.2 |

Run-level metrics are in `results/csv/unsloth-smoke-summary.csv`; raw records are in `results/raw/unsloth-smoke.jsonl`, with one-second hardware traces `results/raw/unsloth-rep-1-resources.jsonl` through `rep-3` and warm-up trace. Logs are `logs/unsloth-warmup-1.log` and `logs/unsloth-rep-1.log` through `rep-3`.

The five successful adapter artifacts represented by the raw records were copied to `E:\\local-llm-results\\unsloth-20261011` after measurement; each copy's SHA-256 matched its recorded adapter hash. SSD copies remain available for ongoing experiments.

Storage audit correction: after these runs, a 2.28 MB `unsloth_compiled_cache` was found under the D: checkout because the initial wrapper kept the shell's working directory there. The model, data, environment and measured outputs were on C:, but this small generated cache was not. It has been moved to the C:-backed WSL storage root, and the wrapper now changes into that SSD root before importing/training. These earlier results are not a perfectly SSD-only cache-I/O series; no HDD speed test was performed.

A separate 0.5B one-run smoke after the cwd fix passed the same deterministic probe, and the D: checkout remained free of `unsloth_compiled_cache` afterward. Its single raw record is `results/raw/unsloth-cwdcheck-smoke.jsonl`; it validates the cache-location correction and is not included in the performance tables.

## Comparison and limits

The earlier SSD-backed PEFT QLoRA baseline on this same tiny 0.49B task had median training time 2.214 s and PyTorch allocated peak 886 MiB. This Unsloth run measures 2.334 s and 507 MiB: about 5% slower training in this short run, with about 43% lower allocated VRAM. End-to-end time is not a fair speed headline: the isolated Unsloth environment took about 10 s to import versus about 4 s for the previous QLoRA environment. Three repeats are small, timing noise is material, and no statistical performance claim is warranted.

Unsloth reported that `lora_dropout=0.05` disabled its fused LoRA kernels for these layers; training still completed. The package also warned that optional `torchcodec` native audio support was unavailable; this text-only benchmark is unaffected. The base model already solved the add probe before training, so this experiment validates installation, CUDA training, adapter serialization, and memory use, not learning quality or a general maximum trainable model size. A larger task/model and quality evaluation remain pending.

A first run completed training but failed before emitting a record because the copied runner looked for Git metadata on the SSD storage directory. Provenance lookup was corrected to use the repository checkout, then the full protocol passed. The successful run records point to base commit `b22ff535e393dc1aab6c2291df558eb198adf583` and `source_tree_dirty=true` because these uncommitted benchmark files were being tested; the exact script hash is printed in the corresponding log.

## Follow-up: fused LoRA kernels with zero dropout

To test the runtime warning above, the runner was extended with `--lora-dropout` and `UNSLOTH_LORA_DROPOUT`; the wrapper also accepts `UNSLOTH_RUN_PREFIX` so named variants keep distinct logs and resource files. A separate one-warm-up/three-measurement series used dropout `0.0` with every other setting unchanged. All four runs passed 8/8 steps and the deterministic AST probe. The logs confirm 24 QKV and 24 O layers were patched with fused LoRA kernels at dropout 0; no MLP layers were patched because of the model/bias path.

| Variant | Median training (s) | Median total (s) | Median Torch allocated peak (MiB) | Peak sampled system VRAM (MiB) | Runs passed |
|---|---:|---:|---:|---:|---:|
| Unsloth dropout 0.05 | 2.334 | 17.262 | 507.0 | 1,483 | 3/3 |
| Unsloth dropout 0.00 | 2.257 | 17.489 | 508.8 | 1,485 | 3/3 |

Zero dropout was about 3% faster for the eight-step training segment but did not reduce total wall time or VRAM. These tiny short-run differences are weak evidence and changing dropout changes regularization; retain 0.05 when that setting is desired, and do not present this as a quality-equivalent speedup. The PEFT QLoRA training median remains 2.214 s, so this result does not make Unsloth the speed winner. Detailed rows, traces, and logs are `results/csv/unsloth-dropout0-summary.csv`, `results/raw/unsloth-dropout0-smoke.jsonl`, `results/raw/unsloth-dropout0-rep-*-resources.jsonl`, and `logs/unsloth-dropout0-*.log`. The four dropout-zero adapter outputs were copied to `E:\\local-llm-results\\unsloth-dropout0-20261011` and SHA-256 verified; their SSD working copies remain available.
