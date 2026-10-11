# Local LLM lab progress checkpoint

Updated: 2026-10-11 (America/Sao_Paulo)

## Current state

- Repository: `andresichelero/local-llm-lab`; at the time this checkpoint was prepared, the checkout was clean on `main` after fast-forward to merge commit `58ba9ad81a874b94f2b14d0c2799f29c99a9c4c7`.
- PR #33 was merged at 2026-10-11 20:44 UTC after CodeQL JavaScript, Python, and aggregate checks passed.
- The PR records the OpenCode subagent probe, raw event streams, and its limitations. Its profile was corrected before merge: `autoupdate: false`, local llama.cpp model endpoint, primary task delegation restricted to two named workers, and both `bash` and `edit` denied to subagents.
- Profile JSON and permission assertions passed locally. The OpenCode profile itself was not reloaded by the runtime after this correction.
- No benchmark was started during this continuation. A process check found no running `llama-server` or `opencode` process.

## Evidence from the completed probe

- OpenCode 1.19.0 completed one delegated read-only repository inspection in 14.25 seconds.
- The unbounded coding attempt was stopped after six minutes. Bounded attempts completed in 65 seconds (1/4 tests passed) and 143 seconds (3/4 passed; the 512 MiB case failed). Neither reached independent review; the last did not delegate to a worker. These runs are incomplete and excluded from task-quality comparisons.
- Active benchmark files and model/runtime paths were on WSL ext4 backed by C:. No HDD performance test was run. The post-run archive was placed on E: and SHA-256 verified; details are in `results/reports/opencode-subagent-probe-20261011.md`.

## Machine and storage snapshot at checkpoint

- WSL Ubuntu-24.04 reports 7.8 GiB memory, 4 GiB swap, 108 GiB ext4 filesystem with 16 GiB available.
- NVIDIA query reported RTX 3070, 8192 MiB total / 7472 MiB free at observation, 37 C, 1725 MHz graphics clock, 45.49 W. These are point-in-time readings, not benchmark averages.
- The isolated OpenCode package and llama.cpp server binaries were found under `/home/foxtrot/local-llm-benchmark` on WSL ext4. The llama.cpp server is not currently on the shell PATH.
- The project checkout is on D:, while active benchmark data is on WSL ext4 backed by C:. Continue treating C: / WSL ext4 as the benchmark SSD and E: as archive-only. Do not run HDD performance tests.

## Resume next

1. Sync the latest repository checkout into the SSD-side WSL workspace without copying model weights or large generated artifacts from the repository drive.
2. Validate the corrected OpenCode profile with the installed Linux binary, using its actual configuration-check/debug interface; then start the pinned llama.cpp server from the existing SSD runtime.
3. Run one bounded, read-only delegation smoke first. If that passes, run a single controlled coding task with fixed tests, wall-time cap, and an independent reviewer stage; preserve failed/incomplete records and do not claim a quality win without the full gate.
4. Keep active model, runtime, scratch, logs, and results on WSL ext4. Archive only after runs finish and verify archive checksums on E:.
5. Continue from the existing status ledger and reports; avoid repeating completed model/harness matrices.

## Scope still open

The overall research mission is not complete. The merged probe only establishes short read-only subagent compatibility and documents failed/incomplete coding attempts. It does not establish the best multi-agent setup, routing design, compaction quality, or a general runtime/model ranking.
