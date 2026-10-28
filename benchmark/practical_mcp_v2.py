"""Isolated stdio MCP server for practical v2 episodes."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ISSUES = [
    {"id": 101, "status": "open", "estimate": 3},
    {"id": 102, "status": "closed", "estimate": 5},
    {"id": 103, "status": "open", "estimate": 8},
    {"id": 104, "status": "open", "estimate": 2},
    {"id": 105, "status": "closed", "estimate": 1},
    {"id": 106, "status": "open", "estimate": 5},
]
ACCOUNTS = [
    {"account_id": "A-01", "balance_cents": 1000, "version": 2},
    {"account_id": "A-02", "balance_cents": 500, "version": 4},
    {"account_id": "A-03", "balance_cents": -25, "version": 1},
]
ADJUSTMENTS = [
    {"id": "ADJ-1", "account_id": "A-01", "delta_cents": 200, "status": "posted"},
    {"id": "ADJ-2", "account_id": "A-01", "delta_cents": -25, "status": "posted"},
    {"id": "ADJ-3", "account_id": "A-02", "delta_cents": -100, "status": "posted"},
    {"id": "ADJ-4", "account_id": "A-02", "delta_cents": 25, "status": "posted"},
    {"id": "ADJ-5", "account_id": "A-03", "delta_cents": 0, "status": "posted"},
    {"id": "ADJ-1", "account_id": "A-02", "delta_cents": 999, "status": "posted"},
]
ASSETS = [
    {"asset_id": "AS-1", "status": "active", "version": 1},
    {"asset_id": "AS-2", "status": "repair", "version": 2},
    {"asset_id": "AS-3", "status": "retired", "version": 1},
    {"asset_id": "AS-4", "status": "active", "version": 3},
]
AUDITS = [
    {"id": "AU-1", "asset_id": "AS-1", "status": "active", "observed_at": 10},
    {"id": "AU-2", "asset_id": "AS-2", "status": "repair", "observed_at": 9},
    {"id": "AU-3", "asset_id": "AS-2", "status": "active", "observed_at": 12},
    {"id": "AU-4", "asset_id": "AS-3", "status": "retired", "observed_at": 5},
    {"id": "AU-5", "asset_id": "AS-4", "status": "retired", "observed_at": 20},
    {"id": "AU-2", "asset_id": "AS-4", "status": "active", "observed_at": 99},
]


def _schema(properties, required=(), additional=False):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": additional,
    }


_CURSOR_PROPS = {
    "cursor": {"type": ["string", "null"]},
    "page_size": {
        "type": "integer",
        "minimum": 1,
        "maximum": 2,
        "default": 2,
        "description": "when omitted the server applies the fallback of 2",
    },
}
_REPORT_SCHEMA = {"type": "object", "additionalProperties": True}
_ISSUE_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "open_ids": {"type": "array", "items": {"type": "integer"}},
        "total_estimate": {"type": "integer"},
    },
    "required": ["open_ids", "total_estimate"],
    "additionalProperties": False,
}
_RECONCILIATION_SCHEMA = _schema({
    'balances': {'type': 'object', 'additionalProperties': {'type': 'integer'}},
    'changed_ids': {'type': 'array', 'items': {'type': 'string'}},
    'ignored_duplicate_ids': {'type': 'array', 'items': {'type': 'string'}},
    'total_balance_cents': {'type': 'integer'},
}, ('balances', 'changed_ids', 'ignored_duplicate_ids', 'total_balance_cents'))
_ASSET_REPORT_SCHEMA = _schema({
    'changed_ids': {'type': 'array', 'items': {'type': 'string'}},
    'statuses': {'type': 'object', 'additionalProperties': {'type': 'string'}},
}, ('changed_ids', 'statuses'))
TOOLS = [
    {
        "name": "list_issues",
        "description": "List issue pages; follow next_cursor until null.",
        "inputSchema": _schema(_CURSOR_PROPS),
    },
    {
        "name": "write_report",
        "description": "Store the completed issue report with open_ids and total_estimate.",
        "inputSchema": _schema({"report": _ISSUE_REPORT_SCHEMA}, ("report",)),
    },
    {
        "name": "get_change",
        "description": "Read change C-17; its first version is stale.",
        "inputSchema": _schema({"change_id": {"type": "string"}}, ("change_id",)),
    },
    {
        "name": "apply_change",
        "description": "Apply C-17 with current version and idempotency key.",
        "inputSchema": _schema(
            {
                "change_id": {"type": "string"},
                "version": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            ("change_id", "version", "idempotency_key"),
        ),
    },
    {
        "name": "list_accounts",
        "description": "List account pages; follow next_cursor until null.",
        "inputSchema": _schema(_CURSOR_PROPS),
    },
    {
        "name": "list_adjustments",
        "description": "List adjustment pages; follow next_cursor until null.",
        "inputSchema": _schema(_CURSOR_PROPS),
    },
    {
        "name": "apply_balance",
        "description": "Set an account balance; same key is idempotent.",
        "inputSchema": _schema(
            {
                "account_id": {"type": "string"},
                "version": {"type": "integer"},
                "target_balance_cents": {"type": "integer"},
                "idempotency_key": {"type": "string"},
            },
            ("account_id", "version", "target_balance_cents", "idempotency_key"),
        ),
    },
    {
        "name": "write_reconciliation",
        "description": "Store the account reconciliation report.",
        "inputSchema": _schema({"report": _RECONCILIATION_SCHEMA}, ("report",)),
    },
    {
        "name": "list_assets",
        "description": "List asset pages; follow next_cursor until null.",
        "inputSchema": _schema(_CURSOR_PROPS),
    },
    {
        "name": "list_audits",
        "description": "List asset audit pages; follow next_cursor until null.",
        "inputSchema": _schema(_CURSOR_PROPS),
    },
    {
        "name": "set_asset_status",
        "description": "Set an asset status; same key is idempotent.",
        "inputSchema": _schema(
            {
                "asset_id": {"type": "string"},
                "version": {"type": "integer"},
                "status": {"type": "string"},
                "idempotency_key": {"type": "string"},
            },
            ("asset_id", "version", "status", "idempotency_key"),
        ),
    },
    {
        "name": "write_asset_report",
        "description": "Store the asset reconciliation report.",
        "inputSchema": _schema({"report": _ASSET_REPORT_SCHEMA}, ("report",)),
    },
]
_ROW_FIELDS = {
    'list_issues': {'id':'integer','status':'string','estimate':'integer'},
    'list_accounts': {'account_id':'string','balance_cents':'integer','version':'integer'},
    'list_adjustments': {'id':'string','account_id':'string','delta_cents':'integer','status':'string'},
    'list_assets': {'asset_id':'string','status':'string','version':'integer'},
    'list_audits': {'id':'string','asset_id':'string','status':'string','observed_at':'integer'},
}
_RECEIPT_FIELDS = {
    'get_change': {'change_id':'string','version':'integer','idempotency_key':'string'},
    'apply_change': {'change_id':'string','applied':'boolean','version':'integer'},
    'apply_balance': {'account_id':'string','balance_cents':'integer','version':'integer','idempotent_replay':'boolean'},
    'set_asset_status': {'asset_id':'string','status':'string','version':'integer','idempotent_replay':'boolean'},
}
for _tool in TOOLS:
    _name = _tool['name']
    if _name in _ROW_FIELDS:
        _fields = _ROW_FIELDS[_name]
        _row = _schema({key:{'type':kind} for key,kind in _fields.items()}, tuple(_fields))
        _data = _schema({'items':{'type':'array','items':_row}, 'next_cursor':{'type':['string','null']}}, ('items','next_cursor'))
    else:
        _fields = _RECEIPT_FIELDS.get(_name, {'stored':'boolean'})
        _data = _schema({key:{'type':kind} for key,kind in _fields.items()}, tuple(_fields))
    _tool['outputSchema'] = _schema({'data':_data}, ('data',))
_TOOL_NAMES = {tool["name"] for tool in TOOLS}
TASK_TOOLS = {
    "C2": frozenset({"list_issues", "write_report"}),
    "M2": frozenset({"get_change", "apply_change"}),
    "D2": frozenset({"list_accounts", "list_adjustments", "apply_balance", "write_reconciliation"}),
    "H2": frozenset({"list_assets", "list_audits", "set_asset_status", "write_asset_report"}),
}


def tools_for_task(task):
    """Return only the tools used by a task; None preserves the standalone server."""
    if task is not None and task not in TASK_TOOLS:
        raise ValueError(f"unknown MCP task: {task!r}")
    names = _TOOL_NAMES if task is None else TASK_TOOLS[task]
    return [copy.deepcopy(tool) for tool in TOOLS if tool["name"] in names]


def validate_value(value, schema):
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'integer': type(value) is int, 'string': isinstance(value, str),
             'boolean': type(value) is bool, 'null': value is None}
    if isinstance(kind, list):
        if not any(valid.get(k, False) for k in kind):
            return False
    elif kind and not valid.get(kind, False):
        return False
    if isinstance(value, dict):
        props = schema.get('properties', {})
        if not set(schema.get('required', [])) <= set(value):
            return False
        for key, item in value.items():
            child = props.get(key, schema.get('additionalProperties', True))
            if child is False or (isinstance(child, dict) and not validate_value(item, child)):
                return False
    if isinstance(value, list) and not all(validate_value(item, schema.get('items', {})) for item in value):
        return False
    return True


class ToolFailure(ValueError):
    """Deliberate tool failure returned to the agent."""


def _initial_state():
    return {
        "calls": [],
        "report": None,
        "get_change_reads": 0,
        "current_version": 2,
        "temporary_seen": False,
        "apply_count": 0,
        "applied_by_key": {},
        "accounts": copy.deepcopy(ACCOUNTS),
        "account_apply_count": {},
        "reconciliation": None,
        "assets": copy.deepcopy(ASSETS),
        "updated_by_key": {},
        "asset_report": None,
    }


class Server:
    """Small stdio MCP server with public data separated from private audit state."""

    def __init__(self, state_path: Path | None = None, *, task: str | None = None):
        self.path = Path(state_path) if state_path is not None else None
        self.tools = tools_for_task(task)
        self.tool_names = {tool["name"] for tool in self.tools}
        self.state = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path is not None and self.path.exists()
            else _initial_state()
        )

    def _save(self):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + ".tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.path)

    def _snapshot(self, call):
        name = call["name"]
        snapshot = {"sequence": len(self.state["calls"]), "call": copy.deepcopy(call)}
        if name in {"list_issues", "write_report"}:
            snapshot["report"] = copy.deepcopy(self.state["report"])
        elif name in {"get_change", "apply_change"}:
            snapshot.update(
                {
                    "current_version": self.state["current_version"],
                    "get_change_reads": self.state["get_change_reads"],
                    "temporary_seen": self.state["temporary_seen"],
                    "apply_count": self.state["apply_count"],
                    "applied_by_key": {
                        key: copy.deepcopy(value)
                        for key, value in self.state["applied_by_key"].items()
                        if key == "C-17-v2"
                    },
                }
            )
        elif name in {
            "list_accounts",
            "list_adjustments",
            "apply_balance",
            "write_reconciliation",
        }:
            snapshot.update(
                {
                    "account_count": len(self.state["accounts"]),
                    "account_apply_count": copy.deepcopy(
                        self.state["account_apply_count"]
                    ),
                    "account_balances": {
                        row["account_id"]: row["balance_cents"]
                        for row in self.state["accounts"]
                    },
                    "account_applied_by_key": {
                        key: copy.deepcopy(value)
                        for key, value in self.state["applied_by_key"].items()
                        if key.startswith("A-")
                    },
                    "reconciliation": copy.deepcopy(self.state["reconciliation"]),
                }
            )
        elif name in {
            "list_assets",
            "list_audits",
            "set_asset_status",
            "write_asset_report",
        }:
            snapshot.update(
                {
                    "asset_count": len(self.state["assets"]),
                    "asset_statuses": {
                        row["asset_id"]: row["status"] for row in self.state["assets"]
                    },
                    "updated_by_key": copy.deepcopy(self.state["updated_by_key"]),
                    "asset_report": copy.deepcopy(self.state["asset_report"]),
                }
            )
        return snapshot

    @staticmethod
    def _page(rows, args):
        cursor, size = args.get("cursor"), args.get("page_size", 2)
        if cursor is None:
            start = 0
        elif isinstance(cursor, str) and cursor.isdigit():
            start = int(cursor)
        else:
            raise ToolFailure("cursor must be null or a returned numeric cursor")
        if type(size) is not int or not 1 <= size <= 2:
            raise ToolFailure("page_size must be an integer from 1 through 2")
        if start > len(rows):
            raise ToolFailure("cursor is outside the catalog")
        end = start + size
        return {
            "items": copy.deepcopy(rows[start:end]),
            "next_cursor": str(end) if end < len(rows) else None,
        }

    def _run(self, name, args):
        if name not in self.tool_names:
            raise ToolFailure("tool is not available for this task")
        if not isinstance(args, dict):
            raise ToolFailure("arguments must be an object")
        if name == "list_issues":
            return self._page(ISSUES, args)
        if name == "write_report":
            report = args.get("report")
            if not isinstance(report, dict):
                raise ToolFailure("report must be an object")
            if (set(report) != {"open_ids", "total_estimate"}
                    or not isinstance(report.get("open_ids"), list)
                    or any(type(item) is not int for item in report["open_ids"])
                    or type(report.get("total_estimate")) is not int):
                raise ToolFailure("report must contain open_ids as an integer array and total_estimate as an integer")
            self.state["report"] = copy.deepcopy(report)
            return {"stored": True}
        if name == "get_change":
            if args.get("change_id") != "C-17":
                raise ToolFailure("unknown change")
            self.state["get_change_reads"] += 1
            return {
                "change_id": "C-17",
                "version": 1 if self.state["get_change_reads"] == 1 else 2,
                "idempotency_key": "C-17-v2",
            }
        if name == "apply_change":
            key = args.get("idempotency_key")
            if key in self.state["applied_by_key"]:
                if (args.get("change_id") != "C-17"
                        or type(args.get("version")) is not int
                        or args.get("version") != 2):
                    raise ToolFailure("idempotency key already used with different values")
                return copy.deepcopy(self.state["applied_by_key"][key])
            if (
                args.get("change_id") != "C-17"
                or type(args.get("version")) is not int
                or args.get("version") != 2
                or key != "C-17-v2"
            ):
                raise ToolFailure(
                    "stale or invalid version; read current change and retry"
                )
            if not self.state["temporary_seen"]:
                self.state["temporary_seen"] = True
                raise ToolFailure(
                    "temporary service failure; retry the same request and key"
                )
            receipt = {"change_id": "C-17", "applied": True, "version": 2}
            self.state["applied_by_key"][key] = receipt
            self.state["apply_count"] += 1
            return copy.deepcopy(receipt)
        if name == "list_accounts":
            return self._page(self.state["accounts"], args)
        if name == "list_adjustments":
            return self._page(ADJUSTMENTS, args)
        if name == "apply_balance":
            account_id, version = args.get("account_id"), args.get("version")
            target, key = args.get("target_balance_cents"), args.get("idempotency_key")
            if key in self.state["applied_by_key"]:
                old = self.state["applied_by_key"][key]
                if old["account_id"] != account_id or old["balance_cents"] != target:
                    raise ToolFailure(
                        "idempotency key already used with different values"
                    )
                return {**copy.deepcopy(old), "idempotent_replay": True}
            account = next(
                (
                    row
                    for row in self.state["accounts"]
                    if row["account_id"] == account_id
                ),
                None,
            )
            if account is None:
                raise ToolFailure("unknown account")
            if type(version) is not int or version != account["version"]:
                raise ToolFailure("stale account version")
            if type(target) is not int:
                raise ToolFailure("balance must be integer cents")
            if key != f"{account_id}-v{version}":
                raise ToolFailure("invalid idempotency key")
            receipt = {
                "account_id": account_id,
                "balance_cents": target,
                "version": version + 1,
                "idempotent_replay": False,
            }
            account["balance_cents"], account["version"] = target, version + 1
            self.state["applied_by_key"][key] = copy.deepcopy(receipt)
            counts = self.state["account_apply_count"]
            counts[account_id] = counts.get(account_id, 0) + 1
            return receipt
        if name == "write_reconciliation":
            report = args.get("report")
            if not isinstance(report, dict):
                raise ToolFailure("report must be an object")
            if not validate_value(report, _RECONCILIATION_SCHEMA):
                raise ToolFailure('invalid input: reconciliation report schema')
            self.state["reconciliation"] = copy.deepcopy(report)
            return {"stored": True}
        if name == "list_assets":
            return self._page(self.state["assets"], args)
        if name == "list_audits":
            return self._page(AUDITS, args)
        if name == "set_asset_status":
            asset_id, version = args.get("asset_id"), args.get("version")
            status, key = args.get("status"), args.get("idempotency_key")
            if key in self.state["updated_by_key"]:
                old = self.state["updated_by_key"][key]
                if old["asset_id"] != asset_id or old["status"] != status:
                    raise ToolFailure(
                        "idempotency key already used with different values"
                    )
                return {**copy.deepcopy(old), "idempotent_replay": True}
            asset = next(
                (row for row in self.state["assets"] if row["asset_id"] == asset_id),
                None,
            )
            if asset is None:
                raise ToolFailure("unknown asset")
            if type(version) is not int or version != asset["version"]:
                raise ToolFailure("stale asset version")
            if not isinstance(status, str):
                raise ToolFailure("status must be text")
            if key != f"{asset_id}-v{version}-{status}":
                raise ToolFailure("invalid idempotency key")
            receipt = {
                "asset_id": asset_id,
                "status": status,
                "version": version + 1,
                "idempotent_replay": False,
            }
            asset["status"], asset["version"] = status, version + 1
            self.state["updated_by_key"][key] = copy.deepcopy(receipt)
            return receipt
        if name == "write_asset_report":
            report = args.get("report")
            if not isinstance(report, dict):
                raise ToolFailure("report must be an object")
            if not validate_value(report, _ASSET_REPORT_SCHEMA):
                raise ToolFailure('invalid input: asset report schema')
            self.state["asset_report"] = copy.deepcopy(report)
            return {"stored": True}
        raise ToolFailure("unknown tool")

    def call(self, name, args):
        call = {
            "name": name,
            "arguments": copy.deepcopy(args),
            "isError": False,
            "result": None,
        }
        self.state["calls"].append(call)
        try:
            value = self._run(name, args)
            call["result"] = copy.deepcopy(value)
            response = {"data": value}
            self._save()
            return response
        except (ToolFailure, TypeError, KeyError) as exc:
            call["isError"], call["result"] = True, {"error": str(exc)}
            response = {"error": str(exc)}
            self._save()
            raise ToolFailure(json.dumps(response, ensure_ascii=False)) from exc

    def respond(self, request):
        method, params = request.get("method"), request.get("params", {})
        if "id" not in request:
            return None
        ident = request["id"]
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "practical-agent-v2", "version": "2.1.0"},
            }
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            result = {"tools": self.tools}
        elif method == "tools/call":
            try:
                output = self.call(params.get("name"), params.get("arguments", {}))
                failed = False
            except ToolFailure as exc:
                try:
                    output = json.loads(str(exc))
                except json.JSONDecodeError:
                    output = {"error": str(exc)}
                failed = True
            result = {
                "content": [
                    {"type": "text", "text": json.dumps(output, ensure_ascii=False)}
                ],
                "isError": failed,
            }
            if not failed:
                definition = next(t for t in self.tools if t['name'] == params.get('name'))
                if not validate_value(output, definition['outputSchema']):
                    raise ValueError('MCP server output violates its advertised schema')
                result['structuredContent'] = output
        elif method == "ping":
            result = {}
        else:
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": -32601, "message": "Method not found"},
            }
        return {"jsonrpc": "2.0", "id": ident, "result": result}


def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: practical_mcp_v2.py STATE_PATH [TASK]")
    # Scoped agent transactions keep hidden state in the server process only.
    # A legacy standalone invocation may still persist state for local tooling.
    task = sys.argv[2] if len(sys.argv) == 3 else None
    server = Server(None if task else Path(sys.argv[1]), task=task)
    for line in sys.stdin:
        try:
            response = server.respond(json.loads(line))
        except (ValueError, TypeError, KeyError):
            continue
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

__all__ = ["Server", "TOOLS", "TASK_TOOLS", "tools_for_task", "ISSUES", "ACCOUNTS",
           "ADJUSTMENTS", "ASSETS", "AUDITS"]
