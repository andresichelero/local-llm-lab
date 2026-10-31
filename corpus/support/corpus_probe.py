"""Private pytest plugin distinguishing assertion failures from errors."""

import json
import os
from pathlib import Path

import pytest

counts = {"assertions": 0, "errors": 0}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        if call.when == "call" and call.excinfo and call.excinfo.errisinstance((AssertionError, pytest.fail.Exception)):
            counts["assertions"] += 1
        else:
            counts["errors"] += 1


def pytest_sessionfinish(session, exitstatus):
    path = Path(os.environ["CORPUS_PROBE_REPORT"])
    path.write_text(json.dumps(counts, sort_keys=True), encoding="utf-8")
