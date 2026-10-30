import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def test_authored_suite_detects_mutants():
    root = Path.cwd()
    test_file = Path('test/test_tests_escape.py')
    assert test_file.is_file()
    original = (root / "bottle.py").read_text(encoding="utf-8")
    for mutation in [None, *[(".replace('&', '&amp;')", ".replace('&', '&')"), ('.replace("\'", \'&#039;\')', '.replace("\'", "\'")'), ('.replace(\'"\', \'&quot;\')', '.replace(\'"\', \'"\')'), (".replace('<', '&lt;')", ".replace('<', '<')"), (".replace('>', '&gt;')", ".replace('>', '>')"), ("return string.replace('&', '&amp;')", "return (string if any(c in string for c in \"&<>\\\"'\") else string.upper()).replace('&', '&amp;')")]]:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "workspace"
            shutil.copytree(root, target)
            if mutation is not None:
                old, new = mutation
                assert original.count(old) == 1
                (target / "bottle.py").write_text(original.replace(old, new, 1), encoding="utf-8")
            report = Path(temp) / "report.json"
            env = dict(os.environ, PYTHONPATH=str(target) + os.pathsep + os.environ["CORPUS_SUPPORT"], PYTHONDONTWRITEBYTECODE="1", CORPUS_PROBE_REPORT=str(report))
            result = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "corpus_probe", "-q", str(test_file)], cwd=target, env=env, capture_output=True, check=False)
            assert result.returncode == (0 if mutation is None else 1)
            evidence = json.loads(report.read_text(encoding="utf-8"))
            assert evidence["errors"] == 0
            assert (evidence["assertions"] == 0) if mutation is None else (evidence["assertions"] > 0)
