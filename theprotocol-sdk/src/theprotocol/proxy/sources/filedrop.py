"""The file drop source: a directory a legacy system writes files into.

V0659 (b). A record is one ROW of a dropped file (a CSV row, an element of a JSON array, a JSONL line, a child of an
XML root), so a 10,000-row export becomes 10,000 records with 10,000 stable ids rather than one blob.

Two properties the order asks for, and they are not the same property:

* **Stable ids.** The same file read again yields the same `record_id`, because the id is derived from the file's path
  and the row's position (or, with `id_field`, from the legacy system's own id inside the row). `check_source(twice=True)`
  pins this: it reads the input a second time with FRESH state and requires the same ids.
* **Resumption.** After a restart the source continues from its cursor: no row is sent twice and none is skipped. The
  cursor is the number of rows committed per file, kept in `ctx.state`. ⚠ `check_source` does NOT test this — its
  second pass uses a fresh context on purpose — so `tests/test_proxy_source_filedrop.py` tests it with a SHARED context.

A file is read only once it has settled (`settle_seconds`), because a drop is not atomic: a writer copying a 2 GB CSV
would otherwise be read mid-write and the tail of it lost, which no cursor can repair afterwards. A `.done`/marker
convention is supported instead with `require_marker`.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import time
import xml.etree.ElementTree as ET
from typing import Any, AsyncIterator, Dict, Iterable, List, Mapping, Tuple

from ..plugins import PluginError, Record, Source

_FORMATS = ("csv", "json", "jsonl", "xml")


def _rows_csv(text: str) -> List[Any]:
    return [dict(r) for r in csv.DictReader(io.StringIO(text))]


def _rows_json(text: str) -> List[Any]:
    doc = json.loads(text)
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):                       # one object, or {"items": [...]}-shaped
        for v in doc.values():
            if isinstance(v, list):
                return v
        return [doc]
    return [doc]


def _rows_jsonl(text: str) -> List[Any]:
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def _rows_xml(text: str) -> List[Any]:
    root = ET.fromstring(text)
    out: List[Any] = []
    for child in root:
        row: Dict[str, Any] = dict(child.attrib)
        for leaf in child:
            if len(leaf) == 0:
                row[leaf.tag] = (leaf.text or "").strip()
        if not row and (child.text or "").strip():
            row = {child.tag: (child.text or "").strip()}
        out.append(row)
    return out


_READERS = {"csv": _rows_csv, "json": _rows_json, "jsonl": _rows_jsonl, "xml": _rows_xml}


class FileDropSource(Source):
    """Rows from the files a legacy system drops in a directory."""

    name = "filedrop"
    description = "Rows from the files a legacy system drops in a directory (CSV, JSON, JSONL, XML)."
    config_schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["path"],
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "description": "The directory the legacy system writes into."},
            "format": {"enum": list(_FORMATS), "default": "csv",
                       "description": "How one file's rows are read: csv, json, jsonl or xml."},
            "suffix": {"type": "string", "default": "",
                       "description": "Only files ending in this are read (default: every file, the marker aside)."},
            "id_field": {"type": "string", "default": "",
                         "description": "A row field holding the legacy system's own id. Empty: the id is the file's "
                                        "path and the row's position, which is stable but local to this drop."},
            "settle_seconds": {"type": "number", "default": 2,
                               "description": "A file is read only once unmodified for this long: a drop is not "
                                              "atomic, and a file read mid-write loses its tail irrecoverably."},
            "require_marker": {"type": "string", "default": "",
                               "description": "If set (e.g. '.done'), a file is read only when its marker file "
                                              "exists beside it, and settle_seconds is not consulted."},
            "poll_seconds": {"type": "number", "minimum": 0, "default": 0,
                             "description": "How often the folder is listed again. 0 (the default, and what the source "
                                            "always did): list it once, read every settled file, then finish (tp-proxy "
                                            "run --once ends). A positive number keeps listing it every that many "
                                            "seconds: a file dropped later is read too, a row appended to a read file is "
                                            "read from where it stopped."},
        },
    }

    _STATE_KEY = "filedrop.rows_done"

    def __init__(self, config: Mapping[str, Any], ctx: Any) -> None:
        super().__init__(config, ctx)
        self._dir = str(config["path"])
        self._format = str(config.get("format") or "csv")
        if self._format not in _READERS:
            raise ValueError(f"filedrop: format {self._format!r} is not one of {', '.join(_FORMATS)}")
        self._suffix = str(config.get("suffix") or "")
        self._id_field = str(config.get("id_field") or "")
        self._settle = float(config.get("settle_seconds", 2))
        self._marker = str(config.get("require_marker") or "")
        poll = config.get("poll_seconds", 0)
        if isinstance(poll, bool) or not isinstance(poll, (int, float)) or poll < 0:
            raise PluginError(f"filedrop: poll_seconds {poll!r} is a number of at least 0 (0: one pass, then finish)")
        self._poll = float(poll)
        self._done: Dict[str, int] = {}

    async def start(self) -> None:
        self._done = dict(await self.ctx.state.get(self._STATE_KEY, {}) or {})

    def _ready(self, path: str) -> bool:
        """A file is ready when its marker is there, or when it has not changed for settle_seconds."""
        if self._marker:
            return os.path.exists(path + self._marker)
        if self._settle <= 0:
            return True
        try:
            return (time.time() - os.path.getmtime(path)) >= self._settle
        except OSError:
            return False

    def _files(self) -> List[Tuple[str, str]]:
        """(relative name, full path) for every ready file, in a stable order so ids and gaps are reproducible."""
        out: List[Tuple[str, str]] = []
        for rel in sorted(os.listdir(self._dir)):
            full = os.path.join(self._dir, rel)
            if not os.path.isfile(full):
                continue
            if self._marker and rel.endswith(self._marker):
                continue
            if self._suffix and not rel.endswith(self._suffix):
                continue
            if self._ready(full):
                out.append((rel, full))
        return out

    def _id(self, rel: str, index: int, row: Any) -> str:
        if self._id_field and isinstance(row, Mapping):
            got = row.get(self._id_field)
            if got not in (None, ""):
                return str(got)
        return f"{rel}#{index}"

    async def records(self) -> AsyncIterator[Record]:
        while True:
            async for rec in self._pass():
                yield rec
            if self._poll <= 0:
                return                                  # one pass, then the source finishes (as sources/sftp.py does)
            await asyncio.sleep(self._poll)

    async def _pass(self) -> AsyncIterator[Record]:
        for rel, full in self._files():
            done = int(self._done.get(rel, 0))
            try:
                with open(full, "r", encoding="utf-8") as fh:
                    rows: Iterable[Any] = _READERS[self._format](fh.read())
            except (OSError, ValueError, ET.ParseError) as exc:
                # A file that cannot be read is named and passed over: it must not stop the rows behind it, and it
                # must not advance a cursor it never produced.
                self.ctx.logger.warning(f"filedrop: {rel} could not be read ({type(exc).__name__}: {exc})")
                continue
            for index, row in enumerate(rows):
                if index < done:                        # already committed before the restart
                    continue
                yield Record(record_id=self._id(rel, index, row),
                             payload={"file": rel, "row": index, "data": row})

    async def rewind(self, point: str) -> None:
        """`point` is a file name, or `file#row`: that file is read again from that row (0 when none is given), and
        every file after it in the read order is read again whole. The read order is `sorted(listdir)`, so "after it"
        is a plain name comparison. Records already in the outbox are not sent twice: their keys are there."""
        name, _, row = str(point or "").partition("#")
        name = name.strip()
        if not name:
            raise PluginError("filedrop: a replay point is a file name, optionally file#row")
        try:
            at = int(row) if row.strip() else 0
        except ValueError:
            raise PluginError(f"filedrop: {point!r} is not a file name or file#row")
        if at < 0:
            raise PluginError(f"filedrop: {point!r} names a negative row")
        if name not in self._done and not os.path.isfile(os.path.join(self._dir, name)):
            raise PluginError(f"filedrop: no file {name!r} in this drop to read again from")
        self._done[name] = at
        for rel in [r for r in self._done if r > name]:
            self._done.pop(rel, None)
        await self.ctx.state.set(self._STATE_KEY, self._done)

    async def committed(self, record: Record) -> None:
        rel = str((record.payload or {}).get("file") or "")
        index = int((record.payload or {}).get("row", -1))
        if not rel or index < 0:
            return
        if index + 1 > int(self._done.get(rel, 0)):
            self._done[rel] = index + 1
            await self.ctx.state.set(self._STATE_KEY, self._done)
