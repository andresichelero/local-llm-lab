# Held-out LORA quality probe

This report compares a pinned local base checkpoint with its adapter on the same deterministic, held-out Python tasks. Each generated function is parsed and run only after an AST allowlist rejects imports, unsafe calls, attributes, and other non-expression code; positional calls to `abs`, `max`, and `min` are permitted. It also records per-token negative log likelihood for a fixed reference completion. These metrics cover a narrow synthetic task set, not general coding ability.

Raw input: `lora-quality-heldout-20261011T185257Z.jsonl`. Measurements: 30. Tasks: 5.
Model: `Qwen/Qwen2.5-Coder-0.5B-Instruct` at revision `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`; quantization: none (FP16 base weights); runtime: Transformers + PEFT + bitsandbytes (PyTorch 2.10.0+cu128, Transformers 5.19.0, PEFT 0.21.2, bitsandbytes 0.50.2).
GPU: NVIDIA GeForce RTX 3070; storage: `ssd-wsl-ext4-c`; source commit: `2b59373958ce95e8892e18f44ae879273af0de73` (dirty: False); context limit: 32768 tokens; greedy decoding, max 128 generated tokens.
Dataset SHA-256: `be9e00ec5f448770d890be38576e1e77bdca2b80925df023b5de1f386a1dfbd3`; adapter SHA-256: `2b8522430f714c9be8273ae735b222d1ff5bb33b77642fdf8397217580632c25`.

| Phase | Task | Runs | Passes | Pass rate | Cases passed | Reference NLL/token | Median generation (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| base_fp16 | clamp | 3 | 3 | 100% | 12/12 | 0.4031 | 0.6647 |
| base_fp16 | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.2082 | 0.3988 |
| base_fp16 | inclusive_range | 3 | 0 | 0% | 0/15 | 0.2197 | 1.6515 |
| base_fp16 | sign | 3 | 3 | 100% | 9/9 | 0.3005 | 0.6775 |
| base_fp16 | triangle_area | 3 | 3 | 100% | 9/9 | 0.3342 | 0.3823 |
| lora_adapter | clamp | 3 | 3 | 100% | 12/12 | 0.3350 | 0.9654 |
| lora_adapter | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.0536 | 0.5246 |
| lora_adapter | inclusive_range | 3 | 3 | 100% | 15/15 | 0.0090 | 0.5249 |
| lora_adapter | sign | 3 | 3 | 100% | 9/9 | 0.1653 | 0.9933 |
| lora_adapter | triangle_area | 3 | 3 | 100% | 9/9 | 0.0696 | 0.4969 |

Overall `base_fp16` success: 12/15 task runs; 39/54 individual cases passed.
Median reference NLL/perplexity: 0.3005 / 1.3505.

Overall `lora_adapter` success: 15/15 task runs; 54/54 individual cases passed.
Median reference NLL/perplexity: 0.0696 / 1.0721.

## Interpretation

Compare `base_fp16` with `lora_adapter` within this LORA run. The base uses FP16 weights; the adapter was trained with the same precision. Repeated identical generations are retained as repeated observations but are not independent samples of model quality. A pass requires the exact function signature, allowed syntax, successful execution, and every listed test case. NLL scores only the fixed reference code, not all correct solutions. This synthetic arithmetic/code set is a pipeline and narrow generalization probe; it does not establish useful real-world fine-tuning gains.
