"""Practical v2 tasks and supervisor-only acceptance/reference material."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

TASKS = ("B1", "B2", "C1", "C2", "M1", "M2", "D1", "D2")
HOLDOUTS = ("H1", "H2")
ALL_TASKS = TASKS + HOLDOUTS

HISTORICAL_CONTRACT = "historical-v2"
M1_INDEPENDENT_CONTRACT = "m1-independent-copy-v1"

TASK_SPECS = {
    "B1": {
        "language": "python",
        "difficulty": "basic",
        "seconds": 180,
        "max_requests": 20,
        "phases": 1,
    },
    "B2": {
        "language": "javascript",
        "difficulty": "basic",
        "seconds": 180,
        "max_requests": 20,
        "phases": 1,
    },
    "C1": {
        "language": "python",
        "difficulty": "everyday",
        "seconds": 300,
        "max_requests": 30,
        "phases": 1,
    },
    "C2": {
        "language": "mcp",
        "difficulty": "everyday",
        "seconds": 300,
        "max_requests": 30,
        "phases": 1,
    },
    "M1": {
        "language": "javascript",
        "difficulty": "medium",
        "seconds": 480,
        "max_requests": 45,
        "phases": 1,
    },
    "M2": {
        "language": "mcp",
        "difficulty": "medium",
        "seconds": 480,
        "max_requests": 45,
        "phases": 1,
    },
    "D1": {
        "language": "python",
        "difficulty": "hard",
        "seconds": 720,
        "max_requests": 60,
        "phases": 2,
    },
    "D2": {
        "language": "javascript",
        "difficulty": "hard",
        "seconds": 720,
        "max_requests": 60,
        "phases": 1,
    },
    "H1": {
        "language": "python",
        "difficulty": "hard",
        "seconds": 720,
        "max_requests": 60,
        "phases": 1,
    },
    "H2": {
        "language": "mcp",
        "difficulty": "hard",
        "seconds": 720,
        "max_requests": 60,
        "phases": 1,
    },
}

_COMMON = {
    "python": """
Work in this project. Read existing files, implement the request, preserve
existing behavior, and add meaningful tests under tests/. Use only the Python
standard library. Run focused tests before finishing. State what changed and
which tests you ran.
""",
    "javascript": """
Work in this project. Read existing files, implement the request, preserve
existing behavior, and add tests under tests/*.test.js. Use only Node.js
built-ins and the built-in node:test runner. Run tests with node --test. State
what changed and which tests you ran.
""",
    "mcp": """
Use the configured local MCP tools. Discover tools first, inspect each result,
and follow every returned cursor until null. Save the requested artifact in
this workspace. Submit a report through a server tool only when the task explicitly requests
submission. Do not invent unseen pages or results. Finish with a brief
verified result.
""",
}

_PROMPTS = {
    "B1": """
Repair orders.report.build_report. Each record has id, customer, and integer
amount_cents. Replayed deliveries can repeat an id: only the first record for
an id counts. Different ids for the same customer all count. Sum cents by the
original customer spelling, include customers whose sum is zero, and support
negative refunds. Do not mutate input. Keep orders.money.format_cents working.
""",
    "B2": """
Implement convertJsonl(text) in the existing JavaScript modules. Each nonblank
line is a JSON object with a positive integer id and string name. Ignore blank
lines, preserve order and duplicate ids, and return pretty-printed JSON for an
array. Preserve Unicode. Reject malformed JSON and invalid records with an
error identifying the 1-based source line. Keep the public src/index.js export.
""",
    "C1": """
Implement collect_pages(fetch_page, *, page_size=2) in pagination.py. Call
fetch_page(cursor, page_size), starting at cursor None. Each response is a dict
with an items list and next_cursor either a nonempty string or None. Append
items in page order; stop only at None. Reject malformed responses, repeated
cursors, and invalid page sizes (integer 1..50; booleans are invalid) with
ValueError. Do not mutate responses or item values. Keep count_items working.
""",
    "C2": """
Discover the local MCP tools, retrieve every issue page, and write report.json
with open_ids (sorted ids whose status is exactly open) and total_estimate
    (their summed estimates). For list_issues, use page_size=2 on every call
    and pass each returned next_cursor unchanged until it is null. Call
    write_report with the same report. The grader checks observed calls, server
    state, and your artifact.
""",
    "M1": """
Fix the configuration merge regression across src/config/defaults.js,
src/config/merge.js, and src/config/index.js. resolveConfig(overrides) starts
from defaults and recursively merges plain objects. A missing property, or an
override property whose value is undefined, keeps the default. Explicit false,
0, empty string, and null are values and must survive. Arrays replace the
default array and must be copied. Never mutate defaults or caller objects.
Preserve existing exports.
""",
    "M2": """
Use MCP to apply change C-17 exactly once. Discover tools. Read the change,
then try the returned version with idempotency key C-17-v2. The first version
is deliberately stale; inspect the error, read the current version, and retry
with it. The first current-version attempt has a transient failure; retry the
exact same request and key. Do not apply another change. After confirmed
success save receipt.json as
{"change_id":"C-17","applied":true,"version":2}. The grader checks the
observed error/success sequence and trusted apply count.
""",
    "D1": """
Implement exporter.render(records, format="json"). JSON output decodes to the
original list and record order, preserves Unicode, and uses stable sorted
object keys. Return a string, do not mutate records, keep exporter.total
unchanged, and raise ValueError for unsupported formats. Finish this first
delivery; a follow-up requirement will arrive in this same session.
""",
    "D2": """
Complete the multi-file reconciliation library in src/ledger.js,
src/reconcile.js, and src/index.js. buildReconciliationReport(accounts,
adjustments) calculates balances from each opening balance_cents. Only
adjustments whose status is exactly posted count. Adjustment ids are replay
keys: the first record for each id wins; later records with that id are
ignored. Do not mutate inputs. Return {balances, changed_ids,
ignored_duplicate_ids, total_balance_cents} with sorted id arrays.

Then use MCP to fetch every page from list_accounts and list_adjustments, run
your implementation on those records, and call apply_balance once for each
changed account with its listed version and key <account_id>-v<version>. Save
the report as reconciliation.json and submit it with write_reconciliation.
The server applies a key at most once. The grader checks JavaScript and MCP.
""",
    "H1": """
Implement TTLCache in ttl_cache.py. It accepts an optional injected
zero-argument clock (default time.monotonic). Provide set(key, value, ttl) and
get(key, default=None). Expiration is measured from set; an entry expires when
expiry time is less than or equal to the current clock. Expired entries behave
as missing even when their value is None, False, or 0. TTL must be a finite,
nonnegative number; booleans and other types raise ValueError. Use a controlled
fake clock in tests and do not sleep.
""",
    "H2": """
Discover local MCP tools and fetch every page from list_assets and list_audits.
Audit ids are replay keys: keep the first audit with each id. For each asset,
select the distinct audit with the greatest integer observed_at; reconcile
status to that audit. Update only assets whose current status differs using
set_asset_status with the asset's current version and key
<asset_id>-v<version>-<status>. Save asset-report.json with sorted changed_ids
and a statuses object, and submit it with write_asset_report. The grader
checks pages, updates, and trusted server state.
""",
}

_SEEDS = {
    "B1": {
        "orders/__init__.py": "",
        "orders/money.py": "def format_cents(value):\n    return f'{value / 100:.2f}'\n",
        "orders/report.py": """
def build_report(records):
    totals = {}
    seen = set()
    for record in records:
        if record['customer'] in seen:
            continue
        seen.add(record['customer'])
        totals[record['customer']] = record['amount_cents']
    return totals
""",
    },
    "B2": {
        "src/validate.js": """
function validateRecord(record, lineNumber) {
  if (!record || typeof record !== 'object' || Array.isArray(record)) {
    throw new TypeError('record must be an object');
  }
  return record;
}
module.exports = { validateRecord };
""",
        "src/convert.js": """
const { validateRecord } = require('./validate');
function convertJsonl(text) {
  throw new Error('JSONL conversion is not implemented');
}
module.exports = { convertJsonl };
""",
        "src/index.js": "module.exports = require('./convert');\n",
    },
    "C1": {
        "pagination.py": """
def count_items(pages):
    return sum(len(page.get('items', [])) for page in pages)

def collect_pages(fetch_page, *, page_size=2):
    raise NotImplementedError('page collection is not implemented')
"""
    },
    "C2": {},
    "M1": {
        "src/config/defaults.js": """
module.exports = {
  enabled: true, retryCount: 3, timeoutMs: 500, label: 'worker',
  transport: { strict: true, headers: { accept: 'application/json' } },
  tags: ['default']
};
""",
        "src/config/merge.js": "function mergeConfig(base, override) { return { ...base, ...override }; }\nmodule.exports = { mergeConfig };\n",
        "src/config/index.js": """
const defaults = require('./defaults');
const { mergeConfig } = require('./merge');
function resolveConfig(overrides = {}) { return mergeConfig(defaults, overrides); }
module.exports = { defaults, mergeConfig, resolveConfig };
""",
    },
    "M2": {},
    "D1": {
        "exporter.py": """
def total(records):
    return sum(record['count'] for record in records)
def render(records, format='json'):
    raise NotImplementedError('report export is not implemented')
"""
    },
    "D2": {
        "src/ledger.js": "function firstAdjustments(adjustments) { throw new Error('not implemented'); }\nmodule.exports = { firstAdjustments };\n",
        "src/reconcile.js": "function buildReport(accounts, adjustments) { throw new Error('not implemented'); }\nmodule.exports = { buildReport };\n",
        "src/index.js": """
const { firstAdjustments } = require('./ledger');
const { buildReport } = require('./reconcile');
function buildReconciliationReport(accounts, adjustments) {
  return buildReport(accounts, firstAdjustments(adjustments));
}
module.exports = { buildReconciliationReport };
""",
    },
    "H1": {
        "ttl_cache.py": """
class TTLCache:
    def __init__(self, clock=None):
        raise NotImplementedError('TTL cache is not implemented')
"""
    },
    "H2": {},
}

_BASELINE_PY = {
    "B1": "from orders.money import format_cents\nassert format_cents(125) == '1.25'\n",
    "C1": "from pagination import count_items\nassert count_items([{'items': [1, 2]}]) == 2\n",
    "D1": "from exporter import total\nassert total([{'name': 'a', 'count': 3}]) == 3\n",
    "H1": "from ttl_cache import TTLCache\nassert callable(TTLCache)\n",
}
_BASELINE_JS = {
    "B2": "const {test}=require('node:test'); const a=require('node:assert/strict'); const {convertJsonl}=require('../src'); test('export',()=>a.equal(typeof convertJsonl,'function'));\n",
    "M1": "const {test}=require('node:test'); const a=require('node:assert/strict'); const {resolveConfig}=require('../src/config'); test('export',()=>a.equal(typeof resolveConfig,'function'));\n",
    "D2": "const {test}=require('node:test'); const a=require('node:assert/strict'); const {buildReconciliationReport}=require('../src'); test('export',()=>a.equal(typeof buildReconciliationReport,'function'));\n",
}

_MCP_ARTIFACTS = {
    "C2": ("report.json", {"open_ids": [101, 103, 104, 106], "total_estimate": 18}),
    "M2": ("receipt.json", {"change_id": "C-17", "applied": True, "version": 2}),
    "D2": (
        "reconciliation.json",
        {
            "balances": {"A-01": 1175, "A-02": 425, "A-03": -25},
            "changed_ids": ["A-01", "A-02"],
            "ignored_duplicate_ids": ["ADJ-1"],
            "total_balance_cents": 1575,
        },
    ),
    "H2": (
        "asset-report.json",
        {
            "changed_ids": ["AS-2", "AS-4"],
            "statuses": {
                "AS-1": "active",
                "AS-2": "active",
                "AS-3": "retired",
                "AS-4": "retired",
            },
        },
    ),
}


def _validate(task: str) -> None:
    if task not in ALL_TASKS:
        raise ValueError(f"Unknown practical v2 task: {task}")


_TASK_CONTRACTS: dict[str, frozenset[str]] = {
    task: frozenset({HISTORICAL_CONTRACT}) for task in ALL_TASKS
}
_TASK_CONTRACTS["M1"] = frozenset(
    {HISTORICAL_CONTRACT, M1_INDEPENDENT_CONTRACT}
)
_TASK_CONTRACTS['C2'] = frozenset({HISTORICAL_CONTRACT,'mcp-no-confirmed-replay-v1'})


def task_contracts(task: str) -> frozenset[str]:
    """Known task-contract ids for ``task``; unknown contract ids need review."""
    _validate(task)
    return _TASK_CONTRACTS[task]


def resolve_task_contract(task: str, task_contract_id: str | None) -> str:
    """Validate a requested contract id; ``None`` selects the historical profile."""
    _validate(task)
    if task_contract_id is None:
        return HISTORICAL_CONTRACT
    if task_contract_id not in _TASK_CONTRACTS[task]:
        raise ValueError(
            f"unknown or inapplicable task contract {task_contract_id!r} "
            f"for {task!r}: review required"
        )
    return task_contract_id


_CONTRACT_STATEMENTS = {
    'mcp-no-confirmed-replay-v1': '''
(Contract mcp-no-confirmed-replay-v1) Submit exactly one successful write_report
after every issue page has been retrieved. Do not replay a confirmed mutation.
Rejected attempts before the first successful submission may be corrected.
page_size may be omitted only when using its advertised default value 2.
''',
    M1_INDEPENDENT_CONTRACT: """
(Contract m1-independent-copy-v1) The returned configuration must be an
independent copy: every plain object and every array in the result shares no
reference with defaults or with the caller-provided overrides, at any depth,
including objects inside arrays, and newly added properties live only on the
copy. Mutating the result must never change defaults or the inputs, and
mutating the inputs after the call must never change the result. A missing key
or an undefined override value keeps the default; explicit false, 0, empty
string, null, and empty arrays are values and must survive. Do not implement
the copy through a JSON round-trip (it loses undefined). Cycles, Date, Map,
Set, and other special classes are outside the scope of this contract round.
""",
}


def _write(workspace: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dedent(content).lstrip(), encoding="utf-8")


def seed_task(task: str, workspace: Path, *, with_skills=True,
              task_contract_id: str = HISTORICAL_CONTRACT) -> str:
    _validate(task)
    contract = resolve_task_contract(task, task_contract_id)
    _write(workspace, _SEEDS[task])
    if task in _BASELINE_PY:
        body = "\n".join("        " + line for line in _BASELINE_PY[task].splitlines())
        _write(
            workspace,
            {
                "tests/test_existing.py": "import unittest\n\nclass ExistingTests(unittest.TestCase):\n"
                "    def test_public_behavior(self):\n" + body + "\n"
            },
        )
    if task in _BASELINE_JS:
        _write(workspace, {"tests/test_existing.test.js": _BASELINE_JS[task]})
    common = _COMMON[TASK_SPECS[task]["language"]]
    prompt = dedent(_PROMPTS[task]).strip()
    if contract != HISTORICAL_CONTRACT:
        prompt += "\n\n" + dedent(_CONTRACT_STATEMENTS[contract]).strip()
    prompt = prompt + "\n\n" + dedent(common).strip()
    if task in {"C2", "M2", "D2", "H2"}:
        prompt += (
            "\n\nMCP tools are already available in your tool list. Inspect their names and "
            "argument schemas and call them directly using the advertised names (the harness "
            "may prefix names with lab_). Discovery means inspecting that tool list: "
            "do not use shell commands to discover MCP, search application configuration, "
            "or install a client. Work only inside /workspace. After context compaction, "
            "reread /workspace/TASK.md before continuing so the artifact and submission "
            "requirements are preserved."
        )
    from benchmark.practical_manual import task_instructions
    prompt = task_instructions(task, with_skills=with_skills) + '\n\n# Current task\n' + prompt
    (workspace / "TASK.md").write_text(prompt + "\n", encoding="utf-8")
    return prompt


def followup_prompt(task: str) -> str:
    _validate(task)
    if task != "D1":
        return ""
    return (
        "New requirement: keep JSON behavior and add format='csv'. CSV has "
        "header name,count and one row per record in input order. Use standard "
        "CSV quoting for commas, quotes, and newlines; use LF row endings and "
        "preserve Unicode. Empty input returns the header. Unsupported formats "
        "still raise ValueError and total() remains unchanged. Update and run "
        "your tests in this same project and session."
    )


def exports(task: str) -> tuple[str, ...]:
    _validate(task)
    files = list(_SEEDS[task])
    if task in _BASELINE_PY:
        files.extend(("tests/test_existing.py", "tests/test_agent.py", "tests/"))
    if task in _BASELINE_JS:
        files.extend(
            ("tests/test_existing.test.js", "tests/test_agent.test.js", "tests/")
        )
    if task in _MCP_ARTIFACTS:
        files.append(_MCP_ARTIFACTS[task][0])
    return tuple(files)


_PY_CHECKS = {
    "B1": """
from orders.report import build_report
from orders.money import format_cents
class Acceptance(unittest.TestCase):
    def test_replays_shared_names_refunds_and_immutability(self):
        rows = [
            {'id': 'x', 'customer': 'Ada', 'amount_cents': 100},
            {'id': 'y', 'customer': 'Ada', 'amount_cents': 50},
            {'id': 'x', 'customer': 'Other', 'amount_cents': 900},
            {'id': 'z', 'customer': 'Ada', 'amount_cents': -150},
            {'id': 'q', 'customer': ' Bea ', 'amount_cents': -25},
            {'id': 'r', 'customer': 'Bea', 'amount_cents': 25},
        ]
        before = copy.deepcopy(rows)
        self.assertEqual(build_report(rows), {'Ada': 0, ' Bea ': -25, 'Bea': 25})
        self.assertEqual(rows, before)
        self.assertEqual(build_report([]), {})
        self.assertEqual(format_cents(125), '1.25')
    def test_ids_not_customer_names_are_replay_keys(self):
        rows = [{'id': 1, 'customer': 'A', 'amount_cents': 4},
                {'id': 2, 'customer': 'A', 'amount_cents': 6},
                {'id': 3, 'customer': 'B', 'amount_cents': -2}]
        self.assertEqual(build_report(rows), {'A': 10, 'B': -2})
""",
    "C1": """
from pagination import collect_pages, count_items
class Acceptance(unittest.TestCase):
    def test_fetches_to_null_and_preserves_order(self):
        pages = {
            None: {'items': [{'id': 3}, {'id': 1}], 'next_cursor': 'next'},
            'next': {'items': [], 'next_cursor': 'last'},
            'last': {'items': [{'id': 2}], 'next_cursor': None},
        }
        calls = []
        def fetch(cursor, size):
            calls.append((cursor, size))
            return pages[cursor]
        self.assertEqual(collect_pages(fetch, page_size=3),
                         [{'id': 3}, {'id': 1}, {'id': 2}])
        self.assertEqual(calls, [(None, 3), ('next', 3), ('last', 3)])
        self.assertEqual(count_items([{'items': [1, 2]}]), 2)
    def test_bad_page_and_repeated_cursor_fail(self):
        with self.assertRaises(ValueError):
            collect_pages(lambda c, n: {'items': [], 'next_cursor': 'loop'})
        for response in (None, {}, {'items': {}, 'next_cursor': None},
                         {'items': [], 'next_cursor': ''}):
            with self.subTest(response=response), self.assertRaises(ValueError):
                collect_pages(lambda c, n, r=response: r)
    def test_page_size_validation(self):
        for size in (0, 51, True, False, 2.0, '2', None):
            with self.subTest(size=size), self.assertRaises(ValueError):
                collect_pages(lambda c, n: {'items': [], 'next_cursor': None},
                              page_size=size)


class Supplemental(unittest.TestCase):
    def test_opaque_cursors_and_response_immutability(self):
        pages = {None: {'items': [{'a': [1]}], 'next_cursor': 'a+b=2'},
                 'a+b=2': {'items': [], 'next_cursor': '000'},
                 '000': {'items': [0, False, None], 'next_cursor': None}}
        before = copy.deepcopy(pages)
        calls = []
        def fetch(cursor, size):
            calls.append((cursor, size))
            return pages[cursor]
        self.assertEqual(collect_pages(fetch, page_size=50),
                         [{'a': [1]}, 0, False, None])
        self.assertEqual(calls, [(None, 50), ('a+b=2', 50), ('000', 50)])
        self.assertEqual(pages, before)
    def test_invalid_cursor_types(self):
        with self.assertRaises(ValueError):
            collect_pages(lambda c, n: {'items': []})
        for cursor in (False, True, 0, 1, [], {}):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                collect_pages(lambda c, n: {'items': [], 'next_cursor': cursor})
""",
    "D1": """
from exporter import render, total
class Acceptance(unittest.TestCase):
    def test_json_contract(self):
        rows = [{'name': 'ação', 'count': 2}, {'name': 'x', 'count': -1}]
        before = copy.deepcopy(rows)
        result = render(rows)
        self.assertEqual(json.loads(result), rows)
        self.assertIn('ação', result)
        self.assertLess(result.index('count'), result.index('name'))
        self.assertEqual(total(rows), 1)
        self.assertEqual(rows, before)
        self.assertEqual(json.loads(render([])), [])
        with self.assertRaises(ValueError):
            render(rows, format='xml')
""",
    "H1": """
from ttl_cache import TTLCache
class FakeClock:
    def __init__(self): self.now = 10.0
    def __call__(self): return self.now
class Acceptance(unittest.TestCase):
    def test_expiry_boundary_and_falsey_values(self):
        clock = FakeClock()
        cache = TTLCache(clock=clock)
        cache.set('none', None, 2)
        cache.set('false', False, 2)
        cache.set('zero', 0, 2)
        self.assertIsNone(cache.get('none', 'missing'))
        self.assertIs(cache.get('false'), False)
        self.assertEqual(cache.get('zero'), 0)
        clock.now = 12.0
        for key in ('none', 'false', 'zero'):
            self.assertEqual(cache.get(key, 'expired'), 'expired')
    def test_independent_expiration_and_ttl_validation(self):
        clock = FakeClock()
        cache = TTLCache(clock=clock)
        cache.set('short', 's', 1)
        cache.set('long', 'l', 4)
        clock.now += 1
        self.assertIsNone(cache.get('short'))
        self.assertEqual(cache.get('long'), 'l')
        for ttl in (-1, True, False, '2', float('inf'), float('nan')):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                cache.set('bad', 'value', ttl)
""",
}

_JS_CHECKS = {
    "B2": r"""
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { convertJsonl } = require(require('node:path').join(process.cwd(), 'src', 'index.js'));
const identifiesLine = (number) => (error) =>
  new RegExp('\\b(?:line|row|source|linha|fonte)\\b\\D{0,12}' + number + '(?!\\d|\\.\\d)', 'i')
    .test(error.message);
test('blank lines, Unicode, duplicate ids, and order', () => {
  const input = '\n{"id":2,"name":"ação"}\r\n  \n{"id":2,"name":"東京"}\n';
  const result = convertJsonl(input);
  assert.equal(result.includes('ação'), true);
  assert.deepEqual(JSON.parse(result), [{id:2,name:'ação'}, {id:2,name:'東京'}]);
  assert.match(result, /[\r\n]/, 'multirow JSON output must be pretty-printed');
});
test('malformed and invalid rows name their line', () => {
  assert.throws(() => convertJsonl('{"id":1,"name":"ok"}\nnot json'), identifiesLine(2));
  assert.throws(() => convertJsonl('\n{"id":0,"name":"bad"}'), identifiesLine(2));
  assert.throws(() => convertJsonl('{"id":1,"name":4}'), identifiesLine(1));
  assert.throws(() => convertJsonl('{"id":1.5,"name":"fraction"}'), identifiesLine(1));
  assert.deepEqual(JSON.parse(convertJsonl(' \n\t\n')), []);
});
test('non-object JSON records name their 1-based source line after blank lines', () => {
  for (const [line, json] of [
    [2, 'null'],
    [4, '[]'],
    [1, '0'],
    [3, '"text"'],
    [5, 'true'],
  ]) {
    assert.throws(
      () => convertJsonl('\n'.repeat(line - 1) + json),
      identifiesLine(line),
    );
  }
});
test('supplemental ids 99/100/101 and boundary-large positives stay valid', () => {
  const rows = [{id:99,name:'a'},{id:100,name:'b'},{id:101,name:'c'}];
  const result = convertJsonl(rows.map((row) => JSON.stringify(row)).join('\n') + '\n');
  assert.deepEqual(JSON.parse(result), rows);
  assert.ok((result.match(/}\s*,\s*[\r\n]/g) || []).length >= 2,
    'records must sit on separate physical lines:' + result);
});
test('supplemental varied valid JSONL with whitespace blanks', () => {
  const rows = Array.from({length:25},(_,i)=>(
    {id:i%4+2147483648,name:['','😀','a"b','東京'][i%4]}));
  const result = convertJsonl('\r\n\t\n' + rows.map((row) => JSON.stringify(row)).join('\n \t\n'));
  assert.deepEqual(JSON.parse(result), rows);
  assert.ok((result.match(/}\s*,\s*[\r\n]/g) || []).length >= 24,
    'records must sit on separate physical lines:' + result);
});
test('supplemental invalid id types name their line', () => {
  for (const id of [null, true, false, '2', -1, 0, 1.01]) {
    assert.throws(() => convertJsonl(JSON.stringify({id, name:'ok'})), identifiesLine(1));
  }
  assert.throws(() => convertJsonl(JSON.stringify({name:'ok'})), identifiesLine(1));
});
test('supplemental the physical line is stated, not the record id', () => {
  const input = '\n\n{"id":99,"name":"a"}\n{"id":2147483647,"name":"b"}\n\n\n{"id":100,"name":4}\n';
  assert.throws(() => convertJsonl(input), identifiesLine(7));
});
""",
    "M1": r"""
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { defaults, mergeConfig, resolveConfig } =
  require(require('node:path').join(process.cwd(), 'src', 'config', 'index.js'));
test('missing and undefined retain nested defaults', () => {
  const result = resolveConfig({transport:{headers:{accept:undefined}}});
  assert.equal(result.enabled, true);
  assert.equal(result.transport.strict, true);
  assert.equal(result.transport.headers.accept, 'application/json');
});
test('false, zero, empty string, and null survive', () => {
  const result = resolveConfig({enabled:false,retryCount:0,label:'',timeoutMs:null,
                                transport:{strict:false}});
  assert.equal(result.enabled, false);
  assert.equal(result.retryCount, 0);
  assert.equal(result.label, '');
  assert.equal(result.timeoutMs, null);
  assert.equal(result.transport.strict, false);
});
test('nested merges and arrays copy without mutation', () => {
  const overrides = {transport:{headers:{authorization:'local'}},tags:['one']};
  const original = structuredClone(overrides);
  const result = mergeConfig(defaults, overrides);
  assert.deepEqual(result.transport.headers,
    {accept:'application/json',authorization:'local'});
  assert.deepEqual(overrides, original);
  assert.notEqual(result.tags, overrides.tags);
  result.tags.push('two');
  assert.deepEqual(overrides.tags, ['one']);
  assert.deepEqual(defaults.tags, ['default']);
});
test('explicit empty replacement array', () =>
  assert.deepEqual(resolveConfig({tags: []}).tags, []));
""",
    "D2": r"""
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { buildReconciliationReport } =
  require(require('node:path').join(process.cwd(), 'src', 'index.js'));
test('first replay wins, only posted counts, ids sort, and inputs stay intact', () => {
  const accounts = [{account_id:'Z',balance_cents:5},{account_id:'A',balance_cents:100}];
  const rows = [
    {id:'t1',account_id:'A',delta_cents:20,status:'posted'},
    {id:'t2',account_id:'Z',delta_cents:-5,status:'posted'},
    {id:'t1',account_id:'Z',delta_cents:900,status:'posted'},
    {id:'t3',account_id:'A',delta_cents:90,status:'pending'}
  ];
  const a0 = structuredClone(accounts), r0 = structuredClone(rows);
  assert.deepEqual(buildReconciliationReport(accounts, rows), {
    balances:{A:120,Z:0}, changed_ids:['A','Z'],
    ignored_duplicate_ids:['t1'], total_balance_cents:120
  });
  assert.deepEqual(accounts, a0);
  assert.deepEqual(rows, r0);
});
test('zero net and empty adjustments are deterministic', () => {
  assert.deepEqual(buildReconciliationReport([{account_id:'A',balance_cents:0}], [
    {id:'x',account_id:'A',delta_cents:4,status:'posted'},
    {id:'y',account_id:'A',delta_cents:-4,status:'posted'}
  ]), {balances:{A:0},changed_ids:[],ignored_duplicate_ids:[],total_balance_cents:0});
});
test('supplemental replay keys include non-posted first records', () => {
  const accounts =
    [{account_id:'X',balance_cents:10},{account_id:'Y',balance_cents:-5}];
  const adjustments = [
    {id:'dup',account_id:'X',delta_cents:90,status:'pending'},
    {id:'dup',account_id:'Y',delta_cents:100,status:'posted'},
    {id:'ok',account_id:'X',delta_cents:-3,status:'posted'},
    {id:'case',account_id:'Y',delta_cents:50,status:'POSTED'},
  ];
  const beforeA = structuredClone(accounts), beforeJ = structuredClone(adjustments);
  assert.deepEqual(buildReconciliationReport(accounts, adjustments), {
    balances:{X:7,Y:-5}, changed_ids:['X'], ignored_duplicate_ids:['dup'],
    total_balance_cents:2});
  assert.deepEqual(accounts, beforeA);
  assert.deepEqual(adjustments, beforeJ);
});
""",
}

_D1_CSV_CHECK = r"""
    def test_followup_csv_contract(self):
        rows = [{'name': 'a,b', 'count': 2}, {'name': 'a"b\nç', 'count': -3}]
        before = copy.deepcopy(rows)
        result = render(rows, format='csv')
        self.assertNotIn('\r\n', result)
        self.assertEqual(list(csv.reader(io.StringIO(result))),
                         [['name', 'count'], ['a,b', '2'], ['a"b\nç', '-3']])
        self.assertEqual(list(csv.reader(io.StringIO(render([], format='csv')))),
                         [['name', 'count']])
        self.assertEqual(rows, before)
"""


_JS_CONTRACT_ADDONS = {
    "M1": {
        M1_INDEPENDENT_CONTRACT: r"""
test('independent result: no alias with defaults at any depth', () => {
  const result = resolveConfig({});
  assert.equal(result.enabled, true);
  assert.notEqual(result.transport, defaults.transport);
  assert.notEqual(result.transport.headers, defaults.transport.headers);
  assert.notEqual(result.tags, defaults.tags);
  result.transport = { strict: false, headers: { accept: 'changed' } };
  assert.equal(defaults.transport.strict, true);
  assert.deepEqual(defaults.transport.headers, { accept: 'application/json' });
  result.tags.push('mutated');
  assert.deepEqual(defaults.tags, ['default']);
});
test('independent result: objects inside arrays; mutation both ways', () => {
  const overrides = {
    transport: { headers: { authorization: 'local' } },
    routes: [{ path: '/x', strict: false }],
    tags: ['one'],
  };
  const original = structuredClone(overrides);
  const result = resolveConfig(overrides);
  assert.deepEqual(overrides, original);
  assert.notEqual(result.transport, overrides.transport);
  assert.notEqual(result.transport.headers, overrides.transport.headers);
  assert.notEqual(result.routes, overrides.routes);
  assert.notEqual(result.routes[0], overrides.routes[0]);
  assert.notEqual(result.tags, overrides.tags);
  result.routes[0].strict = true;
  assert.equal(overrides.routes[0].strict, false);
  result.transport.headers['x-leak'] = 'leak';
  assert.equal('x-leak' in overrides.transport.headers, false);
  assert.deepEqual(defaults.transport.headers, { accept: 'application/json' });
  overrides.routes[0].path = '/after';
  assert.equal(result.routes[0].path, '/x');
  overrides.tags.push('after');
  assert.deepEqual(result.tags, ['one']);
  result.tags.pop();
  assert.deepEqual(overrides.tags, ['one', 'after']);
  overrides.transport.headers['after-call'] = 'later';
  assert.equal('after-call' in result.transport.headers, false);
});
test('independent replacement: new properties and empty arrays stay copied', () => {
  const overrides = { tags: [], note: { why: 'unwritten' } };
  const result = resolveConfig(overrides);
  assert.deepEqual(result.tags, []);
  assert.notEqual(result.tags, overrides.tags);
  result.tags.push('x');
  assert.deepEqual(overrides.tags, []);
  assert.notEqual(result.note, overrides.note);
  result.note.owner = { name: 'result' };
  result.note.why = 'rewritten';
  assert.deepEqual(overrides.note, { why: 'unwritten' });
  overrides.note.why = 'changed';
  assert.equal(result.note.why, 'rewritten');
});
test('frozen inputs yield an independent, still-modifiable result', () => {
  const overrides = Object.freeze({
    transport: Object.freeze({ headers: Object.freeze({ 'x-check': '1' }) }),
    tags: ['z'],
  });
  const result = resolveConfig(overrides);
  assert.notEqual(result.transport, overrides.transport);
  assert.notEqual(result.transport.headers, overrides.transport.headers);
  assert.notEqual(result.tags, overrides.tags);
  assert.deepEqual(result.transport.headers,
                   { accept: 'application/json', 'x-check': '1' });
  result.tags.push('after-frozen');
  assert.deepEqual(result.tags, ['z', 'after-frozen']);
  assert.deepEqual(overrides.tags, ['z']);
});
""",
    },
}



def seed_sources(task: str) -> dict[str, str]:
    """Original source files seeded for ``task``, restored by the authored-test
    regression diagnosis.  The bytes are normalized exactly like ``seed_task``
    applies them, so a restored copy is byte-identical to a fresh seed."""
    _validate(task)
    return {name: dedent(content).lstrip() for name, content in _SEEDS[task].items()}


def checks_source(task: str, phase: int = 1, *,
                  task_contract_id: str = HISTORICAL_CONTRACT) -> str:
    _validate(task)
    contract = resolve_task_contract(task, task_contract_id)
    if type(phase) is not int or not 1 <= phase <= TASK_SPECS[task]["phases"]:
        raise ValueError("phase is not defined for this task")
    language = TASK_SPECS[task]["language"]
    if language == "python":
        header = (
            "import copy, csv, io, json, sys, unittest\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path.cwd()))\n"
        )
        source = dedent(_PY_CHECKS[task]).lstrip()
        if task == "D1" and phase == 2:
            source += _D1_CSV_CHECK
        return header + source + "\nif __name__ == '__main__': unittest.main()\n"
    if language == "javascript":
        source = _JS_CHECKS[task].lstrip()
        if task in _JS_CONTRACT_ADDONS and contract in _JS_CONTRACT_ADDONS[task]:
            source += "\n" + _JS_CONTRACT_ADDONS[task][contract].lstrip()
        return source
    name, expected = _MCP_ARTIFACTS[task]
    return (
        "import json, unittest\nfrom pathlib import Path\n"
        "class Acceptance(unittest.TestCase):\n"
        f"    def test_{task.lower()}_artifact(self):\n"
        f"        self.assertEqual(json.loads(Path({name!r}).read_text(encoding='utf-8')),\n"
        f"                         {expected!r})\n"
        "if __name__ == '__main__': unittest.main()\n"
    )


def reference_files(task: str, variant: int = 0, phase: int = 1, *,
                    task_contract_id: str = HISTORICAL_CONTRACT) -> dict[str, str]:
    _validate(task)
    resolve_task_contract(task, task_contract_id)
    if variant not in (0, 1):
        raise ValueError("variant must be 0 or 1")
    if type(phase) is not int or not 1 <= phase <= TASK_SPECS[task]["phases"]:
        raise ValueError("phase is not defined for this task")

    if task == "B1":
        code = (
            """
def build_report(records):
    totals, seen = {}, set()
    for row in records:
        if row['id'] in seen: continue
        seen.add(row['id'])
        name = row['customer']
        totals[name] = totals.get(name, 0) + row['amount_cents']
    return totals
"""
            if variant == 0
            else """
from collections import defaultdict
def build_report(records):
    first = {}
    for row in records: first.setdefault(row['id'], row)
    totals = defaultdict(int)
    for row in first.values(): totals[row['customer']] += row['amount_cents']
    return dict(totals)
"""
        )
        return {"orders/report.py": dedent(code).lstrip()}

    if task == "B2":
        validate = (
            """
function validateRecord(row, line) {
  if (!row || typeof row !== 'object' || Array.isArray(row) ||
      !Number.isSafeInteger(row.id) || row.id <= 0 || typeof row.name !== 'string')
    throw new TypeError('line ' + line + ': invalid record');
  return row;
}
module.exports = { validateRecord };
"""
            if variant == 0
            else """
const isObject = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);
function validateRecord(row, line) {
  if (!isObject(row) || !Number.isSafeInteger(row.id) || row.id < 1 ||
      typeof row.name !== 'string') throw new TypeError('line ' + line + ': invalid row');
  return row;
}
module.exports = { validateRecord };
"""
        )
        convert = (
            """
const { validateRecord } = require('./validate');
function convertJsonl(text) {
  if (typeof text !== 'string') throw new TypeError('input must be text');
  const rows = [];
  text.split(/\\r?\\n/).forEach((line, i) => {
    if (!line.trim()) return;
    let value;
    try { value = JSON.parse(line); }
    catch (e) { throw new SyntaxError('line ' + (i + 1) + ': ' + e.message); }
    rows.push(validateRecord(value, i + 1));
  });
  return JSON.stringify(rows, null, 2);
}
module.exports = { convertJsonl };
"""
            if variant == 0
            else """
const { validateRecord } = require('./validate');
function convertJsonl(text) {
  if (typeof text !== 'string') throw new TypeError('input must be text');
  const rows = [];
  const lines = text.split(/\\r?\\n/);
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim() === '') continue;
    try { rows.push(validateRecord(JSON.parse(lines[i]), i + 1)); }
    catch (e) {
      if (/^line \\d+:/.test(e.message)) throw e;
      throw new SyntaxError('line ' + (i + 1) + ': ' + e.message);
    }
  }
  return JSON.stringify(rows, null, 2);
}
module.exports = { convertJsonl };
"""
        )
        return {
            "src/validate.js": dedent(validate).lstrip(),
            "src/convert.js": dedent(convert).lstrip(),
            "src/index.js": "module.exports = require('./convert');\n",
        }

    if task == "C1":
        code = (
            """
def collect_pages(fetch_page, *, page_size=2):
    if type(page_size) is not int or not 1 <= page_size <= 50:
        raise ValueError('invalid page_size')
    result, seen, cursor = [], set(), None
    while True:
        page = fetch_page(cursor, page_size)
        if not isinstance(page, dict) or not isinstance(page.get('items'), list) or 'next_cursor' not in page:
            raise ValueError('malformed page')
        result.extend(page['items'])
        cursor = page['next_cursor']
        if cursor is None: return result
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise ValueError('invalid or repeated cursor')
        seen.add(cursor)
"""
            if variant == 0
            else """
def collect_pages(fetch_page, *, page_size=2):
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size not in range(1, 51):
        raise ValueError('invalid page size')
    output, visited, cursor = [], set(), None
    while True:
        response = fetch_page(cursor, page_size)
        if not isinstance(response, dict) or 'items' not in response or 'next_cursor' not in response:
            raise ValueError('invalid page')
        if not isinstance(response['items'], list): raise ValueError('items must be a list')
        output += response['items']
        nxt = response['next_cursor']
        if nxt is None: break
        if not isinstance(nxt, str) or not nxt or nxt in visited: raise ValueError('invalid cursor')
        visited.add(nxt)
        cursor = nxt
    return output
"""
        )
        return {
            "pagination.py": "def count_items(pages):\n    return sum(len(page.get('items', [])) for page in pages)\n\n"
            + dedent(code).lstrip()
        }

    if task in ("C2", "M2", "H2"):
        name, data = _MCP_ARTIFACTS[task]
        return {
            name: json.dumps(data, ensure_ascii=False, indent=(2 if variant else None))
            + "\n"
        }

    if task == "M1":
        defaults = """
module.exports = {enabled:true,retryCount:3,timeoutMs:500,label:'worker',
  transport:{strict:true,headers:{accept:'application/json'}},tags:['default']};
"""
        merge = (
            """
const isPlain = (v) => v !== null && typeof v === 'object' && !Array.isArray(v) &&
  (Object.getPrototypeOf(v) === Object.prototype || Object.getPrototypeOf(v) === null);
function clone(v) {
  if (Array.isArray(v)) return v.map(clone);
  if (!isPlain(v)) return v;
  return Object.fromEntries(Object.entries(v).map(([k,x]) => [k,clone(x)]));
}
function mergeConfig(base, override) {
  const out = clone(base);
  for (const [key,value] of Object.entries(override || {})) {
    if (value === undefined) continue;
    out[key] = isPlain(value) && isPlain(out[key]) ? mergeConfig(out[key],value) : clone(value);
  }
  return out;
}
module.exports = {mergeConfig};
"""
            if variant == 0
            else """
const object = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
function copy(v) {
  if (Array.isArray(v)) return v.map(copy);
  if (!object(v)) return v;
  const out = {};
  for (const key of Object.keys(v)) out[key] = copy(v[key]);
  return out;
}
function mergeConfig(base, override) {
  const out = copy(base);
  if (!object(override)) return out;
  Object.keys(override).forEach((key) => {
    const value = override[key];
    if (value === undefined) return;
    out[key] = object(value) && object(out[key]) ? mergeConfig(out[key],value) : copy(value);
  });
  return out;
}
module.exports = {mergeConfig};
"""
        )
        index = """
const defaults = require('./defaults');
const {mergeConfig} = require('./merge');
function resolveConfig(overrides = {}) { return mergeConfig(defaults,overrides); }
module.exports = {defaults,mergeConfig,resolveConfig};
"""
        return {
            "src/config/defaults.js": dedent(defaults).lstrip(),
            "src/config/merge.js": dedent(merge).lstrip(),
            "src/config/index.js": dedent(index).lstrip(),
        }

    if task == "D1":
        expr = (
            "json.dumps(records, ensure_ascii=False, sort_keys=True)"
            if variant == 0
            else "json.JSONEncoder(ensure_ascii=False, sort_keys=True).encode(records)"
        )
        code = "import json\n"
        if phase == 2:
            code += "import csv\nimport io\n"
        code += (
            "def total(records):\n    return sum(row['count'] for row in records)\n\n"
        )
        code += (
            "def render(records, format='json'):\n    if format == 'json':\n        return "
            + expr
            + "\n"
        )
        if phase == 2:
            if variant == 0:
                code += (
                    "    if format == 'csv':\n        stream = io.StringIO(newline='')\n"
                    "        writer = csv.writer(stream, lineterminator='\\n')\n"
                    "        writer.writerow(['name', 'count'])\n"
                    "        writer.writerows((row['name'], row['count']) for row in records)\n"
                    "        return stream.getvalue()\n"
                )
            else:
                code += (
                    "    if format == 'csv':\n        stream = io.StringIO(newline='')\n"
                    "        writer = csv.DictWriter(stream, fieldnames=['name','count'], lineterminator='\\n')\n"
                    "        writer.writeheader()\n"
                    "        for row in records: writer.writerow({'name':row['name'],'count':row['count']})\n"
                    "        return stream.getvalue()\n"
                )
        return {"exporter.py": code + "    raise ValueError('unsupported format')\n"}

    if task == "D2":
        ledger = (
            """
function firstAdjustments(rows) {
  const seen = new Set(), values = [], duplicates = new Set();
  for (const row of rows) {
    if (seen.has(row.id)) { duplicates.add(row.id); continue; }
    seen.add(row.id); values.push(row);
  }
  return {rows:values,duplicates:[...duplicates].sort()};
}
module.exports = {firstAdjustments};
"""
            if variant == 0
            else """
function firstAdjustments(rows) {
  const first = new Map(), duplicates = new Set();
  rows.forEach((row) => {
    if (first.has(row.id)) duplicates.add(row.id);
    else first.set(row.id,row);
  });
  return {rows:[...first.values()],duplicates:[...duplicates].sort()};
}
module.exports = {firstAdjustments};
"""
        )
        calc = (
            """
function buildReport(accounts, rows, duplicates) {
  const balances = {};
  for (const a of accounts) balances[a.account_id] = a.balance_cents;
  for (const r of rows) if (r.status === 'posted') balances[r.account_id] += r.delta_cents;
  const ids = Object.keys(balances).sort();
  const changed = ids.filter((id) => accounts.find((a) => a.account_id === id).balance_cents !== balances[id]);
  return {balances:Object.fromEntries(ids.map((id) => [id,balances[id]])),
    changed_ids:changed,ignored_duplicate_ids:[...duplicates].sort(),
    total_balance_cents:ids.reduce((sum,id) => sum+balances[id],0)};
}
module.exports = {buildReport};
"""
            if variant == 0
            else """
function buildReport(accounts, rows, duplicates) {
  const opening = Object.fromEntries(accounts.map((a) => [a.account_id,a.balance_cents]));
  const delta = rows.reduce((sum,r) => {
    if (r.status === 'posted') sum[r.account_id] = (sum[r.account_id] || 0) + r.delta_cents;
    return sum;
  }, {});
  const balances = {};
  for (const id of Object.keys(opening).sort()) balances[id] = opening[id] + (delta[id] || 0);
  return {balances,changed_ids:Object.keys(balances).filter((id) => balances[id] !== opening[id]).sort(),
    ignored_duplicate_ids:Array.from(duplicates).sort(),
    total_balance_cents:Object.values(balances).reduce((a,b) => a+b,0)};
}
module.exports = {buildReport};
"""
        )
        index = """
const {firstAdjustments} = require('./ledger');
const {buildReport} = require('./reconcile');
function buildReconciliationReport(accounts, adjustments) {
  const unique = firstAdjustments(adjustments);
  return buildReport(accounts,unique.rows,unique.duplicates);
}
module.exports = {buildReconciliationReport};
"""
        data = json.dumps(_MCP_ARTIFACTS[task][1], ensure_ascii=False, indent=2) + "\n"
        return {
            "src/ledger.js": dedent(ledger).lstrip(),
            "src/reconcile.js": dedent(calc).lstrip(),
            "src/index.js": dedent(index).lstrip(),
            "reconciliation.json": data,
        }

    if task == "H1":
        code = (
            """
import math, time
class TTLCache:
    def __init__(self, clock=None):
        self._clock = clock if clock is not None else time.monotonic
        self._entries = {}
    def set(self, key, value, ttl):
        if isinstance(ttl,bool) or not isinstance(ttl,(int,float)) or not math.isfinite(ttl) or ttl < 0:
            raise ValueError('ttl must be finite and nonnegative')
        self._entries[key] = (value,self._clock()+ttl)
    def get(self, key, default=None):
        entry = self._entries.get(key)
        if entry is None: return default
        value, expiry = entry
        if expiry <= self._clock():
            del self._entries[key]
            return default
        return value
"""
            if variant == 0
            else """
import math, time
class TTLCache:
    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._values = {}
    def set(self, key, value, ttl):
        if type(ttl) not in (int,float) or not math.isfinite(ttl) or ttl < 0:
            raise ValueError('bad ttl')
        self._values[key] = {'value':value,'expiry':self._clock()+ttl}
    def get(self, key, default=None):
        item = self._values.get(key)
        if item is None: return default
        if self._clock() >= item['expiry']:
            self._values.pop(key,None)
            return default
        return item['value']
"""
        )
        return {"ttl_cache.py": dedent(code).lstrip()}

    name, expected = _MCP_ARTIFACTS[task]
    return {
        name: json.dumps(expected, ensure_ascii=False, indent=(2 if variant else None))
        + "\n"
    }


def wrong_files(task: str, *,
                task_contract_id: str = HISTORICAL_CONTRACT) -> list[dict[str, str]]:
    _validate(task)
    contract = resolve_task_contract(task, task_contract_id)
    if task == "B1":
        return [
            {
                "orders/report.py": "def build_report(records):\n    out={}\n    for r in records: out[r['customer']]=out.get(r['customer'],0)+r['amount_cents']\n    return out\n"
            },
            {
                "orders/report.py": "def build_report(records):\n    out={}; seen=set()\n    for r in records:\n        if r['id'] in seen: continue\n        seen.add(r['id']); k=r['customer'].strip(); out[k]=out.get(k,0)+r['amount_cents']\n    return out\n"
            },
        ]
    if task == "B2":
        base = reference_files(task)
        dupe = base["src/convert.js"].replace(
            "rows.push(validateRecord(value, i + 1));",
            "if (!rows.some((r) => r.id === value.id)) rows.push(validateRecord(value, i + 1));",
        )
        weak = base["src/validate.js"].replace(
            "!Number.isSafeInteger(row.id) || row.id <= 0 || typeof row.name !== 'string'",
            "typeof row.name !== 'string'",
        )
        return [{**base, "src/convert.js": dupe}, {**base, "src/validate.js": weak}]
    if task == "C1":
        base = reference_files(task)["pagination.py"]
        one = base.replace(
            "        if cursor is None: return result\n",
            "        if cursor is None: return result\n        return result\n",
        )
        boolean = base.replace(
            "type(page_size) is not int", "not isinstance(page_size, int)"
        )
        return [{"pagination.py": one}, {"pagination.py": boolean}]
    if task == "C2":
        return [
            {"report.json": '{"open_ids":[101,103],"total_estimate":11}\n'},
            {"report.json": '{"open_ids":[101,103,104,106],"total_estimate":19}\n'},
        ]
    if task == "M1":
        if contract == M1_INDEPENDENT_CONTRACT:
            base = reference_files(task, 0, phase=1,
                                   task_contract_id=task_contract_id)
            alias_defaults = base["src/config/merge.js"].replace(
                "const out = clone(base);", "const out = { ...base };"
            )
            shallow = base["src/config/merge.js"].replace(
                ": clone(value)", ": value"
            )
            return [
                {**base, "src/config/merge.js": alias_defaults},
                {**base, "src/config/merge.js": shallow},
            ]
        base = reference_files(task)
        falsey = base["src/config/merge.js"].replace(
            "if (value === undefined) continue;", "if (!value) continue;"
        )
        shallow = base["src/config/merge.js"].replace(
            "isPlain(value) && isPlain(out[key]) ? mergeConfig(out[key],value) : clone(value)",
            "clone(value)",
        )
        return [
            {**base, "src/config/merge.js": falsey},
            {**base, "src/config/merge.js": shallow},
        ]
    if task == "M2":
        return [
            {"receipt.json": '{"change_id":"C-17","applied":true,"version":1}\n'},
            {"receipt.json": '{"change_id":"C-17","applied":false,"version":2}\n'},
        ]
    if task == "D1":
        base = reference_files(task, 0, 2)["exporter.py"]
        naive = base.replace(
            "        writer.writerows((row['name'], row['count']) for row in records)",
            "        stream.write(''.join(row['name'] + ',' + str(row['count']) + '\\n' for row in records))",
        )
        ascii_only = base.replace("ensure_ascii=False", "ensure_ascii=True")
        return [{"exporter.py": naive}, {"exporter.py": ascii_only}]
    if task == "D2":
        base = reference_files(task)
        last = base["src/ledger.js"].replace(
            "if (seen.has(row.id)) { duplicates.add(row.id); continue; }\n    seen.add(row.id); values.push(row);",
            "if (seen.has(row.id)) duplicates.add(row.id);\n    seen.add(row.id); values.push(row);",
        )
        status = base["src/reconcile.js"].replace(
            "r.status === 'posted'", "r.status !== 'void'"
        )
        return [{**base, "src/ledger.js": last}, {**base, "src/reconcile.js": status}]
    if task == "H1":
        base = reference_files(task)["ttl_cache.py"]
        boundary = base.replace(
            "if expiry <= self._clock():", "if expiry < self._clock():"
        )
        falsey = base.replace(
            "if entry is None: return default",
            "if entry is None or not entry[0]: return default",
        )
        return [{"ttl_cache.py": boundary}, {"ttl_cache.py": falsey}]
    if task == "H2":
        return [
            {
                "asset-report.json": '{"changed_ids":["AS-4"],"statuses":{"AS-1":"active","AS-2":"active","AS-3":"retired","AS-4":"retired"}}\n'
            },
            {
                "asset-report.json": '{"changed_ids":["AS-2","AS-4"],"statuses":{"AS-1":"active","AS-2":"repair","AS-3":"retired","AS-4":"retired"}}\n'
            },
        ]
    return []


__all__ = [
    "TASKS",
    "HOLDOUTS",
    "ALL_TASKS",
    "TASK_SPECS",
    "HISTORICAL_CONTRACT",
    "M1_INDEPENDENT_CONTRACT",
    "task_contracts",
    "resolve_task_contract",
    "seed_task",
    "seed_sources",
    "followup_prompt",
    "checks_source",
    "reference_files",
    "wrong_files",
    "exports",
]
