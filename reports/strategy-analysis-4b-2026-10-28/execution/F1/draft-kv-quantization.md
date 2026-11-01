# Quantized draft KV

This test asked whether `-ctkd q4_0 -ctvd q4_0` saves VRAM on the recommended profile. The flags set the KV type of the context that runs the MTP draft, which defaults to f16. They do not save VRAM: total use rose by about 80 MiB, and decode got slower. The profile stays as it is.

- Probe: `benchmark/decode_probe.py`, run on 31/10/2026 with llama.cpp master 792fcf4e7.
- Profile: Q4_K_M, KV q4_0, 64K, MTP with n-max 2, checkpoints, `--cache-ram 2048`, thinking off.
- Design: 4 blocks in ABBA order, one server load per arm and block, 8 loads in all. Each load ran 3 warm-up requests, which do not count, then 3 short and 3 long requests.
- Requests: 400 generated tokens, fixed seed, no prompt cache. The short prompt has 37 tokens. The long one has 22,404 tokens, taken from the start of `bottle.py`.

## Memory

| Buffer | f16 | q4_0 | Change |
| --- | --- | --- | --- |
| Draft KV | 256 MiB | 72 MiB | -184 MiB |
| Draft compute buffer | 106 MiB | 370 MiB | +264 MiB |
| Whole GPU after load | 5,094 MiB | 5,174 MiB | +80 MiB |
| Whole GPU, peak over 4 loads per arm | 5,163 MiB | 5,233 MiB | +70 MiB |

The KV saving matches the 184 MiB estimated in the research report. That estimate left out the compute buffer, which grows by more than the KV shrinks. The buffer figures and the after-load row come from one load of each arm with `--verbose-log`. The whole-GPU figures include the desktop.

## Speed and acceptance

| Prompt | Arm | Requests | Median tok/s | Range | Draft acceptance | Prefill tok/s |
| --- | --- | --- | --- | --- | --- | --- |
| Short | f16 | 12 | 146.5 | 140.9 to 155.3 | 85.4% | 500 |
| Short | q4_0 | 12 | 140.7 | 127.0 to 145.2 | 82.4% | 487 |
| Long | f16 | 12 | 103.3 | 100.9 to 111.0 | 73.3% | 3,147 |
| Long | q4_0 | 12 | 101.4 | 94.5 to 109.3 | 72.0% | 3,106 |

The block medians for f16 were higher in 4 of 4 blocks on the short prompt and 3 of 4 on the long one. The drops are 4.0% and 1.8%, and neither should be read as a precise loss. A later single f16 load, run to check the repository version of the probe, gave 102.8 tok/s on the long prompt, inside the range above, and 135.5 tok/s on the short one, well below it. The short prompt therefore varies between loads more than these four blocks show.

Acceptance is the firmer evidence, because the same draft counts repeat in every block: 251 of 295 against 248 of 301 on the short prompt. Together with the memory result, there is no gain to keep.

All 24 short requests produced the same text, and so did all 24 long ones, across both arms. This confirms that the target verifies every token: the flags change speed and memory, not the answer.

## GPU telemetry during the f16 arm

These requests are the 240 W point of test E0. Busy samples only.

| Measure | Short | Long |
| --- | --- | --- |
| Enforced power limit | 239.8 W | 239.8 W |
| Median power | 230.4 W | 233.7 W |
| Median core clock | 1,905 MHz | 1,875 MHz |
| Median memory clock | 7,001 MHz | 7,001 MHz |
| Busy samples in SW power cap | 100% | 100% |
| Peak temperature | 70°C | 72°C |

The rest of E0 needs the power limit and memory clock changed by hand, which takes administrator rights or MSI Afterburner. `benchmark/e0_power_memory.ps1` walks through those points and ends on a repeat of the 240 W control. Its reading should rest on the long prompt, given the short prompt's spread between loads.
