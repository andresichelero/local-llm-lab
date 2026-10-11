# Qwen3.5-9B GGUF structured output and tool smoke on SSD

Run date: 2026-10-11. The pinned `Qwen/Qwen3.5-9B` GGUF Q4_K_M snapshot (`3885219b6810b007914f3a7950a8d1b469d598a5`) and llama.cpp server ran from the C:-hosted WSL ext4 filesystem on the RTX 3070. llama.cpp commit: `d81235049384534c167caea52b85a694f6103d14`. No inference ran from an HDD.

The clean-source run used 2K context, fp16 K/V, 99 GPU layers, Flash Attention, seed 1234, and reasoning off. Both checks passed:

| Check | Result | Time | Usage / evidence |
|---|---|---:|---|
| Strict JSON response | PASS | 0.484 s | 33 prompt tokens; 18 output tokens; parsed exactly `{"ok": true, "count": 3}` |
| `add(19, 23)` tool round trip | PASS | 1.479 s | 1 valid tool call, 0 failed calls, 0 retries; result 42; final answer included 42; 400 input and 54 output tokens across both requests |

## Failure and correction

The first JSON run used llama.cpp's automatic reasoning mode. The model filled the 128-token output allowance with `reasoning_content`, left the assistant's `content` empty, and the strict parser failed. Reproducing the same request showed this exact response boundary. The tool round trip still passed. The harness now defaults this quality check to `--reasoning off`, records the mode, and supports an explicit `REASONING=on|off|auto` override. With reasoning disabled, strict JSON passed in the exploratory run and again in the clean-source run; the tool round trip passed in both.

Raw attempt and final records are in `results/raw/qwen35-gguf-quality.jsonl`, with one-second resource data in `results/raw/qwen35-gguf-quality-resources.jsonl`. The original failed event is retained so the correction remains auditable. This is one synthetic JSON task and one deterministic arithmetic tool task; it is not a broad tool-use, coding, or quality evaluation.
