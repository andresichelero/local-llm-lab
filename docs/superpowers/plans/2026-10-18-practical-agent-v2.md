# Practical agent selection v2 — implementation contract

Approved design: eight tasks, three clean attempts for each of five local models;
then at most 24 tuning and 12 unseen confirmation episodes. Main selection favors
basic through medium work; an alternative must demonstrate better difficult work.
No new dependencies, weights, training, or academic experiments. Preserve v1.

## Tasks and limits

|ID|Difficulty|Language|Seconds|Model calls|Work|
|--|--|--|--:|--:|--|
|B1|basic|python|180|20|Orders report bugfix, duplicate IDs, refunds, preservation|
|B2|basic|javascript|180|20|JSONL conversion, Unicode, order, validation|
|C1|everyday|python|300|30|Pagination, input validation, immutability|
|C2|everyday|mcp|300|30|Real discovery, pagination, verified report|
|M1|medium|javascript|480|45|Multi-file configuration regression; missing vs false/0/empty|
|M2|medium|mcp|480|45|Stale version, transient error, exactly-once effect|
|D1|hard|python|720|60|JSON then CSV requirement in same session, compatibility|
|D2|hard|javascript|720|60|Multi-file reconciliation, paginated MCP, idempotent changes|

Holdouts H1 (Python cache, controlled clock and expiration) and H2 (different MCP
reconciliation) use 720 seconds and 60 calls. Two distinct reference solutions and
plausible rejected mutants per task. Independent graders are never agent-visible.
Agent-written tests are evaluated separately; coding autonomy requires additional
passing tests. Functional correctness and autonomous completion remain distinct.

## Baseline

Context 16384; max output 4096; temperature .2; top_p .95; repetition seeds
101/202/303. KV q4_0, flash attention, one slot/model, reasoning/speculation off,
prompt cache off. OpenCode input limit must be explicit, with compaction/pruning
and 6144 reserved tokens. Tool output max 6000 bytes/200 lines. Both phases share
one deadline; first phase gets at most 45 percent. Every auxiliary model call
counts. Update once before campaign; resume freezes runtime versions.

## Scheduling and result contract

120 unique baseline episodes, deterministic rotation in three passes, no early
quality elimination. Every record key includes protocol/model/profile/task/repeat.
Fresh conversation, workspace and MCP state. Atomic persistence and resumability.
Statuses running/interrupted/blocked/failed/complete must reflect actual exit.
Primary ranking: core completed count, core tasks 3/3, core elapsed INCLUDING
failed attempts, VRAM. Incomplete coverage is never eligible. Hard leader is the
second finalist; if identical to primary use second core candidate.

Tuning: two finalists, D1/D2, three repeats, cache-on first; then context 32768
on the winning cache profile. Compaction reserves 6144 at both context sizes.
Select on completions, elapsed, memory. Incompatible memory is recorded, no
silent reductions. Holdouts: two tasks x two finalists x three repeats using
chosen profiles. Keep phases separate; disagreement produces inconclusive advice.

## Shared implementation interfaces

`practical_tasks_v2`: TASKS (8 ids), HOLDOUTS (H1/H2), TASK_SPECS mapping with
language/difficulty/seconds/max_requests/phases; seed_task(task, workspace) -> str
for first prompt; followup_prompt(task) -> str; checks_source(task, phase=1) -> str;
reference_files(task, variant=0, phase=1) -> dict; wrong_files(task) -> list[dict].
JavaScript acceptance uses Node built-in test runner. Python uses unittest.
MCP workflow checks operate on supervisor-owned captured call evidence and state.

`practical_runtime_v2`: run_episode(model, task, profile, repetition, output,
models, *, lab=LAB) -> dict. Profiles carry id/context_tokens/cache_prompt;
derive generation seed from repetition 1..3. Export row identity, correct,
autonomous, failure, seconds, tool_errors, resource peaks, artifact identity.
It owns compatibility and server lifecycle for one episode, cleans up in finally,
and never modifies old results. `validate_environment` performs non-inference
runtime checks; `probe_profile` performs one short real MCP/tool compatibility check.

`practical_campaign_v2`: manifest, schedule, rank, stage orchestration and CLI;
invoke runtime adapter only with --execute. CLI supports --output, --execute,
--validate-only; default without --execute produces a plan, never inference.

## Failures and acceptance

Separate wrong_result/workflow/timeout/call_limit/context_exhausted/configuration/
infrastructure. Not every HTTP400 is infrastructure. Preserve raw evidence and
derived regrades. Invalid agent exports are workflow failures. Bounded infrastructure
retry: one retry per episode; a second failure blocks campaign with saved state.
Interrupted episodes retain evidence and resume pending work. No hidden retry for
quality failures. Initial compatibility failures block that profile, not model IQ.

Meaningful unit tests for schedule/ranking/resume/classification/context/deadlines;
all task references/mutants; WSL integration with real Node/CPython/OpenCode/MCP and
fake model API, then Ruff and relevant existing regressions. No TypeScript claim.
Before actual GPU use: independent review, successful integration, daily update,
capacity and ownership preflight. Full campaign is authorized by user instruction.

## Execution ledger

- 2026-10-18: isolated feature worktree created from HEAD; 43 existing changed
  source/documentation files copied without modifying original checkout.
- Ruling: native worktree creation cannot resolve the parent non-repository cwd;
  used git worktree fallback. Native attachment also rejects unmanaged worktrees.
- Ruling: implement v2 in new modules so archived v1 grader/source stays usable.
- Ruling: use Python and JavaScript only: Node 22.23.3 is available, no TypeScript
  compiler found; matches user preference to use installed dependencies only.
