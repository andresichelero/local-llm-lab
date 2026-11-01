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

## Raised GPU clocks

The run above used stock clocks. On 01/11/2026 the core and memory clocks were raised by hand, the power limit stayed at 240 W, and the f16 arm ran again with 6 loads in a row. The first load is left out for the reason given below.

| Prompt | Clocks | Requests | Median tok/s | Range | Prefill tok/s | Median core | Median memory | Median power |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Short | Stock | 12 | 146.5 | 140.9 to 155.3 | 500 | 1,905 MHz | 7,001 MHz | 230.4 W |
| Short | Raised | 15 | 147.2 | 140.1 to 154.0 | 499 | 1,905 MHz | 7,301 MHz | 232.5 W |
| Long | Stock | 12 | 103.3 | 100.9 to 111.0 | 3,147 | 1,875 MHz | 7,001 MHz | 233.7 W |
| Long | Raised | 15 | 103.7 | 101.2 to 107.5 | 3,144 | 1,875 MHz | 7,301 MHz | 233.8 W |

Decode did not change: +0.5% and +0.4%, both inside the spread of the two groups, with prefill flat as well. Memory ran 4.3% faster, so on this card, at this limit, decode does not follow memory clock. The median core clock stayed the same and the SW power cap covered the median request in both groups, which suggests the core has no spare power to use a higher offset. The two groups come from different sessions rather than alternating blocks, so this rules out a gain of several percent and cannot rule out one near 1%.

Memory read 7,501 MHz at idle and 7,301 MHz under the compute load. NVML under WSL reports both offsets as zero, so the offsets themselves are not on record.

Two earlier runs at the same clocks are not in the table. In the first, VLC was open and held 739 MiB of GPU memory, and 9 of 12 long requests fell below 98 tok/s. In the second, a logger read the Windows GPU counters every 4 seconds, no other process showed GPU use, and all 12 long requests fell below 98 tok/s. Neither cause was isolated. In the kept run, the first load was also slow, down to 72.7 tok/s, with Windows CPU load at 80% to 100%; the next five loads saw 7% to 73%. That load was the coolest of the run, so temperature does not explain it. Any later speed run should log CPU load and keep the PC otherwise idle.

All 84 counted requests in the three runs gave the same text as the stock run, and Windows logged no `nvlddmkm` event in that hour, so this short test showed no instability. The power half of E0 was dropped because the limit stays at 240 W, which leaves open whether decode follows the power limit.
