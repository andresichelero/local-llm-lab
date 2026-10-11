# Ornith-1.0-9B Q4_K_M on RTX 3070 SSD — initial result

Date: 2026-10-11. This is a small local compatibility, output-contract, and single-stream throughput probe. It is not a repository-level coding benchmark and does not reproduce the publisher's long-context agent results.

## Pinned setup

- Model: publisher `ornith-ai/Ornith-1.0-9B-GGUF`, revision `3296bc7a404871a72ac3f1903f561459c09b5c17`, `ornith-1.0-9b-Q4_K_M.gguf`, 5,629,108,704 bytes, SHA-256 `5720d1f671b4996481274fffe01868c3c36e87c135cc8538471cc7bd6087b106`.
- Runtime: llama.cpp commit `d81235049384534c167caea52b85a694f6103d14`, C-backed WSL ext4 SSD bundle. Model, runtime, libraries, active outputs, logs and samples remained on ext4 for inference; completed evidence was copied to the repository afterward. E: was not used.
- Hardware: NVIDIA RTX 3070 8 GiB, Windows desktop sharing the GPU; WSL memory cap 8 GiB. Inference used 99 GPU layers, 2,048 context, FP16 K/V, Flash Attention, reasoning off, prompt cache off, temperature 0, seed 1234.
- Quality protocol: one warm-up plus three measured fresh-server runs. Each run required exact JSON and a real `add(19, 23)` OpenAI-compatible function call, tool execution, and final answer.
- Streaming protocol: separate one warm-up plus three measured runs; deterministic 156-token prompt, 64-token generation cap, same sampling and runtime configuration.

## Quality and tool reliability

| Contract | Success | Median wall time | Mean ± sample SD | Range |
|---|---:|---:|---:|---:|
| Exact JSON `{"ok": true, "count": 3}` | 3/3 | 0.3286 s | 0.3212 ± 0.0196 s | 0.2990–0.3360 s |
| `add(19, 23)` complete structured-tool round trip | 3/3 | 1.4072 s | 1.4033 ± 0.0210 s | 1.3807–1.4221 s |

All measured calls returned one structured `add` call with integer arguments `(19, 23)`, executed locally to `42`, and returned a final answer containing `42`. No tool retries or failed calls were recorded. Exact JSON used 33 prompt and 12 completion tokens per run; the tool sequence used 400 input and 54 output tokens.

## Streaming performance

| Metric | Median | Mean ± sample SD | Range |
|---|---:|---:|---:|
| Server startup-to-ready | 5,046 ms (one server start) | — | — |
| TTFT | 137.30 ms | 135.02 ± 6.79 ms | 127.38–140.38 ms |
| Prompt processing | 1,151.50 tokens/s | 1,173.93 ± 60.53 tokens/s | 1,127.81–1,242.47 tokens/s |
| Generation | 62.697 tokens/s | 62.130 ± 2.074 tokens/s | 59.831–63.861 tokens/s |

The request targeted 144 input tokens; llama.cpp reported 156 actual prompt tokens and 28 generated tokens in every measured run. All three outputs were identical. The streaming script started one server for the three repetitions; startup-to-ready is a single observation, not three independent startup samples. One-second system sampling across quality runs peaked at 6,021 MiB VRAM, 1,315 MiB WSL RAM, and 48 C. The GPU is shared with the Windows desktop, so VRAM and temperature are system samples, not model-process allocation. The host sampler briefly observed 9–16 MiB of WSL swap use during the series.

## Interpretation and limits

The pinned Q4_K_M model loads fully on the RTX 3070 through the current llama.cpp build and passed the two fixed output contracts in all three measured repetitions. This is a useful local validation of the official publisher GGUF and tool-call path. It does not show robust repository coding ability, multi-tool planning, long-context behavior, coding-agent task success, or general model superiority.

The corresponding Qwen3.5-9B Q4_K_M short quality probe used the same runtime, context, KV type, GPU-layer count and fixed prompts, and also passed both contracts (5/5). Ornith's median wall times were lower in these exact prompts (0.3286 vs. 0.4925 s for JSON; 1.4072 vs. 1.5115 s for tool round trip), but the repetition counts differ and there is no coding-task quality comparison. Do not generalize this timing difference into a quality or overall-speed ranking.

## Reproduction and evidence

- Stage and verify: `bash scripts/27_download_ornith_ssd.sh --dry-run`, then omit `--dry-run`.
- Short output contracts: `scripts/26_benchmark_qwen35_quality_repeats.sh` with `RUN_LABEL=ornith-q4`, the pinned model path, `MODEL_ID=ornith-ai/Ornith-1.0-9B-GGUF`, `REPETITIONS=3`, `WARMUPS=1`.
- Streaming test: `scripts/09_benchmark_inference.sh` with `EXPERIMENT=ornith_ssd_q4_2k`, 2K context, 99 GPU layers, 156-token prompt, and the pinned model revision.
- Quality CSV: `results/csv/ornith-q4-quality-repeats.csv`.
- Performance CSV: `results/csv/ornith-q4-inference-summary.csv`.
- Same-contract comparison: `results/csv/agentic-model-quality-comparison.csv`.
- Raw responses and one-second system samples: `results/raw/ornith-q4-*`.
- Logs: `logs/ornith-q4-*`.

All benchmark inputs and active artifacts were on the C-backed WSL ext4 SSD. The dataset/model was not evaluated from E:; that drive remains archival storage only.
