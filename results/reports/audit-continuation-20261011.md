# Lab continuation audit and comparative evidence

Date: 2026-10-11 (America/Sao_Paulo). Audit snapshots: 21:00–21:07 UTC (18:00–18:07 local). This is a continuation checkpoint, not completion of the original laboratory scope.

## Current repository and machine

The clean checkout began on `docs/progress-20261011` at `28d9ad783b569fdf316872547e488b7251df14f3`. GitHub confirmed PR33 merged at `58ba9ad`, PR34 open with that base, the expected head, and all three CodeQL checks successful. Independent review found only the 36-line checkpoint addition. PR34 was merged with an expected-head guard at 21:07:07 UTC as `db190b0620c1688c2bf8a3ebf2f6aaba6ee7b0f7`. Local main was fast-forwarded and continuation uses `feat/audit-opencode-controlled-20261011`; no direct push to main occurred.

Ubuntu-24.04 WSL2 was already running, with no llama-server/OpenCode/Ollama inference process detected. WSL reported 7.8 GiB RAM, approximately 7.3 GiB available, 4 GiB swap and about 45 MiB used. Host physical RAM was 32 GiB with approximately 17 GiB available. The RTX3070 had 8192 MiB total and approximately 7.2 GiB free in the snapshot; desktop contention can change this.

Host free storage was approximately C:53.6 GB, D:69.3 GB and E:59.5 GB. C-backed WSL ext4 reported 108 GiB total and 16 GiB available. Its VHD is under `C:\Users\Andre\AppData\Local\wsl`, approximately 96.5 GB allocated. No resize, service shutdown, driver change or reboot was needed.

The 5,680,522,464-byte SSD GGUF matches pinned SHA256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`. The existing OpenCode probe archive on E matches `6bb4d31cf3d3428f5d6b6e8a7b95ba642e61ba2350c8491cdeaf555884a45aed`. OpenCode's absolute isolated executable reports 1.19.0; absence from PATH does not mean it is absent.

The 17,888-byte llama-server is a valid dynamic executable, build 1 at `d81235049`. Its embedded RUNPATH points to D when invoked without an explicit library environment. With `LD_LIBRARY_PATH=/home/foxtrot/local-llm-benchmark/tools/llama-bin`, the llama/ggml/mtmd libraries resolve inside that SSD bundle and `require_llama_cpp_ssd_bundle` passes. All new launches must use this environment and preflight. This observation does not invalidate historical runs that used the documented environment.

## Measurements compared before continuation

| Question | Existing result | Reopened primary evidence and interpretation |
|---|---|---|
| Harness overhead on Qwen3.5-9B | Pi 3/3, 19.92 s; OpenCode 3/3, 46.13 s; Vibe 3/3, 45.02 s | `results/raw/harness-run-summary.jsonl`, selected rows 21–29: measured, successful, clean source at `ddeef10e4f4ee697baf76514114e65e26d98dac3`. First-prompt medians 1709 / 7550 / 8088; total input medians 13875 / 50580 / 53490. One saturated coding task; harness counters differ. |
| Strict coding discipline on Qwen3.5-4B | OpenCode 15/15, Pi 11/15, Vibe 9/15 across 45 measurements | Five raw inputs listed below reproduce totals with clean provenance and `benchmark_valid=true`. Division: 5/5,3/5,0/5; whitespace all 5/5; parser 5/5,3/5,4/5 (OpenCode/Pi/Vibe). Small tasks, not a general ranking. |
| 16K Qwen9B KV generation | q4_0 59.37, q8_0 61.99, f16 59.52 tok/s | Three measured rows per format, 14352-token prompt and 16384 context, same model/runtime. These medians were recomputed; resource peaks and broad semantic quality were not re-audited. |
| Long continuation | Pi 0/5 strict; Vibe 1/4 strict | Pi report includes transcript-derived coverage gates that cannot be recomputed from its small summary alone in this audit. Vibe's four raw rows explicitly show `quality_pass`; first three failed scope on 34 mode changes each, fourth passed with zero. README's former 0/3 was a stale total. |
| Unsloth vs PEFT 7B QLoRA fit | 5640.3 vs 7678.4 MiB Torch allocated | Three measured Unsloth rows vs one matched PEFT quality-series observation (other rank-sweep records exist). Shared pinned model/dataset/seed, but unpaired runs and framework/dropout differences. Capacity evidence; no causal timing or broad adaptation-quality claim. |
| OpenCode subagent compatibility | Read-only delegated inspection 14.25 s; coding 65 s,1/4 and 143.42 s,3/4 | `exploratory-invalid/opencode-subagent-probe-20261011.jsonl` and child events. Six steps used explorer but no reviewer; fourteen steps used neither. No measured quality advantage. `status.md` had reversed pass counts, now corrected. |

Primary 4B inputs: `qwen35-4b-pi-harness-20261011.jsonl`, `qwen35-4b-opencode-harness-20261011.jsonl`, `qwen35-4b-vibe-harness-20261011.jsonl`, `qwen35-4b-whitespace-harness-20261011.jsonl`, `qwen35-4b-env-parser-harness-20261011.jsonl` under `results/raw/`. These include 15 warmups separately from 45 measured runs.

Primary KV inputs under `results/raw/`: `qwen35-ssd-context-16384-q4_0.jsonl`, `qwen35-ssd-kv-16384-q8_0.jsonl`, `qwen35-ssd-kv-16384-f16.jsonl`. Training inputs: `qwen25-coder-7b-peft-qlora-ssd-20261011T1858Z.jsonl` and `qwen25-coder-7b-unsloth-qlora-20261011.jsonl`. Compaction inputs: the two `pi-context-stress*.jsonl` summary files and `vibe-context-stress.jsonl`.

Other established report findings were read but not independently recomputed in this audit: Qwen14B JSON3/3 and protocol tool0/3; Ornith9B/Pi3/3 at25.13s versus Qwen9B19.92s; ExLlama/GGUF configuration comparisons; LoRA/QLoRA synthetic held-out passes. They remain task/configuration-specific and their detailed reports retain their limitations.

## Where the original plan stands

| State | Scope |
|---|---|
| Researched | Runtime/quantization/harness candidates and primary source ledger; three 2026 candidates revalidated without new weight downloads in this continuation. Upstream claims are not local fit or quality. |
| Installed | CUDA llama.cpp, ExLlama/PyTorch training stacks, bitsandbytes/PEFT/Unsloth, local harness environments. This audit verifies active llama/OpenCode and model paths; it does not import every installed stack again. |
| Executed/measured | SSD inference, weight/KV/context configurations, narrow JSON/tool/coding probes, synthetic training capacity/quality, rank/optimizer runs, compaction and exploratory delegation. |
| Incomplete | Reliable multiagent coding/review, broader unsaturated quality, long tool-heavy continuity, Codex local interoperability, generalized adaptation gains. |
| Implemented but not measured end to end | `router/rules.py` has deterministic semantic shortlists and health/exclusion filtering; its unit tests are not evidence of routing quality, live endpoint behavior or cost. |
| Not established | Measured routing and fallback-cloud cost/quality; broader model/weight-quant sweeps; MoE/expert caching; MTP/speculation benefit; remaining named harnesses. No overall winner or complete matrix is claimed. |

The next priority is the cheapest missing operational gate: can the corrected OpenCode profile actually execute a bounded delegated workflow? It uses already verified assets, needs no weight download, and separates tool compatibility from coding success. If calibration fails, the evidence favors deterministic routing/failure escalation work before further cap tuning. A full Cartesian matrix is unnecessary.

Remaining harness inventory has concrete blockers: Codex reached the local Responses endpoint but did not complete a task because of catalog/tool/template incompatibilities (`codex-local-oss.md`); TrueForge passed a zero-tool text smoke, with coding blocked by missing bubblewrap/socat (`trueforge-smoke.jsonl`). Claude Code was not detected on PATH and has no local task result. Hermes is listed as an existing host installation, but its current version command fails with `ModuleNotFoundError: No module named 'hermes_cli'`; installed metadata is not proof of a working CLI. The user installation was not replaced. These need separate interoperability/repair rounds, not model-quality scores.

## New-round protocol and publication

The saved plan is `docs/superpowers/plans/2026-10-11-opencode-controlled.md`. First load the exact profile through isolated runtime diagnostics, require the local endpoint and explicit child shell/edit denies, then perform a 90-second read-only delegation. A passing gate permits one 180-second/20-step calibration pair on the existing calculator task: equal-profile single agent control versus explorer+independent reviewer treatment. Only complete calibration permits warmups and three measured pairs. Preserve every failure; don't change limits after seeing failures. Reserve at least 8 GiB ext4 and limit new scratch to 1 GiB. Archives are checksummed on E only after timing; no HDD test or paid endpoint.

Validation discovery: no repository linter/typechecker is configured. Windows Python 3.12 initially ran 72 tests plus 3 subtests successfully, with one failing Bash-launcher test caused by a Windows path passed to Linux Bash. Baseline verification of a clean `db190b0` source snapshot on SSD ext4 passed 73 tests and 3 subtests in 0.89 s with isolated pytest 9.1.1. This confirms the initial failure was an environment mismatch. The small test environment and pinned dependency versions are recorded in `results/system-audit/lab-validation-20261011.txt`; no global packages were changed. Final new-run validation is recorded below when complete.
