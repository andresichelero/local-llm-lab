"""Small Git provenance helpers shared by benchmark runners."""
from __future__ import annotations

import subprocess
from pathlib import Path


def git_provenance(repository: Path) -> tuple[str, bool]:
    """Return HEAD and whether benchmark source (excluding generated results) is dirty."""
    root = repository.resolve()
    revision = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status = subprocess.run(
        [
            "git", "-C", str(root), "status", "--porcelain", "--untracked-files=all",
            "--", ".", ":(exclude)results/**",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return revision, bool(status.strip())
