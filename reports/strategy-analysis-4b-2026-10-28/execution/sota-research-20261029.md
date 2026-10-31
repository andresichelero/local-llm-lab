# State-of-the-art research (Sonnet agent, high effort, 29/10/2026), condensed by the orchestrator

Primary sources consulted by the agent:
- llama.cpp: [server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md), [PR #21038](https://github.com/ggml-org/llama.cpp/pull/21038), [PR #22673](https://github.com/ggml-org/llama.cpp/pull/22673), [issue #24055](https://github.com/ggml-org/llama.cpp/issues/24055), [discussion #23470](https://github.com/ggml-org/llama.cpp/discussions/23470);
- [Qwen3.5-4B](https://huggingface.co/Qwen/Qwen3.5-4B) model card;
- quantization repositories: [unsloth GGUF](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF), [unsloth MTP GGUF](https://huggingface.co/unsloth/Qwen3.5-4B-MTP-GGUF), [bartowski](https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF);
- OpenCode: [config](https://opencode.ai/docs/config/), [LSP](https://opencode.ai/docs/lsp/), [tools](https://opencode.ai/docs/tools/);
- tools: [Headroom](https://github.com/headroomlabs-ai/headroom), [RTK](https://github.com/rtk-ai/rtk).

Labels used below: **F** is a fact from a primary source, **R** is a third-party report, **I** is an inference.

## KV cache
- **F** Accepted KV types: f32, f16, bf16, q8_0, q4_0, q4_1, iq4_nl, q5_0, q5_1.
- **F** The default CUDA build only compiles flash attention kernels for q4_0-q4_0, q8_0-q8_0, f16-f16 and bf16-bf16 pairs. Mixed pairs, such as K q8_0 with V q5_0, require recompilation with `GGML_CUDA_FA_QUANTS`. Without this, the server falls back to f16 with a warning.
- **F** Hadamard rotation for quantized KV was incorporated on 01/04/2026 (PR #21038). It is active in our build and reduces the loss from q4_0. For A/B testing: `LLAMA_ATTN_ROT_DISABLE=1`.
- **R** In discussion #23470, the key (K) is much more sensitive to quantization than the value (V). q8_0 with q8_0 is close to baseline. The effect of q4_0 with q4_0 varies greatly by model.
- TurboQuant exists only in forks, not upstream.
- **I** Our data (q4_0 67%, q8_0 75%, f16 58%) do not show a difference. q8_0 is the "safe" choice, with slightly more VRAM.

## Weights
- Available quantizations:
  - unsloth: UD-Q4_K_XL (2.91 GB), UD-Q6_K_XL (4.15 GB) and an MTP repository;
  - bartowski: Q6_K_L and Q4_K_L, which store embeddings and output in Q8_0.
- **F** According to unsloth, `attn_*` and `ssm_out` tensors are sensitive to quantization in hybrid models. This favors the XL and _L variants.
- **R** In the llm-quant-bench benchmark (single-turn HumanEval), scores from Q4 upward are between 57% and 61%, and UD-Q4_K_XL was best.
- **I** Our 83% for Q6_K comes from a single round and another quantizer, so it still needs repeating.

## MTP (speculative decoding)
- **F** Supported since PR #22673 (16/05/2026), with `--spec-type draft-mtp --spec-draft-n-max 2`. The value 2 is the starting point; test 1 to 6.
- **F** Requires `-np 1`.
- **F** MTP can change output even at temperature 0 because of batch-size-dependent kernels (issue #23335).
- **R** Reported gains: 1.5× to 2.9× in larger models, with no figure for 4B.

## Official sampling (Qwen3.5-4B model card)
- **Without thinking:** temperature 0,7, top_p 0,8, top_k 20, min_p 0, presence_penalty 1.5.
- **Thinking for code:** temperature 0,6, top_p 0,95, top_k 20, presence_penalty 0.
- The card does not prohibit temperature 0, but all presets use temperature above 0. The Qwen3 card discouraged greedy decoding because of the risk of loops.
- **I** Check whether OpenCode sends `temperature` in the request body, because that value overrides the server value.

## Cache in hybrid models
- **F** `--cache-reuse` is disabled when memory does not support shifting. The log warns with "cache_reuse is not supported". **I** It probably has no effect on Qwen3.5.
- **F** Relevant parameters: `--ctx-checkpoints` (default 32), `--checkpoint-min-step` (default 8192) and `--cache-ram`. Recommendation for multi-turn: `-ctxcp 64 -cms 512..1024`.
- **R** Open bug (#24055): hybrid models sometimes reprocess the entire prompt. **I** In our case, 91% to 95% of prompt tokens come from cache, so the problem seems small.

## Long tasks
- **F** OpenCode compaction: `"compaction": {"auto": true, "prune": true, "reserved": 8192}`, plus `limit.context/input/output` per model. The default reservation is large and overflows small local contexts (#8140).
- **F** Plugins can replace the compaction prompt through the `experimental.session.compacting` hook.
- **F** Headroom compresses tool outputs through a proxy (`headroom-opencode` with `proxyUrl`). Telemetry is enabled by default; disable with `HEADROOM_OFFLINE=1`. The reported figures are from the vendor itself.
- **I** Compressing tool output can change the conversation prefix and break cache checkpoints.

## Tools
- **F** OpenCode LSP is disabled by default. `"lsp": true` enables it, and pyright must be installed.
- **F** The `lsp` tool (definition, references, symbols) is experimental and is enabled with `OPENCODE_EXPERIMENTAL_LSP_TOOL=true`.
- **F** RTK filters bash output, for example leaving only pytest failures. Install with `rtk init -g --opencode`.
- **I** There is no independent evidence of gains for small models. Each MCP adds schemas to the prompt, and filtering tools has more established effects.

## Suggested priorities (used in the overnight plan)
1. Repetitions: with 12 tasks, only differences of 3 or more merit attention.
2. KV q8_0.
3. Weights UD-Q4_K_XL, Q6_K_L and UD-Q6_K_XL.
4. Official sampling versus temperature 0.
5. MTP with n-max 2.
6. Cache checkpoints verified with `-lv 4`.
7. Configured compaction.
8. LSP and output filtering.
9. Notes on disk or session restart.
10. Headroom, low priority.
