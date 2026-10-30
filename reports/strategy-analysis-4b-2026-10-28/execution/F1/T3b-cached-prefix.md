# T3b — cached prefix for the F3 worker

Date: 29/10/2026. Implementation and offline validation in the `feat/4b-worker-v2` worktree. No inference, server or GPU access was started for this task. The campaign was not run; there are no quality or performance results.

## Design

There are 12 tasks from hosts `bottle-0.13.2` and `ms-2.1.3`, three repetitions per task and arm, totaling 108 units. The control is Qwen3.5-4B Q4_K_M bartowski, KV q4_0, prompt cache enabled, zero temperature, seed 42 and thinking disabled. P-W16 uses ctx 16384; P-WL-cold and P-WL-warm use ctx 65536. The model is called by the F3 worker, which accepts SEARCH/REPLACE and up to one repair. Continuation has two conditional submissions sharing the one-repair limit.

- P-W16 maintains one server per host and sends the short package.
- P-WL-cold restarts the server for each episode. Token counting uses template/tokenization endpoints without generation or cache filling. TTFT measures the first prefill; process startup is excluded from episode time.
- P-WL-warm maintains one server per host and generates one token with the prefix before the first task. Warmup cost is in `warmup.json`, separate from episodes.

All arms use the same excerpt selection method: for each regular file listed in `relevant_files`, in lexicographic order, select a single contiguous excerpt of up to 12000 characters divided by the number of relevant entries. For a long file, the line sharing the most words with the public objective determines the center; ties select the first line. Directories and missing files are ignored. Neither reference patch nor oracle is read to select context. The WL prefix is the frozen, redacted corpus prefix, not the original snapshot; the excerpt also provides code with the specific bug.

The coordinator checks the corpus manifest and configured server and model hashes before starting. It obtains the actual template/tokenizer count for every initial package on each host and, if necessary, reduces the prefix by binary search at line boundaries, using the same chosen prefix for both WL arms and all tasks on the host. The decision, sizes and hashes are recorded in `prefix-<host>.json`. The search assumes approximately monotonic counts and ensures the selected option was tested, without promising a mathematically maximal prefix. It reserves 2048 output tokens and 4096 of headroom for repair and follow-up; the runner recounts input on every generation and rejects input over budget. An extraordinarily large repair or follow-up can still exceed that margin; the context window does not guarantee the second request will fit.

The F3 builder accepts only the complete frozen file as `prefix`; the adapter validates the corpus against the manifest, selects the initial excerpt of that file and assigns the package the hash of the excerpt actually used. The runner checks that hash before generation. `--dry-run` prepares temporary workspaces with bug patches and estimates text as characters/3,5, including a reduced-prefix estimate; this estimate does not replace the real tokenizer and does not account exactly for the template or repairs.

## Verification and results

Visible verification determines whether a repair occurs. The private verifier is called only for the final score, after generation ends; if the final submission was rejected, the private score is still measured without feedback to the model. In continuation, follow-up is released only after visible acceptance of phase 1. The supervisor composes `WorkerRunner`, `worker_contract`, `practical_worker_guard` and baseline helpers for preparation, server, resources, classification and grader. Tests and grader run in a subprocess with the guard's Landlock/seccomp; isolation failure is infrastructure. The baseline grader must read the oracle in the same process that imports the candidate: this restriction does not prove oracle file protection against malicious candidate code during grading. Scores must be interpreted with that limitation, as in the baseline; private output is not inserted into the prompt.

Each `result.json` records states and phases, visible and private scores, `opencode_baseline.classify` category, reason, first-generation TTFT, `prompt_n`, `cache_n`, fraction `cache_n/(prompt_n+cache_n)`, generated tokens, median decode, total time, sampled VRAM peak, repairs and request events. Metrics missing from the server are `null`; TTFT is until the first content received, not a direct GPU measurement. Total time includes verification but excludes workspace preparation and server startup. Peak is sampled, not continuously measured.

`summary.json` aggregates valid episodes per arm with success and Wilson 95% CI, metric medians and infrastructure count. Pairing by task/repetition records concordant and discordant passes and times for both arms. Infrastructure episodes are excluded from denominator and pairing. Wilson is descriptive; repetitions of the same task are not independent observations. Upon detecting infrastructure failure, the driver preserves results and stops; there is no automatic resumption. The output directory must not already exist. There is no inferential comparison or multiple-comparison correction.

## Future execution

The real run uses GPU and must occur only after the current campaign ends and with specific authorization for inference. The driver refuses to run if `pgrep -x llama-server` detects another process or inspection fails. The check is not a global lock against another application starting a server afterward.

```sh
cd /path/to/4b-worker-v2
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.prefix_cache_campaign --dry-run
PYTHONDONTWRITEBYTECODE=1 /home/foxtrot/local-llm-benchmark/envs/lab-validation-20261028/bin/python -m benchmark.prefix_cache_campaign
```

Future output: `/home/foxtrot/local-llm-benchmark/results/qwen-4b-prefix-cache-v1`. The second command was not run. The streaming client implementation and tokenization endpoints were evaluated using fakes and local server code reading, without validation against a real server; this remains an acceptance item before interpreting data.

## Offline verification of this implementation

The dry run listed 108 units with numeric package and prefix estimates. Tests with fake server/model verify excerpt selection, reduction, cold/warm cycle, refusal, classification, streaming metrics, summary, repair and continuation; an additional test ran the visible verifier under guard in WSL. The real detector refused because `llama-server` was active. Frozen manifest comparison found 320 matching files. Selected worker and new tests passed; Ruff passed on the new files. No typecheck is configured or installed in the observed environment. The full suite was not run.

Driver/config/tests commit: `a9a6dc0`. Final verification: 94 selected tests passed; after the last error-handling adjustment, the 13 T3b tests passed again and Ruff was clean.

## Orchestrator fixes (29/10, 10h30)

- **Landlock neither protects nor allows paths on `/mnt/d` (drvfs/9p).** With the guard active, even `corpus/support` and `pytest.ini` returned permission denied. The 1st run therefore aborted: the evaluator failed and repair received the permission error, generating prose (`malformed_output`). The campaign now runs from an ext4 snapshot (`/home/foxtrot/local-llm-benchmark/src/4b-worker-v2-31a1d4b`, commit `31a1d4b`), where the probe confirms the rules work.
- **Repository `pytest.ini` allowed** read-only in the verifier sandbox: pytest searches for it upward from the oracle path.
- **Final newline restored** after the last `>>>>>>> REPLACE` marker: the server removes it at the end of generation, and the grammar requires each marker on an LF-terminated line.
- **Output in `qwen-4b-prefix-cache-v2`.** The aborted attempt from `/mnt/d` was archived as `-v2-drvfs-aborted`.
- **On ext4, two more blockers (commit `c05d697`, 13h25).**
  - pytest opens `/dev/null` for writing because it is the default log file. `/dev/null` now has write permission.
  - pytest also lists each directory from the repository root, defined by `pytest.ini`, to the oracle. The sandbox gained `listable_paths`, allowing only directory listings (names), without reading contents.
  - The aborted attempt was archived as `-v2-ext4-aborted-devnull`.

## Campaign results (29/10, 13h28–13h58)

The campaign ran from the ext4 snapshot, commit `c05d697`, and saved results in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-prefix-cache-v2`.

- 108 units, **0 infrastructure failures**.
- The prefix used was the entire `bottle-0.13.2` (179.962 bytes, about 46 thousand tokens), without truncation.

**Caveat:** at temperature 0, all three repetitions of each task were identical. The effective sample is **12 tasks per arm**, not 36.

### Latency: the cache works

| Arm | TTFT (median) | Processed prompt | Cache tokens | Time/episode | Decode | Median peak VRAM per episode |
|---|---:|---:|---:|---:|---:|---:|
| P-W16 (excerpts up to 16K, no prefix) | 82 ms | 557 | 2.844 | 8,3 s | 85 tok/s | 3.871 MiB |
| P-WL-cold (prefix about 46K, cold cache) | **16,1 s** | 46.075 | 0 | 22,1 s | 66 tok/s | 4.510 MiB |
| P-WL-warm (same prefix, already cached) | **158 ms** | 393 | 45.455 (99,5%) | 9,2 s | 67 tok/s | 4.508 MiB |

- With the repository prefix already cached, time to first token falls **about 100 times** (from 16 s to 0,16 s). Episode cost becomes similar to W16, even with 46 thousand context tokens.
- Long-context cost appears in decode: about 22% slower (85 → 67 tok/s).
- Long context uses about 640 MiB more VRAM.

### Quality: inconclusive because of two design defects

| Arm | Tasks passed | Edit failures: `zero_occurrences` / `malformed_output` |
|---|---|---|
| P-W16 | 2/12 (`cont_path`, `recover_decode`) | 5 / 1 tasks |
| P-WL-cold | 1/12 (`recover_decode`) | 6 / 4 tasks |
| P-WL-warm | 2/12 (`mcp_header`, `recover_decode`) | 6 / 4 tasks |

The pass rate was far below OpenCode's 68% with the same model. There are two reasons, neither being the model's ability to solve the task:

1. **The masked prefix induces the error.** `corpus/support/prefix.py` replaces lines touched by any task with `# task-specific line withheld`, to avoid leaking solutions in the common prefix. The model copies that marker into the SEARCH block, which then does not match the real file:
   - in P-WL-cold, this happened in 9 of the 18 units with `zero_occurrences`;
   - in P-WL-warm, in 12 of the 18.
2. **The F3 worker contract gives no repair opportunity when an edit does not apply.** In `worker_runner.py:234-236`, a rejected edit (`zero_occurrences` or `malformed_output`) ends the episode immediately. The sole repair (`repairs: 1`) occurs only after a visible test fails.

   Consequently, T3b measures the 4B's ability to copy an exact excerpt on the first attempt. W16 also fails at this in 5 of 12 tasks, without any marker involved. OpenCode's editing tool is more tolerant and returns the error for the model to try again.

Curious differences between cold and warm on the same task (`mcp_header`, `js_sign`, `cont_path`) indicate that prefill numerics change with cache: the same prompt at temperature 0 generates different outputs.

### Conclusion and next steps

- **Established:** a cached repository prefix is viable on the 3070. With 46 thousand tokens plus KV q4_0, peak was 4,5 GB, and TTFT falls to about 0,16 s.
- **Not established:** whether long context improves quality. Measuring this would require:
  1. showing the actual current excerpt of masked lines in the WL package (or building the unmasked prefix from each task's file), so SEARCH has a correct source;
  2. allowing a repair when an edit is rejected as well, returning the `zero_occurrences` diagnostic to the model;
  3. using 1 repetition at temperature 0, or 3 repetitions with sampling.

## v3: corrected design (29/10, 15h53 to 16h09)

Commits `852803f` (implementation, Codex Terra) and `c37ce40` (alignment fix). ext4 snapshot at `c37ce40`. Results in `/home/foxtrot/local-llm-benchmark/results/qwen-4b-prefix-cache-v3`. The 1st attempt aborted in the first WL episode and was archived in `-v3-aborted-align`: after the phase 1 edit, an omitted line aligned as deleted.

### What changed

- **Visible omitted lines.** WL packages gain a section with the current workspace text of all masked host lines. Each region comes with 2 lines of context and a line number. This is about 670 tokens in bottle and 180 in ms. W16 does not receive this section.
- **Repair after rejected edit.** The model receives the status and error message and can retry. This is behind an option (`repair_rejected_edits`), disabled by default in the worker.
- **Up to 2 repairs**, shared between rejected edits and visible tests.
- **1 repetition.** There are 36 units.

Caveat: WL receives information W16 does not. The W16 and WL comparison therefore does not isolate context size alone.

### Result

There were zero infrastructure failures.

| Arm | Passed | Episodes with edit repair | Last rejection | TTFT (median) | Time/episode |
|---|---|---:|---|---:|---:|
| P-W16 | 2/12 (`cont_path`, `recover_decode`) | 6 | 1 `zero_occurrences` | 1,0 s | 11,9 s |
| P-WL-cold | 2/12 (`cont_path`, `recover_decode`) | 10 | 9 `zero_occurrences`, 1 `malformed_output` | 17,8 s | 32,3 s |
| P-WL-warm | 2/12 (`cont_path`, `recover_decode`) | 9 | 8 `zero_occurrences`, 1 `malformed_output` | 2,1 s | 13,8 s |

The two passes are the same in all three arms. W16's dominant failure changed: in 7 of 12 tasks, the model responded `BLOCKED: insufficient_context` because the selected window did not contain the buggy code.

### Why v3 still does not measure quality

1. **The marker disappeared, but SEARCH is still wrong.** `marker_in_search` was 0 of 36 units. In WL, however, the model writes SEARCH from what it imagines is in the file rather than copying. Examples:
   - in `py_query`, `_parse_qsl` was indented as a method;
   - in `js_sign`, SEARCH includes a `Math.abs` absent from the file;
   - in `mcp_header` (both WL arms) and `recover_date` (cold only), the model copied the **line numbers** from the new section (`1606: ...`).
2. **Edit repair does not help at temperature 0.** The message says only "Search block was not found". With the same information and temperature 0, the model resends the same output, byte-for-byte identical: 15 of 17 edit repairs in cold WL, 14 of 16 in warm WL and 3 of 9 in W16. OpenCode's editing tool works because the model rereads the file after the error.

### Conclusion

- **Established again:** latency cost. Warm WL is close to W16 (13,8 s versus 11,9 s), and cold WL costs almost 3 times more (32,3 s).
- **Quality:** in this single-call worker with SEARCH/REPLACE, long context **did not improve** the pass rate (2/12 in all three arms). The bottleneck is the 4B's exact SEARCH copying, not lack of context. This applies to both the common prefix and the omitted-lines section.
- Continuing T3b would require changing the editing protocol, not the context. Two options:
  - return the closest lines from the real file in the error (approximate search);
  - accept SEARCH with normalized spaces or line-number anchors.

  Both change what is measured. Therefore, I recommend ending T3b with this conclusion and returning to the strong directions from stage 5.

Diagnostics: `scratchpad/t3bv3_diag.py`, `scratchpad/count_lineno.py` and `scratchpad/show_cands.py` and `scratchpad/count_repeats.py`. Output is in `scratchpad/t3bv3-diag.txt`.
