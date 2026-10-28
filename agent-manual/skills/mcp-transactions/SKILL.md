---
name: mcp-transactions
description: Use advertised MCP schemas, follow pagination and perform verified idempotent transactions.
metadata:
  compatibility: An already configured local MCP server exposed by the harness.
---

# MCP transactions

Inspect the advertised schema and call the actual tool name; do not search shell
configuration or install a client. Treat identifiers and cursors as opaque values.
Use the tool's page-size bounds. For example, if a response says next_cursor is
"page-b", the next call must pass cursor="page-b". Continue until null; do not
reuse the first-page arguments, guess cursor arithmetic or invent unseen data.

Read isError and the error payload before using data. A successful request can
still return an application-level error. Conversely, a retryable stale-version
response may be part of the task's explicitly described recovery sequence.

For mutation, read the current version, retain the specified idempotency key and
verify the returned receipt. If success is uncertain, reconcile state or replay
only an explicitly idempotent request with the same key. Never invent a new key
to bypass a stale or transient failure. Do not apply unrelated changes.

Construct reports with exactly the schema's fields. JSON Schema keywords such as
additionalProperties describe the schema; they are not fields to put in a report.
Persist the artifact requested by TASK.md, and submit it only when submission is
required. Verify that the persisted object, submitted object and observed state
agree. Do not assume stored=true establishes that the data are correct.
