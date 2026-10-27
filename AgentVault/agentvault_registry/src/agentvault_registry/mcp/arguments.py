"""§MCPTEST30 (V0524, 2026-10-01): a tools/call argument whose JSON type its tool's inputSchema cannot take is the
caller's -32602, before the tool runs.

The dispatchers handed `arguments` to the tool function unchecked. The MCP tester's type-confusion probe asked every
read tool once per typed argument with a value of the wrong type (sbx-alpha, V0521): of 107 calls, 72 answered -32603
"Internal error" (an integer argument sent as "abc" reached the tool's own int() or max(), and the ValueError or
TypeError became the server's fault), 20 answered -32602 (a TypeError the dispatcher happens to map), 2 crashed inside
the tool. The MCP specification puts the validation on the server.

LENIENT WHERE A CALLER CAN MEAN IT: a numeric string for an integer or a number ("10"), "true"/"false" for a boolean, a
string for an array or an object (some tools read a comma list or a JSON text), any scalar for a string, and null for
anything (an absent optional). STRICT WHERE NOTHING CAN BE MEANT: a non-numeric string, a list or an object for a
number; a list or an object for a string or a boolean; a scalar for an array or an object. An argument the schema does
not declare is left to the tool's own signature (the dispatcher already answers that -32602).
"""
from __future__ import annotations

import inspect
import math
import re
from typing import Any, Dict, List, Optional, Tuple

_INT = re.compile(r"^\s*[-+]?\d+\s*$")
_BOOL_WORDS = {"true", "false", "1", "0", "yes", "no"}
_SECRET_WORDS = ("jwt", "secret", "password", "token", "key", "code", "recovery")


def _is_number_text(v: str) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _fits(value: Any, t: Optional[str]) -> bool:
    if value is None or t is None:   # an absent optional, or a type the schema does not name
        return True
    if t == "null":                  # only None is null (a union's null branch must not take everything)
        return False
    if t == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        if isinstance(value, float):
            return value.is_integer()
        return isinstance(value, str) and bool(_INT.match(value))
    if t == "number":
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return math.isfinite(value)
        return isinstance(value, str) and _is_number_text(value)
    if t == "boolean":
        return isinstance(value, bool) or (isinstance(value, str) and value.strip().lower() in _BOOL_WORDS) \
            or (isinstance(value, int) and value in (0, 1))
    if t == "string":
        return not isinstance(value, (list, dict))
    if t == "array":
        return isinstance(value, (list, str))
    if t == "object":
        return isinstance(value, (dict, str))
    return True   # a type this check does not know is the tool's to read


def argument_problems(input_schema: Optional[Dict[str, Any]], arguments: Dict[str, Any]) -> List[str]:
    """One sentence per argument whose JSON type its declared type cannot take; [] when every argument fits."""
    props = (input_schema or {}).get("properties") or {}
    out: List[str] = []
    for name, value in (arguments or {}).items():
        spec = props.get(name)
        if not isinstance(spec, dict):
            continue
        t = spec.get("type")
        types = t if isinstance(t, list) else [t]
        if any(_fits(value, x) for x in types):
            continue
        want = " or ".join(str(x) for x in types)
        if any(k in name.lower() for k in _SECRET_WORDS):   # never echo what may be a credential
            out.append(f"{name}: expected {want}, got {type(value).__name__}")
            continue
        shown = repr(value)
        shown = shown if len(shown) <= 40 else shown[:37] + "..."
        out.append(f"{name}: expected {want}, got {type(value).__name__} {shown}")
    return out


class ToolArgumentsRefused(TypeError):
    """Arguments that do not bind to the tool's own signature: the caller's -32602, raised BEFORE the tool runs.

    §MCPTEST30 (V0545). The schema check (V0524's argument_problems) reads types; a required argument the schema does not
    mark required, or one missing, reached the call and raised TypeError there. The dispatcher audited that as
    `mcp_tool_failed`, outcome error, logged at ERROR as an unhandled tool failure, and attributed it to "anonymous"
    (the tool raised before the call returned its auth context), then answered the caller -32602: 225 such rows in 15
    minutes on sbx-alpha from one sweep's empty-argument probe. Binding first tells the two apart: a TypeError the
    binding raises is the caller's; one raised inside a running tool is still a failure. It carries the caller."""

    def __init__(self, problem: str, auth_ctx: Any = None) -> None:
        super().__init__(problem)
        self.auth_ctx = auth_ctx


def refuse_unbindable(fn: Any, prefix: Tuple[Any, ...], arguments: Dict[str, Any], auth_ctx: Any = None) -> None:
    """Raise ToolArgumentsRefused when `arguments` (after `prefix`) do not bind to `fn`'s signature; else nothing."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):   # a callable without a readable signature is called as before
        return
    try:
        sig.bind(*prefix, **arguments)
    except TypeError as e:
        raise ToolArgumentsRefused(str(e), auth_ctx) from None
