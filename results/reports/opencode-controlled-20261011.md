# Controlled OpenCode delegation probe — 2026-10-11

## Outcome

The bounded read-only smoke passed, and the control arm completed the calculator task within its 180-second cap. The treatment arm made the requested code changes and passed the independent grader, but reached the 180-second cap before calling `independent-reviewer`. The predeclared workflow gate therefore failed and the run stopped: there were no warm-ups or measured pairs. This is an incomplete treatment workflow, not evidence that delegation improves or worsens code quality.

## Runtime and gates

- Source snapshot: `80a50c5041bf0deef219fcf495aff6c6a5e2c40c`, clean for source files. The `git_provenance` check excludes generated `results/**` content.
- OpenCode: `1.19.0`. llama.cpp: `0.6.0-dev`, commit `d81235049`.
- Model: Qwen3.5-9B Q4_K_M, revision `3885219b6810b007914f3a7950a8d1b469d598a5`, SHA-256 `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`.
- Server: local endpoint `127.0.0.1:8080`, context 16,384, 99 GPU layers, flash attention on, Q4_0 K/V cache, prompt cache off, one slot, reasoning off. The explicit SSD bundle `LD_LIBRARY_PATH` preflight passed.
- The effective smoke profile had 10 primary steps. Both named children were subagents with explicit `bash=deny` and `edit=deny`; the primary’s effective task rules matched the tracked profile. The 20-step control profile denied all task calls. The treatment profile allowed only `repo-explorer` and `independent-reviewer`, with the wildcard task rule still denied. Each effective profile and its hash are in the raw records.
- Focused runner tests: 6 passed. Python compilation and `git diff --check` passed before the source snapshot was created.

## Runs

| Run | Result | Wall time | Evidence |
|---|---|---:|---|
| Read-only smoke, first run | Passed | 20.132 s | Exact three test names; one completed `repo-explorer`; no workspace changes; all effective-profile checks passed. |
| Read-only smoke, sequence run | Passed | 20.132 s | Same exact output and no-change gate. |
| Control calibration | Passed | 44.075 s | Exit 0; grader, unit tests, and behavior probe passed; changes stayed within `src/calculator.py` and `tests/test_calculator.py`; no completed child task calls. |
| Treatment calibration | Workflow failed at cap | 180.378 s | OpenCode was terminated at the 180 s limit (return `-15`). The independent grader, unit tests, behavior probe, and scope checks passed. Events show one completed `repo-explorer`, edits, and successful `python -m unittest` calls, including one after the final edit. No completed `independent-reviewer` call occurred, so workflow success is false. |

The treatment timeout is retained in the denominator as a failed workflow. Because calibration did not pass both arms, the planned warm-up and three alternating measured pairs were not run. No parameters were tuned after the result.

Resource samples use the sampler’s native field units; `*_mb_*` fields are reported as MB. In the full sequence, smoke peak RAM was 2,322 MB and peak VRAM 6,031 MB. Control peaks were 2,380 MB RAM and 6,030 MB VRAM. Treatment peaks were 2,930 MB RAM and 6,030 MB VRAM; swap peaked at 45 MB in all three. The separate first smoke peaked at 2,247 MB RAM and 6,035 MB VRAM. These are sampled system-wide WSL/GPU values, not OpenCode RSS or total installed capacity. The complete raw samples remain with each run.

## Provenance and retained artifacts

The tracked profile SHA-256 is `1c9a852168ea3df6ff2afef26dacee19bc160efe56989b4120157b5fa5abdef3`. The read-only fixture SHA-256 is `4a4eac3a530a28832cd02d0d73a57d0ebe6a5b74dcc5e93975ca0bfeac06eb1b`; the calculator fixture SHA-256 is `f80943a2205b218e485c6fbcb171de7fed32b48da83055e3a8497cc4f32507e6`.

The full sequence output is `/home/foxtrot/local-llm-benchmark/results/raw/opencode-controlled-20261011-20261011T212845Z` on WSL ext4. The initial smoke output is `/home/foxtrot/local-llm-benchmark/results/raw/opencode-controlled-20261011-20261011T212742Z`. Selected records, events, effective settings, resources, prompts, and server logs were copied into the corresponding `results/raw/opencode-controlled-20261011-*` folders beside this report. OpenCode-generated package and config caches were excluded from the Windows copy and archive; the original ext4 outputs remain intact.

The separate preflight diagnostic is at `results/raw/opencode-controlled-20261011-preflight-failure-212546Z`. It records that the llama.cpp version banner was on stderr while the first runner revision checked stdout; no server or model run began in that attempt. The stream handling was corrected and covered by a focused test.

The selected evidence was archived to `E:\LocalLLMLabArchive\2026-10-11\opencode-controlled-probe-20261011.tar.gz` (37 entries, 35 KiB). SHA-256: `6f14213c9d2bad0112aaae082579d3f6ceafe0317c174e9614fdefff9fb04ba4`.

All probe-owned llama-server, OpenCode, and resource-sampler processes were stopped after the run. The archived result includes the timed-out attempt; the original ext4 outputs and the Windows raw copies are retained.

## Reproduction

From a clean checkout at the source commit on C-backed WSL ext4, with the pinned model and installed runtimes present:

```bash
python3 -m benchmark.opencode_controlled_probe --phase all
```

The runner chooses a unique timestamped SSD output directory and checks space, GPU headroom, model hash, library resolution, runtime version and port availability before launching its own server. It enforces the smoke/calibration gates before any repetitions. An explicit `--output-root` must be a new ext4 directory. Retain failed calibration rows and the censored timeout; do not use this one pair as a completed-task latency ranking.
