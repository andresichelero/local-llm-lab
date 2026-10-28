# Qwen quantization and harness optimization — authorized implementation

Goal: select two distinct measured configurations for each Qwen3.5 4B/9B,
prioritizing speed and useful context after a correctness floor, then compare
all eleven historical/current harness candidates, optimize and confirm.

User decisions: four finalists total; GGUF plus compatible alternative engines;
all relevant dependency/model downloads authorized; at most two Luna Extra
agents, only small independent tasks. No concurrent GPU measurements.

## Frozen requirements
- Preserve old installations, weights, evidence and campaign protocols.
- New isolated environments; no driver/OS/clocks/WSL configuration changes.
- Catalog original-model quantizations, pinned revisions and file hashes.
- At least 10/12 qualification checks, then three performance repetitions at
  16/32/64/128K where safe, and six development tasks per eligible artifact.
- Two distinct finalists per model: fastest among best completion; largest
  verified useful context within one task of best, with explicit shortfall.
- Compare six tasks per harness/configuration; top three harnesses deepen to
  twelve tasks/two seeds/two models, best quantization for each pairing.
- Eight parameter profiles maximum, four plugin arms, six fresh confirmation
  tasks/two seeds. No grading or project tests concurrently with inference.
- 120 principal generations, eight compactations, one title, twenty metadata,
  240 tool calls, thirty minutes per episode; all retries counted.
- Durable single-owner queue; preserve interrupted attempts; no retry of a
  completed model failure. Per-unit infrastructure restart limit two.
- D: disposable download cache <=60GiB; ext4 >=8GiB free. Preserve originals.

## Implementation sequence
1. Reconcile interrupted refresh, qualify offline CLIs and security findings.
2. Discover immutable artifact inventory and resumable verified download cache.
3. Qualify isolated llama.cpp/ExLlamaV3/TabbyAPI and oracle foundation.
4. Implement/test immutable queue, measurement workers and evidence selection.
5. Freeze measurement sources/configurations; launch the durable supervisor.
6. Implement the downstream harness/ablation stages before admitting them;
   pending stages are not claimed ready from an installation or model smoke.
7. Produce manifest, failures, selection and final confirmation reports.

No arbitrary fallback model/cloud endpoint. No benchmark-derived answers in
helpers. Distinguish engine+quantization comparisons from within-engine effects.

## Queued follow-up: bounded reasoning effort (not part of recovery-r2)

Status: planned only; do not change or extend the active recovery-r2 manifest.
Run this only in a distinct protocol and output after recovery-r2 is stopped or
complete. The question is whether a Qwen profile can remain responsive during
interactive coding while preserving task correctness.

Use one fixed, selected Qwen 9B artifact and the same engine, harness, task set,
seeds, context, sampling parameters, output ceiling, cache policy, and thread
count in all three arms. Keep `--threads 6` fixed here; thread tuning is a
separate experiment. Proposed profiles:

| Profile | llama.cpp controls |
|---|---|
| Off | `--reasoning off`, `enable_thinking=false`, no reasoning budget |
| Low | `--reasoning on`, `--reasoning-effort low`, `--reasoning-budget 1024` |
| Medium | `--reasoning on`, `--reasoning-effort medium`, `--reasoning-budget 4096` |

The installed llama-server help documents `--reasoning on/off/auto`, effort
levels including `low` and `medium`, a finite reasoning-token budget, and
`--threads`/`--threads-batch`. Effort is passed to the chat template, so qualify
that the pinned Qwen3.5 template honors it before treating low/medium as native
effort levels. If it does not, report the arms honestly as budget-defined
profiles; do not claim the effort selector changed model behavior. Record
reasoning and final-answer token counts separately, budget exhaustion, answer
validity, task correctness, completion time, GPU utilization/temperature, and
CPU/RAM. A response that spends its budget reasoning but omits the answer is a
failed task, not a successful low-latency result.

Start with a six-task, one-seed qualification across all three profiles. Only if
the profile controls are verified and the pilot produces valid final answers,
expand to the same twelve tasks and two seeds per profile. Counterbalance arm
order and run one server/model at a time. The recovery results remain untouched;
the new protocol must identify its artifact, effective flags, and output path.
