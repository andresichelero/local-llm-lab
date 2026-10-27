# Local cleanup — 2026-10-27

This is an inventory of changes made to a local workspace, not a deletion of tracked repository files. The active Qwen R3-DNS run continued independently in another checkout. Counts refer to the cleanup on this date and do not describe future disk state.

- Removed four pytest cache files (4,002 bytes) and 31 Python bytecode files (1,352,697 bytes) from the old `tmp/practical-repair-20261021` snapshot. The snapshot's source files and validation evidence were retained.
- Removed 19 regenerable PNG review images (5,550,753 bytes) from `tmp/pdfs/bonsai-review-20261020`. The source PDF was retained, and its SHA-256 matched the value in `archives/cleanup-20261021/INDEX.md` before removal. The extracted text and page map were then removed from the temporary folder after verifying their SHA-256 against the existing ZIP archive (119,486 bytes).
- Total removed: 7,026,938 bytes. Compression and filesystem allocation may make changes in free space differ.

The active model cache and runtime, current output, and historical records used to establish provenance were not included. Archived model files, logs and other temporary files were not removed merely because of their age; their dependencies or recoverability were not established. No R4 output was located in the checked paths. This cleanup does not establish that a large amount of space has been recovered.
