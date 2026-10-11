# Held-out QLORA quality probe

This report compares a pinned local base checkpoint with its adapter on the same deterministic, held-out Python tasks. Each generated function is parsed and run only after an AST allowlist rejects imports, unsafe calls, attributes, and other non-expression code; positional calls to `abs`, `max`, and `min` are permitted. It also records per-token negative log likelihood for a fixed reference completion. These metrics cover a narrow synthetic task set, not general coding ability.

Raw input: `qwen25-coder-7b-qlora-quality-20261011T1858Z.jsonl`. Measurements: 30. Tasks: 5.
Model: `Qwen/Qwen2.5-Coder-7B-Instruct` at revision `c03e6d358207e414f1eca0bb1891e29f1db0e242`; quantization: bitsandbytes NF4 with double quantization; runtime: Transformers + PEFT + bitsandbytes (PyTorch 2.10.0+cu128, Transformers 5.19.0, PEFT 0.21.2, bitsandbytes 0.50.2).
GPU: NVIDIA GeForce RTX 3070; storage: `ssd-wsl-ext4-c`; source commit: `d10b6122c6011480c50600d050997178156d851a` (dirty: False); context limit: 32768 tokens; greedy decoding, max 128 generated tokens.
Dataset SHA-256: `be9e00ec5f448770d890be38576e1e77bdca2b80925df023b5de1f386a1dfbd3`; adapter SHA-256: `578ca804e866326ca1da16524b65bf0f101aa45da83faa7575a5afb95c3e21e9`.

| Phase | Task | Runs | Passes | Pass rate | Cases passed | Reference NLL/token | Median generation (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| base_nf4 | clamp | 3 | 3 | 100% | 12/12 | 0.5836 | 0.6890 |
| base_nf4 | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.5195 | 0.7184 |
| base_nf4 | inclusive_range | 3 | 3 | 100% | 15/15 | 0.2998 | 0.7194 |
| base_nf4 | sign | 3 | 3 | 100% | 9/9 | 0.6022 | 1.2006 |
| base_nf4 | triangle_area | 3 | 3 | 100% | 9/9 | 0.5083 | 0.6898 |
| qlora_adapter | clamp | 3 | 3 | 100% | 12/12 | 0.2361 | 0.9093 |
| qlora_adapter | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.2726 | 0.8978 |
| qlora_adapter | inclusive_range | 3 | 3 | 100% | 15/15 | 0.0022 | 0.8962 |
| qlora_adapter | sign | 3 | 3 | 100% | 9/9 | 0.3712 | 1.6685 |
| qlora_adapter | triangle_area | 3 | 3 | 100% | 9/9 | 0.0852 | 0.8546 |

Overall `base_nf4` success: 15/15 task runs; 54/54 individual cases passed.
Median reference NLL/perplexity: 0.5195 / 1.6812.

Overall `qlora_adapter` success: 15/15 task runs; 54/54 individual cases passed.
Median reference NLL/perplexity: 0.2361 / 1.2664.

## Interpretation

Compare `base_nf4` with `qlora_adapter` within this QLORA run. The base uses NF4 weights; the adapter was trained with the same precision. Repeated identical generations are retained as repeated observations but are not independent samples of model quality. A pass requires the exact function signature, allowed syntax, successful execution, and every listed test case. NLL scores only the fixed reference code, not all correct solutions. This synthetic arithmetic/code set is a pipeline and narrow generalization probe; it does not establish useful real-world fine-tuning gains.
