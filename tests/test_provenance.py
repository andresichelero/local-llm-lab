from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from benchmark.provenance import git_provenance


class GitProvenanceTests(unittest.TestCase):
    def make_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Lab Test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "lab@example.invalid"], check=True)
        (root / "source.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "source.py"], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "--quiet", "-m", "baseline"], check=True)

    def test_untracked_source_marks_worktree_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_repo(root)
            (root / "new_source.py").write_text("value = 2\n", encoding="utf-8")

            revision, dirty = git_provenance(root)

            self.assertEqual(len(revision), 40)
            self.assertTrue(dirty)

    def test_generated_results_are_excluded_but_tracked_source_edits_are_not(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.make_repo(root)
            generated = root / "results/raw"
            generated.mkdir(parents=True)
            (generated / "run.jsonl").write_text("{}\n", encoding="utf-8")
            self.assertFalse(git_provenance(root)[1])

            (root / "source.py").write_text("value = 3\n", encoding="utf-8")
            self.assertTrue(git_provenance(root)[1])


if __name__ == "__main__":
    unittest.main()
