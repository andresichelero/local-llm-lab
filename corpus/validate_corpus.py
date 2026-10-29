"""Validate frozen tasks in disposable workspaces without model inference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from support.prefix import masked_prefix

ROOT = Path(__file__).resolve().parent
CLASSES = {"python_fix", "javascript_fix", "authored_tests", "continuation", "mcp", "tool_recovery"}


def hash_tree(root):
    root = Path(root)
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def check_manifest(root, expected):
    actual = hash_tree(root)
    return sorted(changed_paths(actual, expected))


def changed_paths(before, after):
    return {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}


def valid_outcomes(bug, reference, visible, original):
    return (bug, reference, visible, original) == (1, 0, 0, 0)


def corpus_hashes():
    entries = {}
    for folder in ("hosts", "tasks", "oracles", "stubs", "support", "prefixes"):
        base = ROOT / folder
        if base.exists():
            entries.update({f"{folder}/{key}": value for key, value in hash_tree(base).items()})
    return entries


def run(cmd, cwd, env):
    try:
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"runner infrastructure failure: {error}") from error
    return result.returncode


def classify_pytest(code, evidence):
    if code == 0 and evidence == {"assertions": 0, "errors": 0}:
        return 0
    if code == 1 and evidence.get("assertions", 0) > 0 and evidence.get("errors") == 0:
        return 1
    return 2


def run_oracle(oracle, workspace, env, phase):
    report = workspace.parent / f"pytest-probe-{phase}.json"
    env = dict(env, CORPUS_PROBE_REPORT=str(report))
    code = run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "corpus_probe", "-q", str(oracle)], workspace, env)
    try:
        evidence = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 2
    return classify_pytest(code, evidence)


def read_stub(task_id, env):
    path = ROOT / "stubs" / task_id / "tool.py"
    outputs = []
    for _ in range(2):
        result = subprocess.run([sys.executable, str(path)], env=env, capture_output=True, timeout=10, check=False)
        if result.returncode:
            raise RuntimeError("stub execution failed")
        outputs.append(result.stdout)
    if outputs[0] != outputs[1]:
        raise ValueError("stub output is not deterministic")
    data = json.loads(outputs[0])
    if not isinstance(data, dict) or not isinstance(data.get("function"), str) or not isinstance(data.get("args"), list) or "expected" not in data:
        raise ValueError("invalid stub contract")
    return data


def check_stub(data, workspace, env):
    program = (
        "import bottle,json,sys; d=json.loads(sys.argv[1]); "
        "a=[bytes(x['bytes']) if isinstance(x,dict) and 'bytes' in x else x for x in d['args']]; "
        "v=getattr(bottle,d['function'])(*a); "
        "assert json.loads(json.dumps(v)) == d['expected']"
    )
    return run([sys.executable, "-c", program, json.dumps(data)], workspace, env)


def apply_patch(path, cwd, env):
    if path.stat().st_size and run(["git", "apply", "--whitespace=nowarn", str(path)], cwd, env):
        raise RuntimeError(f"cannot apply {path.name}")


def validate_task(task_dir, node):
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    task_id = task["id"]
    if task_id != task_dir.name or task["class"] not in CLASSES:
        raise ValueError("task identity or class mismatch")
    host = ROOT / "hosts" / task["host"]
    if host.parent != ROOT / "hosts" or not host.is_dir():
        raise ValueError("invalid host")
    writable = set(task["writable_files"])
    if not writable or any(Path(path).is_absolute() or ".." in Path(path).parts for path in writable):
        raise ValueError("invalid writable file")
    if any(path.is_symlink() for path in host.rglob("*")):
        raise ValueError("host contains symlink")
    oracle = ROOT / "oracles" / task_id / "oracle.py"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", CORPUS_SUPPORT=str(ROOT / "support"))
    stub = read_stub(task_id, env) if task["class"] in {"mcp", "tool_recovery"} else None
    with tempfile.TemporaryDirectory(prefix="corpus-validation-") as tmp:
        workspace = Path(tmp) / "workspace"
        shutil.copytree(host, workspace)
        env["PYTHONPATH"] = str(workspace) + os.pathsep + env["CORPUS_SUPPORT"]
        env["CORPUS_NODE"] = node
        before = hash_tree(workspace)
        apply_patch(task_dir / "bug.patch", workspace, env)
        buggy = hash_tree(workspace)
        if changed_paths(before, buggy) - writable:
            raise ValueError("bug patch changes files outside writable scope")
        if task["class"] == "continuation" and run([sys.executable, str(task_dir / "verify_phase1.py")], workspace, env):
            raise ValueError("continuation phase-one check failed")
        bug = run_oracle(oracle, workspace, env, "bug")
        bug_stub = check_stub(stub, workspace, env) if stub else None
        apply_patch(task_dir / "reference.patch", workspace, env)
        fixed = hash_tree(workspace)
        if not changed_paths(buggy, fixed) or changed_paths(buggy, fixed) - writable:
            raise ValueError("reference patch is empty or changes files outside writable scope")
        reference = run_oracle(oracle, workspace, env, "reference")
        reference_stub = check_stub(stub, workspace, env) if stub else None
        visible = run([sys.executable, str(task_dir / "verify.py")], workspace, env)
        if task["host"].startswith("bottle-"):
            original_cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "test"]
        else:
            original_cmd = [node, "--test", str(ROOT / "support" / "ms_original.test.cjs")]
        original = run(original_cmd, workspace, env)
    stub_ok = stub is None or (bug_stub == 1 and reference_stub == 0)
    return valid_outcomes(bug, reference, visible, original) and stub_ok, (bug, reference, visible, original)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task")
    parser.add_argument("--node", default=os.environ.get("CORPUS_NODE", "node"))
    parser.add_argument("--write-manifest", action="store_true")
    args = parser.parse_args()
    manifest = ROOT / "manifest.json"
    if args.write_manifest:
        prefix_dir = ROOT / "prefixes"
        prefix_dir.mkdir(exist_ok=True)
        for host in ("bottle-0.13.2", "ms-2.1.3"):
            (prefix_dir / f"{host}.txt").write_text(masked_prefix(ROOT, host), encoding="utf-8", newline="\n")
        manifest.write_text(json.dumps(corpus_hashes(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("manifest written")
        return 0
    expected = json.loads(manifest.read_text(encoding="utf-8"))
    actual = corpus_hashes()
    mismatches = sorted(key for key in expected.keys() | actual.keys() if expected.get(key) != actual.get(key))
    if mismatches:
        print("manifest mismatch:", ", ".join(mismatches))
        return 1
    for host in ("bottle-0.13.2", "ms-2.1.3"):
        prefix = (ROOT / "prefixes" / f"{host}.txt").read_text(encoding="utf-8")
        if prefix != masked_prefix(ROOT, host):
            print(f"invalid prefix: {host}")
            return 1
    tasks = sorted((ROOT / "tasks").iterdir())
    metadata = [json.loads((task / "task.json").read_text(encoding="utf-8")) for task in tasks]
    if len(tasks) != 12 or any(sum(t["class"] == c for t in metadata) != 2 for c in CLASSES):
        print("invalid task count or class distribution")
        return 1
    if args.task:
        tasks = [task for task in tasks if task.name == args.task]
        if not tasks:
            print("unknown task")
            return 1
    success = True
    for task_dir in tasks:
        try:
            ok, result = validate_task(task_dir, args.node)
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            print(f"{task_dir.name}: infrastructure error: {error}")
            success = False
            continue
        print(f"{task_dir.name}: {'PASS' if ok else 'FAIL'} bug/oracle/visible/original={result}")
        success &= ok
    print(f"RESULT: {'PASS' if success else 'FAIL'} ({len(tasks)} tasks)")
    return int(not success)


if __name__ == "__main__":
    sys.exit(main())
