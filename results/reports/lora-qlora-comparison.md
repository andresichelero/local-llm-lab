# LoRA FP16 vs QLoRA NF4 smoke comparison

Three measured repeats per method followed one warm-up per method. Runs used the same pinned 0.49B model, eight synthetic rows, seed 42, rank 8, batch 1, sequence length 192, eight optimizer steps, FP16 compute, AdamW, and SSD-backed WSL storage.

| Method | Runs passed | Median model load (s) | Median training (s) | Median total (s) | Peak Torch allocated (MiB) | Peak sampled VRAM (MiB) | Peak RAM (MiB) | Probe passed |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| LoRA | 3/3 | 1.142 | 1.637 | 9.159 | 1109.8 | 2951 | 2425 | all |
| QLoRA | 3/3 | 1.137 | 2.214 | 10.147 | 886.0 | 2500 | 2242 | all |

## Interpretation

Both paths completed the eight-step training smoke on the RTX 3070. NF4 QLoRA used less allocated VRAM than FP16 LoRA in this 0.49B test; both were comfortably within the available GPU memory. The repeated loss traces and adapter hashes were deterministic for each method.
Torch allocator peaks are per-process. One-second sampled VRAM and RAM include the system and shared Windows desktop GPU use, rather than attributing all memory to the training process.

The base model already returned a valid `add(a, b)` before training, and it did so afterward. This is a runtime/capacity comparison only; the tiny synthetic dataset and probe do not measure useful quality improvement or support a general LoRA-versus-QLoRA quality ranking.

Runs: 6 measured (6 successful), all recorded against commit `462d6a6`. Warm-ups are kept separately in `results/raw/lora-qlora-warmup.jsonl`.
Per-run means, medians, standard deviations, ranges, and paired resource summaries: `results/csv/lora-qlora-summary.csv`. Raw measurements: `results/raw/lora-qlora-smoke.jsonl`; per-run resource traces: `results/raw/lora-qlora-resources-*-rep*.jsonl`.

The eight adapter artifacts are archived at `E:\local-llm-results\lora-qlora-20261011`; their archive was checked byte-for-byte against the SSD copies before the temporary adapter and model staging directories were cleared. The pinned base model remains archived at `E:\local-llm-models\Qwen2.5-Coder-0.5B-Instruct`.
