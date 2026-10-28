---
name: verify-and-finish
description: Check artifacts and observed state, then report success or an honest bounded failure.
---

# Verify and finish

Review every requested artifact and acceptance criterion in TASK.md. Check public
exports and tests for code; fields, pagination completeness, receipts and trusted
state for MCP. Equivalent valid solutions are allowed unless the task explicitly
requires a recovery or ordering sequence.

Before claiming success, inspect the persisted artifact rather than relying only
on the final response or on a tool's acknowledgement. Report the artifact path,
what changed or was obtained, and the verification actually performed. Distinguish
functional correctness, tests run and operations confirmed.

If a requirement is not verified, report incomplete with that precise limitation.
Reaching a budget is a bounded execution result, not proof that no solution exists.
Never label an unexecuted test as passing, invent unavailable tools, forge a
receipt, weaken the requirement or suppress an error to make the task look done.
