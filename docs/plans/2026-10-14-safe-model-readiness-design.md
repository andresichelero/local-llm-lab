# Safe model testing readiness design

**Authorized outcome:** implement and verify all prerequisites for a controlled local model campaign; do not start inference as part of preparation. Base `1808da3`, feature branch `fix/evaluation-oracle-observability-v3`.

## Trust and task contract

Native candidate Python must never share the test interpreter. A JSON subprocess adapter would lose authenticated mutable-argument and callable-identity semantics, so this campaign uses an explicit restricted Python task language interpreted by trusted code. Candidate AST is data: no candidate `eval`, `exec`, `compile`, native import, class construction, decorators, arbitrary attribute access, or arbitrary host callable execution. Unsupported syntax is a distinct validator outcome, never a passing test or a silently dropped check.

The interpreter preserves ordinary bounded values, mutable containers, trusted test callbacks and exception classes, and actual function binding identity across allowed source modules. It interprets the syntax needed by all six known references and ordinary alternative solutions. Step, recursion, collection, integer, string, and source/AST-size limits apply before potentially large allocations. No native regex with attacker-controlled pathological patterns is exposed. Test assertions and result aggregation remain ordinary trusted Python outside candidate semantics.

Protocol identity changes to `restricted-python-workspace-v2`. Existing task inputs are explicitly paired with this new language contract and not compared directly with prior CPython grades. Original fixtures, historical evidence, and public probes remain preserved. Input mutation must still be observable; callback calls are actual trusted callback invocations; imported reexports share actual interpreted callable objects. No child-reported test count, marker, mutation snapshot or identity boolean is authoritative.

## Native agent boundary

Linux-only launcher uses existing rootless user/mount/PID/network namespaces and a private root, read-only runtime files, an explicitly writable candidate tree, bounded scratch storage, no host `/proc` or directories, no inherited host directory/namespace FDs, dropped capabilities, and no-new-privileges. Workspace and scratch are bounded tmpfs mounts; only exact safely inspected export paths return to the host after candidate descendants stop. The trusted namespace supervisor itself is non-dumpable and chroots before starting the candidate. Owned namespace termination must stop escaped-session descendants as well as leaders. Unsupported platforms and failed isolation probes fail closed.

Existing transient systemd user scopes have directly demonstrated aggregate `memory.max`, `pids.max` and `cpu.max` enforcement without installation or persistent configuration. Each run must use a unique owned scope and read actual enforced values, including a bounded swap allowance when available; requested properties alone are not evidence. No broad host-network or privileged-host exception is allowed to make a failed probe pass.

The host-local model connection is mediated by a narrow broker: fixed loopback destination, explicit model allowlist, bounded HTTP methods/paths/body/output/time, and no arbitrary destination or forwarded credentials. Agent network namespace may access the broker transport only; no host-network exception. A fake local endpoint validates the channel without models or external network.

## Campaign and release gate

A single supported six-task campaign must freeze source/config/runtime hashes, seed and task order, model contracts, context/generation settings, repetitions, scoring dimensions and failure taxonomy before execution. Observer artifacts remain outside the agent mount and include native event streams, lifecycle/resource evidence and final grading. Alternate unsafe entry points fail closed or are explicitly diagnostic-only.

Readiness is machine-checked and bound to exact source/config/runtime inputs. It requires six correct references, six no-ops, six meaningful mutants, the original runner-forgery proof and alternate attacks, host-file/protected-oracle/sentinel denial, network denial plus allowed broker channel, process cleanup including detached descendants, output/resource bounds, artifact integrity, a complete no-model campaign and project checks. A saved earlier pass cannot authorize changed inputs. Private custody is distinct from public-task contamination; no claim of unseen training data or generalized capability follows from these regression tasks.

## Deliverables and stopping condition

Implement restricted evaluator, native-agent sandbox/broker, canonical observed campaign and readiness gate; validate adversarial and legitimate controls, review once independently, fix confirmed findings, and preserve raw evidence. Finish with a locally committed reproducible READY command/protocol or an explicit fail-closed blocker supported by execution evidence. Do not label incomplete enforcement READY. No dependency installation, driver changes, reboot, model downloads, remote publication or model campaign is included.
