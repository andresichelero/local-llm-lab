---
name: code-and-tests
description: Read, implement and verify changes to existing Python or JavaScript projects.
metadata:
  compatibility: Local workspace with Python standard library or Node built-ins; no installation.
---

# Code and tests

Use for code changes. Preserve public exports and requirements stated in TASK.md.
Read the implementation and existing tests before editing. Search narrowly rather
than repeatedly listing the directory. Use only the available standard library.

For an edit tool, copy oldString from the current file, including actual newlines;
do not substitute literal backslash-n for newlines. oldString and newString must
differ. If a match fails, re-read the affected region and correct the patch. An
unchanged patch is not recovery. With apply_patch, inspect every target path.

Add focused tests of the requested behavior, including the boundary cases the
task specifies. Run the project tests with the available interpreter: Python
unittest or Node's node --test as appropriate. Inspect exit status and output.
Test failures in the program are feedback about the implementation, not proof
that the transport or tool is broken. Re-run tests after changing relevant code;
do not repeat unchanged failing tests without a new hypothesis.

Read the resulting code and verify public exports and non-mutation requirements.
Never modify hidden acceptance tests, baseline tests, task instructions or runtime
settings to make a test pass. Finish only with verified results; a plausible patch
or a test file that was never executed does not establish completion.

When TASK.md states a contract addendum (for example a copy-independence
addendum), its published criteria are requirements. Implement the stated copy
semantics directly, without aliasing the inputs, and keep the published in-scope
primitive and falsey values. Published out-of-scope classes need no handling.

Tests you add must distinguish the behavior TASK.md names as broken from the
required one: they should fail on the stated original behavior and pass after
your fix. The harness verifies this with an isolated copy of your snapshot in
which only the stated original behavior is restored and the same submitted
suite runs again; a suite that passes on both sides does not verify the
regression it claims to guard. Test crashes, import failures, and
infrastructure errors inside the suite are never counted as a detected
regression, on either side of that comparison.
