"""Conservative, evidence-based tool fault attribution shared by driver and host."""
from __future__ import annotations

import json
import posixpath
import re
import shlex

POLICY_VERSION = "task-tool-review-v8"
MODEL_ERROR_LIMIT = 5
CURSOR_VALIDATION_ERROR = 'cursor must be null or a returned numeric cursor'
UNAVAILABLE_TOOL_ERROR = re.compile(
    r"Model tried to call unavailable tool '([^']+)'. Available tools: bash, edit, glob, grep, read, write\."
)
RULE_DENIAL_PREFIX = 'The user has specified a rule which prevents you from using this specific tool call.'
PROTECTED_TEST_WRITE_ERROR = re.compile(
    r"Unknown: FileSystem\.writeFile \((/workspace/tests/[^()\r\n]+)\)")
LITERAL_ABSOLUTE_PATH = re.compile(r"/[A-Za-z0-9._/-]+(?: [A-Za-z0-9._/-]+)*")
LITERAL_HEREDOC_DELIMITER = re.compile(r"[A-Za-z0-9_.-]+")
SHELL_CONTROL_OPERATORS = {'&&', ';', '||', '|', '&'}


def _is_protected_test_write_error(tool, message):
    if tool not in {'write', 'edit'}:
        return False
    match = PROTECTED_TEST_WRITE_ERROR.fullmatch(message)
    if match is None:
        return False
    normalized_path = posixpath.normpath(match.group(1))
    return normalized_path.startswith('/workspace/tests/')


def _is_unavailable_tool_model_error(tool, message):
    if tool not in {'bash', 'edit', 'glob', 'grep', 'read', 'write'}:
        return False
    match = UNAVAILABLE_TOOL_ERROR.fullmatch(message)
    return bool(match and match.group(1) not in {'bash', 'edit', 'glob', 'grep', 'read', 'write'})


def _is_protected_runtime_read(tool, args, message):
    if tool != 'read' or not message.startswith(RULE_DENIAL_PREFIX) or not isinstance(args, dict):
        return False
    path = args.get('filePath')
    if not isinstance(path, str) or not path.startswith('/workspace/'):
        return False
    resolved = posixpath.normpath(path)
    return resolved.startswith('/opt/practical/') and '/agent-manual/' not in resolved


def _is_literal_absolute_path(path):
    return (isinstance(path, str) and path.startswith('/') and not path.startswith('//')
            and LITERAL_ABSOLUTE_PATH.fullmatch(path) is not None)


def _is_outside_workspace_path(path):
    if not _is_literal_absolute_path(path):
        return False
    normalized = posixpath.normpath(path)
    return normalized != '/workspace' and not normalized.startswith('/workspace/')


def _is_protected_test_source(path):
    if not _is_literal_absolute_path(path):
        return False
    normalized = posixpath.normpath(path)
    return (normalized.startswith('/workspace/tests/')
            and posixpath.basename(normalized).endswith('.test.js'))


def _first_shell_command(first_line):
    lexer = shlex.shlex(first_line, posix=True, punctuation_chars=';&|<>')
    lexer.whitespace_split = True
    lexer.commenters = ''
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    for index, token in enumerate(tokens):
        if token in SHELL_CONTROL_OPERATORS:
            return tokens[:index]
    return tokens


def _is_denied_bash_outside_write(tool, args, message):
    if tool != 'bash' or not message.startswith(RULE_DENIAL_PREFIX) or not isinstance(args, dict):
        return False
    command = args.get('command')
    if not isinstance(command, str):
        return False
    first_line = command.split('\n', 1)[0].removesuffix('\r')
    tokens = _first_shell_command(first_line)
    if not tokens:
        return False
    if tokens[0] == 'mkdir':
        operand_index = 1
        if operand_index < len(tokens) and tokens[operand_index] == '-p':
            operand_index += 1
        if operand_index < len(tokens) and tokens[operand_index] == '--':
            operand_index += 1
        operands = tokens[operand_index:]
        return bool(operands) and all(_is_outside_workspace_path(path) for path in operands)
    if (len(tokens) == 3 and tokens[0] == 'cp'
            and _is_protected_test_source(tokens[1])
            and _is_outside_workspace_path(tokens[2])):
        return True
    return (len(tokens) == 5 and tokens[0] == 'cat' and tokens[1] == '>'
            and _is_outside_workspace_path(tokens[2]) and tokens[3] == '<<'
            and LITERAL_HEREDOC_DELIMITER.fullmatch(tokens[4]) is not None)


def error_message(value):
    """Decode OpenCode errors and MCP content without interpreting ordinary output."""
    for _ in range(6):
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                return value
            if decoded == value:
                return value
            value = decoded
        elif isinstance(value, dict):
            if value.get('error'):
                value = value['error']
            elif isinstance(value.get('message'), str):
                return value['message']
            elif isinstance(value.get('content'), list):
                parts = [p.get('text', '') for p in value['content']
                         if isinstance(p, dict) and p.get('type') == 'text']
                value = parts[0] if len(parts) == 1 else '\n'.join(parts)
            else:
                break
        else:
            break
    return str(value or '')


class ToolErrorGuard:
    """Stop on the sixth proven model error, or the first unclassified/infra fault.

    Normal shell/test non-zero output is not itself a tool failure. Unknown errors
    require diagnosis; they are never silently assigned to the model.
    """
    def __init__(self, task: str):
        self.task = task
        self.model_errors = 0
        self.expected_errors = 0
        self.infrastructure_errors = 0
        self.unattributed_errors = 0
        self.reason = None
        self.evidence = []
        self._seen = set()
        self._expected_seen = set()

    def observe(self, event):
        if event.get('type') != 'tool_use' or not isinstance(event.get('part'), dict):
            return
        part = event['part']
        tool = str(part.get('tool', ''))
        is_mcp = tool.startswith('lab_') or tool.startswith('lab.')
        state = part.get('state') or {}
        if not isinstance(state, dict):
            return
        result = state.get('output')
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (ValueError, TypeError):
                pass
        # MCP isError can appear in a completed OpenCode tool event.
        is_error = state.get('status') == 'error' or bool(state.get('error'))
        if is_mcp and isinstance(result, dict):
            is_error |= bool(result.get('isError') or result.get('error'))
            if result.get('isError') and isinstance(result.get('content'), list):
                for content in result['content']:
                    if isinstance(content, dict) and content.get('type') == 'text':
                        try:
                            decoded = json.loads(content.get('text', ''))
                        except (ValueError, TypeError):
                            decoded = content.get('text', '')
                        if isinstance(decoded, dict) and decoded.get('error'):
                            result = decoded
                            break
        if not is_error:
            return
        ident = part.get('callID') or part.get('id')
        if ident and ident in self._seen:
            return
        if ident:
            self._seen.add(ident)
        message = error_message(state.get('error') or result)
        if 'LAB_POLICY_STOP:model_no_progress' in message:
            self.reason = 'model_no_progress'
            self.evidence.append({'call_id': ident, 'tool': tool, 'category': 'model', 'message': message[:1000]})
            return
        if 'LAB_POLICY_STOP:budget_exhausted' in message:
            self.reason = 'budget_exhausted'
            return
        args = state.get('input') or {}
        list_cursor_validation = (
            message == CURSOR_VALIDATION_ERROR
            and tool.startswith(('lab_list_', 'lab.list_')))
        protected_test_write = _is_protected_test_write_error(tool, message)
        unavailable_tool = _is_unavailable_tool_model_error(tool, message)
        protected_runtime_read = _is_protected_runtime_read(tool, args, message)
        denied_bash_outside_write = _is_denied_bash_outside_write(tool, args, message)
        expected = {1: 'stale or invalid version; read current change and retry',
                    2: 'temporary service failure; retry the same request and key'}
        version = args.get('version') if isinstance(args, dict) else None
        recovery = (self.task == 'M2' and tool.endswith('apply_change')
                    and isinstance(args, dict) and args.get('change_id') == 'C-17'
                    and args.get('idempotency_key') == 'C-17-v2'
                    and type(version) is int and message == expected.get(version))
        if recovery and version not in self._expected_seen:
            self._expected_seen.add(version)
            self.expected_errors += 1
            category = 'expected'
        elif (recovery or list_cursor_validation or protected_test_write or unavailable_tool
              or protected_runtime_read or denied_bash_outside_write
              or any(text in message.lower() for text in (
                'oldstring and newstring are identical',
                'invalid arguments', 'invalid input:', 'does not match the schema',
                'oldstring not found', 'oldstring must be unique',
                'could not find oldstring in the file',
                'page_size must be an integer from 1 through 2',
                'report must contain open_ids as an integer array'))):
            self.model_errors += 1
            category = 'model'
            if self.model_errors > MODEL_ERROR_LIMIT and self.reason is None:
                self.reason = 'model_tool_error_threshold'
        elif any(text in message.lower() for text in (
                'transport error', 'connection refused', 'econnrefused',
                'connection closed', 'server disconnected', 'spawn enoent')):
            self.infrastructure_errors += 1
            category = 'infrastructure'
            self.reason = self.reason or 'infrastructure_tool_error'
        else:
            self.unattributed_errors += 1
            category = 'unattributed'
            self.reason = self.reason or 'unattributed_tool_error'
        self.evidence.append({'call_id': ident, 'tool': tool, 'category': category,
                              'message': message[:1000]})

    def as_dict(self):
        return {'policy': POLICY_VERSION, 'reason': self.reason,
                'model_tool_errors': self.model_errors,
                'expected_tool_errors': self.expected_errors,
                'infrastructure_tool_errors': self.infrastructure_errors,
                'unattributed_tool_errors': self.unattributed_errors,
                'evidence': self.evidence}
