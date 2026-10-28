# Qwen DNS Recovery r3 Implementation Plan

> **For agentic workers:** Use the test-driven workflow for the queue change. Keep the active r2 output immutable.

**Goal:** Restore the Qwen queue safely and retry only episodes that r2 recorded as blocked by the verified WSL DNS outage.

**Architecture:** Repair DNS only for the current WSL `eth0` link at runtime, using the Windows host's currently configured resolver and reverting the link override if verification fails. Create protocol r3 as a new output seeded from r2; preserve r2 unchanged, carry forward valid results with source provenance, and make only DNS-only infrastructure episodes pending again.

**Tech Stack:** Python queue/state code, pytest, Ruff, WSL `systemd-resolved`, systemd user service, Codex heartbeat automation.

**Spec:** User request in the 2026-10-26 thread; monitor automation `monitorar-e-recuperar-qwen-a-cada-30-minutos`.

## Global Constraints

- Do not modify or reclassify r2 state, manifests, or raw evidence.
- Do not retry a unit that has a completed model result or any non-DNS completed result.
- Do not edit `/etc/wsl.conf`, `/etc/resolv.conf`, Windows network settings, Docker, drivers, clocks, or global packages.
- Keep DNS repair transient and reversible; start one model/server at a time.
- Use only the frozen artifact catalog and its verified cache; preserve cache limits and hashes.
- New recovery output must use a distinct `protocol_id` and retain source protocol/output for imported attempts.

## Review Focus

- A DNS substring in one attempt must not requeue a unit that also has a completed model result.
- The source r2 state and manifest hashes must remain byte-for-byte unchanged.
- Requeued attempts must retain their original result and source status in r3 provenance.
- A DNS repair that fails its resolver probe must revert and leave inference paused.
- The pause marker must only be removed after the DNS and Hugging Face API probes pass.

## Tasks

### Task 1: Requeue only reviewed DNS infrastructure failures in a fresh recovery output

**Files:** `benchmark/qwen_optimization.py`, `tests/test_qwen_optimization.py`, `benchmark/qwen_quant_runner.py`, `benchmark/configs/qwen-optimization-v4-recovery-r3.json`.

- [ ] Add a failing unit test for importing a stopped source and converting only `finished` attempts whose result is `blocked`, `model_failure` is false, and error contains the exact DNS failure into retryable attempts in the new copy. Assert source bytes stay unchanged and model/completed results remain finished.
- [ ] Run the focused test and verify it fails for the missing requeue behavior.
- [ ] Implement an explicit `--requeue-dns-failures` recovery option, record selected unit IDs and source status in `recovery-origin.json`, and use a new r3 protocol/output.
- [ ] Run the focused test and queue/status tests; verify r3 has only the selected DNS units plus pre-existing pending units pending.

### Task 2: Qualify recovery inputs offline and start r3

**Files:** `benchmark/qwen_quant_runner.py`, `benchmark/qwen_status.py`, `scripts/Watch-QwenQuant.ps1`, `results/reports/qwen-optimization-v4-recovery-r3/`.

- [ ] Copy r2's frozen report assets to a new r3 report directory and regenerate the foundation gate for the r3 code/config.
- [ ] Run the relevant offline tests, Ruff, and compile checks while r2 remains paused.
- [ ] Prepare r3 from r2, verify its manifest and recovery-origin hashes, and confirm r2's hashes did not change.
- [ ] Start one r3 systemd service only after the WSL DNS and Hugging Face API probes pass; verify the first model server uses a frozen catalog artifact.

### Task 3: Make the 30-minute automation self-heal this DNS failure safely

**Files:** Codex heartbeat automation `monitorar-e-recuperar-qwen-a-cada-30-minutos`.

- [ ] Add a read-only DNS diagnosis and a runtime-only WSL `eth0` resolver fallback using the current Windows DNS resolver.
- [ ] Require `resolvectl query` and a small Hugging Face API request to pass before unpausing or starting inference.
- [ ] On probe failure, revert only the transient `eth0` DNS override, keep the output paused, preserve data, and notify with the exact blocker.
- [ ] Monitor r3 and later outputs explicitly; never rewrite the 441 completed r2 DNS records.
