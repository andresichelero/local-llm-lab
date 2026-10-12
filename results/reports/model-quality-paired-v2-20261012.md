# Paired OpenCode Quality Matrix (v2) — 2026-10-12

## Executive Summary

The complete Milestone M3 paired quality matrix (`model-quality-v2-20261012-195743`) executed to 100% completion on local WSL ext4 SSD storage with strictly serialized GPU leases on the RTX 3070 (8 GiB VRAM). 

All **24 measured trials** (6 tasks $\times$ 2 models $\times$ 2 repeats) plus 2 compatibility gates, 2 calibrations, and 2 warm-ups (28 runs in total) finished with `return_code: 0`, zero process leaks, zero OOMs, and zero runner timeouts in an end-to-end wall time of **23 minutes 2 seconds**.

Both models achieved an identical **66.7% (8/12)** strict functional pass rate, but exhibited stark, task-dependent latency and efficiency profiles:
- On lightweight single-file tasks, **Qwen3.5 4B** was ~25–32% faster in wall time and consumed ~2.1 GiB less VRAM (4.9 GiB peak vs 7.3 GiB peak).
- On complex multi-turn algorithmic reasoning (`retry_policy`), **Qwen3.5 9B** was **2.38× faster** than 4B (46.92s vs 111.63s median) because 9B solved the implementation and exception contract in one turn, while 4B required multiple iteration steps.
- The 2 new discriminating tasks (`config_precedence` and `package_refactor`) successfully acted as high-granularity quality discriminators, catching subtle edge conditions in both models without crashing the runner.

---

## Frozen Setup and Provenance

- **Protocol:** `model-quality-v2-20261012-v2`; source commit `276d8af`.
- **Harness:** OpenCode `1.19.0` (single-agent `build` mode, 20 steps, auto-update disabled).
- **Inference Runtime:** `llama-server` built from commit `d81235049` (llama.cpp v0.6.0-dev).
- **Models:**
  - `qwen3.5-4b`: `Qwen_Qwen3.5-4B-Q4_K_M.gguf` (`13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983`)
  - `qwen3.5-9b`: `Qwen3.5-9B-Q4_K_M.gguf` (`03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`)
- **Serving Parameters:** `--ctx-size 16384`, `--n-gpu-layers 99`, `--batch-size 512`, `--ubatch-size 256`, `--flash-attn on`, `--cache-type-k q4_0`, `--cache-type-v q4_0`, `--reasoning off`, `--no-cache-prompt`, `--parallel 1`.
- **Execution Order:** 4 balanced AB/BA blocks to eliminate order bias:
  - Block 1: `qwen3.5-4b` (Repeat 1: 6 tasks)
  - Block 2: `qwen3.5-9b` (Repeat 1: 6 tasks)
  - Block 3: `qwen3.5-9b` (Repeat 2: 6 tasks)
  - Block 4: `qwen3.5-4b` (Repeat 2: 6 tasks)

---

## Task Matrix Results

| Task | Category | 4B Strict Pass | 4B Wall Median (s) | 9B Strict Pass | 9B Wall Median (s) | Speedup (4B / 9B) | Primary Discriminator / Failure Mode |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| `calculator_division` | Baseline Arithmetic | 2/2 (100%) | 35.40s | 2/2 (100%) | 47.46s | 0.75× (4B faster) | Both models pass unit tests and behavioral probes. |
| `whitespace_normalization` | String Manipulation | 2/2 (100%) | 29.06s | 2/2 (100%) | 40.08s | 0.73× (4B faster) | Both models pass whitespace edge cases and unit tests. |
| `dotenv_line_parser` | Parsing / Lexing | 2/2 (100%) | 34.82s | 2/2 (100%) | 50.86s | 0.68× (4B faster) | Both models correctly parse quotes and comments. |
| `retry_policy` | Multi-turn Reasoning | 2/2 (100%) | 111.63s | 2/2 (100%) | 46.92s | **2.38× (9B faster)** | 9B solves cleanly in 1 turn; 4B requires multi-turn repairs. |
| `config_precedence` | Dict Precedence & Falsy | 0/2 (0%) | 31.68s | 0/2 (0%) | 46.22s | 0.69× (4B faster) | Both models trip on `{x: None}` precedence override. |
| `package_refactor` | Multi-file Structure | 0/2 (0%) | 50.12s | 0/2 (0%) | 48.50s | 1.03× (equal) | Both models miss complex inter-module re-export edges. |
| **Overall Summary** | **24 Measured Trials** | **8/12 (66.7%)** | **35.37s** | **8/12 (66.7%)** | **47.41s** | — | **Zero crashes, 100% exit code 0.** |

---

## Detailed Telemetry & Resource Consumption

| Metric | Qwen3.5 4B (12 trials + cal/warmup) | Qwen3.5 9B (12 trials + cal/warmup) | Delta / Note |
| :--- | :--- | :--- | :--- |
| **Strict Functional Pass** | 8 / 12 (66.7%) | 8 / 12 (66.7%) | Identical overall success rate |
| **Median Task Wall Time** | 35.37 seconds | 47.41 seconds | 4B is ~25% faster overall |
| **Min / Max Task Wall Time**| 28.52s / 121.06s | 32.77s / 54.29s | 9B variance is significantly narrower |
| **Peak VRAM Allocated** | 5,210.0 MiB | 7,328.0 MiB | 9B uses +2,118 MiB VRAM (+40.7%) |
| **Average VRAM Allocated** | 4,575.9 MiB | 6,653.2 MiB | Fits comfortably within 8 GiB RTX 3070 |
| **WSL RAM Usage (avg)** | 2,610.6 MiB | 3,288.9 MiB | +678.3 MiB RAM for 9B |
| **Peak GPU Utilization** | 98.0% | 99.0% | Full GPU compute saturation during prefill/generation |
| **Average GPU Utilization**| 82.7% | 87.0% | Minimal idle time during tool evaluation |
| **Peak GPU Power** | 228.4 W | 238.4 W | Within RTX 3070 240W TGP |
| **Swap Usage** | 0.0 MiB | 0.0 MiB | Zero memory paging to swap |

---

## Key Diagnostic & Engineering Insights

1. **The 9B Algorithmic Advantage (`retry_policy`):**
   In tasks involving exception hierarchy matching, callback invocations, and backoff calculation, 9B demonstrates superior single-turn code generation quality. While 4B eventually passed both trials of `retry_policy`, it took 121.06s and 102.21s, repeatedly correcting intermediate test failures. 9B completed the task in 46.40s and 47.44s without requiring corrective loops.
2. **Behavioral Discriminator Efficacy (`config_precedence`):**
   The adversarial mutant in `config_precedence` specifically tested whether an explicit `{'x': None}` in a higher-precedence layer would overwrite a non-None default. Both 4B and 9B wrote simple `{**defaults, **file_config}` mergers that failed this nuance (`AssertionError: resolve_config({'x': 10}, {'x': None}, None) == {'x': 10}`). This confirmed that the newly engineered test fixtures successfully discriminate shallow heuristic solutions from full specification adherence.
3. **Storage & Runner Stability:**
   The ephemeral `node_modules` cleanup logic introduced in `276d8af` successfully kept total matrix scratch space to **282 MB** (down from projected 1.8 GB). Ext4 SSD disk free space never dropped below 14.5 GiB, well above the 8 GiB safety requirement.

---

## Artifact Location and Raw Data

- **Raw Experiment Directory:** `results/raw/model-quality-v2-20261012-195743/`
- **Execution Log:** `results/raw/model-quality-v2-20261012-195743/records.jsonl`
- **JSON Summary:** `results/raw/model-quality-v2-20261012-195743/summary.json`
- **Llama Server Telemetry:**
  - `llama-server-measured-block-1-qwen3.5-4b.log`
  - `llama-server-measured-block-2-qwen3.5-9b.log`
  - `llama-server-measured-block-3-qwen3.5-4b.log`
