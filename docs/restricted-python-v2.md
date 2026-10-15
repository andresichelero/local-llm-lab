# Implementation language contract: restricted-python-workspace-v2

These restrictions apply to implementation modules under `src/`, not to the
ordinary `unittest` test classes you write and run inside the agent sandbox.
The final grader interprets implementation source as data. It never imports your
implementation or your authored tests into its native Python test process.

Use this portable core for these tasks:

- Top-level functions with ordinary named positional parameters and optional
  defaults; assignments, return, if/elif/else, for/while, break/continue, and
  try/except/finally with built-in exceptions. Preserve required signatures.
- None, booleans, bounded integers/floats, strings, lists, tuples, sets and dicts;
  ordinary arithmetic/comparisons, indexing/slicing, comprehensions and f-strings.
- Core built-ins such as len, range, enumerate, zip, int, float, str, bool, list,
  tuple, dict, set, min, max, sum, sorted and isinstance. Prefer simple bounded
  loops and direct operations over metaprogramming.
- Ordinary bounded container/string operations, including split/join/strip,
  startswith/endswith, replace, append/extend, get/update, and items/keys/values.
- Imports of other submitted `src` modules. `from __future__ import annotations`
  and the supported typing/collections.abc annotation names are allowed;
  TypeVar with one string name is an inert annotation marker.

Do not use classes, decorators, nested function definitions, lambda/generators,
async/yield, context managers, positional-only/keyword-only/variadic parameters,
argument/dict unpacking, exception chaining, reflection, private/dunder attribute
access, attribute assignment, dynamic code execution, I/O, subprocesses, network
calls, or arbitrary standard-library imports (including re, os, sys and unittest)
in implementation modules. No native library or regex engine is exposed to the
implementation. Test code may use the normal sandboxed unittest environment.

Implementation source is limited to 262,144 bytes per module, 1,048,576 bytes in
total, 20,000 AST nodes and depth 128. Execution has bounded work, allocation,
container/string/integer sizes and call depth. Candidate test inspection also
has byte/node/depth limits. These are safety limits, not performance targets.

Unsupported implementation syntax is a distinct language outcome; resource
exhaustion is a distinct resource outcome. Neither is silently skipped or counted
as passing. This is a controlled public-task regression protocol, not general
CPython compatibility or evidence of performance on unseen training data.
