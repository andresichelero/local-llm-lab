# Qwen All-Harness Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to execute this authorized preparation in the current session. Preserve unrelated edits and all historical installations/results.

**Goal:** Reinclude the historical harness catalog, add Qwen Code, update isolated runtimes/dependencies/plugins, and qualify installation readiness before new model inference.

**Architecture:** Side-by-side WSL environments under a dated laboratory root, a registry-derived version snapshot and lockfiles, per-component logs/status, and a preparation report. Historical environments and frozen campaign manifests are not upgraded in place. A failure of one package is recorded while independent packages continue.

**Tech Stack:** Existing Python 3.12 for bootstrap, current official Node LTS, uv-managed compatible Python, npm/PyPI official packages and pinned upstream Git sources, current llama.cpp stable release where its GPU binary is compatible.

**Spec:** `docs/superpowers/specs/2026-10-25-qwen-single-model-optimization-design.md`, amended by the user's explicit instruction to compare all historical harnesses and update before testing.

## Global Constraints

- The user authorized dependency/runtime/plugin updates for this comparison on 25/10/2026; no second installation approval is needed for this scoped work.
- Use only the existing Qwen3.5-9B GGUF in future model tests; this preparation does not load it.
- Preserve all old environments, model weights, logs, evaluations and manifests.
- No driver, OS, clocks, forced reboot, WSL restart, host-global CLI replacement or personal credential/config reads.
- Keep at least 8 GiB free on WSL ext4. Record unresolved compatibility/auth/platform requirements explicitly, never as model failure.
- Compare latest compatible official versions. Preserve upstream dependency constraints rather than forcing unrelated transitive major versions.
- Do not install/upgrade system packages globally or silently download models/browser images. Required Ubuntu binaries may be downloaded and hash-verified against repository metadata, then extracted into the isolated native prefix without root or package-maintainer scripts.
- No commits/pushes, monitor automation or inference in the refresh stage.

## Review Focus

1. A formerly excluded harness remains in the inventory with its new qualification result.
2. Registry identity must match the official upstream, not a similarly named unrelated package.
3. Each smoke uses isolated HOME/XDG/config and no ambient API keys or remote model fallback.
4. Archive extraction cannot escape the new runtime directory; low disk stops mutations safely.
5. Dependency/CLI failure never aborts the remaining independent installs or erases its logs.

### Task 1 — Inventory and resolution

**Files:** new `benchmark/configs/qwen-harness-matrix-v1.json`; source `config/harnesses.yaml`, `versions.lock`, their Git history and the methodology sources.

- [ ] Preserve the eight historical catalog entries: Pi, OpenCode, Codex, Claude Code, Hermes, Mistral Vibe, TrueForge, DeepSeek Harness.
- [ ] Add Qwen Code requested in the current design. Include Aider/OpenHands in the readiness screen as research-referenced harnesses, labeled as such rather than falsely claiming past measurements.
- [ ] Resolve official package versions, Python requirements, package integrity and repository metadata. Resolve plugins and official Node/llama.cpp releases separately.
- [ ] Save a timestamped discovery snapshot before installation; distinguish discovery, installed, CLI-qualified and model-compatible states.

### Task 2 — Isolated runtimes and installation

**Files:** new `scripts/refresh_qwen_harnesses.py`; new laboratory root `/home/foxtrot/local-llm-benchmark/envs/qwen-harness-refresh-20261025`; reports under `results/reports/qwen-harness-refresh-20261025`.

- [ ] Create a new bootstrap venv and current pip/uv there. Download and hash-check the current official Node LTS into the new root.
- [ ] Install compatible managed Python interpreters separately, respecting upstream runtime requirements (Hermes requires its current supported 3.14 runtime).
- [ ] Install exact resolved Node/Python harness versions in separate prefixes/venvs. Preserve lockfiles, dependency lists and install logs.
- [ ] Record failure and continue the matrix; do not force a broken dependency override or alter the system interpreter.

### Task 3 — Plugins and model runtime

- [ ] Install Headroom and its available supported optional proxy/MCP dependencies in a separate environment; record the native OpenCode package separately.
- [ ] Stage current official Superpowers at a pinned release/commit, outside the user's global Codex/OpenCode directories.
- [ ] Resolve/stage the current compatible official llama.cpp stable GPU bundle, verifying download integrity; preserve the existing 620d222 bundle and Prism.
- [ ] If native build tools or platform libraries are absent, retain a specific blocked qualification and proceed with other components. No driver/system update is implied.

### Task 4 — Qualification and reporting

- [ ] Validate archive/path and registry-resolution helpers with focused offline checks.
- [ ] Run bounded CLI version/help/import checks with isolated application state, no credentials and telemetry/update checks disabled where supported.
- [ ] Record npm audits/pip dependency consistency without automatic force-fixes. Keep security findings visible for formerly excluded TrueForge.
- [ ] Save exact installed versions, lockfiles, executables, errors, disk use and the next compatibility gate.
- [ ] Amend the optimization design to compare native harnesses fairly first, then their declared optimized plugin stacks; keep the same Qwen and effective inference settings for the first comparison.

Real model/API compatibility, sandbox/tool parity and practical task measurements follow this refresh. They are not inferred from a successful installation or `--version` call.
