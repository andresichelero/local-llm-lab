"""A small, bounded interpreter for untrusted task source.

Candidate code is parsed as data and dispatched by this module.  It is never
compiled or evaluated by CPython.  The supported language is intentionally a
subset of Python; unsupported syntax fails before any module body runs.
"""
from __future__ import annotations

import ast
import builtins
import math
import operator
import types
from dataclasses import dataclass
from typing import Any


class UnsupportedSyntaxError(ValueError):
    """Raised when source uses syntax or imports outside the task language."""


class ExecutionLimitError(RuntimeError):
    """Raised when interpretation exceeds a configured resource bound."""


_MAX_MODULES = 64
_MAX_SOURCE_BYTES = 262_144
_MAX_TOTAL_SOURCE_BYTES = 1_048_576
_MAX_AST_NODES = 20_000
_MAX_STATIC_DEPTH = 128
_MAX_INT_BITS = 4_096
_MAX_FORMAT_WIDTH = 10_000
_MAX_EXCEPTION_ARGS = 4
_MAX_EXCEPTION_MESSAGE = 4_096

_ALLOWED_TYPING_NAMES = {
    "Any", "Callable", "ClassVar", "Final", "Generic", "Iterable", "Iterator",
    "Literal", "Mapping", "MutableMapping", "Optional", "Sequence", "Type",
    "TYPE_CHECKING", "TypeVar", "Union", "cast", "overload",
}
_ALLOWED_ABC_NAMES = {"Callable", "Iterable", "Iterator", "Mapping", "MutableMapping", "Sequence"}
_FORBIDDEN_NAMES = {
    "__import__", "breakpoint", "compile", "delattr", "eval", "exec", "getattr",
    "globals", "hasattr", "help", "input", "locals", "open", "setattr", "vars",
}
_EXCEPTION_NAMES = {
    "ArithmeticError", "AssertionError", "AttributeError", "ConnectionError",
    "EOFError", "Exception", "FileNotFoundError", "IndexError", "IOError",
    "KeyError", "LookupError", "NotImplementedError", "OSError", "OverflowError",
    "RuntimeError", "StopIteration", "TimeoutError", "TypeError", "ValueError",
    "ZeroDivisionError",
}
_EXCEPTION_TYPES = {
    name: getattr(builtins, name)
    for name in _EXCEPTION_NAMES
    if isinstance(getattr(builtins, name, None), type)
}
_SAFE_TYPE_NAMES = {
    "bool": bool,
    "dict": dict,
    "float": float,
    "int": int,
    "list": list,
    "object": object,
    "set": set,
    "str": str,
    "tuple": tuple,
    "type": type,
    "NoneType": type(None),
}


class _ReturnSignal(BaseException):
    def __init__(self, value: Any) -> None:
        self.value = value


class _BreakSignal(BaseException):
    pass


class _ContinueSignal(BaseException):
    pass


@dataclass(frozen=True)
class _TypingMarker:
    name: str


@dataclass(frozen=True)
class _BuiltinRef:
    name: str


@dataclass
class _ModuleState:
    name: str
    tree: ast.Module
    public: types.ModuleType
    namespace: dict[str, Any]
    status: str = "new"


@dataclass(frozen=True)
class _ModuleRef:
    runtime: "_Runtime"
    name: str


@dataclass(frozen=True)
class _TypingModuleRef:
    names: dict[str, Any]


@dataclass(frozen=True)
class _SafeMethod:
    receiver: Any
    name: str


@dataclass(frozen=True, eq=False)
class _Capability:
    runtime: "_Runtime"
    callback: Any


@dataclass
class _Scope:
    local: dict[str, Any]
    global_ns: dict[str, Any]
    local_names: set[str]
    module_scope: bool = False


class _Runtime:
    def __init__(
        self,
        trees: dict[str, ast.Module],
        *,
        step_limit: int,
        max_collection: int,
        max_depth: int,
    ) -> None:
        self.step_limit = step_limit
        self.max_collection = max_collection
        self.max_string = min(1_000_000, max(1_024, max_collection * 8))
        self.max_depth = max_depth
        self.steps = 0
        self.call_depth = 0
        self.allocation_limit = max(4_194_304, min(33_554_432, max_collection * 512))
        self.allocation_remaining = self.allocation_limit
        self.active_exceptions: list[BaseException] = []
        self.states: dict[str, _ModuleState] = {}
        self.builtins = {name: _BuiltinRef(name) for name in (
            "abs", "all", "any", "bool", "callable", "dict", "enumerate", "float",
            "int", "isinstance", "len", "list", "max", "min", "range", "repr",
            "object", "round", "set", "sorted", "str", "sum", "tuple", "type", "zip",
        )}
        for name, value in _EXCEPTION_TYPES.items():
            self.builtins[name] = value
        self.typing_names = {name: _TypingMarker(name) for name in _ALLOWED_TYPING_NAMES}
        self.typing_names["TYPE_CHECKING"] = False
        self.collections_abc_names = {name: _TypingMarker(name) for name in _ALLOWED_ABC_NAMES}

        all_names = set(trees)
        all_names.add("src")
        for name in tuple(trees):
            parts = name.split(".")
            for index in range(1, len(parts)):
                all_names.add(".".join(parts[:index]))
        for name, tree in trees.items():
            public = types.ModuleType(name)
            public.__package__ = name.rpartition(".")[0]
            if name == "src" or any(candidate.startswith(name + ".") for candidate in trees):
                public.__path__ = []
            self.states[name] = _ModuleState(name, tree, public, {})
        self.module_names = all_names

    def tick(self, amount: int = 1) -> None:
        self.steps += amount
        if self.steps > self.step_limit:
            raise ExecutionLimitError("interpreter step limit exceeded")

    def _raise_limit(self, reason: str) -> None:
        raise ExecutionLimitError(reason)

    def charge_allocation(self, amount: int) -> None:
        if amount < 0 or amount > self.allocation_remaining:
            self._raise_limit("cumulative allocation budget exceeded")
        self.allocation_remaining -= amount

    def charge_collection(self, count: int) -> None:
        if count < 0 or count > self.max_collection:
            self._raise_limit("collection size limit exceeded")
        self.charge_allocation(64 + count * 8)

    def charge_string(self, length: int) -> None:
        if length < 0 or length > self.max_string:
            self._raise_limit("string size limit exceeded")
        self.charge_allocation(48 + length * 2)

    def check_int(self, value: int) -> int:
        if type(value) is int and value.bit_length() > _MAX_INT_BITS:
            self._raise_limit("integer bit limit exceeded")
        return value

    def check_string(self, value: str) -> str:
        if len(value) > self.max_string:
            self._raise_limit("string size limit exceeded")
        return value

    def check_collection(self, value: Any) -> Any:
        if type(value) in (list, tuple, set, frozenset, dict, range):
            if len(value) > self.max_collection:
                self._raise_limit("collection size limit exceeded")
        elif type(value) is str:
            self.check_string(value)
        if type(value) is int:
            self.check_int(value)
        return value

    def _is_exception_class(self, value: Any) -> bool:
        return type(value) is type and issubclass(value, BaseException)

    def _is_exception_instance(self, value: Any) -> bool:
        value_type = type(value)
        if type(value_type) is not type:
            return False
        try:
            return BaseException in type.__getattribute__(value_type, "__mro__")
        except TypeError:
            return False

    def _exception_args(self, value: BaseException) -> tuple[Any, ...]:
        return BaseException.args.__get__(value, type(value))

    def _validate_host_value(
        self,
        value: Any,
        *,
        depth: int = 0,
        seen: set[int] | None = None,
        direct_callable: bool = False,
    ) -> None:
        self.tick()
        if depth > self.max_depth:
            self._raise_limit("input nesting limit exceeded")
        if value is None or type(value) in (bool, int, float, str):
            if type(value) is int:
                self.check_int(value)
            if type(value) is str:
                self.check_string(value)
            return
        if self._is_exception_class(value):
            return
        if self._is_exception_instance(value):
            if type(type(value)) is not type:
                raise TypeError("custom exception metaclasses are not task values")
            exception_args = self._exception_args(value)
            self.check_collection(exception_args)
            self._validate_exception_args(exception_args)
            marker = id(value)
            seen = seen or set()
            if marker in seen:
                return
            seen.add(marker)
            for item in exception_args:
                self._validate_host_value(item, depth=depth + 1, seen=seen)
            return
        if type(value) in (list, tuple, set, frozenset, dict):
            self.check_collection(value)
            marker = id(value)
            seen = seen or set()
            if marker in seen:
                return
            seen.add(marker)
            if type(value) is dict:
                for key, item in value.items():
                    if not self._is_safe_hash_key(key):
                        raise TypeError("dictionary keys must be bounded scalar values")
                    self._validate_host_value(key, depth=depth + 1, seen=seen)
                    self._validate_host_value(item, depth=depth + 1, seen=seen)
            else:
                for item in value:
                    if type(value) in (set, frozenset) and not self._is_safe_hash_key(item):
                        raise TypeError("set values must be bounded scalar values")
                    self._validate_host_value(item, depth=depth + 1, seen=seen)
            return
        if callable(value) and direct_callable and not isinstance(value, type):
            return
        raise TypeError("unsupported host value type")

    def _expanded_value_size(
        self,
        value: Any,
        *,
        active: set[int] | None = None,
        memo: dict[int, int] | None = None,
        depth: int = 0,
    ) -> int:
        if depth > self.max_depth:
            self._raise_limit("expanded value nesting limit exceeded")
        active = active if active is not None else set()
        memo = memo if memo is not None else {}
        if value is None or type(value) in (bool, int, float):
            return 24 if type(value) is not int else 24 + (value.bit_length() + 7) // 8
        if type(value) is str:
            return 48 + len(value) * 2
        if self._is_exception_class(value):
            return 64
        if self._is_exception_instance(value):
            return 64 + self._expanded_value_size(self._exception_args(value), active=active, memo=memo, depth=depth + 1)
        if type(value) not in (list, tuple, set, frozenset, dict):
            raise TypeError("unsupported host value type")
        marker = id(value)
        if marker in active:
            self._raise_limit("cyclic value graphs are not supported at the trusted boundary")
        if marker in memo:
            return memo[marker]
        self.check_collection(value)
        active.add(marker)
        try:
            total = 64 + len(value) * 8
            if type(value) is dict:
                items = (part for pair in value.items() for part in pair)
            else:
                items = iter(value)
            for item in items:
                self.tick()
                total += self._expanded_value_size(item, active=active, memo=memo, depth=depth + 1)
                if total > self.allocation_limit:
                    self._raise_limit("expanded value size limit exceeded")
            memo[marker] = total
            return total
        finally:
            active.remove(marker)

    def _check_expanded_value(self, value: Any) -> None:
        expanded_size = self._expanded_value_size(value)
        self.charge_allocation(expanded_size)

    def _is_safe_hash_key(self, value: Any, depth: int = 0) -> bool:
        self.tick()
        if depth > self.max_depth:
            return False
        if value is None or type(value) in (bool, int, float, str):
            return True
        if type(value) is tuple:
            if len(value) > self.max_collection:
                return False
            active: set[int] = set()

            def visit(item: Any, nested_depth: int) -> bool:
                self.tick()
                if nested_depth > self.max_depth:
                    return False
                if item is None or type(item) in (bool, int, float, str):
                    return True
                if type(item) is not tuple or len(item) > self.max_collection or id(item) in active:
                    return False
                active.add(id(item))
                try:
                    return all(visit(child, nested_depth + 1) for child in item)
                finally:
                    active.remove(id(item))

            active.add(id(value))
            try:
                return all(visit(item, depth + 1) for item in value)
            finally:
                active.remove(id(value))
        return False

    def _charge_hash_key(self, value: Any) -> None:
        if type(value) is str:
            self.charge_allocation(48 + len(value) * 2)
        elif type(value) is int:
            self.charge_allocation(48 + (value.bit_length() + 7) // 8)
        elif type(value) is tuple:
            self.charge_allocation(48 + sum(self._hash_key_cost(item, 1) for item in value))

    def _hash_key_cost(self, value: Any, depth: int) -> int:
        self.tick()
        if depth > self.max_depth:
            self._raise_limit("dictionary key nesting limit exceeded")
        if type(value) is str:
            return len(value) * 2 + 8
        if type(value) is int:
            return (value.bit_length() + 7) // 8 + 8
        if type(value) is tuple:
            return 8 + sum(self._hash_key_cost(item, depth + 1) for item in value)
        return 8

    def _prepare_external_arg(self, value: Any) -> Any:
        if callable(value) and not isinstance(value, type) and not isinstance(
            value, (_Capability, _BuiltinRef, _ModuleRef)
        ):
            return _Capability(self, value)
        self._validate_host_value(value)
        self._check_expanded_value(value)
        return value

    def _validate_exception_args(self, args: tuple[Any, ...]) -> None:
        if len(args) > _MAX_EXCEPTION_ARGS:
            raise TypeError("exception values must have at most four scalar arguments")
        total_message_size = 0
        for item in args:
            if item is None or type(item) in (bool, int, float):
                if type(item) is int:
                    self.check_int(item)
                continue
            if type(item) is str:
                self.check_string(item)
                total_message_size += len(item)
                continue
            raise TypeError("exception values require bounded scalar arguments")
        if total_message_size > _MAX_EXCEPTION_MESSAGE:
            self._raise_limit("exception message size limit exceeded")

    def _prepare_result(self, value: Any) -> Any:
        self._validate_host_value(value)
        self._check_expanded_value(value)
        return value

    def _ensure_module(self, name: str) -> None:
        state = self.states.get(name)
        if state is None or state.status in ("done", "running"):
            return
        state.status = "running"
        try:
            scope = _Scope(state.namespace, state.namespace, set(), True)
            self._exec_block(state.tree.body, scope)
            state.status = "done"
            state.public.__dict__.update(state.namespace)
        except BaseException:
            state.status = "new"
            raise

    def _import_module(self, name: str) -> _ModuleRef:
        if name not in self.module_names:
            raise UnsupportedSyntaxError(f"local module is not available: {name}")
        self._ensure_module(name)
        return _ModuleRef(self, name)

    def _resolve_import_name(self, current_name: str, node: ast.ImportFrom) -> str:
        if node.level == 0:
            base = node.module or ""
        else:
            package = current_name.rpartition(".")[0]
            parts = package.split(".") if package else []
            remove = node.level - 1
            if remove > len(parts):
                raise UnsupportedSyntaxError("relative import escapes src package")
            prefix = parts[: len(parts) - remove] if remove else parts
            suffix = node.module.split(".") if node.module else []
            base = ".".join(prefix + suffix)
        if not base.startswith("src") or (base != "src" and not base.startswith("src.")):
            raise UnsupportedSyntaxError("imports are limited to src modules")
        return base

    def _module_attr(self, ref: _ModuleRef, name: str) -> Any:
        if name.startswith("_"):
            raise UnsupportedSyntaxError("private module attributes are not supported")
        child = f"{ref.name}.{name}"
        if child in self.module_names:
            self._ensure_module(child)
            return _ModuleRef(self, child)
        state = self.states.get(ref.name)
        if state is None:
            raise AttributeError(name)
        self._ensure_module(ref.name)
        if name not in state.namespace:
            raise AttributeError(name)
        return state.namespace[name]

    def _load_name(self, name: str, scope: _Scope) -> Any:
        if name in scope.local:
            return scope.local[name]
        if name in scope.local_names and not scope.module_scope:
            raise UnboundLocalError(f"local variable '{name}' referenced before assignment")
        if name in scope.global_ns:
            return scope.global_ns[name]
        if name in self.builtins:
            return self.builtins[name]
        if name in self.typing_names:
            return self.typing_names[name]
        raise NameError(f"name '{name}' is not defined")

    def _store_name(self, name: str, value: Any, scope: _Scope) -> None:
        if name.startswith("__"):
            raise UnsupportedSyntaxError("dunder names cannot be assigned")
        if scope.module_scope:
            if name not in scope.global_ns:
                self.charge_allocation(64)
            scope.global_ns[name] = value
        else:
            if name not in scope.local:
                self.charge_allocation(64)
            scope.local[name] = value

    def _iterable(self, value: Any) -> Any:
        self.tick()
        if type(value) in (list, tuple, str, dict, set, frozenset, range):
            if len(value) > self.max_collection:
                self._raise_limit("iteration collection limit exceeded")
            return iter(value)
        if isinstance(value, _BoundedIterator):
            return value
        raise TypeError("value is not an allowed iterable")

    def _safe_attr(self, value: Any, name: str) -> Any:
        if name.startswith("_"):
            raise UnsupportedSyntaxError("private attributes are not supported")
        if isinstance(value, _TypingModuleRef) and name in value.names:
            return value.names[name]
        if isinstance(value, _ModuleRef):
            return self._module_attr(value, name)
        if type(value) is str and name in {
            "capitalize", "casefold", "count", "endswith", "find", "index", "isalnum",
            "isalpha", "isdigit", "islower", "isspace", "istitle", "isupper", "join",
            "lower", "lstrip", "partition", "removeprefix", "removesuffix", "replace",
            "rfind", "rindex", "rpartition", "rsplit", "rstrip", "split", "splitlines",
            "startswith", "strip", "swapcase", "title", "upper",
        }:
            return _SafeMethod(value, name)
        if type(value) is list and name in {"append", "clear", "copy", "extend", "insert", "pop", "reverse"}:
            return _SafeMethod(value, name)
        if type(value) is tuple and name in {"count", "index"}:
            return _SafeMethod(value, name)
        if type(value) is dict and name in {
            "clear", "copy", "get", "items", "keys", "pop", "popitem", "setdefault", "update", "values",
        }:
            return _SafeMethod(value, name)
        if type(value) is set and name in {"add", "clear", "copy", "discard", "pop", "remove", "update"}:
            return _SafeMethod(value, name)
        if self._is_exception_instance(value) and name == "args":
            args = self._exception_args(value)
            self._validate_host_value(args)
            return args
        raise UnsupportedSyntaxError(f"attribute access is not allowed: {name}")

    def _truth(self, value: Any) -> bool:
        if isinstance(value, (_ModuleRef, _Capability, _BuiltinRef, _SafeMethod, _TypingMarker)):
            return True
        if type(value) in (list, tuple, dict, set, frozenset, range, str):
            self.check_collection(value)
        if type(value) is int:
            self.check_int(value)
        if value is None or type(value) in (bool, int, float, str, list, tuple, dict, set, frozenset, range):
            return bool(value)
        if self._is_exception_instance(value) or type(value) is type:
            return True
        raise TypeError("truth testing this value is not supported")

    def _safe_equal(self, left: Any, right: Any, depth: int = 0) -> bool:
        self.tick()
        if depth > self.max_depth:
            self._raise_limit("comparison nesting limit exceeded")
        if self._numeric(left) and self._numeric(right):
            width = max(left.bit_length() if type(left) is int else 1, right.bit_length() if type(right) is int else 1)
            self.charge_allocation(16 + (width + 7) // 8)
            return left == right
        if left is right:
            return True
        if type(left) is type(right) and type(left) in (type(None), bool, int, float, str):
            if type(left) is int:
                self.check_int(left)
            if type(left) is str:
                self.check_string(left)
                self.charge_allocation(48 + len(left) * 2)
            return left == right
        if type(left) in (list, tuple) and type(left) is type(right):
            if len(left) != len(right):
                return False
            return all(self._safe_equal(a, b, depth + 1) for a, b in zip(left, right))
        if type(left) is dict and type(right) is dict:
            if len(left) != len(right):
                return False
            for key, item in left.items():
                self._charge_hash_key(key)
                if key not in right or not self._safe_equal(item, right[key], depth + 1):
                    return False
            return True
        if type(left) in (set, frozenset) and type(left) is type(right):
            if len(left) != len(right):
                return False
            for item in left:
                self._charge_hash_key(item)
                if item not in right:
                    return False
            return True
        return False

    def _numeric(self, value: Any) -> bool:
        return type(value) in (bool, int, float)

    def _binary(self, op: ast.operator, left: Any, right: Any) -> Any:
        self.tick()
        if isinstance(op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)):
            if isinstance(op, ast.Add) and type(left) is type(right) and type(left) in (str, list, tuple):
                size = len(left) + len(right)
                limit = self.max_string if type(left) is str else self.max_collection
                if size > limit:
                    self._raise_limit("concatenation size limit exceeded")
                if type(left) is str:
                    self.charge_string(size)
                else:
                    self.charge_collection(size)
                result = left + right
                return self.check_string(result) if type(result) is str else self.check_collection(result)
            if isinstance(op, ast.Mult) and (
                type(left) is str and type(right) is int
                or type(right) is str and type(left) is int
                or type(left) in (list, tuple) and type(right) is int
                or type(right) in (list, tuple) and type(left) is int
            ):
                value, count = (left, right) if type(right) is int else (right, left)
                if count < 0:
                    count = 0
                unit_limit = self.max_string if type(value) is str else self.max_collection
                if len(value) and count > unit_limit // len(value):
                    self._raise_limit("repetition size limit exceeded")
                size = len(value) * count
                if type(value) is str:
                    self.charge_string(size)
                else:
                    self.charge_collection(size)
                return self.check_collection(value * count)
            if not (self._numeric(left) and self._numeric(right)):
                raise TypeError("operator operands are not supported")
            if isinstance(op, ast.Pow):
                exponent = right
                if type(exponent) is int and abs(exponent) > self.max_collection:
                    self._raise_limit("power exponent limit exceeded")
                if type(left) is int and type(exponent) is int and exponent >= 0:
                    if abs(left) > 1 and left.bit_length() * exponent > _MAX_INT_BITS + exponent:
                        self._raise_limit("power result bit limit exceeded")
                if type(left) is int and type(exponent) is int and exponent >= 0 and abs(left) > 1:
                    estimated = (abs(left).bit_length() - 1) * exponent + 1
                    if estimated > _MAX_INT_BITS:
                        self._raise_limit("power result bit limit exceeded")
            fn = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
                ast.Pow: operator.pow,
            }[type(op)]
            result = fn(left, right)
            if type(result) is int:
                return self.check_int(result)
            if isinstance(result, float) and not math.isfinite(result):
                return result
            return self.check_collection(result)
        if isinstance(op, (ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift)):
            if type(left) is not int or type(right) is not int:
                raise TypeError("bitwise operands must be integers")
            self.check_int(left)
            self.check_int(right)
            if isinstance(op, ast.LShift) and right >= 0 and left and left.bit_length() + right > _MAX_INT_BITS:
                self._raise_limit("shift result bit limit exceeded")
            if abs(right) > _MAX_INT_BITS:
                self._raise_limit("shift amount limit exceeded")
            fn = {
                ast.BitAnd: operator.and_,
                ast.BitOr: operator.or_,
                ast.BitXor: operator.xor,
                ast.LShift: operator.lshift,
                ast.RShift: operator.rshift,
            }[type(op)]
            return self.check_int(fn(left, right))
        raise UnsupportedSyntaxError(f"operator is not supported: {type(op).__name__}")

    def _compare_one(self, op: ast.cmpop, left: Any, right: Any) -> bool:
        self.tick()
        if isinstance(op, (ast.Eq, ast.NotEq)):
            result = self._safe_equal(left, right)
            return not result if isinstance(op, ast.NotEq) else result
        if isinstance(op, ast.Is):
            return left is right
        if isinstance(op, ast.IsNot):
            return left is not right
        if isinstance(op, (ast.In, ast.NotIn)):
            if type(right) is dict:
                if not self._is_safe_hash_key(left):
                    raise TypeError("dictionary keys must be bounded scalar values")
                self._charge_hash_key(left)
                result = right.__contains__(left)
            elif type(right) is str:
                if type(left) is not str:
                    raise TypeError("string membership requires a string value")
                self.charge_allocation(48 + len(left) * max(1, len(right)))
                result = left in right
            elif type(right) in (list, tuple):
                result = any(self._safe_equal(left, item) for item in right)
            elif type(right) in (set, frozenset, range):
                if type(right) in (set, frozenset):
                    if not self._is_safe_hash_key(left):
                        raise TypeError("set values must be bounded scalar values")
                    self._charge_hash_key(left)
                result = left in right
            else:
                raise TypeError("membership requires an allowed container")
            return not result if isinstance(op, ast.NotIn) else result
        if (self._numeric(left) and self._numeric(right)) or (
            type(left) is str and type(right) is str
        ):
            fn = {
                ast.Lt: operator.lt,
                ast.LtE: operator.le,
                ast.Gt: operator.gt,
                ast.GtE: operator.ge,
            }.get(type(op))
            if fn is not None:
                if type(left) is str:
                    self.charge_allocation(48 + len(left) + len(right))
                else:
                    left_bits = left.bit_length() if type(left) is int else 1
                    right_bits = right.bit_length() if type(right) is int else 1
                    self.charge_allocation(48 + (left_bits + right_bits + 7) // 8)
                return fn(left, right)
        raise TypeError("ordered comparison operands are not supported")

    def _eval_expr(self, node: ast.expr, scope: _Scope) -> Any:
        self.tick()
        if isinstance(node, ast.Constant):
            value = node.value
            if type(value) is int:
                return self.check_int(value)
            if isinstance(value, str):
                return self.check_string(value)
            return value
        if isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES:
                raise UnsupportedSyntaxError(f"builtin is not supported: {node.id}")
            return self._load_name(node.id, scope)
        if isinstance(node, ast.Attribute):
            return self._safe_attr(self._eval_expr(node.value, scope), node.attr)
        if isinstance(node, ast.List):
            if len(node.elts) > self.max_collection:
                self._raise_limit("literal collection size limit exceeded")
            self.charge_collection(len(node.elts))
            return [self._eval_expr(item, scope) for item in node.elts]
        if isinstance(node, ast.Tuple):
            if len(node.elts) > self.max_collection:
                self._raise_limit("literal collection size limit exceeded")
            self.charge_collection(len(node.elts))
            return tuple(self._eval_expr(item, scope) for item in node.elts)
        if isinstance(node, ast.Set):
            if len(node.elts) > self.max_collection:
                self._raise_limit("literal collection size limit exceeded")
            self.charge_collection(len(node.elts))
            result: set[Any] = set()
            for item_node in node.elts:
                item = self._eval_expr(item_node, scope)
                if not self._is_safe_hash_key(item):
                    raise TypeError("set values must be bounded scalar values")
                self._charge_hash_key(item)
                result.add(item)
            return result
        if isinstance(node, ast.Dict):
            if len(node.keys) > self.max_collection:
                self._raise_limit("literal collection size limit exceeded")
            self.charge_collection(len(node.keys))
            result: dict[Any, Any] = {}
            for key_node, value_node in zip(node.keys, node.values):
                if key_node is None:
                    raise UnsupportedSyntaxError("dictionary unpacking is not supported")
                key = self._eval_expr(key_node, scope)
                if not self._is_safe_hash_key(key):
                    raise TypeError("dictionary keys must be bounded scalar values")
                self._charge_hash_key(key)
                result[key] = self._eval_expr(value_node, scope)
            return result
        if isinstance(node, ast.Subscript):
            value = self._eval_expr(node.value, scope)
            index = self._eval_slice(node.slice, scope)
            if not isinstance(value, (str, list, tuple, dict)):
                raise TypeError("subscription is limited to strings and containers")
            if type(value) is dict:
                if not self._is_safe_hash_key(index):
                    raise TypeError("dictionary keys must be bounded scalar values")
                self._charge_hash_key(index)
            result = value[index]
            if isinstance(index, slice) and type(result) in (str, list, tuple):
                if type(result) is str:
                    self.charge_string(len(result))
                else:
                    self.charge_collection(len(result))
            return self.check_collection(result)
        if isinstance(node, ast.BinOp):
            return self._binary(node.op, self._eval_expr(node.left, scope), self._eval_expr(node.right, scope))
        if isinstance(node, ast.UnaryOp):
            value = self._eval_expr(node.operand, scope)
            if isinstance(node.op, ast.Not):
                return not self._truth(value)
            if isinstance(node.op, ast.UAdd) and self._numeric(value):
                return value
            if isinstance(node.op, ast.USub) and self._numeric(value):
                return self.check_int(-value) if type(value) is int else -value
            if isinstance(node.op, ast.Invert) and type(value) is int:
                return self.check_int(~value)
            raise TypeError("unary operator operand is not supported")
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result = self._eval_expr(node.values[0], scope)
                for part in node.values[1:]:
                    if not self._truth(result):
                        return result
                    result = self._eval_expr(part, scope)
                return result
            result = self._eval_expr(node.values[0], scope)
            for part in node.values[1:]:
                if self._truth(result):
                    return result
                result = self._eval_expr(part, scope)
            return result
        if isinstance(node, ast.Compare):
            left = self._eval_expr(node.left, scope)
            for op_node, comparator in zip(node.ops, node.comparators):
                right = self._eval_expr(comparator, scope)
                if not self._compare_one(op_node, left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            branch = node.body if self._truth(self._eval_expr(node.test, scope)) else node.orelse
            return self._eval_expr(branch, scope)
        if isinstance(node, ast.Call):
            if len(node.args) + len(node.keywords) > self.max_collection:
                self._raise_limit("call argument count limit exceeded")
            self.charge_collection(len(node.args) + len(node.keywords))
            function = self._eval_expr(node.func, scope)
            args = [self._eval_expr(arg, scope) for arg in node.args]
            kwargs: dict[str, Any] = {}
            for keyword in node.keywords:
                if keyword.arg is None:
                    raise UnsupportedSyntaxError("keyword unpacking is not supported")
                if keyword.arg in kwargs:
                    raise TypeError(f"multiple values for keyword argument '{keyword.arg}'")
                kwargs[keyword.arg] = self._eval_expr(keyword.value, scope)
            return self._call(function, args, kwargs)
        if isinstance(node, ast.Slice):
            return self._eval_slice(node, scope)
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
            return self._eval_comprehension(node, scope)
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            length = 0
            for value_node in node.values:
                part = self._eval_expr(value_node, scope)
                if not isinstance(part, str):
                    raise TypeError("formatted string part is not text")
                length += len(part)
                if length > self.max_string:
                    self._raise_limit("formatted string size limit exceeded")
                self.charge_allocation(8 + len(part) * 2)
                parts.append(part)
            self.charge_string(length)
            return "".join(parts)
        if isinstance(node, ast.FormattedValue):
            value = self._eval_expr(node.value, scope)
            if node.conversion == ord("r"):
                rendered = self._safe_repr(value)
            elif node.conversion == ord("a"):
                rendered = ascii(self._safe_str(value))
            else:
                rendered = self._safe_str(value)
            if node.format_spec is not None:
                spec = self._eval_expr(node.format_spec, scope)
                rendered = self._safe_format(value, spec, node.conversion)
            return self.check_string(rendered)
        raise UnsupportedSyntaxError(f"expression is not supported: {type(node).__name__}")

    def _eval_slice(self, node: ast.expr, scope: _Scope) -> Any:
        if not isinstance(node, ast.Slice):
            return self._eval_expr(node, scope)
        parts = [self._eval_expr(part, scope) if part is not None else None for part in (node.lower, node.upper, node.step)]
        if any(part is not None and type(part) is not int for part in parts):
            raise TypeError("slice indices must be integers")
        for part in parts:
            if type(part) is int:
                self.check_int(part)
        return slice(*parts)

    def _eval_comprehension(self, node: ast.expr, scope: _Scope) -> Any:
        if len(node.generators) > self.max_depth:
            self._raise_limit("comprehension nesting limit exceeded")
        self.charge_allocation(64 + 16 * len(scope.local) + 8 * len(scope.local_names))
        comp_scope = _Scope(dict(scope.local), scope.global_ns, set(scope.local_names), scope.module_scope)
        self.charge_collection(0)
        result: Any = {} if isinstance(node, ast.DictComp) else (set() if isinstance(node, ast.SetComp) else [])

        def visit(index: int) -> None:
            self.tick()
            if index == len(node.generators):
                if len(result) >= self.max_collection:
                    self._raise_limit("comprehension collection limit exceeded")
                self.charge_allocation(8)
                if isinstance(node, ast.DictComp):
                    key = self._eval_expr(node.key, comp_scope)
                    if not self._is_safe_hash_key(key):
                        raise TypeError("dictionary keys must be bounded scalar values")
                    self._charge_hash_key(key)
                    result[key] = self._eval_expr(node.value, comp_scope)
                else:
                    value = self._eval_expr(node.elt, comp_scope)
                    if isinstance(node, ast.SetComp):
                        if not self._is_safe_hash_key(value):
                            raise TypeError("set values must be bounded scalar values")
                        self._charge_hash_key(value)
                        result.add(value)
                    else:
                        result.append(value)
                if len(result) > self.max_collection:
                    self._raise_limit("comprehension collection limit exceeded")
                return
            generator = node.generators[index]
            for item in self._iterable(self._eval_expr(generator.iter, comp_scope)):
                self.tick()
                self._assign(generator.target, item, comp_scope)
                include = True
                for condition in generator.ifs:
                    if not self._truth(self._eval_expr(condition, comp_scope)):
                        include = False
                        break
                if include:
                    visit(index + 1)

        visit(0)
        return result

    def _safe_str(self, value: Any, depth: int = 0) -> str:
        if depth > self.max_depth:
            self._raise_limit("string conversion nesting limit exceeded")
        if value is None or type(value) in (bool, int, float, str):
            if type(value) is str:
                self.charge_string(len(value))
            elif type(value) is int:
                estimated = int(value.bit_length() * 0.302) + 3
                self.charge_allocation(48 + estimated * 2)
            else:
                self.charge_allocation(128)
            rendered = str(value)
            return self.check_string(rendered)
        if type(value) in (list, tuple, set, frozenset):
            self.check_collection(value)
            opening, closing = ("[", "]") if type(value) is list else (("(", ")") if type(value) is tuple else ("{", "}"))
            if type(value) is tuple and len(value) == 1:
                return self._render_joined("(", ((self._safe_repr(value[0], depth + 1), ""),), ",)")
            if type(value) in (set, frozenset) and not value:
                rendered = "set()" if type(value) is set else "frozenset()"
                self.charge_string(len(rendered))
                return rendered
            return self._render_joined(opening, ((self._safe_repr(item, depth + 1), ", ") for item in value), closing)
        if type(value) is dict:
            self.check_collection(value)
            pairs = (
                (f"{self._safe_repr(key, depth + 1)}: {self._safe_repr(item, depth + 1)}", ", ")
                for key, item in value.items()
            )
            return self._render_joined("{", pairs, "}")
        if self._is_exception_instance(value):
            args = self._exception_args(value)
            self._validate_exception_args(args)
            if not args:
                return ""
            if len(args) == 1:
                return self._safe_str(args[0], depth + 1)
            return self._safe_str(args, depth + 1)
        raise TypeError("string conversion of this value is not supported")

    def _render_joined(self, opening: str, parts: Any, closing: str) -> str:
        self.charge_collection(0)
        rendered_parts: list[str] = []
        length = len(opening) + len(closing)
        for part, separator in parts:
            added = len(part) + (len(separator) if rendered_parts else 0)
            if length + added > self.max_string:
                self._raise_limit("string conversion size limit exceeded")
            self.charge_allocation(8 + len(part) * 2)
            rendered_parts.append(part)
            length += added
        self.charge_string(length)
        return opening + ", ".join(rendered_parts) + closing

    def _safe_repr(self, value: Any, depth: int = 0) -> str:
        if type(value) is str:
            projected = len(value) * 4 + 2
            if projected > self.max_string:
                self._raise_limit("string representation size limit exceeded")
            self.charge_allocation(48 + projected * 2)
            return self.check_string(repr(value))
        return self._safe_str(value, depth)

    def _safe_format(self, value: Any, spec: str, conversion: int) -> str:
        self.check_string(spec)
        if len(spec) > _MAX_FORMAT_WIDTH:
            self._raise_limit("format specification limit exceeded")
        digits = ""
        numeric_budget = 0
        for char in spec:
            if char.isdigit():
                digits += char
            elif char in ".<>=^+- ,_0dxXobn%efFgGcs":
                if digits:
                    number = int(digits)
                    if number > self.max_collection:
                        self._raise_limit("format width limit exceeded")
                    numeric_budget += number
                    digits = ""
            else:
                raise UnsupportedSyntaxError("format specification is not supported")
        if digits:
            number = int(digits)
            if number > self.max_collection:
                self._raise_limit("format width limit exceeded")
            numeric_budget += number
        if conversion == ord("r"):
            value = self._safe_repr(value)
        elif conversion == ord("a"):
            plain = self._safe_str(value)
            projected = len(plain) * 4 + 2
            if projected > self.max_string:
                self._raise_limit("ASCII formatting size limit exceeded")
            self.charge_string(projected)
            value = ascii(plain)
        else:
            if type(value) not in (str, int, float, bool):
                raise TypeError("formatting this value is not supported")
        projected = max(64 + len(spec), numeric_budget + 64)
        if type(value) is str:
            projected += len(value)
        if projected > self.max_string:
            self._raise_limit("formatted string size limit exceeded")
        self.charge_string(projected)
        try:
            output = format(value, spec)
        except (ValueError, TypeError) as error:
            raise error
        return self.check_string(output)

    def _call(self, target: Any, args: list[Any], kwargs: dict[str, Any]) -> Any:
        self.tick()
        if isinstance(target, _InterpretedFunction):
            return self._call_interpreted(target, args, kwargs, external=False)
        if isinstance(target, _Capability):
            for value in (*args, *kwargs.values()):
                self._validate_host_value(value)
                self._check_expanded_value(value)
            try:
                result = target.callback(*args, **kwargs)
            except BaseException as error:
                if self._is_exception_instance(error):
                    self._validate_host_value(error)
                    self._check_expanded_value(error)
                raise
            self._validate_host_value(result)
            self._check_expanded_value(result)
            return result
        if isinstance(target, _SafeMethod):
            return self._call_method(target, args, kwargs)
        if isinstance(target, _BuiltinRef):
            return self._call_builtin(target.name, args, kwargs)
        if isinstance(target, _TypingMarker):
            if target.name == "cast":
                self._arity("cast", args, kwargs, 2)
                return args[1]
            if target.name == "TypeVar":
                self._arity("TypeVar", args, kwargs, 1)
                if type(args[0]) is not str:
                    raise TypeError("TypeVar name must be a string")
                self.check_string(args[0])
                if not args[0].isidentifier():
                    raise ValueError("TypeVar name must be a valid identifier")
                self.charge_allocation(64 + len(args[0]) * 2)
                return _TypingMarker("typevar")
            raise UnsupportedSyntaxError("typing-only imports cannot be called")
        if self._is_exception_class(target) and target in _EXCEPTION_TYPES.values():
            if kwargs:
                raise TypeError("exception constructors do not accept keyword arguments")
            self._validate_exception_args(tuple(args))
            self.charge_allocation(64 + len(args) * 8)
            return target(*args, **kwargs)
        raise UnsupportedSyntaxError("call target is not an interpreted function or registered capability")

    def _call_interpreted(
        self,
        function: "_InterpretedFunction",
        args: list[Any],
        kwargs: dict[str, Any],
        *,
        external: bool,
    ) -> Any:
        if external:
            if self.call_depth == 0:
                self.steps = 0
            args = [self._prepare_external_arg(value) for value in args]
            kwargs = {key: self._prepare_external_arg(value) for key, value in kwargs.items()}
        if self.call_depth >= self.max_depth:
            self._raise_limit("function call depth limit exceeded")
        parameters = function.parameters
        if len(args) > len(parameters.positional):
            raise TypeError(f"{function.name}() takes {len(parameters.positional)} positional arguments")
        if len(parameters.all_names) > self.max_collection:
            self._raise_limit("function parameter limit exceeded")
        self.charge_allocation(64 + len(parameters.all_names) * 64)
        local: dict[str, Any] = {}
        for index, value in enumerate(args):
            local[parameters.positional[index]] = value
        for name, value in kwargs.items():
            if name not in parameters.all_names:
                raise TypeError(f"{function.name}() got an unexpected keyword argument '{name}'")
            if name in local:
                raise TypeError(f"{function.name}() got multiple values for argument '{name}'")
            local[name] = value
        for name, default in parameters.defaults.items():
            if name not in local:
                local[name] = default
        missing = [name for name in parameters.all_names if name not in local]
        if missing:
            raise TypeError(f"{function.name}() missing required argument: '{missing[0]}'")
        self.call_depth += 1
        scope = _Scope(local, function.state.namespace, parameters.local_names, False)
        try:
            try:
                self._exec_block(function.node.body, scope)
            except _ReturnSignal as signal:
                result = signal.value
            else:
                result = None
            return self._prepare_result(result) if external else result
        finally:
            self.call_depth -= 1
            if external:
                for value in (*args, *kwargs.values()):
                    if isinstance(value, _Capability):
                        continue
                    self._validate_host_value(value)
                    self._check_expanded_value(value)

    def _call_builtin(self, name: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
        if name not in {"dict", "int", "float", "str", "list", "tuple", "set", "bool", "range", "enumerate", "zip", "sorted", "sum", "min", "max", "abs", "round", "len", "all", "any", "type", "isinstance", "callable", "repr"}:
            raise UnsupportedSyntaxError(f"builtin is not supported: {name}")
        if name == "len":
            self._arity(name, args, kwargs, 1)
            value = args[0]
            if type(value) not in (str, list, tuple, dict, set, frozenset, range):
                raise TypeError("len() requires a bounded collection")
            return len(self.check_collection(value))
        if name == "range":
            if kwargs or not 1 <= len(args) <= 3 or any(type(value) is not int for value in args):
                raise TypeError("range() accepts one to three integer arguments")
            for value in args:
                self.check_int(value)
            if len(args) == 1:
                start, stop, step = 0, args[0], 1
            elif len(args) == 2:
                start, stop, step = args[0], args[1], 1
            else:
                start, stop, step = args
            if step == 0:
                raise ValueError("range() arg 3 must not be zero")
            if step > 0:
                range_length = max(0, (stop - start + step - 1) // step)
            else:
                range_length = max(0, (start - stop - step - 1) // (-step))
            if range_length > self.max_collection:
                self._raise_limit("range size limit exceeded")
            return range(*args)
        if name == "enumerate":
            if not 1 <= len(args) <= 2 or kwargs or (len(args) == 2 and type(args[1]) is not int):
                raise TypeError("enumerate() accepts an iterable and optional integer start")
            return _BoundedIterator(self, enumerate(self._iterable(args[0]), args[1] if len(args) == 2 else 0))
        if name == "zip":
            if kwargs or len(args) > 8:
                raise TypeError("zip() accepts at most eight iterables")
            return _BoundedIterator(self, zip(*(self._iterable(value) for value in args)))
        if name in ("list", "tuple", "set"):
            self._arity(name, args, kwargs, 0, 1)
            if kwargs:
                raise TypeError(f"{name}() does not accept keyword arguments")
            items = [] if not args else self._materialize(args[0])
            if name == "set" and any(not self._is_safe_hash_key(item) for item in items):
                raise TypeError("set values must be bounded scalar values")
            if name == "set":
                for item in items:
                    self._charge_hash_key(item)
            self.charge_collection(len(items))
            result = {"list": list, "tuple": tuple, "set": set}[name](items)
            return self.check_collection(result)
        if name == "dict":
            if len(args) > 1 or set(kwargs) - set():
                if len(args) > 1:
                    raise TypeError("dict() accepts at most one positional argument")
            self.charge_collection(0)
            result: dict[Any, Any] = {}
            if args:
                source = args[0]
                if type(source) is dict:
                    if len(source) > self.max_collection:
                        self._raise_limit("dict input size limit exceeded")
                    self.charge_collection(len(source))
                    for key, value in source.items():
                        self._charge_hash_key(key)
                        result[key] = value
                else:
                    for pair in self._iterable(source):
                        pair_items = self._materialize(pair)
                        if len(pair_items) != 2:
                            raise ValueError("dictionary update sequence element has length other than two")
                        if not self._is_safe_hash_key(pair_items[0]):
                            raise TypeError("dictionary keys must be bounded scalar values")
                        self._charge_hash_key(pair_items[0])
                        if pair_items[0] not in result:
                            self.charge_allocation(8)
                        result[pair_items[0]] = pair_items[1]
                        if len(result) > self.max_collection:
                            self._raise_limit("dict constructor size limit exceeded")
            for key, value in kwargs.items():
                self._charge_hash_key(key)
                if key not in result:
                    self.charge_allocation(8)
                result[key] = value
            return self.check_collection(result)
        if name in ("bool", "int", "float", "str", "repr", "type", "callable"):
            self._arity(name, args, kwargs, 0, 2 if name == "int" else 1)
            if name == "bool":
                return self._truth(args[0]) if args else False
            if name == "int":
                base = args[1] if len(args) > 1 else 10
                if type(base) is not int or base not in (0, 2, 8, 10, 16):
                    raise ValueError("int() base must be 0, 2, 8, 10, or 16")
                value = args[0] if args else 0
                if type(value) is str:
                    self.check_string(value)
                    digits = sum(char.isalnum() for char in value)
                    if digits > int(_MAX_INT_BITS * 0.302) + 2:
                        self._raise_limit("integer conversion bit limit exceeded")
                    return self.check_int(int(value, base))
                if type(value) in (bool, int, float):
                    return self.check_int(int(value))
                raise TypeError("int() value is not supported")
            if name == "float":
                value = args[0] if args else 0.0
                if type(value) not in (bool, int, float, str):
                    raise TypeError("float() value is not supported")
                return float(value)
            if name == "str":
                return self._safe_str(args[0]) if args else ""
            if name == "repr":
                return self._safe_repr(args[0])
            if name == "type":
                if len(args) != 1:
                    raise TypeError("type() accepts one argument")
                value = args[0]
                if value is None:
                    return _BuiltinRef("NoneType")
                for builtin_name, builtin_type in _SAFE_TYPE_NAMES.items():
                    if type(value) is builtin_type:
                        return _BuiltinRef(builtin_name)
                if isinstance(value, BaseException):
                    return type(value)
                if self._is_exception_class(value):
                    return type
                if isinstance(value, (_InterpretedFunction, _Capability)):
                    return _BuiltinRef("function")
                return _BuiltinRef("object")
            if name == "callable":
                value = args[0]
                return isinstance(value, (_Capability, _InterpretedFunction, _BuiltinRef, _SafeMethod)) or (
                    self._is_exception_class(value) and value in _EXCEPTION_TYPES.values()
                )
        if name == "isinstance":
            self._arity(name, args, kwargs, 2)
            targets = args[1] if isinstance(args[1], tuple) else (args[1],)
            if not targets or any(not self._is_safe_type_spec(target) for target in targets):
                raise TypeError("isinstance() type must be a safe type or tuple of safe types")
            translated = tuple(self._translate_type(target) for target in targets)
            return isinstance(args[0], translated)
        if name in ("sum", "min", "max", "all", "any", "sorted"):
            if kwargs:
                raise TypeError(f"{name}() keyword arguments are not supported")
            if not args:
                raise TypeError(f"{name}() requires an argument")
            if name == "sum":
                if len(args) > 2:
                    raise TypeError("sum() accepts at most two arguments")
                total = args[1] if len(args) == 2 else 0
                if not self._numeric(total):
                    raise TypeError("sum() start must be numeric")
                for item in self._iterable(args[0]):
                    self.tick()
                    if not self._numeric(item):
                        raise TypeError("sum() values must be numeric")
                    total = self._binary(ast.Add(), total, item)
                return total
            if len(args) != 1:
                raise TypeError(f"{name}() accepts one iterable")
            values = self._materialize(args[0])
            if name == "all":
                return all(self._truth(value) for value in values)
            if name == "any":
                return any(self._truth(value) for value in values)
            if name == "sorted":
                self._require_scalar_ordering(values, name)
                self.charge_collection(len(values))
                try:
                    result = sorted(values)
                except TypeError as error:
                    raise TypeError("sorted() values are not mutually orderable") from error
                return self.check_collection(result)
            if not values:
                raise ValueError(f"{name}() arg is an empty sequence")
            self._require_scalar_ordering(values, name)
            return min(values) if name == "min" else max(values)
        if name == "abs":
            self._arity(name, args, kwargs, 1)
            if not self._numeric(args[0]):
                raise TypeError("abs() requires a number")
            result = abs(args[0])
            return self.check_int(result) if type(result) is int else result
        if name == "round":
            self._arity(name, args, kwargs, 1, 2)
            if not self._numeric(args[0]) or (len(args) == 2 and type(args[1]) is not int):
                raise TypeError("round() arguments are not supported")
            result = round(*args)
            return self.check_int(result) if type(result) is int else result
        raise UnsupportedSyntaxError(f"builtin is not supported: {name}")

    def _require_scalar_ordering(self, values: list[Any], name: str) -> None:
        maximum_width = 1
        for value in values:
            self.tick()
            if type(value) not in (bool, int, float, str):
                raise TypeError(f"{name}() accepts only bounded scalar values")
            if type(value) is int:
                self.check_int(value)
                maximum_width = max(maximum_width, (value.bit_length() + 7) // 8)
            elif type(value) is str:
                self.check_string(value)
                maximum_width = max(maximum_width, len(value))
            elif type(value) is float:
                maximum_width = max(maximum_width, 8)
        comparisons = max(1, len(values).bit_length()) if name == "sorted" else 1
        self.charge_allocation(64 + len(values) * maximum_width * comparisons)

    def _is_safe_type_spec(self, value: Any) -> bool:
        if isinstance(value, _BuiltinRef):
            return value.name in _SAFE_TYPE_NAMES
        if value in _SAFE_TYPE_NAMES.values():
            return True
        return self._is_exception_class(value)

    def _translate_type(self, value: Any) -> type:
        if isinstance(value, _BuiltinRef):
            return _SAFE_TYPE_NAMES[value.name]
        return value

    def _arity(self, name: str, args: list[Any], kwargs: dict[str, Any], minimum: int, maximum: int | None = None) -> None:
        if kwargs:
            raise TypeError(f"{name}() keyword arguments are not supported")
        maximum = minimum if maximum is None else maximum
        if not minimum <= len(args) <= maximum:
            raise TypeError(f"{name}() received an invalid number of arguments")

    def _materialize(self, iterable: Any) -> list[Any]:
        self.charge_collection(0)
        result: list[Any] = []
        for value in self._iterable(iterable):
            self.tick()
            if len(result) >= self.max_collection:
                self._raise_limit("materialized collection limit exceeded")
            self.charge_allocation(8)
            result.append(value)
        return result

    def _call_method(self, method: _SafeMethod, args: list[Any], kwargs: dict[str, Any]) -> Any:
        receiver, name = method.receiver, method.name
        if type(receiver) is str:
            allowed = {
                "capitalize", "casefold", "count", "endswith", "find", "index", "isalnum", "isalpha",
                "isdigit", "islower", "isspace", "istitle", "isupper", "join", "lower", "lstrip",
                "partition", "removeprefix", "removesuffix", "replace", "rfind", "rindex", "rpartition",
                "rsplit", "rstrip", "split", "splitlines", "startswith", "strip", "swapcase", "title", "upper",
            }
            if kwargs or name not in allowed:
                raise TypeError("string method call is not supported")
            if name == "join":
                self._arity(name, args, kwargs, 1)
                values = self._materialize(args[0])
                if any(type(item) is not str for item in values):
                    raise TypeError("join() sequence items must be strings")
                total = sum(len(item) for item in values) + max(0, len(values) - 1) * len(receiver)
                if total > self.max_string:
                    self._raise_limit("joined string size limit exceeded")
                self.charge_string(total)
                return receiver.join(values)
            if name == "split":
                self._arity(name, args, kwargs, 0, 2)
                sep = args[0] if args else None
                if sep is not None and type(sep) is not str:
                    raise TypeError("split separator must be a string")
                if sep is None:
                    self.charge_allocation(48 + 2 * len(receiver))
                else:
                    self._charge_text_search(receiver, sep)
                maxsplit = args[1] if len(args) == 2 else -1
                if type(maxsplit) is not int:
                    raise TypeError("split maxsplit must be an integer")
                estimate = self._split_count(receiver, sep)
                if maxsplit >= 0:
                    estimate = min(estimate, maxsplit + 1)
                if estimate > self.max_collection:
                    self._raise_limit("split result size limit exceeded")
                self.charge_collection(estimate)
                self.charge_allocation(48 * estimate + 2 * len(receiver))
                return self.check_collection(receiver.split(*args))
            if name == "rsplit":
                self._arity(name, args, kwargs, 0, 2)
                sep = args[0] if args else None
                if sep is not None and type(sep) is not str:
                    raise TypeError("split separator must be a string")
                if sep is None:
                    self.charge_allocation(48 + 2 * len(receiver))
                else:
                    self._charge_text_search(receiver, sep)
                maxsplit = args[1] if len(args) == 2 else -1
                if type(maxsplit) is not int:
                    raise TypeError("split maxsplit must be an integer")
                estimate = self._split_count(receiver, sep)
                if maxsplit >= 0:
                    estimate = min(estimate, maxsplit + 1)
                if estimate > self.max_collection:
                    self._raise_limit("split result size limit exceeded")
                self.charge_collection(estimate)
                self.charge_allocation(48 * estimate + 2 * len(receiver))
                return self.check_collection(receiver.rsplit(*args))
            if name == "replace":
                self._arity(name, args, kwargs, 2, 3)
                old, new = args[:2]
                if type(old) is not str or type(new) is not str:
                    raise TypeError("replace() values must be strings")
                self._charge_text_search(receiver, old)
                count = args[2] if len(args) == 3 else -1
                if type(count) is not int:
                    raise TypeError("replace() count must be an integer")
                matches = receiver.count(old) if count < 0 else min(receiver.count(old), count)
                projected = len(receiver) + matches * (len(new) - len(old)) if old else len(receiver) + (len(receiver) + 1) * len(new)
                if projected > self.max_string:
                    self._raise_limit("replace result size limit exceeded")
                self.charge_string(projected)
            elif name in {"capitalize", "casefold", "lower", "lstrip", "removeprefix", "removesuffix", "rstrip", "strip", "swapcase", "title", "upper"}:
                factor = 3 if name in {"capitalize", "casefold", "lower", "swapcase", "title", "upper"} else 1
                self.charge_string(len(receiver) * factor)
            elif name in {"count", "find", "index", "rfind", "rindex"} and args:
                self._charge_text_search(receiver, args[0])
            elif name in {"startswith", "endswith"} and args:
                self._charge_text_search(receiver, args[0], prefix=True)
            elif name in {"partition", "rpartition"}:
                self._arity(name, args, kwargs, 1)
                if type(args[0]) is not str:
                    raise TypeError("partition separator must be a string")
                self._charge_text_search(receiver, args[0])
                projected = len(receiver) + 2 * len(args[0])
                self.charge_allocation(64 + projected * 2)
            elif name == "splitlines":
                line_breaks = sum(receiver.count(character) for character in ("\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"))
                estimate = min(line_breaks + 1, self.max_collection)
                self.charge_collection(estimate)
                self.charge_allocation(2 * len(receiver))
            result = getattr(receiver, name)(*args)
            return self.check_collection(result)
        if type(receiver) is list:
            if kwargs:
                raise TypeError("list method keyword arguments are not supported")
            if name == "append":
                self._arity(name, args, kwargs, 1)
                if len(receiver) >= self.max_collection:
                    self._raise_limit("list mutation size limit exceeded")
                self.charge_allocation(8)
                receiver.append(args[0])
                return None
            if name == "extend":
                self._arity(name, args, kwargs, 1)
                incoming = self._materialize(args[0])
                if len(receiver) + len(incoming) > self.max_collection:
                    self._raise_limit("list mutation size limit exceeded")
                self.charge_allocation(8 * len(incoming))
                receiver.extend(incoming)
                return None
            if name == "insert":
                self._arity(name, args, kwargs, 2)
                if len(receiver) >= self.max_collection or type(args[0]) is not int:
                    self._raise_limit("list mutation size limit exceeded")
                self.charge_allocation(8)
                receiver.insert(args[0], args[1])
                return None
            if name == "pop":
                self._arity(name, args, kwargs, 0, 1)
                return receiver.pop(*args)
            if name == "clear":
                self._arity(name, args, kwargs, 0)
                receiver.clear()
                return None
            if name == "copy":
                self._arity(name, args, kwargs, 0)
                self.charge_collection(len(receiver))
                return list(receiver)
            if name == "reverse":
                self._arity(name, args, kwargs, 0)
                receiver.reverse()
                return None
        if type(receiver) is tuple and name in {"count", "index"}:
            if name == "count":
                self._arity(name, args, kwargs, 1)
                start, stop = 0, len(receiver)
            else:
                self._arity(name, args, kwargs, 1, 3)
                start = args[1] if len(args) > 1 else 0
                stop = args[2] if len(args) > 2 else len(receiver)
                if type(start) is not int or type(stop) is not int:
                    raise TypeError("tuple index bounds must be integers")
                start, stop, _ = slice(start, stop, 1).indices(len(receiver))
            matches = 0
            for index in range(start, stop):
                self.tick()
                if self._safe_equal(receiver[index], args[0]):
                    if name == "index":
                        return index
                    matches += 1
            if name == "index":
                raise ValueError("tuple.index(x): x not in tuple")
            return matches
        if type(receiver) is dict:
            if name == "items":
                self._arity(name, args, kwargs, 0)
                self.charge_collection(len(receiver))
                return tuple(receiver.items())
            if name == "keys":
                self._arity(name, args, kwargs, 0)
                self.charge_collection(len(receiver))
                return tuple(receiver.keys())
            if name == "values":
                self._arity(name, args, kwargs, 0)
                self.charge_collection(len(receiver))
                return tuple(receiver.values())
            if name == "get":
                self._arity(name, args, kwargs, 1, 2)
                if not self._is_safe_hash_key(args[0]):
                    raise TypeError("dictionary keys must be bounded scalar values")
                self._charge_hash_key(args[0])
                return receiver.get(*args)
            if name == "setdefault":
                self._arity(name, args, kwargs, 1, 2)
                key = args[0]
                if not self._is_safe_hash_key(key):
                    raise TypeError("dictionary keys must be bounded scalar values")
                self._charge_hash_key(key)
                if key not in receiver and len(receiver) >= self.max_collection:
                    self._raise_limit("dictionary mutation size limit exceeded")
                return receiver.setdefault(*args)
            if name == "update":
                if len(args) > 1:
                    raise TypeError("dict.update() accepts at most one argument")
                items = self._call_builtin("dict", args, kwargs)
                if len(receiver) + len(items) > self.max_collection:
                    self._raise_limit("dictionary mutation size limit exceeded")
                for key in items:
                    self._charge_hash_key(key)
                self.charge_allocation(8 * sum(key not in receiver for key in items))
                receiver.update(items)
                return None
            if name == "pop":
                self._arity(name, args, kwargs, 1, 2)
                if not self._is_safe_hash_key(args[0]):
                    raise TypeError("dictionary keys must be bounded scalar values")
                self._charge_hash_key(args[0])
                return receiver.pop(*args)
            if name == "popitem":
                self._arity(name, args, kwargs, 0)
                return receiver.popitem()
            if name == "clear":
                self._arity(name, args, kwargs, 0)
                receiver.clear()
                return None
            if name == "copy":
                self._arity(name, args, kwargs, 0)
                self.charge_collection(len(receiver))
                return receiver.copy()
        if type(receiver) is set:
            if kwargs:
                raise TypeError("set method keyword arguments are not supported")
            if name == "add":
                self._arity(name, args, kwargs, 1)
                if not self._is_safe_hash_key(args[0]):
                    raise TypeError("set values must be bounded scalar values")
                self._charge_hash_key(args[0])
                if args[0] not in receiver and len(receiver) >= self.max_collection:
                    self._raise_limit("set mutation size limit exceeded")
                if args[0] not in receiver:
                    self.charge_allocation(8)
                receiver.add(args[0])
                return None
            if name == "update":
                self.charge_collection(0)
                incoming: list[Any] = []
                for source in args:
                    for item in self._iterable(source):
                        self.tick()
                        if len(incoming) >= self.max_collection:
                            self._raise_limit("set mutation size limit exceeded")
                        self.charge_allocation(8)
                        incoming.append(item)
                if any(not self._is_safe_hash_key(item) for item in incoming):
                    raise TypeError("set values must be bounded scalar values")
                for item in incoming:
                    self._charge_hash_key(item)
                if len(receiver) + len(incoming) > self.max_collection:
                    self._raise_limit("set mutation size limit exceeded")
                self.charge_allocation(8 * sum(item not in receiver for item in incoming))
                receiver.update(incoming)
                return None
            if name in {"discard", "remove"}:
                self._arity(name, args, kwargs, 1)
                if not self._is_safe_hash_key(args[0]):
                    raise TypeError("set values must be bounded scalar values")
                self._charge_hash_key(args[0])
                getattr(receiver, name)(args[0])
                return None
            if name == "pop":
                self._arity(name, args, kwargs, 0)
                return receiver.pop()
            if name == "clear":
                self._arity(name, args, kwargs, 0)
                receiver.clear()
                return None
            if name == "copy":
                self._arity(name, args, kwargs, 0)
                self.charge_collection(len(receiver))
                return receiver.copy()
        raise UnsupportedSyntaxError(f"method is not supported: {name}")

    def _split_count(self, value: str, separator: str | None) -> int:
        if separator is not None:
            if separator == "":
                raise ValueError("empty separator")
            return value.count(separator) + 1
        words = 0
        inside = False
        for character in value:
            self.tick()
            if character.isspace():
                inside = False
            elif not inside:
                words += 1
                inside = True
                if words > self.max_collection:
                    return words
        return words

    def _charge_text_search(self, text: str, needle: Any, *, prefix: bool = False) -> None:
        if type(needle) is str:
            width = len(needle)
        elif prefix and type(needle) is tuple and all(type(item) is str for item in needle):
            width = sum(len(item) for item in needle)
            for _ in needle:
                self.tick()
        else:
            raise TypeError("string search value must be text")
        work = len(text) + width + 48 if prefix else max(1, len(text)) * max(1, width) + 48
        self.charge_allocation(work)

    def _assign(self, target: ast.expr, value: Any, scope: _Scope) -> None:
        self.tick()
        if isinstance(target, ast.Name):
            self._store_name(target.id, value, scope)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            values = self._materialize(value)
            if len(values) != len(target.elts):
                raise ValueError("unpacking assignment length mismatch")
            for child, item in zip(target.elts, values):
                self._assign(child, item, scope)
            return
        if isinstance(target, ast.Subscript):
            receiver = self._eval_expr(target.value, scope)
            index = self._eval_slice(target.slice, scope)
            if isinstance(receiver, list):
                if isinstance(index, slice):
                    values = self._materialize(value)
                    start, stop, step = index.indices(len(receiver))
                    removed = len(range(start, stop, step))
                    updated_size = len(receiver) - removed + len(values)
                    if updated_size > self.max_collection:
                        self._raise_limit("list assignment size limit exceeded")
                    self.charge_allocation(8 * max(0, updated_size - len(receiver)))
                    receiver[index] = values
                else:
                    receiver[index] = value
                return
            if isinstance(receiver, dict):
                if not self._is_safe_hash_key(index):
                    raise TypeError("dictionary keys must be bounded scalar values")
                if index not in receiver and len(receiver) >= self.max_collection:
                    self._raise_limit("dictionary assignment size limit exceeded")
                if index not in receiver:
                    self.charge_allocation(8)
                receiver[index] = value
                return
            raise TypeError("item assignment is limited to lists and dictionaries")
        raise UnsupportedSyntaxError("assignment target is not supported")

    def _exec_block(self, statements: list[ast.stmt], scope: _Scope) -> None:
        for statement in statements:
            self._exec_stmt(statement, scope)

    def _exec_stmt(self, node: ast.stmt, scope: _Scope) -> None:
        self.tick()
        if isinstance(node, ast.FunctionDef):
            defaults: dict[str, Any] = {}
            args = node.args
            if args.posonlyargs or args.kwonlyargs:
                raise UnsupportedSyntaxError("positional-only and keyword-only parameters are not supported")
            parameters = list(args.posonlyargs) + list(args.args)
            positional_names = [argument.arg for argument in parameters]
            default_start = len(positional_names) - len(args.defaults)
            for index, expression in enumerate(args.defaults):
                defaults[positional_names[default_start + index]] = self._eval_expr(expression, scope)
            keyword_names: list[str] = []
            for argument, expression in zip(args.kwonlyargs, args.kw_defaults):
                keyword_names.append(argument.arg)
                if expression is not None:
                    defaults[argument.arg] = self._eval_expr(expression, scope)
            all_names = positional_names + keyword_names
            local_names = set(all_names)
            for statement in node.body:
                local_names.update(self._assigned_names(statement))
            state = self._state_for_scope(scope)
            function = _InterpretedFunction(
                self, state.namespace, node, node.name,
                _Parameters(positional_names, all_names, defaults, local_names), state,
            )
            self._store_name(node.name, function, scope)
            return
        if isinstance(node, ast.Return):
            raise _ReturnSignal(self._eval_expr(node.value, scope) if node.value is not None else None)
        if isinstance(node, ast.Expr):
            self._eval_expr(node.value, scope)
            return
        if isinstance(node, ast.Assign):
            value = self._eval_expr(node.value, scope)
            for target in node.targets:
                self._assign(target, value, scope)
            return
        if isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self._assign(node.target, self._eval_expr(node.value, scope), scope)
            return
        if isinstance(node, ast.AugAssign):
            if not isinstance(node.target, (ast.Name, ast.Subscript)):
                raise UnsupportedSyntaxError("augmented assignment target is not supported")
            current = self._eval_expr(node.target, scope)
            value = self._binary(node.op, current, self._eval_expr(node.value, scope))
            self._assign(node.target, value, scope)
            return
        if isinstance(node, ast.If):
            if self._truth(self._eval_expr(node.test, scope)):
                self._exec_block(node.body, scope)
            else:
                self._exec_block(node.orelse, scope)
            return
        if isinstance(node, ast.For):
            iterator = self._iterable(self._eval_expr(node.iter, scope))
            for item in iterator:
                self.tick()
                self._assign(node.target, item, scope)
                try:
                    self._exec_block(node.body, scope)
                except _ContinueSignal:
                    continue
                except _BreakSignal:
                    break
            else:
                self._exec_block(node.orelse, scope)
            return
        if isinstance(node, ast.While):
            while self._truth(self._eval_expr(node.test, scope)):
                self.tick()
                try:
                    self._exec_block(node.body, scope)
                except _ContinueSignal:
                    continue
                except _BreakSignal:
                    break
            else:
                self._exec_block(node.orelse, scope)
            return
        if isinstance(node, ast.Break):
            raise _BreakSignal()
        if isinstance(node, ast.Continue):
            raise _ContinueSignal()
        if isinstance(node, ast.Pass):
            return
        if isinstance(node, ast.Assert):
            if not self._truth(self._eval_expr(node.test, scope)):
                message = self._eval_expr(node.msg, scope) if node.msg is not None else ""
                raise AssertionError(self._safe_str(message))
            return
        if isinstance(node, ast.Raise):
            if node.exc is None:
                if not self.active_exceptions:
                    raise RuntimeError("No active exception to reraise")
                raise self.active_exceptions[-1]
            value = self._eval_expr(node.exc, scope)
            if self._is_exception_class(value) and value in _EXCEPTION_TYPES.values():
                value = value()
            if not isinstance(value, BaseException):
                raise TypeError("exceptions must derive from BaseException")
            raise value
        if isinstance(node, ast.Try):
            self._exec_try(node, scope)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "typing":
                    bound = _TypingModuleRef(self.typing_names)
                else:
                    module_ref = self._import_module(alias.name)
                    bound = module_ref if alias.asname else _ModuleRef(self, alias.name.split(".")[0])
                self._store_name(alias.asname or alias.name.split(".")[0], bound, scope)
            return
        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__" and node.level == 0:
                return
            if node.module == "typing" and node.level == 0:
                for alias in node.names:
                    self._store_name(alias.asname or alias.name, self.typing_names[alias.name], scope)
                return
            if node.module == "collections.abc" and node.level == 0:
                for alias in node.names:
                    self._store_name(alias.asname or alias.name, self.collections_abc_names[alias.name], scope)
                return
            module_name = self._resolve_import_name(self._state_for_scope(scope).name, node)
            if node.module is None:
                module_ref = self._import_module(module_name)
                for alias in node.names:
                    self._store_name(alias.asname or alias.name, self._module_attr(module_ref, alias.name), scope)
                return
            module_ref = self._import_module(module_name)
            for alias in node.names:
                self._store_name(alias.asname or alias.name, self._module_attr(module_ref, alias.name), scope)
            return
        raise UnsupportedSyntaxError(f"statement is not supported: {type(node).__name__}")

    def _state_for_scope(self, scope: _Scope) -> _ModuleState:
        for state in self.states.values():
            if state.namespace is scope.global_ns:
                return state
        for value in scope.local.values():
            if isinstance(value, _InterpretedFunction):
                return value.state
        raise RuntimeError("interpreter scope has no module state")

    def _assigned_names(self, node: ast.AST) -> set[str]:
        names: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.ClassDef)) and child is not node:
                continue
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                names.add(child.name)
            elif isinstance(child, ast.Import):
                names.update(alias.asname or alias.name.split(".")[0] for alias in child.names)
            elif isinstance(child, ast.ImportFrom):
                names.update(alias.asname or alias.name for alias in child.names if alias.name != "*")
        return names

    def _exec_try(self, node: ast.Try, scope: _Scope) -> None:
        pending: BaseException | None = None
        try:
            try:
                self._exec_block(node.body, scope)
            except (ExecutionLimitError, UnsupportedSyntaxError, _ReturnSignal, _BreakSignal, _ContinueSignal):
                raise
            except BaseException as error:
                handled = False
                for handler in node.handlers:
                    if handler.type is None:
                        matches = True
                    else:
                        exception_type = self._eval_expr(handler.type, scope)
                        matches = self._matches_exception(error, exception_type)
                    if not matches:
                        continue
                    handled = True
                    if handler.name:
                        scope.local[handler.name] = error
                        scope.local_names.add(handler.name)
                    self.active_exceptions.append(error)
                    try:
                        self._exec_block(handler.body, scope)
                    finally:
                        self.active_exceptions.pop()
                        if handler.name:
                            scope.local.pop(handler.name, None)
                    break
                if not handled:
                    pending = error
            else:
                self._exec_block(node.orelse, scope)
        finally:
            if node.finalbody:
                self._exec_block(node.finalbody, scope)
        if pending is not None:
            raise pending

    def _matches_exception(self, error: BaseException, exception_type: Any) -> bool:
        types_to_check = exception_type if isinstance(exception_type, tuple) else (exception_type,)
        if not types_to_check or any(not self._is_exception_class(item) for item in types_to_check):
            raise TypeError("except clause must catch exception classes")
        return any(isinstance(error, item) for item in types_to_check)


@dataclass
class _Parameters:
    positional: list[str]
    all_names: list[str]
    defaults: dict[str, Any]
    local_names: set[str]


class _BoundedIterator:
    def __init__(self, runtime: _Runtime, iterator: Any) -> None:
        self.runtime = runtime
        self.iterator = iterator
        self.count = 0

    def __iter__(self) -> "_BoundedIterator":
        return self

    def __next__(self) -> Any:
        self.runtime.tick()
        if self.count >= self.runtime.max_collection:
            try:
                next(self.iterator)
            except StopIteration:
                raise
            self.runtime._raise_limit("iterator item limit exceeded")
        self.count += 1
        return next(self.iterator)


class _InterpretedFunction:
    def __init__(
        self,
        runtime: _Runtime,
        global_ns: dict[str, Any],
        node: ast.FunctionDef,
        name: str,
        parameters: _Parameters,
        state: _ModuleState,
    ) -> None:
        self.runtime = runtime
        self.global_ns = global_ns
        self.node = node
        self.name = name
        self.parameters = parameters
        self.state = state

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.runtime.call_depth == 0:
            self.runtime.steps = 0
            self.runtime.allocation_remaining = self.runtime.allocation_limit
        self.runtime.charge_allocation(64 + 8 * (len(args) + len(kwargs)))
        return self.runtime._call_interpreted(self, list(args), dict(kwargs), external=True)


_ALLOWED_NODES = {
    ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Expr, ast.Assign,
    ast.AnnAssign, ast.AugAssign, ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler,
    ast.Raise, ast.Break, ast.Continue, ast.Pass, ast.Assert, ast.Import, ast.ImportFrom,
    ast.alias, ast.keyword, ast.Name, ast.Load, ast.Store, ast.Del, ast.Constant, ast.BinOp,
    ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Call, ast.Attribute, ast.Subscript, ast.Slice,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.ListComp, ast.SetComp, ast.DictComp,
    ast.comprehension, ast.IfExp, ast.JoinedStr, ast.FormattedValue, ast.Add, ast.Sub, ast.Mult,
    ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift,
    ast.RShift, ast.UAdd, ast.USub, ast.Not, ast.Invert, ast.And, ast.Or, ast.Eq, ast.NotEq,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
}


def _check_target(target: ast.expr) -> None:
    if isinstance(target, ast.Name):
        if target.id.startswith("__"):
            raise UnsupportedSyntaxError("dunder names cannot be assigned")
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        for item in target.elts:
            _check_target(item)
        return
    if isinstance(target, ast.Subscript):
        return
    raise UnsupportedSyntaxError("assignment target is not supported")


def _validate_tree(name: str, tree: ast.Module, module_names: set[str]) -> None:
    nodes = 0
    stack: list[tuple[ast.AST, int]] = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_AST_NODES:
            raise ExecutionLimitError("AST node limit exceeded")
        if depth > _MAX_STATIC_DEPTH:
            raise ExecutionLimitError("AST nesting limit exceeded")
        if type(node) not in _ALLOWED_NODES:
            raise UnsupportedSyntaxError(f"syntax is not supported: {type(node).__name__}")
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise UnsupportedSyntaxError("private attributes are not supported")
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise UnsupportedSyntaxError(f"builtin is not supported: {node.id}")
        if isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                raise UnsupportedSyntaxError("decorated functions are not supported")
            if getattr(node, "type_params", ()):
                raise UnsupportedSyntaxError("generic functions are not supported")
            if node.args.posonlyargs or node.args.kwonlyargs:
                raise UnsupportedSyntaxError("positional-only and keyword-only parameters are not supported")
            if node.args.vararg is not None or node.args.kwarg is not None:
                raise UnsupportedSyntaxError("variadic parameters are not supported")
            if len(set(argument.arg for argument in list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs))) != len(list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)):
                raise UnsupportedSyntaxError("duplicate function parameter")
            for statement in node.body:
                for child in ast.walk(statement):
                    if isinstance(child, ast.FunctionDef) and child is not node:
                        raise UnsupportedSyntaxError("nested function definitions are not supported")
                    if isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Store):
                        raise UnsupportedSyntaxError("attribute assignment is not supported")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                _check_target(target)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            _check_target(node.target)
        elif isinstance(node, (ast.For, ast.comprehension)):
            _check_target(node.target)
            if isinstance(node, ast.comprehension) and node.is_async:
                raise UnsupportedSyntaxError("async comprehensions are not supported")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "typing":
                    continue
                if alias.name != "src" and not alias.name.startswith("src."):
                    raise UnsupportedSyntaxError("imports are limited to local src modules")
                if alias.name not in module_names:
                    raise UnsupportedSyntaxError(f"local module is not available: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module == "__future__":
                if any(alias.name != "annotations" for alias in node.names):
                    raise UnsupportedSyntaxError("only future annotations import is supported")
            elif node.level == 0 and node.module == "typing":
                if any(alias.name not in _ALLOWED_TYPING_NAMES for alias in node.names):
                    raise UnsupportedSyntaxError("typing import is not in the safe subset")
            elif node.level == 0 and node.module == "collections.abc":
                if any(alias.name not in _ALLOWED_ABC_NAMES for alias in node.names):
                    raise UnsupportedSyntaxError("collections.abc import is not in the safe annotation subset")
            else:
                module_name = _resolve_static_import(name, node)
                if module_name not in module_names:
                    raise UnsupportedSyntaxError(f"local module is not available: {module_name}")
                if any(alias.name == "*" for alias in node.names):
                    raise UnsupportedSyntaxError("wildcard imports are not supported")
        elif isinstance(node, ast.Call):
            if any(keyword.arg is None for keyword in node.keywords):
                raise UnsupportedSyntaxError("keyword unpacking is not supported")
            if any(isinstance(argument, ast.Starred) for argument in node.args):
                raise UnsupportedSyntaxError("argument unpacking is not supported")
        elif isinstance(node, ast.Dict) and any(key is None for key in node.keys):
            raise UnsupportedSyntaxError("dictionary unpacking is not supported")
        elif isinstance(node, ast.Raise) and node.cause is not None:
            raise UnsupportedSyntaxError("exception chaining is not supported")
        elif isinstance(node, ast.Try) and not node.handlers and not node.finalbody:
            raise UnsupportedSyntaxError("try statement has no handler or final block")
        elif isinstance(node, ast.FormattedValue) and node.conversion not in (-1, ord("s"), ord("r"), ord("a")):
            raise UnsupportedSyntaxError("formatted string conversion is not supported")
    _validate_control_contexts(tree)


def _validate_control_contexts(tree: ast.Module) -> None:
    future_nodes = {
        id(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    }
    direct_future_nodes = {
        id(statement)
        for statement in tree.body
        if isinstance(statement, ast.ImportFrom) and statement.module == "__future__"
    }
    if future_nodes != direct_future_nodes:
        raise UnsupportedSyntaxError("future imports must be at module scope")

    seen_nonfuture = False
    for index, statement in enumerate(tree.body):
        if index == 0 and isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and type(statement.value.value) is str:
            continue
        if isinstance(statement, ast.ImportFrom) and statement.module == "__future__":
            if seen_nonfuture:
                raise UnsupportedSyntaxError("future imports must precede module statements")
        else:
            seen_nonfuture = True

    stack: list[tuple[ast.AST, bool, int]] = [(tree, False, 0)]
    while stack:
        node, in_function, loop_depth = stack.pop()
        if isinstance(node, ast.Return) and not in_function:
            raise UnsupportedSyntaxError("return is only supported inside a function")
        if isinstance(node, (ast.Break, ast.Continue)) and loop_depth == 0:
            raise UnsupportedSyntaxError("break and continue require an enclosing loop")
        if isinstance(node, ast.FunctionDef):
            stack.extend((statement, True, 0) for statement in node.body)
        elif isinstance(node, (ast.For, ast.While)):
            stack.extend((statement, in_function, loop_depth + 1) for statement in node.body)
            stack.extend((statement, in_function, loop_depth) for statement in node.orelse)
        else:
            stack.extend((child, in_function, loop_depth) for child in ast.iter_child_nodes(node))


def _resolve_static_import(current_name: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        base = node.module or ""
    else:
        package = current_name.rpartition(".")[0]
        parts = package.split(".") if package else []
        remove = node.level - 1
        if remove > len(parts):
            raise UnsupportedSyntaxError("relative import escapes src package")
        prefix = parts[: len(parts) - remove] if remove else parts
        suffix = node.module.split(".") if node.module else []
        base = ".".join(prefix + suffix)
    if not base.startswith("src") or (base != "src" and not base.startswith("src.")):
        raise UnsupportedSyntaxError("imports are limited to src modules")
    return base


def _validate_module_name(name: str) -> bool:
    if type(name) is not str or not name.startswith("src."):
        return False
    parts = name.split(".")
    return all(part.isidentifier() and not part.startswith("_") for part in parts)


def load_modules(
    sources: dict[str, str],
    *,
    step_limit: int = 100_000,
    max_collection: int = 10_000,
    max_depth: int = 128,
) -> dict[str, types.ModuleType]:
    """Parse and interpret bounded ``src.*`` modules without native execution."""
    if type(sources) is not dict or len(sources) > _MAX_MODULES:
        raise UnsupportedSyntaxError("sources must be a bounded mapping of src modules")
    for value, name in ((step_limit, "step_limit"), (max_collection, "max_collection"), (max_depth, "max_depth")):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name} must be a positive integer")
    if step_limit > 1_000_000 or max_collection > 100_000 or max_depth > _MAX_STATIC_DEPTH:
        raise ValueError("interpreter limits exceed their hard maxima")
    trees: dict[str, ast.Module] = {}
    total_bytes = 0
    for name, source in sources.items():
        if not _validate_module_name(name):
            raise UnsupportedSyntaxError(f"invalid source module name: {name!r}")
        if type(source) is not str:
            raise UnsupportedSyntaxError("module source must be text")
        encoded = source.encode("utf-8")
        if len(encoded) > _MAX_SOURCE_BYTES:
            raise ExecutionLimitError("module source byte limit exceeded")
        total_bytes += len(encoded)
        if total_bytes > _MAX_TOTAL_SOURCE_BYTES:
            raise ExecutionLimitError("total source byte limit exceeded")
        try:
            tree = ast.parse(source, filename=f"<{name}>", mode="exec")
        except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
            raise UnsupportedSyntaxError(f"source cannot be parsed: {type(error).__name__}") from None
        trees[name] = tree
    module_names = set(trees)
    module_names.add("src")
    for name in tuple(trees):
        parts = name.split(".")
        for index in range(1, len(parts)):
            module_names.add(".".join(parts[:index]))
    for name, tree in trees.items():
        _validate_tree(name, tree, module_names)
    runtime = _Runtime(
        trees,
        step_limit=step_limit,
        max_collection=max_collection,
        max_depth=max_depth,
    )
    for name in trees:
        runtime._ensure_module(name)
    runtime.steps = 0
    return {name: state.public for name, state in runtime.states.items()}
