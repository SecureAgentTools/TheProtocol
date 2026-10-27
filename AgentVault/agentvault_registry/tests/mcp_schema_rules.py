"""§MCPTEST30 (V0548) — the census's rules (tests/mcp_schema_census.py), apart so a test can read them: importing the
census patches httpx in the importing process (it rides the request survey), these import nothing.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Tuple

STRING_KEYS = ("enum", "pattern", "minLength", "maxLength", "format")
NUMBER_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
FORMATS = ("email", "date-time", "date", "uri", "uuid")
_ALTERNATION = re.compile(r"^\^\(([A-Za-z0-9_.\-]+(?:\|[A-Za-z0-9_.\-]+)+)\)\$$")


def route_constraints(sc: Dict[str, Any], deref: Callable[[Any], Dict[str, Any]] = lambda x: x if isinstance(x, dict) else {}) -> Tuple[str, Dict[str, Any]]:
    """(the route's JSON type, the constraints a caller must meet), a pattern of plain alternatives read as an enum."""
    sc = deref(sc)
    t = sc.get("type") or ""
    out: Dict[str, Any] = {}
    if t == "string" or (not t and any(k in sc for k in STRING_KEYS)):
        for k in STRING_KEYS:
            if k in sc:
                out[k] = sc[k]
        m = _ALTERNATION.match(str(out.get("pattern") or ""))
        if m and "enum" not in out:
            out["enum"] = m.group(1).split("|")
            out.pop("pattern")
        if out.get("format") not in FORMATS:
            out.pop("format", None)
    elif t in ("integer", "number"):
        for k in NUMBER_KEYS:
            if k in sc:
                out[k] = int(sc[k]) if isinstance(sc[k], float) and sc[k].is_integer() else sc[k]
    elif t == "array" and isinstance(sc.get("items"), dict):
        it = deref(sc["items"])
        if it.get("type") or it.get("properties"):
            out["items"] = {"type": it.get("type") or "object"}
    return t, out


def looser(key: str, schema_v: Any, route_v: Any) -> bool:
    """Whether the schema allows what the route refuses. A schema STRICTER than its route is safe (a tool may narrow
    on purpose: discoverAgents asks for at most 50 where the route takes 120): only the looser one misleads a caller."""
    try:
        if key in ("maximum", "exclusiveMaximum", "maxLength"):
            return float(schema_v) > float(route_v)
        if key in ("minimum", "exclusiveMinimum", "minLength"):
            return float(schema_v) < float(route_v)
    except (TypeError, ValueError):
        return True
    if key == "enum":
        return not set(map(str, schema_v or [])) <= set(map(str, route_v or []))
    return schema_v != route_v


def kind(prop: Dict[str, Any]) -> str:
    t = prop.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "")
    return t or ""


def compatible(route_t: str, tool_t: str) -> bool:
    if not tool_t:
        return True
    if route_t == "string":
        return tool_t == "string"
    if route_t in ("integer", "number"):
        return tool_t in ("integer", "number")
    return route_t == tool_t
