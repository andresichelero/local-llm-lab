# Pristine grading validation — 2026-10-14

This checkpoint validates the `pristine-workspace-v1` diagnostic replay and its ordinary no-model controls. It does not validate an adversarially secure grader.

## Results

| Check | Source revision | Result |
|---|---|---|
| Full project tests | `489c0d57ca5f58ca742117759f4abf99fc4b7a6a` | 298 passed; 19 subtests passed in a Git-aware Ubuntu 24.04 ext4 clone |
| Ruff | `489c0d57ca5f58ca742117759f4abf99fc4b7a6a` | Passed with Ruff 0.15.17 |
| `compileall` | `489c0d57ca5f58ca742117759f4abf99fc4b7a6a` | Passed with Python 3.12.3 |
| Shell syntax, 41 files | `489c0d57ca5f58ca742117759f4abf99fc4b7a6a` | Passed |
| Independent control driver, 29 cases | `489c0d57ca5f58ca742117759f4abf99fc4b7a6a` | 29 controls, zero assertion failures with the schema-corrected driver; source Git state unchanged |
| Typecheck | `489c0d57ca5f58ca742117759f4abf99fc4b7a6a` | Not available: no mypy/pyright executable or typecheck configuration was found; no installation was attempted |

Validation used the existing WSL environment and dependencies. No model, GPU campaign, network benchmark, or dependency installation was used. Raw check logs and driver snapshots are under `D:/Usuario/Downloads/LLM/audit-session-20261013/pristine/validation-final-20261014-489c0d57-221008/`. The corrected control run and replay artifacts are under `D:/Usuario/Downloads/LLM/audit-session-20261013/pristine/validation-20261014-489c0d57-221223/`; the Git-aware test clone retained `.git` metadata on WSL ext4.

The first invocation of the external driver asserted the nonexistent field `result_authentication_verified`, producing 28 schema-only assertion failures; every other assertion passed. Its full output is preserved under `validation-20261014-489c0d57-221112/`. A copied driver changed that assertion to the actual `runtime_result_authenticated=false` field and added `adversarial_evaluation_validated=false`; it did not change the source commit, control cases, or other expectations. The corrected driver's hash and both run manifests are indexed below. The first run is retained as failed evidence and was not reclassified.

## Security finding and gate

The 29-control matrix is ordinary functional and workspace-integrity evidence. The existing independent review reproduced a runner-forgery case: candidate code made `divide()` return the wrong value and patched `unittest`, yet all five gates and aggregate `success` were reported true without trusted test methods running. Therefore `runtime_result_authenticated=false`, `adversarial_evaluation_validated=false`, `aggregate_is_security_proof=false`, `private_holdout=false`, and `capability_evidence_eligible=false` remain required. Static integrity checks do not authenticate runtime outcomes.

The final scoped review accepted the artifact fixes and documentation while leaving the result-authentication P0 open. The next acceptance gate is assertion/result authority outside the candidate-controlled interpreter, with authenticated transfer of the result. OS/network isolation and separately controlled private holdout custody also need independent evidence. Until these gates close, this checkpoint supports grader diagnostics only.

Evidence metadata, hashes, and durable artifact paths are listed in the [evidence index](pristine-grading-validation-evidence-index-20261014.json). The protocol details are in [pristine grading protocol](../../docs/methodology/pristine-grading-protocol.md).
