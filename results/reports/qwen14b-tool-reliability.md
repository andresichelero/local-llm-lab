# Qwen2.5-Coder-14B structured output and tool-call repeatability — SSD

Date: 2026-10-11. The pinned Q4_K_M model was copied from its E: archive to the C:-hosted WSL ext4 filesystem and SHA-256 verified before testing. Model, llama.cpp runtime and libraries, server logs, sampler traces, and active JSONL remained on SSD during inference. A runner preflight required ext4 paths and llama.cpp library resolution from the SSD runtime bundle. No HDD inference or storage-performance comparison was run. The pre-existing E: archive was left intact.

## Protocol

- Model: official `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF`, revision `d0a692ef765eefbf2fabb130b3cb2e8917e3d225`, Q4_K_M, 8,988,110,272 bytes, SHA-256 `c1e659736d89ac1065fb495330fb824d94001974a4bfa78e7270e43476a8d940`.
- Runtime: llama.cpp `d81235049384534c167caea52b85a694f6103d14`; RTX 3070 with 32 GPU layers; 2K context, FP16 K/V, Flash Attention on, reasoning off, temperature 0, seed 1234.
- One warm-up and three measured repetitions. Each repetition started a fresh server and ran exact JSON plus the `add(19, 23)` tool-round-trip contract. The wrapper was corrected after an initial pre-fix warm-up failure showed it stopped the series on a model-level quality failure; the complete final series below is from the corrected runner.
- Source commit: `d6586de44ab0bcf14fbc7f029e62aa169062e064`; source tree clean. The measured records and traces are under `results/raw/qwen14b-quality-20261011-qwen14b-tool-final-*`.

## Results

| Check | Success | Wall-time median (mean ± SD) | Range | Evidence |
|---|---:|---:|---:|---|
| Exact JSON `{"ok": true, "count": 3}` | 3/3 | 2.155 s (2.169 ± 0.049) | 2.129–2.224 s | 50 prompt / 20 completion tokens |
| `add(19, 23)` tool round trip | 0/3 | 12.589 s (12.627 ± 0.111) | 12.540–12.752 s | 0 structured calls; 1 failed call, 0 retries; model emitted a textual `<tools>` block and answer rather than `tool_calls` |

The tool response repeatedly used its 128-token output allowance on a textual pseudo-call followed by a long repetitive answer. Because the API did not return a structured call, the test correctly did not execute the tool or count the answer text as success. One-second external samples measured a 6,723 MiB system VRAM peak in each measured run and median WSL RAM peak of 978 MiB. These are system samples, not process-only model allocation; the GPU is shared with the Windows desktop.

This is evidence that strict JSON worked in this exact prompt/template path while the OpenAI-compatible function-tool contract failed consistently at 32 GPU layers. It does not prove the model cannot use tools with another prompt, template, or harness. Compare with the Qwen3.5-9B repeat probe: that smaller model passed the corresponding fixed tool round trip 5/5, but the tests are not a broad model-quality comparison.

Reproduce with `scripts/26_benchmark_qwen35_quality_repeats.sh`, setting `RUN_LABEL=qwen14b`, `MODEL_ID=qwen2.5-coder-14b-instruct`, `GPU_LAYERS=32`, and the SSD model path. Consolidated rows are in `results/csv/qwen14b-quality-repeats.csv`. The first pre-fix aborted warm-up remains preserved separately as `results/raw/qwen14b-quality-20261011-qwen14b-tool-warmup-1.jsonl`.
