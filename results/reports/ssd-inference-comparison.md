# SSD-backed Qwen3.5-9B inference follow-up

Run date: 2026-10-11. The original GGUF remains at `E:\local-llm-models\Qwen3.5-9B-GGUF`; active runs used a hash-verified copy in WSL ext4 at `/home/foxtrot/local-llm-benchmark/models/gguf/Qwen3.5-9B-Q4_K_M.gguf`, whose virtual disk is hosted on the C: Samsung 970 EVO Plus SSD. The model is `unsloth/Qwen3.5-9B-GGUF`, revision `3885219b6810b007914f3a7950a8d1b469d598a5`, GGUF Q4_K_M, SHA-256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`.

After the inference series, both the archived E: file and SSD test copy were verified against that SHA-256. The temporary 5.68 GB SSD model copy was then removed; the original E: archive remains intact and the WSL filesystem returned from 29 to 34 GiB free. Stage it again before future Qwen tests.

The runtime is llama.cpp commit `d81235049384534c167caea52b85a694f6103d14` (0.6.0-dev), CUDA build for sm_86. The first SSD runs loaded the model from C: but the runtime executable and libraries from D:, which is an ST1000DM003 HDD. The 71.75 MiB runtime bundle was then copied to WSL ext4 on C:. SHA-256 checks matched for the executable and core libraries, `--version` matched, and `ldd` resolved `libllama` and `libggml` from the C: copy. The final profiled series records both runtime and model locations.

## Measurements

| Configuration | Model / runtime storage | Inference outputs | Model-load log median | TTFT median | Prompt tok/s median | Generation tok/s median | Sampled VRAM max |
|---|---|---:|---:|---:|---:|---:|---:|
| 2K, FP16 K/V, short prompt | E: model / D: runtime | 3 | 41,470 ms (3 startup logs: 38,330–44,857) | 64.32 ms | 462.78 | 64.13 | 5,801 MiB |
| 2K, FP16 K/V, short prompt, two SSD series | C: model / D: runtime | 6 | 4,393 ms (3 startup logs: 2,719–5,733) | 70.66 ms | 424.45 | 63.26 | 6,212 MiB |
| 2K, FP16 K/V, short prompt | C: model / C: runtime | 3 | 4,898 ms (1 startup log); 6,068 ms command-to-health | 78.82 ms | 376.94 | 52.18 | 6,658 MiB |
| 16K, Q4_0 K/V, 14K prompt | E: model / D: runtime | 3 | 38,062 ms (one startup log) | 7,289.00 ms | 1,971.38 | 61.85 | 5,935 MiB |
| 16K, Q4_0 K/V, 14K prompt | C: model / D: runtime | 3 | 4,064 ms (one startup log) | 7,324.97 ms | 1,965.55 | 62.04 | 6,191 MiB |

The 2K model-load intervals are derived from the monotonic llama.cpp log timestamps between `llama_server: initializing` and `model loaded`. The SSD-backed median was about 9.4x lower. The three HDD starts came from the same model and context, though they were separate experiments; the three SSD starts span two full series and one startup repeat. The operating-system file cache was not cleared or controlled. Treat this as observed startup behavior rather than a cold-cache guarantee. The `server_startup_to_ready_ms` JSONL field is a separate wall-clock measurement from launching the process to a successful health check; do not compare it directly to the log interval.

Across the two complete 2K SSD series using the C: model and D: runtime, generation median was 63.26 tok/s versus 64.13 tok/s on E:, and TTFT was 70.66 versus 64.32 ms. Their small prompts and deterministic response only check the inference path; they do not measure reasoning or coding quality. For the 16K test, the SSD processed 14,380 prompt tokens and completed 3/3 outputs with median 1,965.55 prompt tok/s, 62.04 generation tok/s, and a 6,191 MiB peak in paired resource samples. The prior HDD run used 14,352 prompt tokens, so the two long-context prompts were close but not identical.

The C-only runtime series completed 3/3, but its sampled total VRAM rose to about 6.7 GiB and generation fell to 49.96–52.67 tok/s. At the same time, idle GPU memory was about 1.3 GiB versus 0.7–0.9 GiB during earlier series. The RTX 3070 also drives the Windows desktop, so the evidence points to changing GPU contention; it does not establish a runtime-storage regression. Keep this series visible and separate.

## Reproduction

1. Run `bash scripts/18_stage_qwen35_gguf_to_ssd.sh --dry-run`, then omit `--dry-run` to stage the pinned GGUF from E: and verify its SHA-256.
2. Stage the runtime with `bash scripts/17_stage_llamacpp_to_ssd.sh`; the script never deletes the D: build.
3. Run the benchmark with `MODEL_PATH`, `MODEL_REVISION`, `STORAGE_PROFILE=ssd-wsl-ext4-c`, `LLAMA_SERVER=/home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server`, `LD_LIBRARY_PATH=/home/foxtrot/local-llm-benchmark/tools/llama-bin`, and `RUNTIME_STORAGE_PROFILE=ssd-wsl-ext4-c`.
4. Use one warm-up and at least three measured repetitions. Keep the Windows desktop GPU load in mind and record resource samples.

Raw inference JSONL, paired hardware samples, the log-derived startup JSONL, and the corresponding server logs are retained in `results/raw/` and `logs/`. `scripts/09_benchmark_inference.sh` records model/runtime paths, storage profiles, model revision, and server startup-to-ready time for future runs.
