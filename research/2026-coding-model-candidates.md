# Additional 2026 coding-model candidates

Research snapshot: 2026-10-11. These are catalog candidates, not locally benchmarked models. No model weights were downloaded for this research pass; all experiments remain SSD-only.

| Model | Evidence and possible value | Fit and caveats | Lab decision |
|---|---|---|---|
| [Microsoft FrogNano-4B-2609](https://huggingface.co/microsoft/FrogNano-4B-2609) | Microsoft describes a Qwen3.5-4B-derived, 4.66B hybrid model post-trained for repository coding with its five-tool Leaf harness. The card reports evaluations at about 131K combined context and 61.5% Avg@3 on SWE-bench Verified. | Its BF16 checkpoint is 9.34 GB, before runtime/KV memory. The repository metadata says MIT but the model card's license table says Apache-2.0. Its narrow English/Python-heavy evaluation is explicitly Leaf/harness-dependent. | **Do not download yet.** Resolve the license discrepancy and identify a verified quantized format plus compatible runtime first. If resolved, it is the most interesting compact specialized coding-agent candidate. |
| [Ornith-1.0-9B](https://huggingface.co/ornith-ai/Ornith-1.0-9B) | The MIT model card describes agentic coding post-training, native tool-call markup and a hybrid DeltaNet/attention layout. The publisher also supplies an official [GGUF Q4_K_M](https://huggingface.co/ornith-ai/Ornith-1.0-9B-GGUF) that llama.cpp can load. | Official Q4_K_M is 5,629,108,704 bytes; exact revision and SHA are pinned in `versions.lock`. The BF16 card serving recipes require recent Transformers/vLLM/SGLang plus reasoning/tool parsers. Reported evaluations use long contexts and substantially more CPU/RAM than this machine. | **Selected for the next SSD probe.** The GGUF has been pinned; download, load, and local quality remain pending. Vendor benchmark scores are not local evidence. |
| [Xiaomi MiMo-V2.6-Distill-Qwen-9B](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B) | Official Xiaomi repository declares MIT metadata and labels the model for agentic, code and tool-use tasks; this is a promising 9B distillation control against Qwen3.5-9B. | The repository lists 18.8 GB of BF16 weights. The reviewed source did not establish an applicable context length, a pinned quantization, or full support in the lab's current runtime. | **Candidate only.** Require a verified SSD-hosted quantized artifact and a small architecture/tool-call smoke before a benchmark series. |

## Evidence handling

These quality and capability statements come from model authors' cards. The cited benchmark scores are not independent evidence and were not reproduced on the RTX 3070. Repository size is not a quantized artifact size. No model was installed, loaded, or tested as part of this research update.

FrogNano's license conflict is visible within the same official repository: the Hugging Face repository metadata labels the license MIT, while the model card's summary table states Apache-2.0. Treat the license as unresolved until the publisher clarifies it.

The active SSD has about 21 GiB free at this snapshot. Since all three official BF16 repositories are large and the test must use SSD-backed storage, this pass records them as candidates without staging full-precision weights. Any future download must first confirm the pinned quantized artifact's exact size and available SSD space. E: remains archival storage only; it is not used for performance tests.

## Sources

- Microsoft FrogNano card, release dated 2026-09-22, observed revision `b90468c`: [model card and files](https://huggingface.co/microsoft/FrogNano-4B-2609/blob/main/README.md), [repository metadata/files](https://huggingface.co/microsoft/FrogNano-4B-2609/tree/main).
- Ornith-1.0-9B official card, observed revision `024bce7`: [model card](https://huggingface.co/ornith-ai/Ornith-1.0-9B/blob/024bce7afff830443ba83083a3125af0e8d9950b/README.md); official GGUF repository pinned at `3296bc7a404871a72ac3f1903f561459c09b5c17`: [files and llama.cpp usage](https://huggingface.co/ornith-ai/Ornith-1.0-9B-GGUF/tree/3296bc7a404871a72ac3f1903f561459c09b5c17).
- Xiaomi MiMo-V2.6-Distill-Qwen-9B official repository, observed revision `2367e86`: [model card and files](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B/tree/main).

Full retrieval dates, claim scope, and caveats are recorded in [`source-ledger.csv`](source-ledger.csv); candidates and non-download decisions are recorded in [`../config/models.yaml`](../config/models.yaml).
