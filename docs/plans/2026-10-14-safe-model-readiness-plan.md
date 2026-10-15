# Safe model testing readiness implementation plan

**Goal:** permit model testing only through an observed, isolated, validated path.
**Spec:** [design](2026-10-14-safe-model-readiness-design.md).
**Execution:** controller orchestrates; Luna xhigh workers implement and validate independent ownership areas. Existing Python/WSL tooling only.

## 1. Restricted interpreter

Files: `benchmark/restricted_python.py`, `tests/test_restricted_python.py`.
API: `load_modules(sources: dict[str, str], *, step_limit=100000, max_collection=10000, max_depth=128) -> dict[str, ModuleType]`; source keys are dotted `src.*` module names. Errors: `UnsupportedSyntaxError`, `ExecutionLimitError`. Interpreted functions are callable by trusted tests and maintain shared alias identity. Native trusted callbacks passed as arguments are explicit call capabilities, not arbitrary attribute-reachable callables.

- [x] Capture red cases for native unittest patch/import, reflective attributes and host-call escapes.
- [x] Implement the bounded AST interpreter and genuine container/callback/exception/import-binding semantics.
- [x] Run six known-reference sources and alternatives; reject unsupported syntax explicitly and bound adversarial allocation/loops.
- [x] Commit only owned module/tests after focused checks.

## 2. Agent OS isolation and broker

Files: `benchmark/linux_sandbox.py`, `benchmark/sandbox_bootstrap.py`, `benchmark/model_broker.py`, relevant new tests. Worker proposes precise API before integration.

- [x] Build rootless namespace/chroot with explicit mounts, capability drop, private network and bounded resources.
- [x] Implement fixed-target broker and namespace-local transport without broad host-network access.
- [x] Demonstrate file/oracle/observer denial, runtime read-only, allowed workspace edits, network denial, bounded output, and detached descendant cleanup using harmless controls.
- [x] Commit owned runtime/tests after focused checks.

## 3. Trusted grading integration

Files: `benchmark/pristine_grading.py`, active protocol/provenance callers and focused tests; separate ownership from tasks 1 and 2.

- [x] Replace candidate-native suite execution with trusted fixtures/probes importing interpreted module values under a scoped import binding.
- [x] Preserve all original six task checks, static workflow and independent gates. Report unsupported syntax, resource limit and infrastructure failure distinctly.
- [x] Bump grader protocol, hash interpreter and manifests, close runtime-result P0 only when original and alternate attacks fail and legitimate references remain valid.

## 4. Canonical campaign/readiness

Files: new canonical campaign/preflight modules, integration into supported entry point, observer and configuration tests. Start after runtime APIs are agreed.

- [x] Freeze seeded six-task/repetition schedule, protocol/content hashes and model settings before inference.
- [x] Require source-bound sandbox/evaluator controls before execute; block unsafe alternate execution paths.
- [x] Add complete observation, fake-endpoint no-model E2E, strict readiness outcomes and exact restart instructions.

## 5. Release verification

- [x] Run controls, then fresh independent bypass/regression review of the final patch; fix confirmed in-scope findings.
- [x] Run full pytest, Ruff, compilation, shell syntax and configured typecheck if available; report unavailable tools without installation.
- [x] Persist managed evidence, source hashes, final readiness status, limitations and updated methodology; commit locally with a clean branch.
- [x] Start no model campaign during preparation. READY requires every enforcement gate supported by current execution evidence.

## Completion evidence — 2026-10-15

Tested implementation: `6133bb6bd2af2daed6c1678b88ff61570df92464`.
All 20 required readiness gates passed with current input digest
`92d301b7fcfb665743354f8c800a8c01283fbf20057c962cdcd05b1aaceaf862`.
Full verification: 389 tests, 70 subtests, Ruff, compilation, 40 shell syntax
checks and diff check passed. No configured typechecker was available.
Independent final review has no open critical or warning findings.

The campaign lifecycle was tested with synthetic task/server adapters (56 records,
48 denominator rows, eight warmups, including a partial-session failure). A separate
native canonical task used real tools against a fake provider and trusted final
grading; all six task contracts had reference/noop/mutant controls. No real model
campaign was run. See [operator procedure and retained evidence](../SAFE_MODEL_TESTING.md).
