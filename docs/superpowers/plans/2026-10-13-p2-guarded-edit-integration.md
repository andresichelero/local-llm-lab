# Implementation Plan — P2: Integração do Guarded Edit no OpenCode

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate `benchmark/guarded_edit.py` into the OpenCode execution environment, providing whitespace-tolerant block matching, helper preservation enforcement, syntax leak protection, and an executable CLI tool `guarded-edit` available on PATH.

**Architecture:** Enhance `benchmark/guarded_edit.py` with whitespace-tolerant line-level matching when exact string matching fails, add a full CLI interface with JSON diagnostic support, create an executable helper script `bin/guarded-edit` injected into the agent environment PATH, and verify against edge cases (line-ending differences, trailing spaces, CLI invocation).

**Tech Stack:** Python 3.12+, `argparse`, `ast`, `hashlib`, `unittest`, `pytest`.

## Global Constraints
- Disk invariant: maintain $\ge 8\text{ GiB}$ free space on WSL ext4 SSD at all times.
- Backward compatibility: preserve all existing `apply_guarded_edit` signatures, `EditStatus` enums, and return structures.
- Zero syntax regressions: Ruff clean (0 errors, 0 warnings), 100% test pass rate across entire suite (224+ tests).

---

### Task 1: Whitespace-Tolerant Block Matching in `benchmark/guarded_edit.py`

**Files:**
- Modify: `benchmark/guarded_edit.py:130-160`
- Test: `tests/test_guarded_edit.py`

**Interfaces:**
- Consumes: `current_content`, `search_block`, `replacement_block`
- Produces: Enhanced `apply_guarded_edit` that attempts fuzzy line-matching when exact string matching yields 0 occurrences.

- [x] **Step 1: Write failing test in `tests/test_guarded_edit.py` for whitespace tolerance**

Test that search blocks with trailing spaces, minor indentation differences, or CRLF vs LF line endings succeed when a unique sequence of lines matches.

- [x] **Step 2: Implement line-normalized fuzzy matching in `apply_guarded_edit`**

When exact `count == 0`:
1. Split `current_content` and `search_block` into lines.
2. Normalize lines by stripping trailing whitespace.
3. Search for a unique contiguous slice of matching normalized lines.
4. If exactly one slice matches, replace the corresponding original slice with `replacement_block`.
5. If still 0 matches, return `ZERO_OCCURRENCES`. If multiple slices match, return `MULTIPLE_OCCURRENCES`.

- [x] **Step 3: Run pytest in WSL**

Verify that all existing tests + new fuzzy matching tests pass.

- [x] **Step 4: Commit**

```bash
git add benchmark/guarded_edit.py tests/test_guarded_edit.py
git commit -m "feat(guarded_edit): add whitespace-tolerant block matching"
```

---

### Task 2: CLI Interface in `benchmark/guarded_edit.py`

**Files:**
- Modify: `benchmark/guarded_edit.py:180-250`
- Test: `tests/test_guarded_edit.py`

**Interfaces:**
- Produces: `main(args: list[str] | None = None) -> int` and `if __name__ == "__main__": sys.exit(main())`
- Commands:
  - `apply --file <path> (--search <s> | --search-file <sf>) (--replace <r> | --replace-file <rf>) [--expected-sha <sha>] [--allow-helper-deletion] [--json]`
  - `check --file <path> [--content <c> | --content-file <cf>] [--json]`

- [x] **Step 1: Write tests in `tests/test_guarded_edit.py` for CLI execution**

Test `apply` via CLI with `--search` and `--replace`, with `--search-file` and `--replace-file`, exit codes (0 for success, 1 for error), and `--json` structured output.

- [x] **Step 2: Implement CLI in `benchmark/guarded_edit.py`**

Add `main()` function with `argparse`, supporting `--search`, `--search-file`, `--replace`, `--replace-file`, `--json`, and clean error reporting to stdout/stderr.

- [x] **Step 3: Run pytest in WSL and verify**

- [x] **Step 4: Commit**

```bash
git add benchmark/guarded_edit.py tests/test_guarded_edit.py
git commit -m "feat(guarded_edit): implement CLI interface with JSON output support"
```

---

### Task 3: OpenCode Environment Injection (`bin/guarded-edit`)

**Files:**
- Modify: `benchmark/opencode_controlled_probe.py` and `benchmark/model_quality_paired.py`
- Test: `tests/test_opencode_controlled_probe.py` and `tests/test_model_quality_paired.py`

**Interfaces:**
- Produces: `bin/guarded-edit` executable helper inside `run_dir/bin` added to `PATH` in `_isolated_environment`.

- [x] **Step 1: Write test for `bin/guarded-edit` presence in isolated environment**

Verify that `_isolated_environment` adds `run_dir / "bin"` to `PATH` and that `guarded-edit` executable is created with execute permissions.

- [x] **Step 2: Implement helper injection in `_isolated_environment`**

Create `run_dir / "bin" / "guarded-edit"` bash wrapper executing `python3 -m benchmark.guarded_edit "$@"`, set mode to `0o755`, and prepend `run_dir / "bin"` to `PATH`.

- [x] **Step 3: Run full test suite in WSL and verify Ruff**

- [x] **Step 4: Commit**

```bash
git add benchmark/opencode_controlled_probe.py benchmark/model_quality_paired.py tests/
git commit -m "feat(harness): inject guarded-edit CLI into OpenCode execution environment"
```

---

### Task 4: Integration Verification, PR & Merge

- [ ] **Step 1: Run full test suite in WSL (224+ tests passing)**
- [ ] **Step 2: Check WSL disk space ($\ge 8\text{ GiB}$ invariant)**
- [ ] **Step 3: Push branch and create PR**
- [ ] **Step 4: Await CodeQL CI checks and squash merge into `main`**
- [ ] **Step 5: Sync local and WSL `main`**
