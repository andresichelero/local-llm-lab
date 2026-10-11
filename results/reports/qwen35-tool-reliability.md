# Qwen3.5-9B structured output and tool-call repeatability — SSD

Date: 2026-10-11. The C:-hosted WSL ext4 SSD held the active Qwen3.5-9B GGUF, llama.cpp runtime bundle and its llama.cpp shared libraries, sampler traces, logs, and raw JSONL for the complete inference runs. A preflight verified the model and runtime were on ext4 and that `llama-server` resolved its llama.cpp libraries from the SSD bundle; it refuses `/mnt/d`, `/mnt/e`, or unresolved runtime libraries. The benchmark script was invoked from the D: checkout, and completed measurements were copied into the checkout for versioning after each run. No HDD inference or storage-performance test was performed.

## Protocol

- Model: `unsloth/Qwen3.5-9B-GGUF`, revision `3885219b6810b007914f3a7950a8d1b469d598a5`, Q4_K_M, SHA-256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`.
- Runtime: llama.cpp `d81235049384534c167caea52b85a694f6103d14`; RTX 3070, 99 GPU layers, 2K context, FP16 K/V, Flash Attention on, reasoning off, temperature 0, seed 1234.
- One warm-up and five measured repetitions. Each repetition started a fresh local server, then checked strict JSON and a real `add(19, 23)` function-tool round trip. Tool success requires the expected structured call, arguments, result, and final answer.
- Source commit: `0ffb6260f1c6ee3acbc31a52fb23c47b03ed2ab7`; source tree was clean in all recorded runs.

## Results

| Check | Success | Wall-time median (mean ± SD) | Range | Other evidence |
|---|---:|---:|---:|---|
| Exact JSON `{"ok": true, "count": 3}` | 5/5 | 0.4925 s (0.4823 ± 0.0198) | 0.4533–0.4995 s | 33 prompt / 18 completion tokens |
| `add(19, 23)` tool round trip | 5/5 | 1.5115 s (1.4887 ± 0.0666) | 1.3741–1.5363 s | 1 structured call, zero failed calls/retries; result 42; 400 input / 54 output tokens |

One-second external samples measured a median per-run system VRAM peak of 6,080 MiB (range 6,079–6,084 MiB) and median WSL RAM peak of 1,276 MiB (range 1,238–1,311 MiB). These include idle samples and represent system-level readings; they are not process-only model allocation. The GPU was shared with the Windows desktop.

This repeat series supports reliability for these two fixed, short prompts on this exact model/template/runtime configuration. It does not establish general tool-use quality, multi-tool planning, coding ability, or quality under other sampling, context, or quantization settings. Compare against the previous single-run smoke in `results/reports/qwen35-gguf-quality-smoke.md` without treating five repetitions of one prompt as five independent task types.

Reproduce with `scripts/26_benchmark_qwen35_quality_repeats.sh`. The runner defaults to one warm-up plus five measurements, stores all active inference artifacts on WSL ext4, and fails before inference if model/runtime/storage are not on ext4 or llama.cpp libraries resolve outside the SSD bundle. See `results/csv/qwen35-quality-repeats.csv` and `results/raw/qwen35-quality-20261011-qwen35-tool-*.jsonl` for per-run outputs and samples.
