# Local LLM research and revised priorities — 2026-10-12

## Decision

Keep llama.cpp CUDA/GGUF as the reference. First establish matched 4B-versus-9B quality, then test speculation and prefix reuse separately, then admit one new model at a time. Build live routing only after these measurements identify useful destinations and deterministic failure gates. Defer further parallel subagent coding on this single 8 GB GPU.

This revises the previous router-first decision: its offline policy tests can proceed cheaply, but implementing a live router before matched destination evidence would encode assumptions. It also promotes a no-download MTP compatibility probe because the installed binary advertises `draft-mtp` and existing 4B logs contain unused `blk.32.nextn.*` tensors. Neither fact proves working MTP.

## Current evidence and resources

Read-only audit around 01:25 BRT: WSL ext4 108 GiB total, 87 used, 16 free; RAM 7.8 GiB with 7.3 available; swap 4 GiB unused. RTX 3070 8192 MiB, 7396 free, driver 610.62. C/D/E free space was 50.3/64.5/55.4 GiB. No inference or OpenCode processes were found. Recheck these transient values before execution.

Checkout began clean at `dc54c4e`; PR35 was open at that same head with all three CodeQL checks passing. Qwen3.5-4B and 9B GGUFs and llama.cpp remain on C-backed ext4. ExLlamaV3 is installed and previously measured, but its model is currently archived on E, not staged for inference.

The 4B harness suite covers three small tasks (OpenCode 15/15, Pi 11/15, Vibe 9/15). The 9B three-harness comparison covers one task. These are not a matched model comparison. The recent treatment passed its code grader but timed out before review; it does not establish a coding-quality disadvantage. Historical Pi continuity was 0/5 and Vibe 1/4 under their stated protocols. Capacity, speed, coding correctness and workflow completion remain separate endpoints.

## Models worth admitting

All candidates below are researched, not downloaded or measured by this continuation. Sizes refer to individual files, not GPU allocations. Start text-only; do not download vision projectors for this question. Store release/revision, checksum and template before each admission.

| Candidate | Verified distribution | Selection reason | Gate or limitation |
|---|---|---|---|
| Qwen3.5-4B / 9B | Existing pinned Q4_K_M files, 3.013 / 5.681 GB | Strong local controls; compare these first | No broad 4B/9B matched result yet |
| OmniCoder-9B | Tesslate Q4_K_M, 5,737,242,944 B (5.34 GiB), Apache-2.0, created March 2026 | Coding specialization with the existing Qwen architecture | Publisher scores are self-reported; load, tools and short-context quality must pass |
| Gemma 4 E4B-it | Unsloth Q4_K_M, 4,977,171,584 B (4.64 GiB), Apache-2.0; April release | Independent architecture and native function calling | E4B means 4.5B effective, about 8B including embeddings; 128K is an upstream claim |
| Ternary Bonsai 2 27B | Prism PTQ1_0, 5,946,648,928 B (5.54 GiB), Apache-2.0; repository created September 16 | Recent larger model at a small file footprint | Requires Prism fork and its transforms; file size does not establish CUDA memory or correctness |
| Qwen3.5-2B | Existing research candidate; community Q4 approximately 1.28 GB | Optional very cheap classification/extraction tier | Admit only if 4B is too expensive for a defined task |

Pinned new-model references:

- OmniCoder GGUF revision `c06117a99179f36962d782946970726b9fc9e533`, file `omnicoder-9b-q4_k_m.gguf`, SHA256 `550e8f7253c8e07997fbce2570d37259b69b0d21faf77e5ed518d4ee4c73d8b3`. [Publisher card](https://huggingface.co/Tesslate/OmniCoder-9B), [files](https://huggingface.co/Tesslate/OmniCoder-9B-GGUF/tree/c06117a99179f36962d782946970726b9fc9e533). The card's BibTeX year 2025 conflicts with Hub creation and its March 2026 update; do not use that year as release proof.
- Gemma GGUF revision `bfc15c382204943c3a8fff0c750b94ae2364d7a3`, file `gemma-4-E4B-it-Q4_K_M.gguf`, SHA256 `85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87`. [Google card](https://huggingface.co/google/gemma-4-E4B-it), [files](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/tree/bfc15c382204943c3a8fff0c750b94ae2364d7a3), [HF launch and integration guide, April 2](https://huggingface.co/blog/gemma4).
- Bonsai revision `b072e1d3b35a0a630cece372c2127528e0994386`, file `Ternary-Bonsai-2-27B-PTQ1_0.gguf`, SHA256 `53107f530aa52eb00912263ab1ee29bd199261c87cd7b4ad4ca1318c1fe33ee3`. [Publisher files](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf/tree/b072e1d3b35a0a630cece372c2127528e0994386). [Backend engineering notes](https://github.com/PrismML-Eng/Bonsai-demo/blob/main/BACKEND-SUPPORT.md) pin `prism-b10772-e8fd209` and explicitly require the fork for all Bonsai 2 formats. Stock Q2_0 loading can omit necessary transforms and yield incorrect output; a successful load is insufficient.

Uncompressed Qwen3.8-27B and Qwen3.6-35B-A3B remain impractical under the present disk/RAM cap. Ordinary quantizations would require a separate fit analysis. The Bonsai compression is a distinct eligible experiment, not evidence that ordinary 27B or 35B weights fit. Active MoE parameters are not stored-weight size. [Official Qwen release history](https://github.com/QwenLM/Qwen3.8).

## Popularity and engineering evidence

Popularity is a search signal, not a quality ranking. On this date the Hub observations showed approximately 592k monthly downloads / 645 likes for the Gemma GGUF and 15.3k / 349 for the OmniCoder GGUF. Bonsai's page and API disagreed (page approximately 2.82M monthly downloads; API `downloads` 4.55M); preserve both observations rather than manufacture a precise ranking. Base and quantization repositories split activity, and these snapshots can change.

[Reddit harness discussion](https://www.reddit.com/r/LocalLLaMA/comments/1w8f7bp/which_agent_harness_do_you_use_and_why/) and [OmniCoder experience](https://www.reddit.com/r/LocalLLaMA/comments/1rsa8wd/omnicoder9b_slaps_in_opencode/) supply useful failure/configuration leads. The [3070 Qwen3.8 hybrid report](https://www.reddit.com/r/LocalLLM/comments/1vw95x6/i_pushed_qwen3827b_q4_to_731_toks_on_an_rtx_3070/) uses a different runtime and memory arrangement. These are anecdotal reports, not comparable controls or representative market shares.

The January 2026 [Anthropic engineering evaluation guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) separates capability from regression tasks and scores environment outcomes as well as traces. Adopt that distinction: the calculator becomes a regression/control fixture, while harder tasks supply evidence for model selection. The August [same-model harness preprint](https://arxiv.org/abs/2608.26218) reports context-handling effects with fixed weights; the [scaffold study](https://arxiv.org/abs/2607.22585) reports token-efficiency differences and uncertain pass-rate differences. Both support testing model–harness pairs; neither proves a universal harness-first policy or a local winner.

Pi remains a minimal extensible option, OpenCode offers explicit agent permissions, and Vibe offers configurable agents. Their upstream features do not repair the lab's measured failures by themselves. The original Pi URL now redirects to [earendil-works/pi](https://github.com/earendil-works/pi); record upstream migration without replacing the installed version silently. Keep OpenCode 1.19.0, Pi 1.1.0 and Vibe 2.26.1 pinned for controls. Hermes repair, Codex/Claude local interoperability and TrueForge prerequisites are independent later rounds; DeepSeek Harness stays excluded.

## Runtime and optimization choices

[llama.cpp speculation documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md) lists native MTP and n-gram modes. The installed binary advertises these options. First prove activation and correctness using the existing 4B file; an ignored flag or zero draft activity is compatibility failure, not a performance comparison. N-grams need no draft weights but depend on repetition; test iterative code rather than only arbitrary prose. Prefix caching is a separate experiment because harness input-token totals do not equal actual server prefill work.

[ExLlamaV3](https://github.com/turboderp-org/exllamav3/releases) is already installed and measured here. Repeated throughput-only sweeps have low priority; restoring its verified archive only makes sense for a defined coding/tool-quality question. Quantization differs from GGUF, so comparisons concern complete configurations.

[vLLM quantization](https://docs.vllm.ai/en/latest/features/quantization/index.html) and [NVIDIA compute capabilities](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/compute-capabilities.html) distinguish Ampere weight-only options from native FP8 activation acceleration. Do not select a recipe just because it says FP8. vLLM/SGLang batching, additional training, large MoE expert caching and extra draft-model stacks are deferred until a workload justifies their installation and memory cost. The [MoE cache proposal](https://github.com/ggml-org/llama.cpp/discussions/28248) is an RFC with different hardware, not a proven 3070 path.

## Plan and state

The executable next-round plan is [2026-10-12-evidence-first-local-lab.md](../../docs/superpowers/plans/2026-10-12-evidence-first-local-lab.md). No new inference, installation, model download or merge was performed in this research revision. New candidates and optimizations remain unmeasured. The original broad mission is incomplete.

Validation of this docs/config revision: full suite on an ext4 snapshot with current overlays passed 80 tests and 3 subtests. Existing PyYAML 6.0.1 parsed both configuration files with duplicate-key rejection: 23 unique model IDs and 11 experiment tiers. The source ledger has 106 six-column data rows. New internal links and diff whitespace checks passed. No linter/typechecker is configured. Installed versions did not change, so `versions.lock` retains measured historical pins; researched candidates are pinned separately in `config/models.yaml`.
