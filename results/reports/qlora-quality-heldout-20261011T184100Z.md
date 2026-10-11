# Held-out QLoRA quality probe

This report compares a pinned local NF4 base checkpoint with its adapter on the same deterministic, held-out Python tasks. Each generated function is parsed and run only after an AST allowlist rejects imports, unsafe calls, attributes, and other non-expression code; positional calls to `abs`, `max`, and `min` are permitted. Results measure this narrow task set, not general coding ability or adapter quality across domains.

Raw input: `qlora-quality-heldout-20261011T184100Z.jsonl`. Measurements: 30. Tasks: 5.
Model: `Qwen/Qwen2.5-Coder-0.5B-Instruct` at revision `ea3f2471cf1b1f0db85067f1ef93848e38e88c25`; quantization: bitsandbytes NF4 with double quantization; runtime: Transformers + PEFT + bitsandbytes (PyTorch 2.10.0+cu128, Transformers 5.19.0, PEFT 0.21.2, bitsandbytes 0.50.2).
GPU: NVIDIA GeForce RTX 3070; storage: `ssd-wsl-ext4-c`; source commit: `4f3e2d56c1d100d32b4ff5b643629876f24c31f2` (dirty: False); context limit: 32768 tokens; greedy decoding, max 128 generated tokens.
Dataset SHA-256: `2759876746f726464b5e9073fd166decadf8635c160e1e52983866eed8d8c1ec`; adapter SHA-256: `3b44d863b9c8d4f12f5da84545c7c0b15deb448f8e53654be7553ce993c8c965`.

| Phase | Task | Runs | Passes | Pass rate | Cases passed | Median generation (s) |
|---|---|---:|---:|---:|---:|---:|
| base_nf4 | clamp | 3 | 3 | 100% | 12/12 | 0.9182 |
| base_nf4 | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.5555 |
| base_nf4 | inclusive_range | 3 | 3 | 100% | 15/15 | 0.5553 |
| base_nf4 | sign | 3 | 3 | 100% | 9/9 | 0.9386 |
| base_nf4 | triangle_area | 3 | 3 | 100% | 9/9 | 0.5312 |
| qlora_adapter | clamp | 3 | 3 | 100% | 12/12 | 1.2902 |
| qlora_adapter | difference_of_cubes | 3 | 3 | 100% | 9/9 | 0.7022 |
| qlora_adapter | inclusive_range | 3 | 3 | 100% | 15/15 | 0.7003 |
| qlora_adapter | sign | 3 | 3 | 100% | 9/9 | 1.3200 |
| qlora_adapter | triangle_area | 3 | 3 | 100% | 9/9 | 0.6695 |

Overall `base_nf4` success: 15/15 task runs; 54/54 individual cases passed.

Overall `qlora_adapter` success: 15/15 task runs; 54/54 individual cases passed.

## Interpretation

Compare `base_nf4` and `qlora_adapter` under identical prompts and deterministic decoding. Repeated identical outputs are retained as repeated observations but are not independent samples of model quality. A pass requires the exact function signature, allowed syntax, successful execution, and every listed test case. This synthetic arithmetic/code set is a pipeline and narrow generalization probe; it does not establish useful real-world fine-tuning gains.
