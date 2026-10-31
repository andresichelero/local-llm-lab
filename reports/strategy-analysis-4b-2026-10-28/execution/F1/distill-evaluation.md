# Evaluation of Qwen3.8-4B-Distill

This campaign tested `empero-ai/Qwen3.8-4B-Distill`, a full fine-tune of Qwen3.5-4B made by distillation, on the same 18 calibrated tasks as the [factor separation](factor-separation.md). It used the publisher's Q4_K_M GGUF, 2,783,446,304 bytes, with the checksum matched against the publisher's list.

`CMP-distill` ran 54 units with the control settings: KV q4_0, 64K, prompt cache, `--cache-ram 2048`, thinking cascade. `CMP-distill-mtp` added MTP for one repetition, 18 units, to check the draft head.

- Config: `benchmark/configs/qwen-4b-opencode-distill.json`.
- Aggregate: [distill-v1-summary.txt](../../../../results/3070-benchmark/distill-v1-summary.txt).

## Result

The model did worse than Qwen3.5-4B on these tasks, and it should not replace it.

| Measure | CMP-base | CMP-base2 | CMP-distill |
| --- | --- | --- | --- |
| Passed first attempt | 21/54 | 27/54 | 14/54 |
| Passed after retry | 34/54 | 31/54 | 22/54 |
| Retries | 20 | 12 | 21 |
| Rescued by retry | 13 | 4 | 8 |
| Decode tok/s | 72.7 | 74.8 | 71.3 |
| Prompt tok/s | 2,523 | 2,511 | 2,705 |
| Median unit | 125 s | 89 s | 106 s |
| Median VRAM | 4,606 MiB | 4,619 MiB | 4,329 MiB |

McNemar exact on final passes:

| Pair | Control only | Distill only | p |
| --- | --- | --- | --- |
| `CMP-base`, `CMP-distill` | 12 | 0 | < 0.001 |
| `CMP-base2`, `CMP-distill` | 11 | 2 | 0.022 |

The gap exceeds the noise of 9 changed outcomes seen between the two controls. The losses concentrate in `cont_plugins`, `py_query` and `recover_date`, where the model scored 0 of 9 against 8 of 9 and 7 of 9 for the controls. Its model card warns of this: the training traces emphasize math, reasoning and instruction following, not code.

## MTP head

The GGUF holds the MTP block, `blk.32`, with 441 tensors like the base file. The head works: 89.8% of drafted tokens were accepted (195,800 of 218,117), against 90.6% for Qwen3.5-4B, and decode reached 106.9 tok/s. So speed is not the problem. `CMP-distill-mtp` passed 8 of 18 final, in line with the arm without MTP.

## Limits

- The Distill arms ran after the controls, not interleaved.
- The training mix and the card's numbers are self-reported. Only the 18 tasks here were measured.
- Temperature 0 on the first attempt is outside the card's recommended sampling of 0.6, as it is for the control. The control comparison stays fair, but the model was not tested at its own recommended setting.

## Decision

Keep Qwen3.5-4B. Remove Distill from the list of candidates.
