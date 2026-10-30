# F0 preflight — items 1–4

Date: 2026-10-28. Scope performed offline, without starting llama-server, inference, GPU, downloads, installations, code/configuration changes, branch, checkout, stash or commit. The only workspace write was this report; pytest used temporary files in /tmp and bytecode/cache were disabled.

## 1. Model

### Commands used

    Get-ChildItem -LiteralPath D:\ -Filter '*.gguf' -File -Recurse -Force -ErrorAction SilentlyContinue -ErrorVariable +errs |
      Where-Object { $_.FullName -match '(?i)4b' }
    Get-ChildItem -LiteralPath E:\ -Filter '*.gguf' -File -Recurse -Force -ErrorAction SilentlyContinue -ErrorVariable +errs |
      Where-Object { $_.FullName -match '(?i)4b' }
    Get-FileHash -LiteralPath 'E:\LocalLLMLabArchive\models\bartowski-Qwen_Qwen3.5-4B-GGUF\4168f45a16a1290d65a4ec0fa312ae917a4c15d6\Qwen_Qwen3.5-4B-Q4_K_M.gguf' -Algorithm SHA256
    Get-FileHash -LiteralPath '<workspace>\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q6-k-1943f53d06a9a1e6\Qwen3.5-4B-Q6_K.gguf' -Algorithm SHA256

The D: and E: roots were accessible. The final enumeration returned code 0 and found five files on D: and one on E:. Five access-denied enumeration errors were recorded: D:\$RECYCLE.BIN\S-1-5-18, D:\System Volume Information, two subfolders of E:\$RECYCLE.BIN and E:\System Volume Information.

### Q4_K_M and variants found

| File | Path | Bytes | SHA-256 |
|---|---|---:|---|
| Qwen3.5-4B Q4_K_M | E:\LocalLLMLabArchive\models\bartowski-Qwen_Qwen3.5-4B-GGUF\4168f45a16a1290d65a4ec0fa312ae917a4c15d6\Qwen_Qwen3.5-4B-Q4_K_M.gguf | 3.013.027.808 | 13c16f426047e2de38cd075bdade4a7bcbc8c774384876f677740cda65f8a983 |
| Qwen3.5-4B Q5_K_M | <workspace>\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q5-k-m-523af779a39fdf28\Qwen3.5-4B-Q5_K_M.gguf | 3.143.656.608 | not calculated |
| Qwen3.5-4B Q5_K_S | <workspace>\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q5-k-s-c290a3d9efc52920\Qwen3.5-4B-Q5_K_S.gguf | 3.024.934.048 | not calculated |
| Qwen3.5-4B Q6_K | <workspace>\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q6-k-1943f53d06a9a1e6\Qwen3.5-4B-Q6_K.gguf | 3.525.956.768 | fdedd781c9ce676ab66b018ca247ff78e8a33c98098a822c1e2d5075e7718f66 |
| Qwen3.5-4B Q8_0 | <workspace>\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-q8-0-8c94708900a06875\Qwen3.5-4B-Q8_0.gguf | 4.482.403.488 | not calculated |
| Qwen3.5-4B UD-Q5_K_XL | <workspace>\qwen-optimization-cache\models\qwen-4b-unsloth-qwen3-5-4b-gguf-ud-q5-k-xl-1027ef16cfbfd447\Qwen3.5-4B-UD-Q5_K_XL.gguf | 3.250.869.408 | not calculated |

Q4_K_M matches the expected October SHA-256. The Q6_K SHA-256 was calculated as requested; the other variant hashes were not calculated.

WSL search performed:

    find /home/foxtrot -type f -iname '*.gguf' -printf '%p %s\n' 2>/dev/null | grep -Ei '4b'

Result: no 4B match (grep returned 1 because there were no matches). prefix_cache_paired.py and cascade_routing_matrix.py declare models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf relative to REPO_ROOT; that file does not exist under WSL root /home/foxtrot/local-llm-benchmark or the mounted repository and worktree roots. qwen_engines.py receives the artifact as an argument and pins only the runtime/binary root to /home/foxtrot/local-llm-benchmark.

## 2. llama.cpp build

The three runners examined converge on one execution path: /home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server. llama-bin is a symlink to tools/llama-bin-v0.7.0-620d2225c/llama-server. Code references: benchmark/qwen_engines.py:16,352; benchmark/prefix_cache_paired.py:397,312; benchmark/cascade_routing_matrix.py:939-940. qwen_engines.py exists only in the practical-agent-v2 worktree; prefix and cascade were checked in local-llm-lab and practical-agent-v2.

Commands run in informational mode only:

    /home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server --version
    /home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server --help 2>&1 | grep -E -- '--cache-prompt|--no-cache-prompt|--cache-reuse|--ctx-checkpoints|--swa-full|--cache-ram|--slot-save-path|--reasoning|--cache-type-k'
    /home/foxtrot/local-llm-benchmark/tools/llama-bin/llama-server --help 2>&1 | grep -i -E -- 'cache-type-k|q4_0'

Output of --version:

    version: 0.7.0-dev (build 1, commit 620d222)
    built with GNU 13.3.0 for Linux x86_64

The local source tools/llama.cpp-v0.7.0-620d2225c has HEAD 620d2225cc436ab0b001e3200e590e3b286ef9ab and empty git status --short. --help confirmed all requested features:

| Option | Result in --help |
|---|---|
| --cache-prompt / --no-cache-prompt | supported |
| --cache-reuse | supported |
| --ctx-checkpoints | supported, also appears as --swa-checkpoints |
| --swa-full | supported |
| --cache-ram | supported |
| --slot-save-path | supported |
| --reasoning | supported (on, off, auto) |
| --cache-type-k q4_0 | supported; q4_0 is in the list of allowed values |

Static confirmation in local source:

- tools/server/server.cpp:290,292: POST /tokenize and POST /apply-template.
- tools/server/server.cpp:303-304: GET /slots and POST /slots/:id_slot.
- tools/server/server-context.cpp:5415-5421: dispatch of action=save and action=restore; handlers read filename from the body.
- tools/server/server-common.cpp:86,88: fields timings.cache_n and timings.prompt_n.

No server was started; routes were checked in code, without an HTTP runtime test. Other llama-server binaries exist under tools/, but the three runners indicated resolve the symlink above; they are not builds referenced by those scripts.

## 3. Codebase

Summary obtained with git branch --show-current, git rev-parse HEAD and git status --porcelain=v1 --untracked-files=all:

| Worktree | Branch | HEAD | Modified | Deleted | Untracked | Entries | Most common status roots |
|---|---|---|---:|---:|---:|---:|---|
| local-llm-lab | fix/evaluation-oracle-observability-v3 | 4577aeb921587feaee8518c656a32a64d593ea9c | 13 | 0 | 43 | 56 | benchmark:14, results:21, tests:11, research:4, docs:2, scripts:3, versions.lock:1 |
| .worktrees/practical-agent-v2 | feat/practical-agent-v2 | 4577aeb921587feaee8518c656a32a64d593ea9c | 16 | 68 | 326 | 410 | results:221, benchmark:67, tests:63, scripts:25, docs:18, agent-manual:6, research:5 and state/lock files |
| .worktrees/qwen-cleanup-r3-r4 | chore/qwen-cleanup-record | f940432b4733d764ac2d3a5406e09067c02d1c7a | 0 | 0 | 0 | 0 | clean tree |

git diff --stat between HEADs for benchmark/guarded_edit.py, benchmark/prefix_cache_paired.py, benchmark/qwen_engines.py and benchmark/qwen_workloads.py:

- local-llm-lab..practical-agent-v2: empty; both are at the same HEAD.
- local-llm-lab..qwen-cleanup-r3-r4 and practical-agent-v2..qwen-cleanup-r3-r4: guarded_edit.py (206 lines changed) and prefix_cache_paired.py (9 lines changed), total 16 insertions(+), 199 deletions(-).
- qwen_engines.py and qwen_workloads.py are not in the HEAD of these worktrees; they exist only as untracked files in practical-agent-v2. Their tests and scripts/check_qwen_readiness.py are also untracked there. Therefore the HEAD diff does not count them.

Recommendation: use common commit 4577aeb921587feaee8518c656a32a64d593ea9c as the base for feat/4b-worker-v2 in a clean worktree; use local-llm-lab/fix/evaluation-oracle-observability-v3 as the tracked-tree reference, since it has the same HEAD and fewer dirty entries than practical-agent-v2. The current guarded_edit.py and prefix_cache_paired.py versions are identical between these two trees. If the untracked Qwen modules are needed, review and bring only those files from practical-agent-v2 to the future branch. qwen-cleanup-r3-r4 is clean but at an earlier HEAD and does not contain the Qwen modules. No branch was created.

## 4. Reuse and current state of guarded_edit.py

scripts/check_qwen_readiness.py uses sys.executable and does not itself pin an interpreter. The existing foundation.json, dated 2026-10-27, records /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python; that path was revalidated live: Python 3.12.3 and pytest 9.1.1. Global /usr/bin/python3 lacks pytest, so it was not used.

Command run in practical-agent-v2, with temporary files in /tmp:

    cd /path/to/workspace/.worktrees/practical-agent-v2
    PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp TMP=/tmp TEMP=/tmp \
      /home/foxtrot/local-llm-benchmark/envs/lab-validation/bin/python -m pytest \
      -p no:cacheprovider -q \
      tests/test_guarded_edit.py tests/test_qwen_engines.py \
      tests/test_qwen_workloads.py tests/test_prefix_cache_paired.py

Actual result:

    ...........................................                              [100%]
    43 passed in 10.22s

test_qwen_engines.py uses a fake HTTP server at 127.0.0.1; it does not start llama-server. Tests use tmp_path; there was no inference/GPU. The post-test status summary remained at 410 entries (16 modified, 68 deleted, 326 untracked); no new change appeared in the tested files.

benchmark/guarded_edit.py already guarantees (lines 83-157, 215-373): confinement to the workspace and rejection of traversal/symlink; checking the expected SHA when provided; rejection of empty, absent or ambiguous SEARCH; comparison fallback ignoring trailing spaces; conversational leakage detector; AST validation for Python; preservation of existing function/class names; and atomic writing of one file. The API applies a single SEARCH/REPLACE block per call (apply_guarded_edit, lines 215-224).

Missing for F3 of the plan (PLANO-ESTRATEGICO-v2.md:82-85):

- no transactional batch of multiple SEARCH/REPLACE blocks per file;
- does not receive or validate a writable_files allowlist; workspace-root is only a broad boundary;
- has no rule specifically prohibiting changes to tests/oracles;
- the receipt is partial: EditResult.to_dict() exposes success, status, new_sha256, diff and error_message, but success fills only new_sha256 (diff remains null); it includes neither the previous hash nor file path.

The module itself cautions that the checks are application guards, not an operating-system sandbox, and do not prevent concurrent path replacement.

## Blockers

- The intact Q4_K_M was found on Windows E:, but does not exist in the WSL installation or the runners’ relative model paths. I did not copy the file because that would exceed authorized writes; future execution in WSL remains blocked until the model is made available in that environment with authorization.
- The contents of five protected folders ($RECYCLE.BIN/System Volume Information) could not be enumerated because access was denied. The six reported results cover readable GGUF paths on D:/E:.
- Endpoints and timings were confirmed in source corresponding to the binary commit; their behavior on a live server was not tested, in accordance with the prohibition on starting a server.
- The Qwen modules and tests enabling reuse are untracked in practical-agent-v2; the recommended base commit alone does not contain them. They require review before incorporation into a future branch.
- F0 item 5 (task corpus) was not evaluated; it is outside the requested scope, limited to items 1–4.

## F0 gate items 1–4: passed/failed

1. **Failed for WSL operational availability; passed for model integrity.** Q4_K_M exists on E: and its SHA-256 matches, but the file is not at the runners’ WSL path.
2. **Passed.** The build used, requested options and endpoints/fields in source were confirmed.
3. **Passed.** States and diffs of the three worktrees were recorded; a base was recommended without creating a branch.
4. **Passed.** The four requested test files passed: 43 tests.

## Orchestrator review (Claude, 28/10/2026)

The report was accepted. Independent checks:

- Q4_K_M SHA-256 on E:: recalculated, matches (`13c16f42…8a983`).
- `llama-server --version`: returns 0.7.0-dev, commit 620d222. All 5 cache flags are present in `--help`.
- Free space in WSL: 36 GB, enough to copy the model (3,0 GB).

Outstanding items before F1 and F3, dependent on user approval:

1. Copy Q4_K_M from E: to `/home/foxtrot/local-llm-benchmark/models/gguf/qwen3.5-4b/Qwen_Qwen3.5-4B-Q4_K_M.gguf` and check the hash after copying.
2. Create the `feat/4b-worker-v2` worktree from commit `4577aeb` and bring from `practical-agent-v2`, after reviewing them, only the untracked Qwen modules needed by F1 and F3: `qwen_*.py`, corresponding tests and `scripts/check_qwen_readiness.py`.
3. F0 item 5 (corpus of 12 tasks embedded in a 40–100K-token repo): goes to Terra 6.1 High, after item 2.




