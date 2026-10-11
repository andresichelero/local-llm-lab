# Held-out QLORA quality probe

This report compares a pinned local base checkpoint with its adapter on the same deterministic, held-out Python tasks. Each generated function is parsed and run only after an AST allowlist rejects imports, unsafe calls, attributes, and other non-expression code; positional calls to `abs`, `max`, and `min` are permitted. It also records per-token negative log likelihood for a fixed reference completion. These metrics cover a narrow synthetic task set, not general coding ability.

Raw input: `qwen25-coder-7b-unsloth-qlora-quality-20261011T1915Z.jsonl`. Measurements: 30. Tasks: 5.
Model: `Qwen/Qwen2.5-Coder-7B-Instruct` at revision `c03e6d358207e414f1eca0bb1891e29f1db0e242`; quantization: bitsandbytes NF4 with double quantization; adapter training backend: unsloth; evaluation runtime: Transformers + PEFT + bitsandbytes (PyTorch 2.10.0+cu128, Transformers 5.19.0, PEFT 0.21.2, bitsandbytes 0.50.2).
GPU: NVIDIA GeForce RTX 3070; storage: `ssd-wsl-ext4-c`; source commit: `341eb671291b8114f484109e41be79ebe065721a` (dirty: False); context limit: 32768 tokens; greedy decoding, max 128 generated tokens.
Dataset SHA-256: `be9e00ec5f448770d890be38576e1e77bdca2b80925df023b5de1f386a1dfbd3`; adapter SHA-256: `28e2b3e464aa29f7d5ffb5e5d00495e9dcc4993c6c40e41fb2040ff49a31c858`.

| Phase | Task | Runs | Passes | Pass rate | Cases passed | Reference NLL/token | Median generation (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| base_nf4 | clamp | 3 | 3 | 100% | 12/12 | 0.5836 | 0.7179 |
| base_nf4 | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.5195 | 0.7448 |
| base_nf4 | inclusive_range | 3 | 3 | 100% | 15/15 | 0.2998 | 0.7465 |
| base_nf4 | sign | 3 | 3 | 100% | 9/9 | 0.6022 | 1.2483 |
| base_nf4 | triangle_area | 3 | 3 | 100% | 9/9 | 0.5083 | 0.7164 |
| qlora_adapter | clamp | 3 | 3 | 100% | 12/12 | 0.2364 | 0.9380 |
| qlora_adapter | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.2719 | 0.9267 |
| qlora_adapter | inclusive_range | 3 | 3 | 100% | 15/15 | 0.0022 | 0.9260 |
| qlora_adapter | sign | 3 | 3 | 100% | 9/9 | 0.3712 | 1.7227 |
| qlora_adapter | triangle_area | 3 | 3 | 100% | 9/9 | 0.0859 | 0.8791 |

Overall `base_nf4` success: 15/15 task runs; 54/54 individual cases passed.
Median reference NLL/perplexity: 0.5195 / 1.6812.

Overall `qlora_adapter` success: 15/15 task runs; 54/54 individual cases passed.
Median reference NLL/perplexity: 0.2364 / 1.2666.

## Interpretation

Compare `base_nf4` with `qlora_adapter` within this QLORA run. The base uses NF4 weights; the adapter was trained with the same precision. Repeated identical generations are retained as repeated observations but are not independent samples of model quality. A pass requires the exact function signature, allowed syntax, successful execution, and every listed test case. NLL scores only the fixed reference code, not all correct solutions. This synthetic arithmetic/code set is a pipeline and narrow generalization probe; it does not establish useful real-world fine-tuning gains.
