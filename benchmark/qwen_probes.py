"""Twelve fixed qualification checks. Candidate Python executes only in namespaces."""

from __future__ import annotations

import json
import tempfile
import time
import secrets
import shutil
from pathlib import Path

from benchmark.qwen_optimization import write_json

CODE_CASES = [
    dict(
        prompt="Write solve(value, low, high): clamp a number inclusively; raise ValueError if low > high.",
        reference="def solve(value, low, high):\n if low > high: raise ValueError()\n return min(high,max(low,value))",
        checks='assert solve(2,3,7)==3\nassert solve(9,3,7)==7\nassert solve(4,3,7)==4\ntry:\n solve(0,4,2)\nexcept ValueError: pass\nelse: raise AssertionError("invalid range")',
    ),
    dict(
        prompt="Write solve(values): return a new list removing duplicates while preserving first occurrence. Values are JSON scalars.",
        reference="def solve(values):\n result=[]\n for v in values:\n  if v not in result: result.append(v)\n return result",
        checks='x=[3,1,3,2,1]\nassert solve(x)==[3,1,2]\nassert x==[3,1,3,2,1]\nassert solve([])==[]\nassert solve(["a","b","a"])==["a","b"]',
    ),
    dict(
        prompt="Write solve(defaults, overrides): recursively merge dictionaries, overrides win, lists replace. Result and all nested lists/dicts must be independent copies of both inputs.",
        reference="import copy\ndef solve(a,b):\n r=copy.deepcopy(a)\n for k,v in b.items():\n  r[k]=solve(r[k],v) if isinstance(r.get(k),dict) and isinstance(v,dict) else copy.deepcopy(v)\n return r",
        checks='a={"x":{"y":[{"v":1}]},"z":1};b={"w":[{"q":2}],"z":3}\nr=solve(a,b)\nassert r["z"]==3\nr["x"]["y"][0]["v"]=9;r["w"][0]["q"]=9\nassert a["x"]["y"][0]["v"]==1 and b["w"][0]["q"]==2',
    ),
    dict(
        prompt="Write solve(attempts, base, cap): list of delays min(base * 2**i, cap) for i from zero to attempts-1. Reject negative attempts, base or cap with ValueError.",
        reference="def solve(n,b,c):\n if min(n,b,c)<0: raise ValueError()\n return [min(b*2**i,c) for i in range(n)]",
        checks="assert solve(5,2,7)==[2,4,7,7,7]\nassert solve(0,2,7)==[]\nassert solve(2,0,7)==[0,0]\nfor args in [(-1,2,7),(1,-2,7),(1,2,-7)]:\n try:\n  solve(*args)\n except ValueError: pass\n else: raise AssertionError()",
    ),
    dict(
        prompt="Write solve(obj, path, default=None): retrieve nested dictionary keys given as a list. Missing key or non-dict returns default. Empty path returns obj. Do not mutate obj.",
        reference="def solve(obj,path,default=None):\n for k in path:\n  if not isinstance(obj,dict) or k not in obj:return default\n  obj=obj[k]\n return obj",
        checks='x={"a":{"b":None,"c":4}}\nassert solve(x,["a","c"])==4\nassert solve(x,["a","b"],9) is None\nassert solve(x,["missing"],9)==9\nassert solve(x,["a","c","d"],9)==9\nassert solve(x,[]) is x',
    ),
    dict(
        prompt="Write solve(rows): CSV string with header name,count and newline \\n. Rows are dictionaries containing name and count. Quote commas, quotes and newlines correctly. Preserve Unicode.",
        reference='import csv,io\ndef solve(rows):\n s=io.StringIO(newline="")\n w=csv.writer(s,lineterminator="\\n");w.writerow(["name","count"])\n for r in rows:w.writerow([r["name"],r["count"]])\n return s.getvalue()',
        checks='import csv,io\nrows=[{"name":"a,b","count":2},{"name":"á\\nq\\"","count":0}]\nr=solve(rows)\nassert r.endswith("\\n")\nassert list(csv.reader(io.StringIO(r)))==[["name","count"],["a,b","2"],["á\\nq\\"","0"]]',
    ),
]


def grade_code(code, case):
    from benchmark.campaign_readiness import _runtime_binds
    from benchmark.linux_sandbox import (
        ResourceLimits,
        RuntimeBind,
        SandboxSpec,
        SandboxSupervisor,
    )
    from benchmark.practical_grade_contract import (
        REPORT_PREFIX,
        SEED_FILE_NAME,
        python_check_case_ids,
        report_export_paths,
        validate_grade_report,
    )

    if not isinstance(code, str) or len(code.encode()) > 128 * 1024:
        return {
            "passed": False,
            "reason": "missing_or_oversized_code",
            "cleanup_verified": True,
        }
    with tempfile.TemporaryDirectory(prefix="qwen-grade-") as directory:
        workspace = Path(directory)
        (workspace / "candidate.py").write_text(code)
        receipt = secrets.token_hex(16)
        (workspace / SEED_FILE_NAME).write_text(
            json.dumps({"schema": "practical-grade-seed-v1", "nonce": receipt})
        )
        source_text = (
            "import unittest\nfrom candidate import solve\nclass Contract(unittest.TestCase):\n def test_contract(self):\n"
            + "".join("  " + line + "\n" for line in case["checks"].splitlines())
            + "\nif __name__=='__main__': unittest.main()\n"
        )
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="qwen-private-checks-") as checks_dir:
            runtime = Path(checks_dir)
            check = runtime / "qualification_checks.py"
            check.write_text(source_text)
            binds = list(_runtime_binds())
            copies = [
                ("practical_python_checks.py", "checks_launcher.py"),
                ("practical_grade_contract.py", "practical_grade_contract.py"),
                ("practical_worker_guard.py", "practical_worker_guard.py"),
                ("practical_node_rpc.mjs", "practical_node_rpc.mjs"),
            ]
            for original, name in copies:
                target = runtime / name
                shutil.copyfile(root / "benchmark" / original, target)
                binds.append(RuntimeBind(target, "/opt/" + name))
            binds.append(RuntimeBind(check, "/opt/qualification_checks.py"))
            result = SandboxSupervisor().run(
                SandboxSpec(
                    argv=(
                        "/usr/bin/python3",
                        "-B",
                        "-I",
                        "/opt/checks_launcher.py",
                        "--parent",
                        "--language",
                        "python",
                        "--checks",
                        "/opt/qualification_checks.py",
                        "--seed-file",
                        SEED_FILE_NAME,
                    ),
                    workspace=workspace,
                    runtime_ro=tuple(binds),
                    workspace_exports=report_export_paths(receipt),
                    limits=ResourceLimits(
                        memory_bytes=256 * 1024**2,
                        swap_bytes=1024**2,
                        wall_seconds=20,
                        cpu_seconds=15,
                        pids=32,
                        output_bytes=32768,
                    ),
                )
            )
        packets = [
            line[len(REPORT_PREFIX) :]
            for line in result.output.decode(errors="replace").splitlines()
            if line.startswith(REPORT_PREFIX)
        ]
        report = None
        if len(packets) == 1:
            try:
                report = json.loads(packets[0])
            except ValueError:
                pass
        verdict = validate_grade_report(
            report,
            set(python_check_case_ids(source_text)),
            returncode=result.returncode,
            cleanup_verified=result.cleanup_verified,
            expected_nonce=receipt,
        )
        return {
            **verdict,
            "returncode": result.returncode,
            "cleanup_verified": result.cleanup_verified,
            "infrastructure_error": result.infrastructure_error
            or (None if result.cleanup_verified else "grader_cleanup_unverified"),
            "output": result.output.decode("utf-8", errors="replace")[-4000:],
        }


def tool_arguments_valid(call, expected):
    try:
        return (
            bool(call["id"])
            and call["function"]["name"] == "lookup"
            and json.loads(call["function"]["arguments"]) == expected
        )
    except (KeyError, TypeError, ValueError):
        return False


def run_qualification(client, output):
    """Client.chat(messages, tools=None) returns a recorded OpenAI response dict."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    started = time.monotonic()
    for index, case in enumerate(CODE_CASES):
        response = client.chat(
            [
                {
                    "role": "user",
                    "content": case["prompt"]
                    + " Return only a JSON object with one key code containing complete Python source; no markdown.",
                }
            ]
        )
        try:
            code = json.loads(response["choices"][0]["message"]["content"])["code"]
            verdict = grade_code(code, case)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            verdict = {
                "passed": False,
                "reason": "invalid_code_envelope",
                "error": str(exc),
            }
        if (
            verdict.get("infrastructure_error")
            or verdict.get("infrastructure")
            or verdict.get("contract_invalid")
        ):
            raise RuntimeError(
                "qualification grader infrastructure: "
                + str(verdict.get("infrastructure_error") or verdict.get("reason"))
            )
        rows.append(dict(index=index, kind="code", **verdict))
        write_json(output / "checks.json", rows)
    for index in range(4):
        expected = {"ids": [index + 2, index + 7], "active": index % 2 == 0}
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look up IDs and return a receipt.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ids": {"type": "array", "items": {"type": "integer"}},
                            "active": {"type": "boolean"},
                        },
                        "required": ["ids", "active"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        messages = [
            {
                "role": "user",
                "content": "Call lookup with exactly these arguments: "
                + json.dumps(expected)
                + ". Then return only the receipt supplied by the tool.",
            }
        ]
        if index == 3:
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "prior_error",
                                "type": "function",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"ids":[],"active":true}',
                                },
                            }
                        ],
                    },
                    {
                        "role": "tool",
                        "tool_call_id": "prior_error",
                        "content": '{"error":"empty ids; correct arguments from the user and retry once"}',
                    },
                ]
            )
        response = client.chat(messages, tools=tools)
        message = response["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        ok = len(calls) == 1 and tool_arguments_valid(calls[0], expected)
        if ok:
            receipt = "receipt-" + str(index) + "-7db28"
            messages.extend(
                [
                    message,
                    {
                        "role": "tool",
                        "tool_call_id": calls[0]["id"],
                        "content": json.dumps({"receipt": receipt}),
                    },
                ]
            )
            final = client.chat(messages, tools=tools)["choices"][0]["message"]
            ok = (final.get("content") or "").strip() == receipt and not final.get(
                "tool_calls"
            )
        rows.append(
            dict(
                index=index + 6,
                kind="tool_recovery" if index == 3 else "tool",
                passed=ok,
            )
        )
        write_json(output / "checks.json", rows)
    for index, expected in enumerate(
        (
            {"ok": True, "items": [3, 1, 4]},
            {"status": "blocked", "reason": "missing_file"},
        )
    ):
        response = client.chat(
            [
                {
                    "role": "user",
                    "content": "Return exactly this JSON value and nothing else: "
                    + json.dumps(expected),
                }
            ]
        )
        try:
            ok = json.loads(response["choices"][0]["message"]["content"]) == expected
        except (ValueError, KeyError, TypeError, IndexError):
            ok = False
        rows.append(dict(index=index + 10, kind="instructions", passed=ok))
        write_json(output / "checks.json", rows)
    passed = sum(row["passed"] for row in rows)
    result = dict(
        status="complete" if passed >= 10 else "model_failure",
        passed=passed,
        total=12,
        protocol_valid=True,
        seconds=time.monotonic() - started,
        calls=client.calls,
        metadata_calls=client.metadata_calls,
        checks=rows,
    )
    write_json(output / "result.json", result)
    return result
