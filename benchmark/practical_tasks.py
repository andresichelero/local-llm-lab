"""Small practical projects and independent CPython acceptance checks.

Only ``seed_task`` content is exposed to the agent. Reference implementations
and acceptance checks stay in the supervisor, outside its workspace.
"""

from pathlib import Path
from textwrap import dedent

TASKS = (
    "bugfix", "feature", "mcp_report", "recovery", "maintenance",
    "continuation", "tiebreak",
)

ISSUES = (
    {"id": 101, "status": "open", "estimate": 3},
    {"id": 102, "status": "closed", "estimate": 5},
    {"id": 103, "status": "open", "estimate": 8},
    {"id": 104, "status": "open", "estimate": 2},
    {"id": 105, "status": "closed", "estimate": 1},
    {"id": 106, "status": "open", "estimate": 5},
)

_COMMON = """
Work in this project. Read the existing files, implement the requested change,
preserve existing behavior and run Python tests before your final answer.
Add meaningful tests under tests/ (for example tests/test_agent.py); test method
names are your choice. Use standard-library Python only. Finish with a brief
description of what changed and which tests you ran.
"""

_PROMPTS = {
    "bugfix": """
The order report sometimes drops paid orders and gives incorrect totals when
two customers share a name. Repair orders.report.build_report. Input is a list
of dicts with id, customer and amount_cents (integers). Duplicate IDs represent
replayed deliveries: keep ONLY the first record for each id, even if a later
record has a different amount/customer. Distinct IDs must all count even with
identical customer names. Preserve customer spelling. Return a dict mapping
customer to summed cents; include zero totals and support refunds (negative
cents). Do not mutate records. Keep orders.money.format_cents behavior.
""",
    "feature": """
Implement events.page_events(events, *, after=None, limit=2). Events are dicts
with unique positive integer id and arbitrary other fields. Return a NEW list
of events sorted by id, selecting id > after (or all when after is None),
at most limit entries. after must be None or a nonnegative integer. limit must
be an integer from 1 through 50. Reject booleans, strings and invalid numeric
values with ValueError. Do not mutate input order or contents. Keep existing
events.count_events working. Include validation tests and pagination tests.
""",
    "mcp_report": """
Use the configured local MCP server. Discover its tools, retrieve every page
of its issue catalog (the server limits page size), and write report.json:
{"open_ids": [sorted integer IDs of all open issues], "total_estimate": sum
of the estimates of those open issues}. Only status exactly "open" counts.
Follow pagination until next_cursor is null. Do not fabricate unseen pages or
hardcode an expected catalog. Your final response should summarize the report.
""",
    "recovery": """
Use the configured local MCP server to apply change C-17 exactly once. First
retrieve it with get_change(change_id="C-17") to learn the required version.
apply_change requires change_id, version and idempotency_key; use "C-17-v2"
as the key. A tool failure may describe invalid arguments or a transient
failure: inspect it, fix invalid arguments or retry transient failures using
the same key. Do not apply another change. On confirmed success save
receipt.json with {"change_id":"C-17","applied":true,"version":2}.
The actual server state will be checked as well as your receipt.
""",
    "maintenance": """
Refactor catalog.search.search_titles so normalization is a reusable helper
catalog.normalize.normalize(text). normalize returns casefolded text with
leading/trailing and repeated Unicode whitespace collapsed to single spaces.
search_titles(titles, query) returns ORIGINAL titles in their original order
whose normalized form contains the normalized query. Empty normalized query
returns []. Fix Unicode case matching and repeated-space regressions without
mutating titles. Preserve public imports from catalog and catalog.search;
catalog.normalize.normalize must be importable. Add regression tests.
""",
    "continuation": """
Implement exporter.render(records, format="json") for a small report exporter.
records are dictionaries with name (string) and count (integer). JSON output
must decode to the original records in order, preserve Unicode and use stable
sorted dictionary keys. Return a string. Reject unsupported format with
ValueError. Do not mutate the input. Keep exporter.total(records) unchanged.
Add tests and finish this first delivery; a user follow-up will then arrive.
""",
    "tiebreak": """
Implement triage.summarize(issues), returning {"open_ids": sorted unique IDs,
"total_estimate": sum of estimates} for status exactly "open". Duplicate IDs
are replayed deliveries: only the FIRST record per ID counts, even if its
status or estimate changes later. Do not mutate input; empty input returns
empty IDs and total 0. Then use the local MCP issue catalog through every
page, call your implementation on the retrieved data and save report.json.
The code will also be checked on other data, including duplicates and closed
issues. Discover the MCP tools and follow next_cursor until null.
""",
}

_SEEDS = {
    "bugfix": {
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
    "feature": {"events.py": """
def count_events(events):
    return len(events)

def page_events(events, *, after=None, limit=2):
    raise NotImplementedError('pagination is not implemented')
"""},
    "mcp_report": {},
    "recovery": {},
    "maintenance": {
        "catalog/__init__.py": "from .search import search_titles\n",
        "catalog/search.py": """
def search_titles(titles, query):
    return [title for title in titles if query.lower() in title.lower()]
""",
    },
    "continuation": {"exporter.py": """
def total(records):
    return sum(record['count'] for record in records)

def render(records, format='json'):
    raise NotImplementedError('report export is not implemented')
"""},
    "tiebreak": {"triage.py": """
def summarize(issues):
    raise NotImplementedError('triage is not implemented')
"""},
}

_BASELINE = {
    "bugfix": "from orders.money import format_cents\nassert format_cents(125) == '1.25'\n",
    "feature": "from events import count_events\nassert count_events([{}, {}]) == 2\n",
    "maintenance": "from catalog import search_titles\nassert search_titles(['Alpha', 'Beta'], 'alp') == ['Alpha']\n",
    "continuation": "from exporter import total\nassert total([{'name': 'a', 'count': 3}]) == 3\n",
    "tiebreak": "from triage import summarize\nassert callable(summarize)\n",
    "mcp_report": "import json\nassert json.loads('{}') == {}\n",
    "recovery": "import json\nassert json.loads('true') is True\n",
}


def _validate(task):
    if task not in TASKS:
        raise ValueError(f"Unknown practical task: {task}")


def _write(workspace, files):
    for name, content in files.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(dedent(content).lstrip(), encoding="utf-8")


def seed_task(task, workspace: Path) -> str:
    _validate(task)
    _write(workspace, _SEEDS[task])
    baseline = "\n".join("        " + line for line in _BASELINE[task].splitlines())
    _write(workspace, {"tests/test_existing.py":
        "import unittest\n\nclass ExistingTests(unittest.TestCase):\n"
        "    def test_public_behavior(self):\n" + baseline + "\n"})
    common = (_COMMON if task not in {"mcp_report", "recovery"} else
              "Use the configured MCP tools and save the requested JSON file. "
              "Finish with a brief verified result. No Python implementation or new unit tests are needed.")
    prompt = dedent(_PROMPTS[task]).strip() + "\n\n" + dedent(common).strip()
    (workspace / "TASK.md").write_text(prompt + "\n", encoding="utf-8")
    return prompt


def exports(task) -> tuple:
    _validate(task)
    additional = {
        "maintenance": ("catalog/normalize.py",),
        "mcp_report": ("report.json",),
        "recovery": ("receipt.json",),
        "tiebreak": ("report.json",),
    }.get(task, ())
    return tuple(_SEEDS[task]) + additional + (
        "tests/test_existing.py", "tests/test_agent.py", "tests",
    )


def followup_prompt(task) -> str:
    _validate(task)
    if task != "continuation":
        return ""
    return (
        "New requirement: keep JSON behavior and add format='csv'. Return CSV "
        "with header name,count, one row per record in order, using standard "
        "CSV quoting for commas, quotes and newlines. Empty input still returns "
        "the header. Use LF row endings. Unicode must survive. Unsupported "
        "formats still raise ValueError; preserve total(). Update and run tests."
    )


_CHECKS = {
    "bugfix": """
from orders.report import build_report
from orders.money import format_cents
class Acceptance(unittest.TestCase):
    def test_replays_and_shared_names(self):
        rows = [dict(id=1, customer='Ada', amount_cents=100),
                dict(id=2, customer='Ada', amount_cents=50),
                dict(id=1, customer='Other', amount_cents=900),
                dict(id=3, customer='Ada', amount_cents=-150),
                dict(id=4, customer='Bea', amount_cents=-25)]
        before = copy.deepcopy(rows)
        self.assertEqual(build_report(rows), {'Ada': 0, 'Bea': -25})
        self.assertEqual(rows, before)
        self.assertEqual(build_report([]), {})
        self.assertEqual(format_cents(125), '1.25')
    def test_arbitrary_ids_and_names(self):
        rows = [dict(id=i, customer=('A' if i % 2 else 'B'), amount_cents=i-5)
                for i in range(1, 9)]
        self.assertEqual(build_report(rows), {'A': -4, 'B': 0})
""",
    "feature": """
from events import page_events, count_events
class Acceptance(unittest.TestCase):
    def test_pages_and_immutability(self):
        rows = [{'id': n, 'name': str(n)} for n in (9, 1, 5, 3)]
        before = copy.deepcopy(rows)
        self.assertEqual(page_events(rows), [rows[1], rows[3]])
        self.assertEqual(page_events(rows, after=3, limit=50), [rows[2], rows[0]])
        self.assertEqual(page_events(rows, after=99), [])
        self.assertEqual(page_events([], after=0), [])
        self.assertEqual(rows, before)
        self.assertEqual(count_events(rows), 4)
    def test_validation(self):
        for limit in (0, -1, 51, True, False, '2', 2.0, None):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                page_events([], limit=limit)
        for after in (-1, True, False, '1', 1.0):
            with self.subTest(after=after), self.assertRaises(ValueError):
                page_events([], after=after)
""",
    "mcp_report": """
class Acceptance(unittest.TestCase):
    def test_full_report(self):
        self.assertEqual(json.loads(Path('report.json').read_text()),
                         {'open_ids': [101, 103, 104, 106], 'total_estimate': 18})
""",
    "recovery": """
class Acceptance(unittest.TestCase):
    def test_receipt(self):
        self.assertEqual(json.loads(Path('receipt.json').read_text()),
                         {'change_id': 'C-17', 'applied': True, 'version': 2})
""",
    "maintenance": """
from catalog import search_titles
from catalog.search import search_titles as public_search
from catalog.normalize import normalize
class Acceptance(unittest.TestCase):
    def test_unicode_normalization_and_public_api(self):
        self.assertEqual(normalize('  STRAẞE\\t  Guide\\u00a0'), 'strasse guide')
        rows = ['Straße  Guide', 'other', 'STRASSE\\tguide', 'Guide Straße']
        before = list(rows)
        self.assertEqual(search_titles(rows, '  strasse\\u00a0guide '), rows[::2])
        self.assertEqual(public_search(rows, '\\t '), [])
        self.assertEqual(search_titles([], 'a'), [])
        self.assertEqual(rows, before)
""",
    "continuation": """
from exporter import render, total
class Acceptance(unittest.TestCase):
    def test_json_preserved(self):
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
    "tiebreak": """
from triage import summarize
class Acceptance(unittest.TestCase):
    def test_summarize_replays_and_state(self):
        rows = [{'id': 9, 'status': 'closed', 'estimate': 70},
                {'id': 4, 'status': 'open', 'estimate': 2},
                {'id': 9, 'status': 'open', 'estimate': 90},
                {'id': 2, 'status': 'open', 'estimate': 7},
                {'id': 4, 'status': 'open', 'estimate': 100}]
        before = copy.deepcopy(rows)
        self.assertEqual(summarize(rows), {'open_ids': [2, 4], 'total_estimate': 9})
        self.assertEqual(summarize([]), {'open_ids': [], 'total_estimate': 0})
        self.assertEqual(rows, before)
    def test_live_report(self):
        self.assertEqual(json.loads(Path('report.json').read_text()),
                         {'open_ids': [101, 103, 104, 106], 'total_estimate': 18})
""",
}

_CSV_CHECK = """
    def test_followup_csv(self):
        import csv
        import io
        rows = [{'name': 'a,b', 'count': 2}, {'name': 'a"b\\nç', 'count': -3}]
        before = copy.deepcopy(rows)
        result = render(rows, format='csv')
        self.assertNotIn('\\r\\n', result)
        self.assertEqual(list(csv.reader(io.StringIO(result))),
                         [['name', 'count'], ['a,b', '2'], ['a"b\\nç', '-3']])
        self.assertEqual(list(csv.reader(io.StringIO(render([], format='csv')))),
                         [['name', 'count']])
        self.assertEqual(rows, before)
"""


def checks_source(task, phase=1) -> str:
    _validate(task)
    if phase not in (1, 2):
        raise ValueError("phase must be 1 or 2")
    header = (
        "import copy, json, sys, unittest\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path.cwd()))\n"
    )
    source = dedent(_CHECKS[task]).lstrip()
    if task == "continuation" and phase == 2:
        source += _CSV_CHECK
    return header + source + "\nif __name__ == '__main__': unittest.main()\n"


def reference_files(task, variant=0, phase=1) -> dict:
    _validate(task)
    if variant not in (0, 1) or phase not in (1, 2):
        raise ValueError("variant must be 0 or 1; phase must be 1 or 2")
    if task == "bugfix":
        source = (
            "def build_report(records):\n    seen = set()\n    totals = {}\n"
            "    for row in records:\n        if row['id'] in seen:\n            continue\n"
            "        seen.add(row['id'])\n        name = row['customer']\n"
            "        totals[name] = totals.get(name, 0) + row['amount_cents']\n    return totals\n"
            if variant == 0 else
            "from collections import defaultdict\ndef build_report(records):\n"
            "    unique = {}\n    for row in records:\n        unique.setdefault(row['id'], row)\n"
            "    totals = defaultdict(int)\n    for row in unique.values():\n"
            "        totals[row['customer']] += row['amount_cents']\n    return dict(totals)\n"
        )
        return {"orders/report.py": source}
    if task == "feature":
        selection = (
            "    return sorted((row for row in events if after is None or row['id'] > after), "
            "key=lambda row: row['id'])[:limit]\n" if variant == 0 else
            "    ordered = sorted(events, key=lambda row: row['id'])\n"
            "    result = []\n    for row in ordered:\n"
            "        if (after is None or row['id'] > after) and len(result) < limit:\n"
            "            result.append(row)\n    return result\n"
        )
        return {"events.py": "def count_events(events):\n    return len(events)\n\n"
                "def page_events(events, *, after=None, limit=2):\n"
                "    if type(limit) is not int or not 1 <= limit <= 50:\n"
                "        raise ValueError('invalid limit')\n"
                "    if after is not None and (type(after) is not int or after < 0):\n"
                "        raise ValueError('invalid cursor')\n" + selection}
    if task in ("mcp_report", "recovery"):
        name = "receipt.json" if task == "recovery" else "report.json"
        content = ('{"change_id":"C-17","applied":true,"version":2}'
                   if task == "recovery" else
                   '{"open_ids":[101,103,104,106],"total_estimate":18}')
        if variant:
            import json
            content = json.dumps(json.loads(content), indent=2, sort_keys=True)
        return {name: content + "\n"}
    if task == "maintenance":
        normalize = ("def normalize(text):\n    return ' '.join(text.casefold().split())\n"
                     if variant == 0 else
                     "import re\ndef normalize(text):\n"
                     "    return re.sub(r'\\s+', ' ', text.strip()).casefold()\n")
        search = ("from .normalize import normalize\ndef search_titles(titles, query):\n"
                  "    needle = normalize(query)\n    if not needle:\n        return []\n"
                  "    return [title for title in titles if needle in normalize(title)]\n"
                  if variant == 0 else
                  "from .normalize import normalize\ndef search_titles(titles, query):\n"
                  "    needle = normalize(query)\n    matches = []\n"
                  "    for title in titles:\n        if needle and needle in normalize(title):\n"
                  "            matches.append(title)\n    return matches\n")
        return {"catalog/normalize.py": normalize, "catalog/search.py": search}
    if task == "continuation":
        json_code = ("json.dumps(records, ensure_ascii=False, sort_keys=True)" if variant == 0
                     else "json.JSONEncoder(ensure_ascii=False, sort_keys=True).encode(records)")
        source = ("import json\nimport csv\nimport io\n"
                  "def total(records):\n    return sum(row['count'] for row in records)\n"
                  "def render(records, format='json'):\n    if format == 'json':\n"
                  f"        return {json_code}\n")
        if phase == 2:
            source += "    if format == 'csv':\n        stream = io.StringIO()\n"
            source += (
                "        writer = csv.writer(stream, lineterminator='\\n')\n"
                "        writer.writerow(['name', 'count'])\n"
                "        writer.writerows((row['name'], row['count']) for row in records)\n"
                if variant == 0 else
                "        writer = csv.DictWriter(stream, fieldnames=['name', 'count'], lineterminator='\\n')\n"
                "        writer.writeheader()\n        writer.writerows(records)\n"
            )
            source += "        return stream.getvalue()\n"
        return {"exporter.py": source + "    raise ValueError('unsupported format')\n"}
    source = (
        "def summarize(issues):\n    first = {}\n    for issue in issues:\n"
        "        first.setdefault(issue['id'], issue)\n"
        "    rows = [issue for issue in first.values() if issue['status'] == 'open']\n"
        "    return {'open_ids': sorted(row['id'] for row in rows), "
        "'total_estimate': sum(row['estimate'] for row in rows)}\n"
        if variant == 0 else
        "def summarize(issues):\n    seen = set()\n    ids = []\n    total = 0\n"
        "    for issue in issues:\n        if issue['id'] in seen:\n            continue\n"
        "        seen.add(issue['id'])\n        if issue['status'] == 'open':\n"
        "            ids.append(issue['id'])\n            total += issue['estimate']\n"
        "    return {'open_ids': sorted(ids), 'total_estimate': total}\n"
    )
    return {"triage.py": source, "report.json":
            '{"open_ids":[101,103,104,106],"total_estimate":18}\n'}


def wrong_files(task) -> list:
    _validate(task)
    if task == "bugfix":
        return [{"orders/report.py": "def build_report(records):\n    totals = {}\n"
                 "    for row in records:\n"
                 "        totals[row['customer']] = totals.get(row['customer'], 0) + row['amount_cents']\n"
                 "    return totals\n"}]
    if task == "feature":
        correct = reference_files(task)["events.py"]
        return [{"events.py": correct.replace("row['id'] > after", "row['id'] >= after")},
                {"events.py": correct.replace("type(limit) is not int", "not isinstance(limit, int)")}]
    if task == "mcp_report":
        return [{"report.json": '{"open_ids":[101],"total_estimate":3}'}]
    if task == "recovery":
        return [{"receipt.json": '{"change_id":"C-17","applied":true,"version":1}'}]
    if task == "maintenance":
        files = reference_files(task)
        files["catalog/normalize.py"] = "def normalize(text):\n    return text.strip().lower()\n"
        return [files]
    if task == "continuation":
        files = reference_files(task, phase=2)
        files["exporter.py"] = files["exporter.py"].replace(
            "writer.writerows((row['name'], row['count']) for row in records)",
            "stream.write(''.join(row['name'] + ',' + str(row['count']) + '\\n' for row in records))")
        return [files]
    files = reference_files(task)
    files["triage.py"] = files["triage.py"].replace(
        "first.setdefault(issue['id'], issue)", "first[issue['id']] = issue")
    return [files]
