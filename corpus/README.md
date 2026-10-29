# Frozen offline pilot corpus

This corpus is for pilot development, not a held-out confirmation set. All
episodes for a task must begin from the same snapshot with its `bug.patch`
applied. The `reference.patch`, `bug.patch`, `oracles/`, `manifest.json`,
`validate_corpus.py` and supervisor fixture builder must never be given to a
worker. A coordinator may provide the task metadata, the relevant stub, the
visible check and the prepared host workspace. For continuation, give only
`task.json`, `verify_phase1.py` and `visible_phase1.py` at first; release
`followup.json`, `verify.py` and `visible.py` only after the first delivery.
The runner for F3 must enforce
that boundary; merely storing files separately does not enforce isolation.

Bottle 0.13.2: <https://github.com/bottlepy/bottle>, tag `0.13.2`, commit
`ab49e0c22491f8acfcb02e4a7b8c648843268233`, MIT. The SHA-256 of the
uncompressed `git archive --format=tar HEAD` is
`6cb77dbe442edec538ebc9af0b4cb3d9c22fb3b8e262d4ecfb0e064a2e28ea44`.
The production source `bottle.py` has 180,178 Unicode characters (UTF-8
decoded), or 51,479 estimated tokens at characters/3.5. This is not a model
token count, and excludes tests and documentation. The two production sources
together have 183,202 characters, about 52,343 tokens by the same estimate.

Never use the unmodified snapshot as the cached worker prefix: it contains the
reference lines. `prefixes/` contains stable versions with every original line
removed by a bug patch replaced by a marker. The manifest covers these files,
and validation regenerates and compares them. The coordinator provides the
buggy task-specific source separately. This reduces direct answer leakage,
but does not guarantee that neighboring code or upstream tests cannot reveal
the behavior. The small JavaScript host alone does not meet the large-prefix
size; its tasks need an explicitly designed context comparison in F4.

ms 2.1.3: <https://github.com/vercel/ms>, tag `2.1.3`, commit
`1c6264b795492e8fdecbc82cb8802fcfbfc08d26`, MIT. The SHA-256 of the
uncompressed `git archive --format=tar HEAD` is
`8320d0029c9cd17cb89f5f5d2509a14373d3e2efc6f4824907237f63475d882b`.
The upstream tests use Mocha and expect.js. `support/ms_original.test.cjs`
runs the original test file unchanged with `node:test` and a minimal adapter
for its three assertion forms; this is an adaptation, not Mocha execution.

The `mcp` and `tool_recovery` tasks use deterministic local stub outputs as
external evidence needed to repair Bottle, rather than claiming to exercise
an MCP transport or a real remote service. They do not measure protocol-level
discovery, call traces, idempotency or retries. The validator runs each stub
twice and checks its sample against both the buggy and corrected code.
Continuation tasks provide separate phase-one and follow-up material; a future
runner must actually sequence them.

Run from the repository root with the approved validation environment:

```sh
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python \
  corpus/validate_corpus.py --node /home/foxtrot/.nvm/versions/node/v25.5.0/bin/node
```

The validator checks the manifest, applies patches to disposable copies and
requires an assertion failure for the bug, success for the reference, visible
check and upstream tests. The authored-test private oracles additionally run
the reference suite against the correct code and two distinct mutants.
`--task ID` selects one task while retaining the complete manifest check.
`--write-manifest` is for deliberate corpus freezing, never routine checks.
