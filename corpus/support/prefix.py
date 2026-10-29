"""Build a stable large-context prefix without exposing task solutions."""

import json
from pathlib import Path


def masked_prefix(root, host):
    root = Path(root)
    source_name = "index.js" if host.startswith("ms-") else "bottle.py"
    source = (root / "hosts" / host / source_name).read_text(encoding="utf-8")
    removed = set()
    for task in sorted((root / "tasks").iterdir()):
        meta = json.loads((task / "task.json").read_text(encoding="utf-8"))
        if meta["host"] != host:
            continue
        patch = (task / "bug.patch").read_text(encoding="utf-8")
        removed.update(line[1:] for line in patch.splitlines() if line.startswith("-") and not line.startswith("---") and line[1:])
    lines = source.splitlines(keepends=True)
    marker = "/* task-specific line withheld */\n" if source_name.endswith(".js") else "# task-specific line withheld\n"
    return "".join(marker if line.rstrip("\r\n") in removed else line for line in lines)
