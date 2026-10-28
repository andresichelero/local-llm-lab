"""Untrusted workspace runner for one bounded practical-agent-v2 episode."""
from __future__ import annotations

import json
import os
import re
import selectors
import signal
import shlex
import subprocess
import sys
import time
import zipfile
from pathlib import Path


try:
    from benchmark.practical_tool_guard import ToolErrorGuard
except ModuleNotFoundError:
    from practical_tool_guard import ToolErrorGuard


CONFIG_PATH = Path("/opt/practical/driver.json")
METADATA_PATH = Path("/workspace/.practical.json")
NODE = "/opt/node/bin/node"



def environment_preflight(language: str) -> dict[str, object]:
    """Exercise interpreters through the same PATH and shell as candidate tools."""
    commands = ["python3 -I -c " + shlex.quote("import json; assert json.loads('[1]') == [1]")]
    if language == "javascript":
        script = "const a=require('node:assert/strict');a.equal(1+1,2)"
        commands.append("node -e " + shlex.quote(script))
    for command in commands:
        try:
            result = subprocess.run(["/usr/bin/bash", "-c", command],
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"passed": False, "reason": f"candidate interpreter unavailable: {type(exc).__name__}"}
        if result.returncode:
            return {"passed": False, "reason": "candidate shell interpreter check failed",
                    "command": command, "returncode": result.returncode,
                    "output": (result.stdout + result.stderr)[-2000:]}
    return {"passed": True, "reason": "candidate shell interpreters executed successfully"}


def phase_timeout(*, remaining_seconds: float, total_seconds: float,
                  phase_index: int, phase_count: int,
                  elapsed_seconds: float = 0.0) -> int:
    """Return a whole-second subprocess budget within the shared task deadline."""
    remaining = max(0.0, min(float(remaining_seconds), float(total_seconds) - elapsed_seconds))
    if phase_count > 1 and phase_index == 1:
        remaining = min(remaining, total_seconds * 0.45 - elapsed_seconds)
    return max(0, int(remaining))


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _snapshot(phase: int) -> None:
    root = Path("/workspace")
    target = root / f".snapshot{phase}.zip"
    temporary = target.with_suffix(target.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(root.rglob("*")):
            relative = source.relative_to(root)
            if (source.is_file() and not source.is_symlink()
                    and not any(part in {".git", "__pycache__", "node_modules"}
                                for part in relative.parts)
                    and source.name not in {".practical.json", ".practical.json.tmp"}
                    and not source.name.startswith(".snapshot")):
                archive.write(source, str(relative))
    temporary.replace(target)


def _run_authored_tests(language: str, timeout_seconds: int) -> dict[str, object]:
    tests = Path("/workspace/tests")
    if language == "mcp" or not tests.is_dir():
        return {"passed": None, "count": 0, "output": ""}
    if language == "python":
        command = ["/usr/bin/python3", "-B", "-m", "unittest", "discover", "-s", "tests"]
    elif language == "javascript":
        command = [NODE, "--test", "--test-reporter=tap"]
    else:
        return {"passed": False, "count": 0, "output": f"unsupported language: {language}"}

    output_path = Path("/tmp/practical-authored-tests.log")
    try:
        with output_path.open("wb") as output:
            process = subprocess.Popen(command, cwd="/workspace", stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       close_fds=True, start_new_session=True)
            try:
                returncode = process.wait(timeout=max(1, timeout_seconds))
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
                return {"passed": False, "count": 0, "output": "authored tests timed out"}
        raw = output_path.read_bytes()
    except OSError as exc:
        return {"passed": False, "count": 0,
                "output": f"authored test runner failed: {type(exc).__name__}: {exc}"}

    text = raw[-12000:].decode("utf-8", errors="replace")
    if language == "python":
        match = re.search(r"Ran\s+(\d+)\s+tests?", text)
    else:
        match = re.search(r"(?:^|\n)#\s+tests\s+(\d+)(?:\n|$)", text)
        if match is None:
            match = re.search(r"\u2139\s+tests\s+(\d+)", text)
    count = int(match.group(1)) if match else 0
    return {"passed": returncode == 0 and count > 0, "count": count, "output": text}


def _events(raw: bytes) -> list[dict[str, object]]:
    result = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def budget_halt(event: dict[str, object]) -> str | None:
    """A trusted terminal-limit signal, never model-authored text.

    Only the harness's own error events (type='error', emitted when the
    typed local budget reply aborts a generation) are honored here; the
    LAB_POLICY_STOP tool path is handled by the tool guard.
    """
    if not isinstance(event, dict) or event.get('type') != 'error':
        return None
    part = event.get('part')
    text = ""
    if isinstance(part, dict):
        text = str(part.get('message') or part.get('text') or "")
    if not text:
        text = str(event.get('message') or "")
    if text.startswith('budget_exhausted:'):
        return text[:64]
    return None


def run_guarded(command, budget, guard, *, stream=False):
    """Consume JSONL as it arrives and terminate the whole agent group on review."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
    selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
    captured = {'stdout': bytearray(), 'stderr': bytearray()}
    pending = bytearray()
    deadline = time.monotonic() + budget
    tool_deadlines = {}
    code = None
    halt = None
    try:
        while selector.get_map():
            if any(time.monotonic() >= limit for limit in tool_deadlines.values()):
                guard.reason = 'tool_timeout'
                code = 85
                break
            if time.monotonic() >= deadline:
                code = 124
                break
            for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                captured[key.data].extend(chunk)
                if stream:
                    target = sys.stdout.buffer if key.data == 'stdout' else sys.stderr.buffer
                    target.write(chunk)
                    target.flush()
                if key.data == 'stdout':
                    pending.extend(chunk)
                    while b'\n' in pending:
                        line, _, remainder = pending.partition(b'\n')
                        pending = bytearray(remainder)
                        for event in _events(bytes(line)):
                            kind = event.get('_practical_driver')
                            if kind == 'policy_tool_start':
                                tool_deadlines[event['call_id']] = time.monotonic() + float(event['timeout_seconds'])
                            elif kind == 'policy_tool_end':
                                tool_deadlines.pop(event.get('call_id'), None)
                            elif event.get('type') == 'tool_use':
                                part = event.get('part') or {}
                                if (part.get('state') or {}).get('status') in {'completed', 'error'}:
                                    tool_deadlines.pop(part.get('callID'), None)
                            guard.observe(event)
                            if halt is None:
                                halt = budget_halt(event)
                        if guard.reason or halt:
                            code = 86 if guard.reason else 88
                            break
                if code is not None:
                    break
            if code is not None:
                break
        if code is None:
            for event in _events(bytes(pending)):
                guard.observe(event)
                if halt is None:
                    halt = budget_halt(event)
            if halt:
                code = 88
            else:
                try:
                    code = 86 if guard.reason else process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    code = 124
    finally:
        # Kill descendants too, including MCP servers and shell commands.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        selector.close()
        process.stdout.close()
        process.stderr.close()
    return bytes(captured['stdout']), bytes(captured['stderr']), code


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    prompts = config["prompts"]
    total_seconds = int(config["seconds"])
    policy = config.get('policy') or {}
    if policy.get('mode') == 'operational':
        total_seconds *= 2
    language = str(config["language"])
    # PATH is reserved by the sandbox API. Only this trusted, mounted driver
    # adds the pinned Node runtime before launching any candidate commands.
    os.environ["PATH"] = "/opt/node/bin:/usr/bin:/bin"
    # The minimal namespace has no C.UTF-8 locale archive. Bash warnings on
    # stderr otherwise interleave nondeterministically with tool stdout.
    os.environ['LC_ALL'] = 'C'
    os.environ['LANG'] = 'C'
    os.environ['PYTHONUTF8'] = '1'
    os.environ['OPENCODE_DISABLE_DEFAULT_PLUGINS'] = '1'
    os.environ['OPENCODE_DISABLE_PROJECT_CONFIG'] = '1'
    os.environ['OPENCODE_DISABLE_EXTERNAL_SKILLS'] = '1'
    environment = environment_preflight(language)
    print(json.dumps({"_practical_driver": "environment", **environment}), flush=True)
    if not environment["passed"]:
        return 125
    started = time.monotonic()
    deadline = started + total_seconds
    events: list[dict[str, object]] = []
    phases: list[dict[str, object]] = []
    session_id = None
    guard = ToolErrorGuard(str(config.get("task", "")))
    recovery_used = False

    for phase_index, prompt in enumerate(prompts, start=1):
        elapsed = time.monotonic() - started
        phase_deadline = deadline
        if len(prompts) > 1 and phase_index == 1:
            phase_deadline = min(deadline, started + total_seconds * 0.45)
        remaining = phase_deadline - time.monotonic()
        # Keep room inside the phase-one cap for authored tests and the snapshot.
        reserve = 25 if language != "mcp" else 5
        budget = max(0, phase_timeout(remaining_seconds=remaining, total_seconds=total_seconds,
                                      phase_index=phase_index, phase_count=len(prompts),
                                      elapsed_seconds=elapsed) - reserve)
        if budget <= 0:
            break
        command = ["/opt/opencode", "run", "--format", "json", "--agent", "build",
                   "--model", config["model"], "--dir", "/workspace"]
        if phase_index > 1:
            if not session_id:
                break
            command.extend(["--session", session_id])
        command.append(str(prompt))

        phase_started = time.monotonic()
        raw, stderr, returncode = run_guarded(command, budget, guard, stream=True)
        if (guard.reason == 'model_no_progress' and policy.get('mode') == 'operational'
                and not recovery_used and phase_deadline - time.monotonic() > 5):
            recovery_used = True
            captured = _events(raw)
            recovery_session = next((e.get('sessionID') for e in reversed(captured) if e.get('sessionID')), None)
            if recovery_session:
                guard.reason = None
                resume = command[:-1] + ['--session', recovery_session,
                    'The harness stopped a repeated action without observable progress. Re-read TASK.md, '
                    'inspect the last actual tool result and change approach. Do not repeat completed mutations. '
                    'This is the only recovery; all prior time and calls remain charged.']
                more, errors, returncode = run_guarded(resume, phase_deadline-time.monotonic()-reserve,
                                                       guard, stream=True)
                raw += more
                stderr += errors
                print(json.dumps({'_practical_driver':'recovery', 'attempt':1, 'phase':phase_index,
                                  'exit_code':returncode, 'stop_reason':guard.reason,
                                  'session_id':recovery_session}), flush=True)
        if guard.reason:
            print(json.dumps({"_practical_driver": "tool_review", **guard.as_dict()}), flush=True)
        phase_events = _events(raw)
        for event in phase_events:
            session_id = event.get("sessionID") or session_id
        events.extend(phase_events)
        halted = next((budget_halt(event) for event in phase_events if budget_halt(event)), None)
        if halted:
            # Terminal budget limit: stop the generation loop now. Tests and
            # the snapshot below still run; no cgroup kill and no waiting for
            # further client retries.
            print(json.dumps({"_practical_driver": "budget_halt", "phase": phase_index,
                              "stop_reason": halted}), flush=True)

        tests = {"passed": None, "count": 0, "output": ""}
        if language != "mcp" and Path("/workspace/tests").is_dir():
            left = max(0, int(phase_deadline - time.monotonic()) - 3)
            if left > 0:
                tests = _run_authored_tests(language, min(left, 20))
            else:
                tests = {"passed": False, "count": 0, "output": "task deadline expired before authored tests"}

        _snapshot(phase_index)
        texts = [str(event.get("part", {}).get("text", "")) for event in phase_events
                 if event.get("type") == "text" and isinstance(event.get("part"), dict)]
        phase = {
            "phase": phase_index,
            "exit_code": returncode,
            "seconds": round(time.monotonic() - phase_started, 3),
            "session_id": session_id,
            "authored_tests": tests,
            "final_text": "\n".join(texts),
            "event_count": len(phase_events),
            "stop_reason": halted,
            'stderr_tail': stderr.decode('utf-8', errors='replace')[-4000:],
        }
        phases.append(phase)
        _write_json(METADATA_PATH, {"phases": phases, "elapsed_seconds": round(time.monotonic() - started, 3),
                                   "event_count": len(events)})
        sys.stdout.write(json.dumps({"_practical_driver": "phase", "phase": phase_index,
                                     "exit_code": returncode, "session_id": session_id,
                                     "stop_reason": halted,
                                     'stderr_tail': stderr.decode('utf-8', errors='replace')[-4000:],
                                     "authored_tests": tests}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        if returncode != 0 or time.monotonic() >= deadline:
            break

    return 0


if __name__ == "__main__":
    os.chdir("/workspace")
    raise SystemExit(main())
