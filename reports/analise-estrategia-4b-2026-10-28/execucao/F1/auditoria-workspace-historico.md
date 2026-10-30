# Historical audit of the `/workspace` path defect

**Date:** 28/10/2026
**Scope:** `development` attempts in protocols `qwen-quant-harness-optimization-final` and `qwen-quant-harness-optimization-final-oom-v2`.

## Conclusion

The version of `benchmark/qwen_workloads.py` recorded in both manifests contains the same F1 defect: `safe_path()` rejects absolute paths using `PurePosixPath(value).is_absolute()` and returns `path must stay inside /workspace`, while the prompt says paths are relative to `/workspace`. The SHA-256 of the file in the worktree specified by the manifests matches the hash recorded in both protocols.

The defect appears in `-final-oom-v2` data, but not in `development` attempts recorded for `-final`. In `-final-oom-v2`, I counted **101 emitted tool calls** with `path` starting with `/workspace`; **95 have a recorded response with the exact rejection**. The other 6 are emitted calls without a corresponding tool response and were therefore not counted as rejected.

Among `-final-oom-v2` terminal codes `model_no_progress` and `budget_exhausted`, **two 4B attempts end with the same pattern of a previously rejected `/workspace` call**: `python_fix` (`7cfd…`) and `continuation` (`85a9…`). Both are `model_no_progress`. No `budget_exhausted` attempt ends in this pattern. Other rejections occurred in attempts with other outcomes or before subsequent actions; I do not attribute those outcomes to the path solely because an error occurred.

In protocol `-final`, 9 attempts are recorded, all 9B, and no `/workspace` calls. The state lists 18 planned 4B `development` units, but no 4B attempt is recorded. Thus, the observed terminal failures in `-final` cannot be explained by this rejection based on available evidence.

## Scope and method

- I read `F1-diagnostico.md`, `tentativas.csv`, `resultados-completos.json`, and relevant manifests/states inside the raw archive. I listed the archive's **8.170 members** without extracting it in full. For attempts, I selectively read `client/metrics.json`, `client/request-*.json`, `client/response-*.json`, `messages.json`, `compaction-*.json`, and, when available, `episode-progress.json`.
- The attempt key is `(protocolo, unit_id, tentativa)`. The CSV records 9 `-final` attempts and 36 `-final-oom-v2` attempts (18 per model). The `-final` state shows 42 scheduled `development` units: 18 4B and 24 9B; only 9 9B attempts were executed/recorded.
- I counted calls once per `tool_call` ID emitted in `client/response-####.json`. I matched results by the same ID in tool messages in `client/request-*.json` and `messages.json`; this avoids recounting history repeated in later requests. Argument content counts only when the `path` field literally begins with `/workspace`.
- A call counts as **rejected** only if the corresponding response contains `path must stay inside /workspace`. The phase is **pre-compaction** if there is no previous `kind=compaction` generation in the `client/metrics.json` sequence; otherwise it is **post-compaction**. The `compaction-N.json` files corroborate these boundaries.
- For terminal outcome I used `resultado_json.failure` when populated, then `resultado_json.status`; for attempts without `resultado_json`, I used `estado_registrado`. `model_failure` without cause fields was retained without further attribution.
- For “rejection as last pattern,” I required the last model response to emit the same tool/path pair of a previously rejected `/workspace` call again, and the terminal record to be `model_no_progress` or `budget_exhausted`. The two corresponding final calls have no recorded tool response; they count as emitted calls, not confirmed rejections.

## Totals by protocol, model, and terminal cause

`Calls` and `rejections` are summed across all phases. The next table gives pre/post details.

| Protocol | Model | Recorded terminal outcome | Attempts | Calls `/workspace` | Rejected | Rejection as last pattern |
|---|---|---|---:|---:|---:|---:|
| `-final` | 4B | no attempt recorded (18 scheduled units) | 0 | 0 | 0 | — |
| `-final` | 9B | `model_no_progress` | 6 | 0 | 0 | 0 |
| `-final` | 9B | `complete` | 2 | 0 | 0 | 0 |
| `-final` | 9B | interrupted, no terminal result | 1 | 0 | 0 | 0 |
| `-final-oom-v2` | 4B | `model_no_progress`¹ | 8 | 36 | 30 | 2 |
| `-final-oom-v2` | 4B | `budget_exhausted` | 3 | 20 | 20 | 0 |
| `-final-oom-v2` | 4B | `model_failure`, cause not populated | 3 | 7 | 7 | 0 |
| `-final-oom-v2` | 4B | `complete` | 4 | 7 | 7 | 0 |
| `-final-oom-v2` | 9B | `model_no_progress` | 9 | 9 | 9 | 0 |
| `-final-oom-v2` | 9B | `budget_exhausted` | 1 | 11 | 11 | 0 |
| `-final-oom-v2` | 9B | `model_failure`, cause not populated | 2 | 0 | 0 | 0 |
| `-final-oom-v2` | 9B | `complete` | 4 | 11 | 11 | 0 |
| `-final-oom-v2` | 9B | interrupted, no terminal result | 2 | 0 | 0 | 0 |

¹ One of the 8 4B rows has `failure=model_no_progress`, but its `error` field says `compaction did not produce a usable text checkpoint`; it has no `/workspace` calls. The other 7 have `repeated tool result without observable progress`.

| Protocol | Model | Calls pre/post-compaction | Rejections pre/post-compaction | Total calls | Total rejected |
|---|---|---:|---:|---:|---:|
| `-final` | 9B | 0 / 0 | 0 / 0 | 0 | 0 |
| `-final-oom-v2` | 4B | 11 / 59 | 11 / 53 | 70 | 64 |
| `-final-oom-v2` | 9B | 10 / 21 | 10 / 21 | 31 | 31 |
| **`-final-oom-v2` total** | **4B + 9B** | **21 / 80** | **21 / 74** | **101** | **95** |

## Individual attempts: `qwen-quant-harness-optimization-final`

There are no 4B attempts in this protocol. All 9 attempts below are 9B. In count columns, the order is pre/post-compaction.

| Unit ID / attempt | Task | Calls `/workspace` | Rejections | Recorded terminal outcome | Rejection as last pattern |
|---|---|---:|---:|---|---|
| `c663a3393ce3d28e8928f987f56373ee427af8a9ca987c952ae2f5e4a424cf73` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `4e2d2b4aadd48be2a438522974b0374a95df4ee7a7eb024a3aab62d96386f9ee` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `dc6ef04b3fd4beea5566b912c9e4f676b41ee29a50f280591e0fbc82ce02eedf` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `3cfb60c19dc994db96869062037cfc29ef84a8fd04423f2f0246736122fbfb43` / 1 | `mcp` | 0 / 0 | 0 / 0 | `complete` | no |
| `5d58644b6eab84b55e884f94ac7fe6b15c52118e8f34a0a0b5d25831bb69fbbb` / 1 | `continuation` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `4244a87c83398469e4d2e53d8bc249410e77f9f20aedacb56aeeb040539d15c2` / 1 | `tool_recovery` | 0 / 0 | 0 / 0 | `complete` | no |
| `c7a9d4f0b4c0687352bf09a5856a4e90b4b26372fefa25a5da54993a7f449f97` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `2e1e6a92fc11b12e4ec11e722b569219d184c14425610c18b7c87a4618fd8876` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `80da3df59c59a32c3d5ecf60fa93719ff76476d0b3d3c7bc4543284ede874254` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | interrupted, no result | — |

## Individual attempts: `qwen-quant-harness-optimization-final-oom-v2`, 4B

| Unit ID / attempt | Task | Calls `/workspace` | Rejections | Recorded terminal outcome | Rejection as last pattern |
|---|---|---:|---:|---|---|
| `29184ffa562f5ea75cfea53560312fb4dc23cb721c151ac90bedb480605bf084` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress`; compaction checkpoint error | no |
| `885ca74cc7eda3ee2f2779af4f42dcb6dd3e65e490b0b1f7f3ac4650dd861585` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `c5dd4134fab6d48ad4fb98191c2e325023ea3e952a9be672d0f337f96b94b571` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `budget_exhausted` | no |
| `130466244e2bc3f6b8c033a2e2aa8b0280ad2d36bb4a3a297eb791c6b02bf842` / 1 | `mcp` | 2 / 0 | 2 / 0 | `model_failure`, cause not populated | no |
| `85a9d834d9ecb05bcadf685a53978dd0e28cd19b40868ea8e8b36f8120ff4c83` / 1 | `continuation` | 0 / 10 | 0 / 9 | `model_no_progress` | yes |
| `eac502b7de41c9b33f769836191dbc6f0746a27e9cafc0a0486faf49e16fc53e` / 1 | `tool_recovery` | 3 / 0 | 3 / 0 | `complete` | no |
| `7cfda498534e8a3c5200b89e6db767e9a5ae816fa71f70f1ed0bc76a0924c428` / 1 | `python_fix` | 0 / 26 | 0 / 21 | `model_no_progress` | yes |
| `9494fb7d8edfb8e0e506d32b76cd48582447ae8f33c4946c244eb0e730c7a1f9` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `19b02efa1097fd9fec45a451462b98a007613259baddf1fe532da6da9959aba0` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `budget_exhausted` | no |
| `7389d876f3f7318dd1fb2c649ad427b2a22334124dd373ce68fad8698e31d77c` / 1 | `mcp` | 2 / 0 | 2 / 0 | `model_failure`, cause not populated | no |
| `1a0eb823001b7d26fafd7af9de0c0c41b9ec7a173736c1d1fb35309fde38ce1b` / 1 | `continuation` | 0 / 3 | 0 / 3 | `model_failure`, cause not populated | no |
| `8135896cf8c8bfc99778ee1a4982b226f577732f52ef8d4529796d863417c9ab` / 1 | `tool_recovery` | 2 / 0 | 2 / 0 | `complete` | no |
| `a939d858d3931aba4e2472ede2bab6df16065b676a20940dc510cd8b73b5a9e6` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `c2d13ac5732eab19ec26d53bcae952c699deb4a388cf02fac4565c5223bbfc62` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `7c63b9de66f87cb3ad31a87c2dc97de37939ad19087f77e6c8f21bcc84137cc7` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `af9613baf31d6c3d3d244f5c7016b096b4d536bd6b49876d610acc14e530ae30` / 1 | `mcp` | 2 / 0 | 2 / 0 | `complete` | no |
| `81e49412aa3dff3abc8adfef4fce2dc51f5035e5a981f68e510bce303a124765` / 1 | `continuation` | 0 / 20 | 0 / 20 | `budget_exhausted` | no |
| `2345ee5d8817c2feb0c6d2a26bde25b0a25a8addbe722e726d2ce5d4b87fb858` / 1 | `tool_recovery` | 0 / 0 | 0 / 0 | `complete` | no |

## Individual attempts: `qwen-quant-harness-optimization-final-oom-v2`, 9B

| Unit ID / attempt | Task | Calls `/workspace` | Rejections | Recorded terminal outcome | Rejection as last pattern |
|---|---|---:|---:|---|---|
| `80da3df59c59a32c3d5ecf60fa93719ff76476d0b3d3c7bc4543284ede874254` / 2 | `authored_tests` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `7db0d2b9aa374fb52bae12ab6efba6a0953976c49d43019cfc85d0afdae66f1c` / 1 | `mcp` | 1 / 0 | 1 / 0 | `complete` | no |
| `0b6c4bc61faac6a765960cd037b4c359004a4c90ea975f6a9cec4ac3cf9eabca` / 1 | `continuation` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `4f5326820ccafd4fa286be27e47d62d5318536b90ad8f9745756472a59d32148` / 1 | `tool_recovery` | 1 / 0 | 1 / 0 | `complete` | no |
| `3e2ee894875dac97786a887b1c34305dcb7b6ecb440c450845b27b7a90bb929a` / 1 | `python_fix` | — | — | interrupted, no result; raw evidence missing | n/a |
| `3e2ee894875dac97786a887b1c34305dcb7b6ecb440c450845b27b7a90bb929a` / 2 | `python_fix` | 0 / 0 | 0 / 0 | interrupted, no result | — |
| `3e2ee894875dac97786a887b1c34305dcb7b6ecb440c450845b27b7a90bb929a` / 3 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `5464f2b3cb23a7e7d0897212b339e216d929888f530b6b746da565a484f0629b` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `06e404c7c2a9c94f67da7cbed7cb7ad38b3376873dc437c6afde0783d26215a8` / 1 | `authored_tests` | 0 / 9 | 0 / 9 | `model_no_progress` | no |
| `758884e65dc09e4125bc257d24f20144bb7ed66ad536e2b2bfe79e03c5e9bda9` / 1 | `mcp` | 0 / 0 | 0 / 0 | `model_failure`, cause not populated | no |
| `365b0c6adcbe525a536a739217ce34260e50700992ea12b0a000cac8b5ee907e` / 1 | `continuation` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `04d4318cb8360a9356da064db269e273f7f7bd83baabdacd9c4ce58dc614cfa6` / 1 | `tool_recovery` | 5 / 1 | 5 / 1 | `complete` | no |
| `10fe7b603175ceeab8d73b76f7cce6ef6ce01f75952c2461fc64afe2d236c0c6` / 1 | `python_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `440e84728ad0ec6efc120978889acf485d69159e767260c30ceba8c61a320294` / 1 | `javascript_fix` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `82638b8722c1fc05c09e98485acc2554de229963f84bb2a8b935442daafe54f1` / 1 | `authored_tests` | 0 / 0 | 0 / 0 | `model_no_progress` | no |
| `144383498106e0b6c33acde4772c704990188682ecb369c1701c2a2ac111bb5f` / 1 | `mcp` | 0 / 0 | 0 / 0 | `model_failure`, cause not populated | no |
| `c563067a93274300f54490772ef6f022133358aa003f6367310938752e015664` / 1 | `continuation` | 0 / 11 | 0 / 11 | `budget_exhausted` | no |
| `00161c8c1b72d1ba3af4af5167ee988c01887f8d51a39659ca02e93899af7c12` / 1 | `tool_recovery` | 3 / 0 | 3 / 0 | `complete` | no |

## Verification of code identified in the manifest

| Protocol | SHA-256 of `benchmark/qwen_workloads.py` in manifest | SHA-256 of current file in specified worktree | Match |
|---|---|---|---|
| `qwen-quant-harness-optimization-final` | `f74a2c1833aa77cfa2ceb76ff46b7aad86750aadb01c65a72824b1be57139087` | `f74a2c1833aa77cfa2ceb76ff46b7aad86750aadb01c65a72824b1be57139087` | yes |
| `qwen-quant-harness-optimization-final-oom-v2` | `f74a2c1833aa77cfa2ceb76ff46b7aad86750aadb01c65a72824b1be57139087` | `f74a2c1833aa77cfa2ceb76ff46b7aad86750aadb01c65a72824b1be57139087` | yes |

Both manifests name `<workspace-root>/.worktrees/practical-agent-v2/benchmark/qwen_workloads.py`. In the file with that hash, `safe_path()` (lines 37–40) tests `path.is_absolute()` and raises `ValueError("path must stay inside /workspace")`; the prompt text (“All paths are relative to /workspace”) appears on line 310. Thus, the same incompatible implementation was recorded for both protocols.

## Limitations and discrepancies

- The `-final-oom-v2` 9B `python_fix` attempt for unit `3e2ee894…`, attempt 1, is recorded as interrupted, but there is no corresponding raw directory in the archive. Its calls could not be counted, nor its rejections or phase verified. Attempt 2 of the same unit is also interrupted, but has raw evidence and contains no `/workspace` calls.
- Three attempts have exported state `interrupted` and no terminal result: `-final` 9B `authored_tests`/1 and `-final-oom-v2` 9B `python_fix`/1 and /2. The archived `state.json` snapshot for `-final` still shows the first unit `80da…` as `running`; the closing CSV/export records it as `interrupted`.
- In 12 completed attempts, `episode-progress.json.tools` is between 1 and 5 below the number of calls emitted in client responses. This is consistent with pending tool calls at the end of the episode. Therefore, an emitted call without a response was counted as a call but not a confirmed rejection.
- Terminal `model_failure` causes in five attempts do not have internal `failure`/`error` fields populated; the aggregate result does not allow attribution to the path. Outcomes recorded as `complete` can also coexist with recovered rejections.
- The audit covers only `development` attempts from the two specified protocols; it does not attribute causality to other campaign stages.

## Sources consulted

- `reports/analise-estrategia-4b-2026-10-28/execucao/F1/F1-diagnostico.md`
- `reports/outputs/qwen-final-encerrado/tentativas.csv`
- `reports/outputs/qwen-final-encerrado/resultados-completos.json`
- `reports/outputs/qwen-final-encerrado/evidencias-brutas.tar.gz` — manifests, `state.json`/`summary.json` snapshots, and selective evidence under `qwen-quant-harness-optimization-final/units/` and `qwen-quant-harness-optimization-final-oom-v2/units/`
- `.worktrees/practical-agent-v2/benchmark/qwen_workloads.py`

No workload was run, no GPU was used, and no code or commit was changed.
