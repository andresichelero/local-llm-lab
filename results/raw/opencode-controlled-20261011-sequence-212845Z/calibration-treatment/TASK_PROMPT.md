Read `TASK.md` and follow it exactly. Implement the requested change, run its specified unit-test command from the workspace root, inspect the result, and repair any failures. Do not change files outside `src/calculator.py` and `tests/test_calculator.py`. Reply with a brief summary of the implementation and test result.

Orchestration: first call repo-explorer to identify the calculator behavior and relevant tests. Then implement the requested change and run the existing tests. Finally call independent-reviewer to inspect the diff and test evidence. Do not broaden scope.
