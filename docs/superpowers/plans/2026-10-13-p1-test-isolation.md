# Implementation Plan — P1: Isolamento de Testes (SWE-bench Verified Standard) e Paridade TDD

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement held-out evaluation test suites isolated from the agent's mutable workspace (aligned with SWE-bench Verified standard) and establish TDD parity for `config_precedence_task` so agents have visibility of all contractual requirements.

**Architecture:** Held-out evaluation oracles are extracted from inline string probes in `benchmark/harness_eval.py` into structured, read-only test suites located in `benchmark/eval_suites/<task>/test_probe.py` outside of the agent's workspace. Graders in `benchmark/harness_eval.py` run both workspace unit tests (verifying agent tests) and isolated held-out suites (verifying behavioral correctness without risk of model tampering). Fixture `config_precedence_task` is updated to include `None`-as-absent test assertions in its workspace suite.

**Tech Stack:** Python 3.12+, `unittest`, `subprocess`, `pathlib`, `ast`.

## Global Constraints
- Disk invariant: maintain $\ge 8\text{ GiB}$ free space on WSL ext4 SSD at all times.
- Backward compatibility: `grade_workspace` must preserve existing return keys (`success`, `unit_tests_passed`, `behavioral_probe_passed`, `unchanged_helpers`, `changes_scoped`, `required_tests_present`, `test_output`, `behavioral_probe_stderr`) while adding granular keys (`workspace_tests_passed`, `baseline_tests_passed`, `held_out_tests_passed`).
- Zero syntax regressions: Ruff clean (0 errors, 0 warnings), 100% test pass rate across entire suite (218+ tests).

---

### Task 1: TDD Parity for `config_precedence_task`

**Files:**
- Modify: `benchmark/fixtures/config_precedence_task/tests/test_config.py:20-27`
- Test: `tests/test_harness_eval.py`

**Interfaces:**
- Consumes: `src.config.resolve_config`
- Produces: Updated test suite in `benchmark/fixtures/config_precedence_task/tests/test_config.py` including `test_none_treated_as_absent` to match Requirement 2 of `TASK.md`.

- [x] **Step 1: Write test in `tests/test_harness_eval.py` for TDD parity**

Verify that `config_precedence_task` baseline tests include an assertion that `None` in higher-precedence sources does not override defaults.

- [x] **Step 2: Update `benchmark/fixtures/config_precedence_task/tests/test_config.py`**

Add `test_none_treated_as_absent` verifying `resolve_config({"port": 8000}, {"port": None})["port"] == 8000`.

- [x] **Step 3: Run pytest in WSL**

Verify all tests pass.

- [x] **Step 4: Commit**

```bash
git add benchmark/fixtures/config_precedence_task/tests/test_config.py tests/test_harness_eval.py
git commit -m "fix(fixtures): add test_none_treated_as_absent to config_precedence_task tests"
```

---

### Task 2: Create Held-Out Evaluation Suites (`benchmark/eval_suites/`)

**Files:**
- Create:
  - `benchmark/eval_suites/calculator_division/test_probe.py`
  - `benchmark/eval_suites/whitespace_normalization/test_probe.py`
  - `benchmark/eval_suites/dotenv_line_parser/test_probe.py`
  - `benchmark/eval_suites/config_precedence/test_probe.py`
  - `benchmark/eval_suites/retry_policy/test_probe.py`
  - `benchmark/eval_suites/package_refactor/test_probe.py`

**Interfaces:**
- Consumes: Target task modules (`src.calculator`, `src.text_utils`, `src.config_parser`, `src.config`, `src.retry`, `src.service`, `src.metrics`).
- Produces: Standard `unittest.TestCase` files executing the strict behavioral probes currently inlined in `harness_eval.py`.

- [x] **Step 1: Create test probe files for each of the 6 benchmark tasks**

Structure each probe as a standard `unittest.TestCase` with explicit assertions and informative error messages.

- [x] **Step 2: Verify test probe files compile cleanly**

Run `python -m py_compile benchmark/eval_suites/*/test_probe.py`.

- [x] **Step 3: Commit**

```bash
git add benchmark/eval_suites/
git commit -m "feat(benchmark): create isolated held-out test suites for all 6 tasks"
```

---

### Task 3: Integrate Held-Out Test Runner into `benchmark/harness_eval.py`

**Files:**
- Modify: `benchmark/harness_eval.py`
- Test: `tests/test_harness_eval.py`

**Interfaces:**
- Consumes: `benchmark/eval_suites/<task>/test_probe.py`
- Produces: `run_held_out_tests(workspace: Path, task: str) -> tuple[bool, str, str]`
- Updates: `_grade_*` functions in `harness_eval.py` to run held-out suites and baseline regression tests.

- [x] **Step 1: Implement `run_held_out_tests` in `benchmark/harness_eval.py`**

Execute `unittest` on `benchmark/eval_suites/<task>/test_probe.py` with `PYTHONPATH` set to `workspace`. Fallback to inline probe if probe file is not found.

- [x] **Step 2: Update all 6 grading functions**

Incorporate `run_held_out_tests` into `_grade_whitespace_normalization`, `_grade_env_parser`, `_grade_config_precedence`, `_grade_retry_policy`, `_grade_package_refactor`, and `calculator_division`.
Set:
- `workspace_tests_passed`: bool
- `held_out_tests_passed`: bool
- `baseline_tests_passed`: bool
- `unit_tests_passed`: `workspace_tests_passed and baseline_tests_passed`
- `behavioral_probe_passed`: `held_out_tests_passed`

- [x] **Step 3: Add unit tests in `tests/test_harness_eval.py`**

Test that held-out tests pass for valid implementations, fail for invalid implementations, and detect tampering when workspace tests are modified.

- [x] **Step 4: Run test suite in WSL and verify Ruff**

```bash
PYTHONPATH=. pytest tests/
ruff check benchmark/ tests/
```

- [x] **Step 5: Commit**

```bash
git add benchmark/harness_eval.py tests/test_harness_eval.py
git commit -m "feat(benchmark): wire held-out test suites into harness_eval grading pipeline"
```

---

### Task 4: Integration Verification, PR & Merge

**Files:**
- Review: all modified and created files
- Git branch: `feat/eval-pipeline-p1-held-out-tests`

- [ ] **Step 1: Run full test suite in WSL (218+ tests)**
- [ ] **Step 2: Check WSL disk space ($\ge 8\text{ GiB}$)**
- [ ] **Step 3: Push branch and create PR**
- [ ] **Step 4: Await CodeQL CI checks and squash merge into `main`**
- [ ] **Step 5: Sync local and WSL `main`**
