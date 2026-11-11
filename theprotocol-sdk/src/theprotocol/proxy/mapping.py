"""A mapping turns one Record into what an action takes, and its version is part of the exactly-once key.

    fields:
      container: $.payload.container_id         # a path into the record
      at: {path: $.payload.ts, default: null}    # a path with a default when the record has no such field
      terminal: HAM-CTA                          # anything else is a constant
      lines: [$.payload.a, $.payload.b]          # lists and objects are mapped inside
    when: {path: $.payload.status, equals: OUT}  # the record is taken only when it holds (also: in, exists)

A path starts at the record: `$.payload...`, `$.record_id`, `$.source`, `$.meta...`, `$.observed_at`. A field whose path
the record does not have, and that names no default, refuses the record (to the dead letters, with the path), so a
legacy system that changes its export is seen at once rather than sent half-empty.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Mapping

from .plugins import Record, Refused

_MISSING = object()


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


def _map(node: Any, doc: Any, where: str) -> Any:
    if isinstance(node, str) and node.startswith("$"):
        v = lookup(doc, node)
        if v is _MISSING:
            raise Refused(f"the record has no {node} (the mapping's field {where})")
        return v
    if isinstance(node, Mapping) and "path" in node and set(node) <= {"path", "default"}:
        v = lookup(doc, str(node["path"]))
        if v is _MISSING:
            if "default" in node:
                return node["default"]
            raise Refused(f"the record has no {node['path']} (the mapping's field {where})")
        return v
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
