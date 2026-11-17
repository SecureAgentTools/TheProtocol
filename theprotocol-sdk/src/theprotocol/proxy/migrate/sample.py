"""migrate_sample: the source `tp-proxy migrate dry-run --sample` (and `plan --sample`) puts in place of each of a kit's
sources. Used by --sample only.

It reads the kit's sample file once and yields the records the REPLACED source would yield over the same rows: the same
payload shape, the same record id and the same meta, each built by an instance of the replaced source's own class (its
own id function, never a copy of it), then finishes. So a mapping written against `$.payload.data.email` (a file
source) or `$.payload.email` (a table) reads the sample exactly as it will read the real system.

config: {file: <path of the sample>, format: csv | json | jsonl | xml, stands_in_for: sqlpoll | filedrop | sftp |
webhook, config: <the replaced source's own config>}

The sample of a SQL source is JSONL: one row per line, the values as sqlpoll gives them (int, bool and null as JSON;
decimals, dates and times as strings). A file source's sample is in the file's own format.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any, AsyncIterator, List, Mapping

from ..plugins import PluginError, Record, Source

STANDS_IN_FOR = ("sqlpoll", "filedrop", "sftp", "webhook")


def read_rows(path: str, fmt: str) -> List[Any]:
    from ..sources.filedrop import _READERS
    if fmt not in _READERS:
        raise PluginError(f"migrate_sample: format {fmt!r} is not one of {', '.join(_READERS)}")
    with open(path, "r", encoding="utf-8") as fh:
        return _READERS[fmt](fh.read())


class MigrateSampleSource(Source):
    name = "migrate_sample"
    description = ("Used by tp-proxy migrate --sample only: a kit's sample file read once, as the source it stands in "
                   "for would read the same rows (its record ids, payload and meta), then finished.")
    config_schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["file", "stands_in_for", "config"],
        "additionalProperties": False,
        "properties": {
            "file": {"type": "string", "description": "The sample file."},
            "format": {"enum": ["csv", "json", "jsonl", "xml"],
                       "description": "How it is read (default: jsonl for sqlpoll and webhook, else the replaced "
                                      "source's format, else csv)."},
            "stands_in_for": {"enum": list(STANDS_IN_FOR)},
            "config": {"type": "object", "description": "The replaced source's own config."},
            "limit": {"type": "integer", "minimum": 1, "description": "At most this many records."},
        },
    }

    def __init__(self, config: Mapping[str, Any], ctx: Any) -> None:
        super().__init__(config, ctx)
        kind = str(self.config.get("stands_in_for") or "")
        if kind not in STANDS_IN_FOR:
            raise PluginError(f"migrate_sample: stands_in_for {kind!r} is not one of {', '.join(STANDS_IN_FOR)}")
        self._kind = kind
        self._file = str(self.config["file"])
        inner = dict(self.config.get("config") or {})
        from ..plugins import load
        cls = load("source", kind)
        self._inner = cls(inner, ctx)          # never started: only its id function and its names are used
        default = "jsonl" if kind in ("sqlpoll", "webhook") else str(inner.get("format") or "csv")
        self._format = str(self.config.get("format") or default)
        self._limit = self.config.get("limit")

    def _records(self) -> List[Record]:
        rows = read_rows(self._file, self._format)
        return getattr(self, f"_{self._kind}")(rows)

    # ── one per replaced source, each through that source's own functions ─────────────────────────────────────────

    def _sqlpoll(self, rows: List[Any]) -> List[Record]:
        from ..sources.sqlpoll import _json
        s = self._inner
        cols = s.config.get("columns")
        out = []
        for i, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise PluginError(f"migrate_sample: line {i + 1} of {os.path.basename(self._file)} is not an object "
                                  f"(a SQL source's sample is one JSON object per line)")
            for c in [s._cursor, *s._keys]:
                if c not in row:
                    raise PluginError(f"migrate_sample: line {i + 1} of {os.path.basename(self._file)} has no "
                                      f"{c} (the source's cursor or key)")
            payload = {str(c): _json(row.get(c)) for c in cols} if cols else {str(k): _json(v) for k, v in row.items()}
            cursor = s._cursor_value(row[s._cursor])
            keys = [cursor if k == s._cursor else s._key_value(row[k], k) for k in s._keys]
            out.append(((cursor, keys), Record(record_id=s._record_id(cursor, keys), payload=payload,
                                               meta={"table": s._sql.table, "cursor": cursor, "key": keys})))
        out.sort(key=lambda t: _order(t[0]))      # the source reads in (cursor, key) order
        return [r for _, r in out]

    def _filedrop(self, rows: List[Any]) -> List[Record]:
        rel = os.path.basename(self._file)
        return [Record(record_id=self._inner._id(rel, i, row), payload={"file": rel, "row": i, "data": row})
                for i, row in enumerate(rows)]

    def _sftp(self, rows: List[Any]) -> List[Record]:
        name = os.path.basename(self._file)
        with open(self._file, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        s = self._inner
        return [s._record(name, digest[:16], digest, i, row, s._path(name)) for i, row in enumerate(rows)]

    def _webhook(self, rows: List[Any]) -> List[Record]:
        out = []
        for i, item in enumerate(rows):
            if not isinstance(item, dict):
                raise PluginError(f"migrate_sample: item {i} is not a JSON object")
            rid = self._inner._record_id(item)
            if rid is None:
                raise PluginError(f"migrate_sample: item {i} has no {self._inner.config.get('id_field') or 'id'}")
            out.append(Record(record_id=rid, payload=item, meta={"via": "webhook", "path": self._inner.config["path"]}))
        return out

    async def records(self) -> AsyncIterator[Record]:
        for n, rec in enumerate(self._records()):
            if self._limit is not None and n >= int(self._limit):
                return
            yield rec


def _order(t: Any) -> Any:
    cursor, keys = t
    return (_k(cursor), [_k(k) for k in keys])


def _k(v: Any) -> Any:
    # ints before texts, each in its own order (a table orders one type per column; this only keeps sort() total)
    return (0, v, "") if isinstance(v, int) and not isinstance(v, bool) else (1, 0, str(v))
