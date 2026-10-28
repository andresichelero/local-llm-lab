---
name: recover-and-checkpoint
description: Recover from actionable errors and preserve verified state across a bounded session.
---

# Recovery and continuity

Classify the observed failure before retrying: malformed arguments, stale state,
transient read failure, program/test failure, unavailable capability, or unknown.
Correct arguments after inspecting the schema. Re-read a file before retrying an
edit. Read current state after a stale-version error. Follow the task's explicit
retry sequence for a deliberate transient failure; do not generalize it to other
tools. Unknown failures require a clear blocker report, not repeated attempts.

A useful checkpoint contains: original goal; remaining acceptance criteria;
changed files; test command and observed outcome; next cursor; current versions
and idempotency keys; receipts proving completed mutations; and the next concrete
action. Keep observations distinct from hypotheses. Do not include invented
reasoning or a statement that unexecuted work is complete.

After compaction, re-read TASK.md and verify the checkpoint against current files
and tool state. Do not reapply a mutation just because its earlier messages are
absent. A larger budget is not permission to keep making the same failed call.
If the operational harness grants one recovery continuation, change the approach
using the actual error evidence; all previous attempts and time remain charged.
