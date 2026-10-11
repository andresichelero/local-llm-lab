# Qwen model refresh — 2026-10-11

This is a source audit, not a benchmark. No new weights were downloaded. The C-backed WSL ext4 filesystem had about 21 GiB free at inspection; E: remains archival storage only.

## Candidate updates

| Model | Officially documented | RTX 3070 / current storage decision |
|---|---|---|
| Qwen3.5-4B | 4B, Apache-2.0, native 262K context; the card provides agent/tool and MTP serving guidance. | Best new local candidate in this refresh. A pinned Q4 GGUF should fit in the 8 GiB WSL RAM budget, but verify artifact/runtime before downloading and measure agent quality locally. |
| Qwen3.5-2B | 2B official small model, Apache-2.0; part of the small Qwen3.5 family. | Useful low-cost harness/worker control, not presumed to match Qwen3.5-9B quality. Quant provenance still needed. |
| Qwen3.6-27B | Dense 27B (28B including model-card parameter accounting), Apache-2.0; native 262K context, coding/agent claims and MTP. | Research candidate only for extreme quantization/offload. BF16 payload is about 52 GiB by parameter-count arithmetic, before vision/runtime overhead; current 8 GiB WSL memory and 21 GiB SSD free make it a poor download target. |
| Qwen-AgentWorld-35B-A3B | 35B total / 3B active, 256 experts, native 262K context; a language world-model trained to simulate environment state transitions. | Specialized agent-world-model reference, not a general code worker. Its card advises at least 128K context for intended tasks and serving examples use four-way tensor parallelism; do not download for this machine. |
| Qwen3.8-27B | 27B dense, Apache-2.0, 262K native context, MTP. Its official HF repository contains 55.6 GB of BF16 files. | User-listed candidate, but defer download: the source checkpoint exceeds currently free SSD space. An extreme community quant needs separate provenance, quality, and runtime checks before consideration. |

These 2026 candidates newly identified for this lab are Qwen3.5-4B, Qwen3.5-2B, Qwen3.6-27B, and Qwen-AgentWorld-35B-A3B. The upstream model cards' performance claims are not independent evidence and none of these candidates has local lab results yet.

## Version check

The official Qwen GitHub organization and Qwen3.8 repository checked on 2026-10-11 list the Qwen3.5, Qwen3.6, and Qwen3.8 families. I did not find an official Qwen3.9 repository or model card in the sources checked. This is a dated search result, not proof that no private, renamed, or later release exists.

## Sources

- Qwen3.5-4B: [official model card](https://huggingface.co/Qwen/Qwen3.5-4B).
- Qwen3.5-2B: [official model card](https://huggingface.co/Qwen/Qwen3.5-2B).
- Qwen3.6-27B: [official model card](https://huggingface.co/Qwen/Qwen3.6-27B).
- Qwen-AgentWorld-35B-A3B: [official model card](https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B).
- Qwen3.8-27B: [official card](https://huggingface.co/Qwen/Qwen3.8-27B) and [file tree](https://huggingface.co/Qwen/Qwen3.8-27B/tree/main).
- Release chronology: [official Qwen3.8 repository](https://github.com/QwenLM/Qwen3.8).
- Runtime support lead for compact quantized Qwen3.5 variants: [llama.cpp OpenVINO support table](https://github.com/ggml-org/llama.cpp/blob/master/docs/backend/OPENVINO.md). This is not CUDA RTX 3070 validation.

Exact retrieval date, evidence class, claims, and caveats are also in [`source-ledger.csv`](source-ledger.csv).
