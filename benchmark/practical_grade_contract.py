"""Trusted acceptance grading contract for practical v2 checks (post-audit Task 1).

The grader never appeals to candidate stdout.  A parent collector process
parses the harness-authored check source itself to enumerate the expected
case IDs, observes per-check events on a channel separate from
stdout/stderr, and writes the verdict to a nonce-named workspace slot.
Missing, repeated, unexpected, or skipped checks, non-JSON event records,
stdout TAP/JSON mimicry, and the absence of the collector report are all
rejected. Collector faults are infrastructure; partial execution requires
review. A trusted guarded import error is a functional candidate failure even
when the acceptance functions cannot run.
"""
from __future__ import annotations

import ast
import re

REPORT_SCHEMA = "practical-grade-report-v1"
REPORT_PREFIX = "PRACTICAL_GRADE_REPORT:"

SEED_FILE_NAME = ".practical-grade-seed.json"
STOPS = ("pass", "fail", "error", "skipped")
_KNOWN_STATUSES = ("complete", "invalid", "infrastructure")

_TEST_CALL_RE = re.compile(r"\btest\(\s*(['\"])([^\n'\"]{1,400}?)\1")


def report_export_paths(nonce: str) -> tuple[str, ...]:
    """Nonce-named workspace report slots; earlier slots may be planted."""
    if not nonce or not isinstance(nonce, str):
        raise ValueError("grade report nonce must be a nonempty string")
    return (
        f".practical-grade-{nonce}.json",
        f".practical-grade-{nonce}-2.json",
        f".practical-grade-{nonce}-3.json",
        f".practical-grade-{nonce}-late.json",
    )


def python_check_case_ids(source: str) -> tuple[str, ...]:
    """Enumerate unittest case ids from trusted check source, in order."""
    tree = ast.parse(source)
    ids: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not _has_testcase_base(node):
            continue
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("test"):
                ids.append(f"{node.name}.{stmt.name}")
    return tuple(ids)


def python_candidate_module_roots(source: str) -> tuple[str, ...]:
    """Return non-stdlib import roots that the trusted checks may call."""
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".", 1)[0])
    return tuple(sorted(name for name in roots
                        if name not in __import__("sys").stdlib_module_names
                        and name not in __import__("sys").builtin_module_names))


def node_check_case_ids(source: str) -> tuple[str, ...]:
    """Enumerate node:test case ids from trusted check source, in order."""
    ids = [_unescape(match.group(2)) for match in _TEST_CALL_RE.finditer(source)]
    return tuple(ids)


def _has_testcase_base(node: ast.ClassDef) -> bool:
    for base in node.bases:
        target = base.attr if isinstance(base, ast.Attribute) else (
            base.id if isinstance(base, ast.Name) else "")
        if target == "TestCase":
            return True
    return False


def _unescape(value: str) -> str:
    return value.replace("\\'", "'").replace('\\"', '"')


def validate_grade_report(report: dict | None, expected_case_ids, *,
                          returncode: int | None = None,
                          cleanup_verified: bool = True,
                          expected_nonce: str | None = None) -> dict:
    """Grade a collector report against the trusted check contract."""
    verdict = {
        "passed": False,
        "infrastructure": False,
        "contract_invalid": False,
        "reason": None,
        "checks_completed": 0,
        "tests_run": 0,
        "failures": [],
        "candidate_failure_observed": False,
    }
    expected = sorted(tuple(expected_case_ids))
    if report is None:
        return _with_infrastructure(verdict, "grade collector report absent")
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA:
        return _with_contract_invalid(verdict, "grade collector report unreadable")
    if report.get("nonce") != expected_nonce:
        return _with_contract_invalid(verdict, "grade collector report failed authentication")
    if sorted(report.get("expected_case_ids") or ()) != expected:
        return _with_contract_invalid(
            verdict, "grade collector report disagrees with the trusted check contract")
    status = report.get("status")
    if status not in _KNOWN_STATUSES:
        return _with_contract_invalid(
            verdict, f"unknown grade collector status: {status!r}")
    if status == "infrastructure":
        return _with_infrastructure(
            verdict, str(report.get("reason") or "grade collector reported a fault"))
    if report.get("candidate_import_error") is not None:
        detail = report.get("candidate_import_error")
        checks = report.get("checks")
        if (status != "complete"
                or not isinstance(detail, str) or not detail or len(detail) > 2000
                or not isinstance(checks, list) or len(checks) != len(expected)
                or not all(isinstance(item, dict) for item in checks)
                or any(not isinstance(item.get("id"), str) for item in checks)
                or sorted(item.get("id") for item in checks) != expected
                or any(item.get("stop") != "error" for item in checks)
                or report.get("tests_run") != 0):
            return _with_contract_invalid(
                verdict, "candidate import failure report disagrees with completed guarded imports")
        verdict.update(candidate_failure_observed=True,
                       reason="candidate import failed: " + detail[:500])
        return verdict
    if status == "invalid":
        verdict.update(
            contract_invalid=True,
            reason=str(report.get("reason") or "grade collector reported invalid execution"),
            tests_run=int(report.get("tests_run") or 0),
        )
        return verdict
    if not cleanup_verified:
        return _with_infrastructure(verdict, "grader sandbox cleanup failed")
    if returncode is None or returncode != 0:
        return _with_infrastructure(
            verdict, f"grade collector terminated with returncode {returncode}")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        return _with_contract_invalid(verdict, "grade collector report carries no checks")
    observed: dict[str, str] = {}
    for entry in checks:
        if not isinstance(entry, dict):
            return _with_contract_invalid(
                verdict, "grade collector report carries malformed check entries")
        case_id, stop = entry.get("id"), entry.get("stop")
        if not isinstance(case_id, str) or stop not in STOPS:
            return _with_contract_invalid(
                verdict, "grade collector report carries malformed check entries")
        if case_id in observed:
            return _with_contract_invalid(
                verdict, f"grade collector report repeats check {case_id!r}")
        observed[case_id] = stop
    missing = [case for case in expected if case not in observed]
    if missing:
        return _with_contract_invalid(
            verdict, "checks terminated before: " + ", ".join(missing))
    extra = [case for case in observed if case not in set(expected)]
    if extra:
        return _with_contract_invalid(
            verdict, "grade collector report carries checks outside the trusted contract: "
            + ", ".join(extra))
    if report.get("tests_run") != len(observed):
        return _with_contract_invalid(
            verdict, "grade collector report count disagrees with executed checks")
    skipped = [case for case, stop in observed.items() if stop == "skipped"]
    if skipped:
        return _with_contract_invalid(
            verdict, "checks skipped without execution: " + ", ".join(sorted(skipped)))
    failures = [{"case": case, "stop": stop}
                for case, stop in observed.items() if stop != "pass"]
    verdict.update(
        checks_completed=len(observed),
        tests_run=len(observed),
        failures=failures,
        passed=not failures,
    )
    if failures:
        verdict["reason"] = "checks reported " + ", ".join(
            f"{failure['case']}:{failure['stop']}" for failure in failures)
    return verdict


def _with_infrastructure(verdict: dict, reason: str) -> dict:
    verdict.update(infrastructure=True, reason=reason)
    return verdict


def _with_contract_invalid(verdict: dict, reason: str) -> dict:
    verdict.update(contract_invalid=True, reason=reason)
    return verdict
