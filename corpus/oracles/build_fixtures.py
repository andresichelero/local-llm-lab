"""Rebuild the frozen task fixtures; this file is supervisor-only material."""

import difflib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOTTLE = (ROOT / "hosts/bottle-0.13.2/bottle.py").read_text(encoding="utf-8")
MS = (ROOT / "hosts/ms-2.1.3/index.js").read_text(encoding="utf-8")


def diff(before, after, name):
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                      fromfile=f"a/{name}", tofile=f"b/{name}"))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def make(task_id, cls, old, new, objective, visible, private, difficulty="medium", stub=None, phases=None):
    js = cls == "javascript_fix"
    host = "ms-2.1.3" if js else "bottle-0.13.2"
    name = "index.js" if js else "bottle.py"
    source = MS if js else BOTTLE
    assert source.count(old) == 1, (task_id, source.count(old))
    buggy = source.replace(old, new, 1)
    task = ROOT / "tasks" / task_id
    metadata = {
        "id": task_id, "class": cls, "host": host, "objective": objective,
        "relevant_files": [name], "writable_files": [name],
        "invariants": ["Preserve the public API and unrelated behavior.", "Do not modify upstream tests."],
        "difficulty": difficulty,
    }
    if stub:
        metadata["stub"] = f"corpus/stubs/{task_id}/tool.py"
        metadata["adaptation"] = "A deterministic tool response supplies the external evidence for an edit in Bottle; no live MCP service is required."
        write(ROOT / "stubs" / task_id / "tool.py", "import json\n\nprint(json.dumps(" + repr(stub) + ", sort_keys=True))\n")
    if phases:
        metadata["objective"] = phases[0]
        metadata["phase"] = 1
        metadata["visible_test"] = "verify_phase1.py"
        write(task / "followup.json", json.dumps({"phase": 2, "objective": objective, "visible_test": "verify.py"}, indent=2) + "\n")
        first_check = "bottle.html_escape('<') == '&lt;'" if task_id == "cont_quote" else "bottle.path_shift('/app', '/x/y', 1) == ('/app/x', '/y') and bottle.path_shift('/app/x', '/y', -1) == ('/app', '/x/y')"
        write(task / "visible_phase1.py", py_visible(first_check))
        write(task / "verify_phase1.py", "import runpy\nimport sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path.cwd()))\nrunpy.run_path(str(Path(__file__).with_name('visible_phase1.py')), run_name='__main__')\n")
    write(task / "task.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    write(task / "bug.patch", diff(source, buggy, name))
    write(task / "reference.patch", diff(buggy, source, name))
    write(task / "visible.py", visible)
    write(task / "verify.py", "import runpy\nimport sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path.cwd()))\nrunpy.run_path(str(Path(__file__).with_name('visible.py')), run_name='__main__')\n")
    write(ROOT / "oracles" / task_id / "oracle.py", private)


def py_visible(expr):
    return "import bottle\n\nassert " + expr + "\nprint('visible: PASS')\n"


def py_oracle(expressions):
    return "import bottle\n\n\ndef test_private_contract():\n" + "".join("    assert " + x + "\n" for x in expressions)


def js_visible(code):
    return "import os\nimport subprocess\n\nsubprocess.run([os.environ.get('CORPUS_NODE', 'node'), '-e', " + repr(code) + "], check=True)\nprint('visible: PASS')\n"


def js_oracle(code):
    wrapped = "try { " + code + "; console.log('PASS'); } catch (e) { if (e && e.code === 'ERR_ASSERTION') { console.log('ASSERT'); process.exitCode = 1; } else { console.error(e); process.exitCode = 2; } }"
    return ("import os\nimport subprocess\n\n\ndef test_private_contract():\n"
            "    result = subprocess.run([os.environ['CORPUS_NODE'], '-e', " + repr(wrapped) + "], capture_output=True, check=False)\n"
            "    if (result.returncode, result.stdout.strip()) not in {(0, b'PASS'), (1, b'ASSERT')}:\n"
            "        raise RuntimeError('JavaScript oracle infrastructure failure')\n"
            "    assert result.returncode == 0\n")


def make_authored(task_id, function, assertions, mutations, objective):
    name = f"test/test_{task_id}.py"
    tests = "import bottle\n\n\ndef test_contract():\n" + "".join("    assert " + a + "\n" for a in assertions)
    task = ROOT / "tasks" / task_id
    meta = {"id": task_id, "class": "authored_tests", "host": "bottle-0.13.2", "objective": objective,
            "relevant_files": ["bottle.py", "test"], "writable_files": [name],
            "invariants": ["Do not modify bottle.py or existing tests.", "Tests must pass on the original implementation."], "difficulty": "medium"}
    write(task / "task.json", json.dumps(meta, indent=2) + "\n")
    write(task / "bug.patch", "")
    write(task / "reference.patch", "--- /dev/null\n+++ b/" + name + "\n@@ -0,0 +1," + str(len(tests.splitlines())) + " @@\n" + "".join("+" + line for line in tests.splitlines(True)))
    visible = (
        "import subprocess\nimport sys\nfrom pathlib import Path\n\n"
        "assert Path(" + repr(name) + ").is_file()\n"
        "subprocess.run([sys.executable, '-m', 'pytest', '-p', 'no:cacheprovider', '-q', "
        + repr(name) + "], check=True)\n"
        "print('visible: authored tests pass')\n"
    )
    write(task / "visible.py", visible)
    write(task / "verify.py", "import runpy\nimport sys\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path.cwd()))\nrunpy.run_path(str(Path(__file__).with_name('visible.py')), run_name='__main__')\n")
    oracle = '''import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def test_authored_suite_detects_two_mutants():
    root = Path.cwd()
    test_file = Path(NAME)
    assert test_file.is_file()
    original = (root / "bottle.py").read_text(encoding="utf-8")
    for mutation in [None, *MUTATIONS]:
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
'''.replace("NAME", repr(name)).replace("MUTATIONS", repr(mutations))
    write(ROOT / "oracles" / task_id / "oracle.py", oracle)


def main():
    make("py_range", "python_fix", "min(int(end) + 1, maxlen)", "min(int(end), maxlen)",
         "Repair HTTP byte ranges: explicit ends are inclusive, while yielded ends are exclusive; clamp to resource length and skip invalid ranges.",
         py_visible("list(bottle.parse_range_header('bytes=2-4', 10)) == [(2, 5)]"),
         py_oracle(["list(bottle.parse_range_header('bytes=0-0,5-99,-2', 8)) == [(0, 1), (5, 8), (6, 8)]", "list(bottle.parse_range_header('bytes=9-12', 8)) == []"]))
    make("py_query", "python_fix", "value = urlunquote(nv[1].replace('+', ' '))", "value = urlunquote(nv[1])",
         "Restore form query decoding, including plus as space in values, percent escapes, blank values and ordering of repeated keys.",
         py_visible("bottle._parse_qsl('q=two+words') == [('q', 'two words')]"),
         py_oracle(["bottle._parse_qsl('x=a+b&x=%2B&empty=') == [('x', 'a b'), ('x', '+'), ('empty', '')]", "bottle._parse_qsl('a=1&&b') == [('a', '1'), ('b', '')]"]))
    make("js_sign", "javascript_fix", "var n = parseFloat(match[1]);", "var n = Math.abs(parseFloat(match[1]));",
         "Repair signed duration parsing, retaining fractional and case-insensitive units without changing formatting.",
         js_visible("const a=require('node:assert/strict'),ms=require('./');a.equal(ms('-1h'),-3600000)"),
         js_oracle("const a=require('node:assert/strict'),ms=require('./');a.equal(ms('-.5H'),-1800000);a.equal(ms('-3ms'),-3);a.equal(ms('2s'),2000)"))
    make("js_plural", "javascript_fix", "var isPlural = msAbs >= n * 1.5;", "var isPlural = msAbs >= n * 2;",
         "Restore the long-format singular/plural boundary at 1.5 units, for negative as well as positive durations.",
         js_visible("const a=require('node:assert/strict'),ms=require('./');a.equal(ms(1500,{long:true}),'2 seconds')"),
         js_oracle("const a=require('node:assert/strict'),ms=require('./');a.equal(ms(1499,{long:true}),'1 second');a.equal(ms(1500,{long:true}),'2 seconds');a.equal(ms(-1500,{long:true}),'-1 seconds')"))
    make("cont_quote", "continuation", ".replace('\\r', '&#13;').replace('\\t', '&#9;')", ".replace('\\r', '&#13;')",
         "Complete the second delivery: HTML attribute quoting must escape control whitespace as well as HTML metacharacters.",
         py_visible("bottle.html_quote('a\\tb') == '\"a&#9;b\"'"),
         py_oracle(["bottle.html_quote('<\\t&\\n\\r') == '\"&lt;&#9;&amp;&#10;&#13;\"'", "bottle.html_quote('x') == '\"x\"'"]),
         phases=["First delivery: preserve HTML metacharacter escaping.", "Follow-up: preserve tab, newline and carriage-return escaping in attribute values."])
    make("cont_path", "continuation", "if path_info.endswith('/') and pathlist: new_path_info += '/'", "if False: new_path_info += '/'",
         "Complete the follow-up to path shifting: preserve a trailing slash on a nonempty remaining path while supporting shifts in both directions.",
         py_visible("bottle.path_shift('/app', '/one/two/', 1) == ('/app/one', '/two/')"),
         py_oracle(["bottle.path_shift('/app', '/a/b/', 1) == ('/app/a', '/b/')", "bottle.path_shift('/app/x', '/b/', -1) == ('/app', '/x/b/')", "bottle.path_shift('/a', '/b/', 0) == ('/a', '/b/')"]),
         phases=["First delivery: shift path fragments in both directions.", "Follow-up: preserve a trailing slash in the remaining path."])
    make("mcp_header", "mcp", "return key.title().replace('_', '-')", "return key.title()",
         "Inspect the deterministic tool output, then repair Bottle header-name normalization to satisfy its reported interoperability contract.",
         py_visible("isinstance(bottle._hkey('content-type'), str)"),
         py_oracle(["bottle._hkey('x_request_id') == 'X-Request-Id'", "bottle._hkey('content-type') == 'Content-Type'"]),
         stub={"tool": "header_contract", "function": "_hkey", "args": ["x_request_id"], "expected": "X-Request-Id", "rule": "underscores map to hyphens"})
    make("mcp_params", "mcp", "values[-1][1][name.strip().lower()] = value.strip()", "values[-1][1][name.strip()] = value.strip()",
         "Read the tool response describing a downstream header parser failure, then fix parameter-name normalization in Bottle.",
         py_visible("bottle._parse_http_header('text/plain') == [('text/plain', {})]"),
         py_oracle(["bottle._parse_http_header('text/html; Q=0.5,application/json; LEVEL=1') == [('text/html', {'q': '0.5'}), ('application/json', {'level': '1'})]", "bottle._parse_http_header('text/plain') == [('text/plain', {})]"]),
         stub={"tool": "header_diagnostic", "function": "_parse_http_header", "args": ["text/plain; CHARSET=UTF-8"], "expected": [["text/plain", {"charset": "UTF-8"}]], "observed": "parameter CHARSET not found", "rule": "parameter names are case-insensitive"})
    make("recover_decode", "tool_recovery", "return s.decode(enc, err)", "return s.decode(enc)",
         "Inspect the deterministic failure report and repair Bottle's byte-to-text conversion while preserving its public behavior.",
         py_visible("bottle.touni(b'plain') == 'plain'"),
         "import bottle\n\n\ndef test_private_contract():\n    try:\n        replaced = bottle.touni(bytes([255]), err='replace')\n        ignored = bottle.touni(bytes([255]), err='ignore')\n    except UnicodeDecodeError:\n        assert False, 'decode error policy was not honored'\n    assert replaced == '\\ufffd'\n    assert ignored == ''\n    assert bottle.touni(b'hello') == 'hello'\n",
         stub={"tool": "decode_test_runner", "first_attempt": "UnicodeDecodeError despite replacement policy", "retry": "honor the specified decode error policy", "function": "touni", "args": [{"bytes": [255]}, "utf8", "replace"], "expected": "\ufffd"})
    make("recover_date", "tool_recovery", "calendar.timegm(ts[:8] + (0, )) - (ts[9] or 0)", "calendar.timegm(ts[:8] + (0, ))",
         "Inspect the deterministic failure report and repair Bottle's HTTP date conversion, preserving its behavior for invalid input.",
         py_visible("bottle.parse_date('not a date') is None"),
         py_oracle(["bottle.parse_date('Sun, 06 Nov 1994 08:49:37 GMT') == bottle.parse_date('Sun, 06 Nov 1994 09:49:37 +0100')", "bottle.parse_date('not a date') is None"]),
         stub={"tool": "date_check", "first_attempt": "FAIL: +0100 differs from equivalent GMT", "retry": "subtract parsed UTC offset", "function": "parse_date", "args": ["Sun, 06 Nov 1994 09:49:37 +0100"], "expected": 784111777})
    make_authored("tests_query", "_parse_qsl", ["bottle._parse_qsl('q=a+b&q=%2B') == [('q', 'a b'), ('q', '+')]", "bottle._parse_qsl('x=1&x=2') == [('x', '1'), ('x', '2')]"],
                  [("value = urlunquote(nv[1].replace('+', ' '))", "value = urlunquote(nv[1])"), ("r.append((key, value))", "r.insert(0, (key, value))")],
                  "Write tests for Bottle form query parsing: plus-as-space, encoded plus, duplicate keys and ordering. Do not change implementation.")
    make_authored("tests_range", "parse_range_header", ["list(bottle.parse_range_header('bytes=0-0', 3)) == [(0, 1)]", "list(bottle.parse_range_header('bytes=-2', 5)) == [(3, 5)]"],
                  [("min(int(end) + 1, maxlen)", "min(int(end), maxlen)"), ("max(0, maxlen - int(end)), maxlen", "0, maxlen")],
                  "Write tests for Bottle HTTP byte ranges that detect inclusive-end and suffix-range regressions. Do not change implementation.")


if __name__ == "__main__":
    main()
