# Qwen2.5-Coder-14B hybrid inference — SSD

Date: 2026-10-11. All model reads, runtime files, logs, and benchmark output were on the C:-hosted WSL ext4 filesystem. The E: HDD was not used for benchmark I/O.

## Reproduction

- Model: official `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF`, pinned revision `d0a692ef765eefbf2fabb130b3cb2e8917e3d225`, Q4_K_M, 8,988,110,272 bytes, SHA-256 `c1e659736d89ac1065fb495330fb824d94001974a4bfa78e7270e43476a8d940`.
- Runtime: llama.cpp commit `d81235049384534c167caea52b85a694f6103d14`; RTX 3070 8 GiB; WSL memory limit 8 GiB; 2,048 context; FP16 K/V; Flash Attention; batch 256 / ubatch 128; seed 1234; temperature 0; prompt caching off.
- The same short factual prompt was run three times at each of 24, 32, and 36 GPU layers. The 24-layer pilot was collected while source files were dirty, so treat it as calibration only. The 32- and 36-layer series have clean-source provenance at `6157d23020fcc0966cef99ba8ea7958746d6b729`.
- Raw records and one-second resource samples: `results/raw/qwen25coder14b-hybrid*.jsonl`.

## Results

| GPU layers | valid runs | median generation | median TTFT | sampled VRAM peak | Interpretation |
|---:|---:|---:|---:|---:|---|
| 24 | 3/3 | 8.81 tok/s | 492 ms | 5,440 MiB | Calibration only; source tree was dirty. |
| 32 | 3/3 | 11.73 tok/s | 350 ms | 6,731 MiB | Safer tested operating point with about 1.4 GiB below the 8 GiB device limit at sampled peak. |
| 36 | 3/3 | 13.92 tok/s | 289 ms | 7,366 MiB | Fastest tested setting; only about 0.8 GiB remained at sampled peak, so desktop contention can make it fragile. |

The model is usable interactively with hybrid CPU/GPU placement, but generation is substantially slower than the 9B fully-GPU checkpoints. Under this host's desktop-sharing constraint, 32 layers are the practical default; 36 layers are a throughput option when memory headroom is confirmed. The sampler observed up to 227 MiB WSL swap during the 36-layer run; swap activity makes the peak resource margin relevant, though it did not cause a failed inference.

## Quality smoke

At 32 GPU layers, the exact JSON contract passed (1/1). Tool calling failed (0/1): llama.cpp returned a normal assistant message whose text contained a literal `<tools>…</tools>` block rather than an OpenAI-compatible `tool_calls` object, even though the result text was 42. The harness correctly marks this as a tool-call failure; a natural-language answer is not counted as a successful tool invocation. The failure is preserved in `results/raw/qwen25coder14b-quality*.jsonl` and the server log. This establishes a tool-protocol incompatibility in this tested model/runtime/template path; it does not establish that the model cannot use tools in other templates or harnesses.

This was a smoke test, not a coding-quality benchmark, and no result here establishes broad task quality or long-context behavior.

## Archive

After all SSD tests, the pinned model was copied to `E:\local-llm-models\hybrid\qwen2.5-coder-14b-instruct-q4_k_m.gguf`, verified against the same byte size and SHA-256, and then the SSD working copy was removed. E: is archival storage only; no HDD performance measurements were taken in this checkpoint.
