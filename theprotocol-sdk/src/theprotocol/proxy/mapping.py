"""A mapping turns one Record into what an action takes, and its version is part of the exactly-once key.

    fields:
      container: $.payload.container_id         # a path into the record
      at: {path: $.payload.ts, default: null}    # a path with a default when the record has no such field
      terminal: HAM-CTA                          # anything else is a constant
      lines: [$.payload.a, $.payload.b]          # lists and objects are mapped inside
    when: {path: $.payload.status, equals: OUT}  # the record is taken only when it holds (also: in, exists)

A field can also be a VALUE NODE (V0664, Migrate a system): a dict whose keys are all in VALUE_KEYS and that has `path` (a string
starting with $) or `concat` (a list), which reads a value and transforms it, pure, no eval:

      created:  {path: $.payload.created, as: datetime, format: "%d.%m.%Y %H:%M", tz: Europe/Berlin}
      status:   {path: $.payload.state, trim: true, case: upper, map: {A: active, B: blocked}, map_default: unknown}
      price:    {path: $.payload.price, as: decimal, round: 2, null_if: ["", "N/A"]}
      customer: {concat: [$.payload.first, $.payload.last], sep: " "}

  The steps run in this order: read the path (a missing one: `default` if given; `required: false` gives null; else the record
  is refused) -> null_if -> trim -> case (upper, lower, title) -> regex + group (no match: refused, or `default`) -> map +
  map_default (no entry and no map_default: refused) -> as (text, int, decimal, float, bool, date, datetime, json; format and tz
  for the dates) -> round (ROUND_HALF_EVEN on a Decimal). A null stays null through the rest. `concat` joins a list of paths,
  nodes and constants with `sep` (a null part refuses unless that part says required: false, and then it is empty text), and its
  result goes through the same steps. Every other dict stays a nested object. A refusal names the mapping's field and the rule,
  never the record's value; a bad node is refused when the spec is loaded (check_fields), not at the first record.

A path starts at the record: `$.payload...`, `$.record_id`, `$.source`, `$.meta...`, `$.observed_at`. A field whose path
the record does not have, and that names no default, refuses the record (to the dead letters, with the path), so a
legacy system that changes its export is seen at once rather than sent half-empty.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping

from .plugins import Record, Refused

_MISSING = object()

VALUE_KEYS = frozenset({"path", "default", "required", "as", "format", "tz", "trim", "case", "map", "map_default", "null_if",
                        "round", "regex", "group", "concat", "sep"})
AS_TYPES = ("text", "int", "decimal", "float", "bool", "date", "datetime", "json")
CASES = ("upper", "lower", "title")
_NUMERIC_AS = ("int", "decimal", "float")
_BOOLS = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False}
_INT = re.compile(r"^[+-]?[0-9]+$")


def is_value_node(node: Any) -> bool:
    """A dict whose keys are all value keys and that has a path (a string starting with $) or a concat (a list)."""
    if not isinstance(node, Mapping) or not node or not set(node) <= VALUE_KEYS:
        return False
    path = node.get("path")
    return (isinstance(path, str) and path.startswith("$")) or isinstance(node.get("concat"), list)


def key_for(source: str, record_id: str, mapping: str, version: int) -> str:
    """The record's exactly-once key: the same record, through the same version of a mapping, is sent once."""
    h = hashlib.sha256("\x1f".join((source, record_id, mapping, str(int(version)))).encode("utf-8")).hexdigest()
    return f"tpx-{h[:40]}"


def _record_doc(rec: Record) -> Dict[str, Any]:
    return {"payload": rec.payload, "record_id": rec.record_id, "source": rec.source, "meta": rec.meta,
            "observed_at": rec.observed_at.isoformat() if rec.observed_at else None}


def lookup(doc: Any, path: str) -> Any:
    """The value at a `$.a.b.0.c` path, or _MISSING."""
    if path == "$":
        return doc
    if not path.startswith("$."):
        raise ValueError(f"a path starts with $.: {path!r}")
    cur = doc
    for part in path[2:].split("."):
        if isinstance(cur, Mapping):
            if part not in cur:
                return _MISSING
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            i = int(part)
            if i >= len(cur):
                return _MISSING
            cur = cur[i]
        else:
            return _MISSING
    return cur


# ── value nodes ──────────────────────────────────────────────────────────────────────────────────────────────

def _same(a: Any, b: Any) -> bool:
    """Equal with a bool kept apart from a number (False is not the number 0)."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _iso(text: str) -> _dt.datetime:
    """An ISO 8601 date or datetime (a Z for UTC, which Python 3.10's fromisoformat does not take)."""
    t = text.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    return _dt.datetime.fromisoformat(t)


def _utc_text(d: _dt.datetime) -> str:
    d = d.astimezone(_dt.timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S") + (f".{d.microsecond:06d}" if d.microsecond else "") + "Z"


def _zone(name: str) -> Any:
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


def _as(v: Any, node: Mapping[str, Any], where: str) -> Any:
    kind = node["as"]
    if v is None:
        return None
    if kind == "text":
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (Mapping, list)):
            return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return str(v)
    if kind == "int":
        if isinstance(v, bool):
            raise Refused(f"{where}: not a whole number")
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            if v.is_integer():
                return int(v)
            raise Refused(f"{where}: not a whole number")
        if isinstance(v, str) and _INT.match(v.strip()):
            return int(v.strip())
        raise Refused(f"{where}: not a whole number")
    if kind in ("decimal", "float"):
        if isinstance(v, bool) or not isinstance(v, (int, float, Decimal, str)):
            raise Refused(f"{where}: not a number")
        try:
            d = Decimal(str(v).strip() if isinstance(v, str) else str(v))
        except InvalidOperation:
            raise Refused(f"{where}: not a number") from None
        if not d.is_finite():
            raise Refused(f"{where}: not a number")
        return d if kind == "decimal" else float(d)
    if kind == "bool":
        if isinstance(v, bool):
            return v
        key = str(v).strip().lower() if isinstance(v, (str, int)) else None
        if key in _BOOLS:
            return _BOOLS[key]
        raise Refused(f"{where}: not a boolean")
    if kind in ("date", "datetime"):
        fmt = node.get("format")
        tz = node.get("tz")
        if not isinstance(v, str):
            raise Refused(f"{where}: not a {kind}" + (f" in the format {fmt}" if fmt else ""))
        try:
            d = _dt.datetime.strptime(v.strip(), fmt) if fmt else _iso(v)
        except (ValueError, TypeError):
            raise Refused(f"{where}: not a {kind} in the format {fmt}" if fmt else
                          f"{where}: not an ISO 8601 {kind}") from None
        if kind == "date":
            return d.date().isoformat()
        if d.tzinfo is None:
            if not tz:
                raise Refused(f"{where}: a datetime with no zone needs tz")
            d = d.replace(tzinfo=_zone(str(tz)))
        return _utc_text(d)
    if kind == "json":
        if isinstance(v, (Mapping, list)):
            return v
        try:
            return json.loads(v) if isinstance(v, (str, bytes)) else (_ for _ in ()).throw(ValueError())
        except (ValueError, TypeError):
            raise Refused(f"{where}: not JSON") from None
    raise Refused(f"{where}: as {kind!r} is not a type")        # unreachable after check_fields


def _round(v: Any, digits: int, where: str) -> Any:
    if v is None:
        return None
    if not _is_number(v):
        raise Refused(f"{where}: round needs a number")
    q = Decimal(1).scaleb(-int(digits))
    if isinstance(v, float):
        return float(Decimal(repr(v)).quantize(q, rounding=ROUND_HALF_EVEN))
    if isinstance(v, int):
        return v
    return Decimal(v).quantize(q, rounding=ROUND_HALF_EVEN)


def _steps(v: Any, node: Mapping[str, Any], where: str) -> Any:
    """null_if -> trim -> case -> regex+group -> map+map_default -> as -> round, on a value that was read."""
    if "null_if" in node:
        nulls = node["null_if"] if isinstance(node["null_if"], list) else [node["null_if"]]
        if any(_same(v, n) for n in nulls):
            return None
    if v is None:
        return None
    if node.get("trim") and isinstance(v, str):
        v = v.strip()
    if "case" in node:
        if not isinstance(v, str):
            raise Refused(f"{where}: case needs text")
        v = {"upper": v.upper, "lower": v.lower, "title": v.title}[node["case"]]()
    if "regex" in node:
        m = re.search(node["regex"], v if isinstance(v, str) else str(v))
        if m is None:
            if "default" in node:
                return node["default"]
            raise Refused(f"{where}: does not match the pattern")
        group = node.get("group", 1 if m.re.groups else 0)
        got = m.group(group)
        if got is None:
            if "default" in node:
                return node["default"]
            raise Refused(f"{where}: does not match the pattern")
        v = got
    if "map" in node:
        table = node["map"]
        if isinstance(v, (str, int, float)) and not isinstance(v, bool) and v in table:
            v = table[v]
        elif str(v) in table:
            v = table[str(v)]
        elif "map_default" in node:
            v = node["map_default"]
        else:
            raise Refused(f"{where}: no map entry and no map_default")
    if "as" in node:
        v = _as(v, node, where)
    if "round" in node:
        v = _round(v, node["round"], where)
    return str(v) if isinstance(v, Decimal) else v


def _value(node: Mapping[str, Any], doc: Any, where: str) -> Any:
    if "concat" in node:
        sep = str(node.get("sep") or "")
        parts: List[str] = []
        for i, part in enumerate(node["concat"]):
            at = f"{where}[{i}]"
            if isinstance(part, str) and part.startswith("$"):
                got = lookup(doc, part)
                if got is _MISSING:
                    raise Refused(f"the record has no {part} (the mapping's field {where})")
                part_value, optional = got, False
            elif is_value_node(part):
                part_value = _value(part, doc, at)
                optional = part.get("required") is False
            else:
                part_value, optional = part, False
            if part_value is None:
                if not optional:
                    raise Refused(f"{where}: a part of concat is null")
                parts.append("")
            else:
                parts.append(_as(part_value, {"as": "text"}, where))
        return _steps(sep.join(parts), node, where)
    v = lookup(doc, str(node["path"]))
    if v is _MISSING:
        if "default" in node:
            return node["default"]
        if node.get("required") is False:
            return None
        raise Refused(f"the record has no {node['path']} (the mapping's field {where})")
    return _steps(v, node, where)


# ── checking a mapping's fields when the spec is loaded ──────────────────────────────────────────────────────────

def check_fields(fields: Any, where: str = "") -> List[str]:
    """The problems of the value nodes in `fields`, each naming its field and the rule (an empty list when there are none).
    Anything that is not a value node is not looked at: a nested object, a path, a constant."""
    out: List[str] = []

    def at(path: str) -> str:
        return path or "(the mapping's fields)"

    def node_problems(node: Mapping[str, Any], path: str) -> None:
        if "path" in node and "concat" in node:
            out.append(f"{at(path)}: concat: a value node has a path or a concat, not both")
            return
        kind = node.get("as")
        if "as" in node and kind not in AS_TYPES:
            out.append(f"{at(path)}: as: {kind!r} is not one of {', '.join(AS_TYPES)}")
        if "case" in node and node["case"] not in CASES:
            out.append(f"{at(path)}: case: {node['case']!r} is not one of {', '.join(CASES)}")
        for flag in ("trim", "required"):
            if flag in node and not isinstance(node[flag], bool):
                out.append(f"{at(path)}: {flag}: true or false")
        if "regex" in node:
            try:
                rx = re.compile(node["regex"]) if isinstance(node["regex"], str) else None
                if rx is None:
                    out.append(f"{at(path)}: regex: a pattern (text)")
                elif "group" in node:
                    g = node["group"]
                    ok = (isinstance(g, int) and not isinstance(g, bool) and 0 <= g <= rx.groups) or \
                         (isinstance(g, str) and g in rx.groupindex)
                    if not ok:
                        out.append(f"{at(path)}: group: {g!r} is not a group of the regex")
            except re.error as e:
                out.append(f"{at(path)}: regex: not a valid pattern ({e})")
        elif "group" in node:
            out.append(f"{at(path)}: group: needs a regex")
        if "map" in node and not isinstance(node["map"], Mapping):
            out.append(f"{at(path)}: map: an object of from: to entries")
        if "map_default" in node and "map" not in node:
            out.append(f"{at(path)}: map_default: needs a map")
        if "format" in node:
            if kind not in ("date", "datetime"):
                out.append(f"{at(path)}: format: only for as: date or datetime")
            elif not isinstance(node["format"], str) or not node["format"]:
                out.append(f"{at(path)}: format: a strptime format (text)")
        if "tz" in node:
            if kind != "datetime":
                out.append(f"{at(path)}: tz: only for as: datetime")
            else:
                try:
                    _zone(str(node["tz"]))
                except Exception:  # noqa: BLE001 - ZoneInfoNotFoundError, ValueError, a platform without tz data
                    out.append(f"{at(path)}: tz: {node['tz']!r} is not a time zone name")
        if "round" in node:
            r = node["round"]
            if not isinstance(r, int) or isinstance(r, bool):
                out.append(f"{at(path)}: round: a whole number of digits")
            elif "as" in node and kind not in _NUMERIC_AS:
                out.append(f"{at(path)}: round: needs as: int, decimal or float (not {kind!r})")
        if "sep" in node and "concat" not in node:
            out.append(f"{at(path)}: sep: only with concat")
        if "concat" in node:
            parts = node["concat"]
            if not parts:
                out.append(f"{at(path)}: concat: a list with at least one part")
            for i, part in enumerate(parts):
                if is_value_node(part):
                    node_problems(part, f"{path}.concat[{i}]" if path else f"concat[{i}]")

    def walk(node: Any, path: str) -> None:
        if is_value_node(node):
            node_problems(node, path)
        elif isinstance(node, Mapping):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(fields, where)
    return out


def _map(node: Any, doc: Any, where: str) -> Any:
    if isinstance(node, str) and node.startswith("$"):
        v = lookup(doc, node)
        if v is _MISSING:
            raise Refused(f"the record has no {node} (the mapping's field {where})")
        return v
    if is_value_node(node):
        return _value(node, doc, where)
    if isinstance(node, Mapping):
        return {k: _map(v, doc, f"{where}.{k}" if where else str(k)) for k, v in node.items()}
    if isinstance(node, list):
        return [_map(v, doc, f"{where}[{i}]") for i, v in enumerate(node)]
    return node


def apply(fields: Mapping[str, Any], rec: Record) -> Dict[str, Any]:
    """What the action takes for this record (Refused when a field's path is not in it)."""
    return _map(dict(fields), _record_doc(rec), "")


def takes(when: Mapping[str, Any] | None, rec: Record) -> bool:
    """Whether the mapping takes this record."""
    if not when:
        return True
    v = lookup(_record_doc(rec), str(when.get("path", "$")))
    if "exists" in when:
        return (v is not _MISSING) == bool(when["exists"])
    if v is _MISSING:
        return False
    if "equals" in when:
        return v == when["equals"]
    if "in" in when:
        return v in (when["in"] or [])
    return True
