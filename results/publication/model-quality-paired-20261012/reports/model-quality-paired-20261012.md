# Paired OpenCode quality series — 2026-10-12

## Outcome

The released r1d series stopped at the first compatibility gate. Qwen3.5 4B loaded at the required context and passed the effective-profile checks. The model first ran `python -c`, which returned command-not-found, then recovered with `python3 -c` and got `42`. Its required Edit call errored because the model supplied the literal `oldString` `TASK`, which was absent from the fixture file. The task prompt asked to replace the whole file; the model attempted Edit before reading its contents. The later Read event captured the original fixture text, and a subsequent Write produced the requested bytes, but neither changes the failed Edit-tool gate. This is an observed model-selected edit-string/tool-use mismatch against a present fixture, not evidence that the runner omitted the file. The runner recorded the result and stopped the series without a runner-level retry.

This is a failure to complete the compatibility task as specified. It does not establish general model incompatibility. Round 0 remains recorded as failed and is not changed by the separate single-agent release.

## Frozen setup and provenance

- Protocol: `model-quality-paired-20261012-r1d`; source commit `da99669c29d334bd12de6544b6e77dda6bb09794`.
- Runner SHA-256: `8bc4134cb8d089398f4a35e4c6fa7576b22a700243a06f703cc6afb2442eb547`; tests SHA-256: `daa6f64b71fba05aaa99ae5c14ea732c2969770ea9fb8795123b64fd57b33574`.
- OpenCode `1.19.0`; llama.cpp reports commit `d81235049`. Model file hashes matched the frozen Qwen3.5 4B and 9B hashes before execution.
- Configuration remained the released single-agent profile: localhost, 16,384 context, Q4_0 KV cache, prompt cache off, reasoning off, 20 steps, Task denied, Bash and Edit explicitly allowed, auto-update disabled. The planned matrix was three tasks with three measured repeats per model, after one calibration and one excluded warm-up per model.

## Attempt record and denominators

| Attempt | Result | Classification |
| --- | --- | --- |
| r1b (`c4f7663`) | Stopped before model load: runtime check expected a 10-character revision prefix while the pinned runtime reported `d81235049`. | Runner preflight failure; no inference. |
| r1c (`d2873e5`) | 4B compatibility run reached post-edit file verification, then raised `NameError: name 'fixture' is not defined`. | Executor failure; gate result invalid; no matrix. |
| r1d (`da99669`) | 4B compatibility gate failed: Bash passed; Edit returned an error; subsequent Write made the expected bytes, but no completed Edit event targeted `TASK.md`. | Compatibility task/tool-use failure; no runner-level retry; no general incompatibility claim. |

For r1d, the denominator is one attempted compatibility gate, zero calibrations, zero warm-ups, and **0 of 18 measured rows attempted**. The 9B compatibility gate was not reached. There are no quality medians or ranges to report, and no 4B-versus-9B comparison can be made.

The 4B compatibility resource sample recorded 22 samples, 77.0% average and 98.0% peak GPU utilization, 4,529 MiB peak VRAM, 1,992 MiB peak RAM, and zero swap use. These are compatibility-run resource observations, not measured-task performance results. After cleanup, the server process was absent, port 8080 was free, and GPU usage returned to about 1% with 1,245 MiB used.

## Evidence

- The publication subset is described by `results/publication/model-quality-paired-20261012/SCOPE.txt`; its 64 selected files are covered by `results/publication/model-quality-paired-20261012/PUBLICATION.sha256`. This is the published subset, separate from the complete raw exports.
- The selected subset omits OpenCode home/database/WAL/SHM/lock state, snapshot cache, temporary shared-object files, and workspace `.git` metadata. The complete original exports are preserved in the E archives and retain that runtime state. Their original manifests verify 9 entries for r1b, 87 for r1c, and 90 for r1d. The copied original manifests describe those complete exports; `PUBLICATION.sha256` covers only the selected subset.
- The updated E archive is `E:\LocalLLMLabArchive\2026-10-12\model-quality-paired-20261012-final\model-quality-paired-evidence-20261012-v3.zip`. Its SHA-256 is recorded in the adjacent `.sha256` sidecar; `EVIDENCE-SHA256SUMS.txt` lists the included complete raw archives and report/audit hashes.
- The complete r1d raw attempt remains at `results/raw/model-quality-paired-20261012-r1d-20261012T055905Z/`; its 90-entry `MANIFEST.sha256` verifies. The preflight files were captured after the clean source checkout and copied once into this raw export, where they are covered by that manifest; they are not extra files from the source snapshot. The execution audit is `results/system-audit/model-quality-paired-r1d-execution.json`.
- Earlier r1b and r1c raw evidence remains in `results/raw/model-quality-paired-20261012-r1b-*` and `r1c-*`; their full archives and manifests are included with the E evidence bundle.