# Held-out QLORA quality probe

This report compares a pinned local base checkpoint with its adapter on the same deterministic, held-out Python tasks. Each generated function is parsed and run only after an AST allowlist rejects imports, unsafe calls, attributes, and other non-expression code; positional calls to `abs`, `max`, and `min` are permitted. It also records per-token negative log likelihood for a fixed reference completion. These metrics cover a narrow synthetic task set, not general coding ability.

Raw input: `qlora-quality-heldout-20261011T185205Z.jsonl`. Measurements: 30. Tasks: 5.
Model: `Qwen/Qwen2.5-Coder-0.5B-Instruct` at revision `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`; quantization: bitsandbytes NF4 with double quantization; runtime: Transformers + PEFT + bitsandbytes (PyTorch 2.10.0+cu128, Transformers 5.19.0, PEFT 0.21.2, bitsandbytes 0.50.2).
GPU: NVIDIA GeForce RTX 3070; storage: `ssd-wsl-ext4-c`; source commit: `2b59373958ce95e8892e18f44ae879273af0de73` (dirty: False); context limit: 32768 tokens; greedy decoding, max 128 generated tokens.
Dataset SHA-256: `be9e00ec5f448770d890be38576e1e77bdca2b80925df023b5de1f386a1dfbd3`; adapter SHA-256: `3b44d863b9c8d4f12f5da84545c7c0b15deb448f8e53654be7553ce993c8c965`.

| Phase | Task | Runs | Passes | Pass rate | Cases passed | Reference NLL/token | Median generation (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| base_nf4 | clamp | 3 | 3 | 100% | 12/12 | 0.4226 | 0.9267 |
| base_nf4 | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.1755 | 0.5610 |
| base_nf4 | inclusive_range | 3 | 3 | 100% | 15/15 | 0.1878 | 0.5587 |
| base_nf4 | sign | 3 | 3 | 100% | 9/9 | 0.2929 | 0.9486 |
| base_nf4 | triangle_area | 3 | 3 | 100% | 9/9 | 0.2665 | 0.5389 |
| qlora_adapter | clamp | 3 | 3 | 100% | 12/12 | 0.4483 | 1.3094 |
| qlora_adapter | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.0486 | 0.7201 |
| qlora_adapter | inclusive_range | 3 | 3 | 100% | 15/15 | 0.0111 | 0.7154 |
| qlora_adapter | sign | 3 | 3 | 100% | 9/9 | 0.2005 | 1.3491 |
| qlora_adapter | triangle_area | 3 | 3 | 100% | 9/9 | 0.0848 | 0.6784 |

Overall `base_nf4` success: 15/15 task runs; 54/54 individual cases passed.
Median reference NLL/perplexity: 0.2665 / 1.3054.

Overall `qlora_adapter` success: 15/15 task runs; 54/54 individual cases passed.
Median reference NLL/perplexity: 0.0848 / 1.0885.

## Interpretation

Compare `base_nf4` with `qlora_adapter` within this QLORA run. The base uses NF4 weights; the adapter was trained with the same precision. Repeated identical generations are retained as repeated observations but are not independent samples of model quality. A pass requires the exact function signature, allowed syntax, successful execution, and every listed test case. NLL scores only the fixed reference code, not all correct solutions. This synthetic arithmetic/code set is a pipeline and narrow generalization probe; it does not establish useful real-world fine-tuning gains.
