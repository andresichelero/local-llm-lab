# Factor separation: MTP, checkpoints, cache limit and llama.cpp master

This campaign tested one change at a time on the setup from the [calibrated comparison](calibrated-comparison.md), to see which settings behind that report's faster profile do anything. Every arm used Qwen3.5-4B Q4_K_M, KV q4_0, 64K, prompt cache and the thinking cascade, on 18 tasks with three repetitions.

| Arm | Change from `CMP-base` |
| --- | --- |
| `CMP-base2` | None. Repeats `CMP-base` to measure the noise of the setup |
| `CMP-mtp` | `--spec-type draft-mtp --spec-draft-n-max 2` |
| `CMP-ckpt` | `--ctx-checkpoints 64 --checkpoint-min-step 1024` |
| `CMP-ram4g` | `--cache-ram 4096`, WSL memory 12 GB instead of 8 GB, NVML sampling |

A separate run repeated `R-q4`, the full profile on 12 pilot tasks, on llama.cpp master `792fcf4e7` instead of `8642541`.

- Configs: `qwen-4b-opencode-factor-separation.json`, `qwen-4b-opencode-factor-cache-ram-nvml.json`, `qwen-4b-opencode-combined-master.json`, all in `benchmark/configs/`.
- Aggregate: [factor-separation-v1-summary.txt](../../../../results/3070-benchmark/factor-separation-v1-summary.txt).

## Result

No setting changed the pass rate beyond the noise of the setup. MTP raised decode speed by 44% to 48%. Checkpoints and the larger cache gave no measured gain. Master raised decode speed by 13% over the older build.

| Measure | CMP-base | CMP-base2 | CMP-mtp | CMP-ckpt | CMP-ram4g |
| --- | --- | --- | --- | --- | --- |
| Passed first attempt | 21/54 | 27/54 | 21/54 | 23/54 | 21/54 |
| Passed after retry | 34/54 | 31/54 | 29/54 | 32/54 | 32/54 |
| Retries | 20 | 12 | 17 | 17 | 16 |
| Rescued by retry | 13 | 4 | 8 | 9 | 11 |
| Decode tok/s | 72.7 | 74.8 | 107.8 | 71.4 | 70.0 |
| Prompt tok/s | 2,523 | 2,511 | 2,160 | 2,543 | 2,390 |
| Prompt tokens reused | 95.8% | 95.9% | 95.2% | 95.1% | 95.1% |
| Median unit | 125 s | 89 s | 105 s | 83 s | 62 s |
| Arm total | 183 min | 129 min | 151 min | 175 min | 152 min |
| Median VRAM | 4,606 MiB | 4,619 MiB | 5,210 MiB | 4,369 MiB | 4,511 MiB |
| Lowest WSL available | 2,454 MiB | 2,512 MiB | 2,180 MiB | 1,247 MiB | 4,406 MiB |

McNemar exact on final passes, paired by task and repetition:

| Pair | First only | Second only | p |
| --- | --- | --- | --- |
| `CMP-base`, `CMP-base2` | 6 | 3 | 0.508 |
| `CMP-base`, `CMP-mtp` | 8 | 3 | 0.227 |
| `CMP-base`, `CMP-ckpt` | 5 | 3 | 0.727 |
| `CMP-base`, `CMP-ram4g` | 6 | 4 | 0.754 |
| `CMP-base2`, `CMP-mtp` | 7 | 5 | 0.774 |
| `CMP-base2`, `CMP-ckpt` | 4 | 5 | 1.000 |
| `CMP-base2`, `CMP-ram4g` | 5 | 6 | 1.000 |

## The noise floor

`CMP-base` and `CMP-base2` ran the same command apart from the port. Nine of 54 final outcomes changed, first-attempt passes went from 21 to 27 (p = 0.070), and arm time went from 183 to 129 minutes. That is the size of change this setup produces on its own, and each factor below has to be read against it.

Retries rescued 13 units in `CMP-base` and 4 in `CMP-base2`. The gap the earlier report wanted to explain, 13 against 8, sits inside that range, so it needs no separate cause. It concentrated in `py_cookie`, `recover_date` and `cont_plugins`, three tasks out of 18.

## Each factor

**MTP.** Decode rose from 72.7 and 74.8 to 107.8 tok/s and prompt speed fell about 14%. The MTP block and its context add about 600 MiB of VRAM. Total time did not improve in a measurable way: 151 minutes sits between the two controls. Time per unit mixes decode, prompt processing, tool time and how far each attempt went, and those parts vary more than decode gains.

**Checkpoints.** No gain in passes, speed or time, and they cost RAM. The arm had the lowest WSL headroom of the campaign, 1,247 MiB. This corpus may not exercise the context restores they exist for, since no episode here compacted in the earlier comparison.

**Cache limit.** Prompt reuse stayed near 95% in every arm, so 4 GiB did not raise it. Evictions fell from 68 in `CMP-base2` to 24. With 2 GiB, prompt states larger than the limit were not stored: 21 times in `CMP-mtp` and 18 in `CMP-ckpt`, none in `CMP-base2`, with sizes up to 3.7 GiB. Those events did not show up in the pass rate or in reuse. No arm hit an out-of-memory error.

The 12 GB WSL limit moved pressure to Windows. Commit reached 89% of 36.8 GiB, and 91% in the first part of the run.

## llama.cpp master

| Measure | R-q4 on 8642541 | R-q4 on 792fcf4e7 |
| --- | --- | --- |
| Passed first attempt | 27/36 | 25/36 |
| Passed after retry | 29/36 | 31/36 |
| Decode tok/s | 97.6 | 110.2 |
| Prompt tok/s | 2,145 | 2,355 |
| Arm total | 72 min | 60 min |
| Median VRAM | 5,259 MiB | 4,955 MiB |

Final passes differ by 1 against 3 (p = 0.625). Speed improved on both sides. The two runs are hours apart, so the VRAM difference may come from what the Windows desktop held at the time: the samples cover the whole GPU, and server logs give no breakdown. Even so, the speed gain is large enough to adopt master.

## Corrections to earlier reports

- The time saving of 25% to 31% in the calibrated comparison does not hold. `CMP-base` was a slow run of the control.
- The peak of 5,273 MiB in `CMP-base` came from three units in the first repetition. The usual peak is about 4,635 MiB.
- Differences of a few hundred MiB between arms cannot be assigned to a flag, for the reason given above. Only the MTP difference is large and consistent.
- `py_range` got no replacement task. Its failures are recorded in the [corpus notes](../../../../corpus/README.md).

## Tasks that separate arms

Six of the 18 tasks gave the same result in all five arms and in `CMP-rec`: `cont_path`, `tests_list` and `tests_query` always passed, and `js_decimal`, `js_units` and `recover_httpdate` never did. More repetitions on the other 12 would add more information than more arms on the same 54 units.

## Sampling and the NVIDIA driver pool

Polling `nvidia-smi` inside WSL left about 23 live allocations per call in the Windows NVRM pool, and `wsl --shutdown` did not free them; a reboot did. In this campaign that grew the pool by 0.45 MiB/min, matching one call per second. On Windows, 452 calls left none.

The benchmark now reads the GPU through one NVML session per process, in `benchmark/nvml_session.py`. Across the four-hour NVML run the pool stayed flat, from 73 to 71 MiB. Windows free memory now comes from one PowerShell per sampler instead of one per second.

## Interruptions

Some units of `CMP-ckpt` ran with extra Windows monitors, and some with Bitdefender off, while a PC freeze was diagnosed. The arm stopped twice at unit boundaries and resumed. Partial units were set aside and run again.

`CMP-ram4g` first ran on `nvidia-smi` sampling and stopped at 21 units. Those units are kept outside this count. They scored 13 passes, the same as the same 21 units in the final run. The NVML run then repeated all 54 in a new directory, because the code change invalidates the manifest. An early start with a Windows memory helper that died was discarded after one unit.

The NVML run stopped once more at `tests_list-r1`, when the grader timed out twice in the sandbox on a harmless test file. The unit was set aside and run again, and it passed. Counting it as a failure gives 31/54 and p = 0.549 against `CMP-base`, so the conclusion stands.

## Limits

- Arms ran one after the other, some over a day apart, so anything that changed on the PC falls on one arm.
- `CMP-ram4g` differs from the control in three ways, so a difference could not be assigned to the cache alone. None appeared.
- 54 units cannot detect a difference of a few points, and repetitions of a task are not independent.
- The profile with master, MTP and no checkpoints was not run as such. Its parts were measured separately.

## Decision

Use llama.cpp master and keep MTP for speed, with no claim about pass rate. Remove context checkpoints from the recommended profile, since they showed no benefit here and cost RAM. Keep `--cache-ram 2048`.
