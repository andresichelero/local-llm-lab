# Local cleanup — 2026-10-27

The cleanup below affected local files under `D:\Usuario\Downloads\LLM`, not tracked files in the active campaign checkout. The Qwen R3-DNS run continued independently. Counts are a dated checkpoint, not a live free-space measurement.

## Space and models

- Removed `wsl-storage-archive/2026-10-26/legacy-gguf-models.tar` (17,952,921,600 bytes): it contained Gemma 4 12B Q4_0, Ornith 1.0 9B Q4_K_M, and Granite 4.2 8B Q4_K_M. They were absent from the active Qwen catalog and configuration. Their earlier WSL originals had already been removed; these weights now require reacquisition if needed again. A local record remains in `archives/legacy-models-removed-20261027.md`.
- Removed 3,655 files (54,884,955 bytes) from a disposable `node_modules` tree belonging to the 2026-10-13 synthetic, no-model audit. The other audit files were compressed into `archives/audit-session-20261013-sem-dependencias.zip` and verified by SHA-256. Seven read-only Git object files remain in the archived remnants directory.
- Removed 19 regenerable PNG review images (5,550,753 bytes) after verifying the source PDF hash; removed the text and page map (119,486 bytes) after comparing their hashes with the existing ZIP.

## Root organization

- Removed seven loose historical documents/scripts only after comparing each hash with the existing `historical-notes-and-granite-scripts-20261012-16.zip`. Archived the old handoff and QLoRA bundle as `historico-raiz-20261027.zip`, verifying both hashes before removing the loose copies.
- Compressed 34 historical report files as `reports-20261016.zip`; verified all 34 hashes before removing the originals. Compressed seven temporary Ornith scripts as `ornith-scripts-temporarios-20261016.zip` and verified them before removing the originals.
- Removed 238 files (2,370,124 bytes) from the old practical-repair temporary snapshot after confirming each matched `practical-repair-preparation-20261021.zip`. Earlier in the same cleanup, removed four pytest cache files (4,002 bytes) and 31 bytecode files (1,352,697 bytes).
- Removed the clean `local-llm-lab-cross-model-phase1` worktree via Git; its local branch and commits remain in the shared repository. Kept the main `local-llm-lab` repository because it contains shared Git data and local changes, the active `practical-agent-v2` worktree, and this PR worktree while the PR is being updated.
- `reports/` and `tmp/` may reappear when other work creates new output; do not assume they are obsolete based on directory name alone.

The active Qwen cache, runtime, outputs, imported provenance, and the v4/r1/r2 recovery sources were retained. Filesystem free space also changes as the campaign downloads and stages models.
