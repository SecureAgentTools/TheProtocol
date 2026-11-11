"""The log tail source: a file a legacy system appends lines to.

V0659 (b). A record is one line, or one multi-line entry when `continuation` is set (a Java stack trace belongs to the
line that started it, not to itself). Optionally parsed by a regex with named groups, so a record carries fields rather
than a string.

The cursor is a BYTE OFFSET plus the file's identity, and the identity is what makes a tail honest across rotation:

* An offset alone is wrong the moment the file rotates. `app.log` becomes `app.log.1` and a new `app.log` starts at
  zero; an offset of 40,000 into the new file skips its first 40,000 bytes, which is a silent gap, and the operator
  sees only that some lines never arrived.
* So the cursor keeps the inode and the size as well. A file whose inode changed, or that is SHORTER than the cursor
  (truncate-in-place, `: > app.log`), is a NEW file and is read from its start.

A partial last line is not a record. A writer appending "2026-11-07 ERRO" is mid-line, and emitting it would produce a
record that never existed and whose id can never match the complete line. The tail stops at the last newline and the
remainder waits for the rest of itself.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional

from ..plugins import PluginError, Record, Source


class LogTailSource(Source):
    """Lines (or multi-line entries) appended to a log file."""

    kind = "source"
    name = "logtail"
    description = "Lines a legacy system appends to a log file, resumed by offset and file identity across rotation."
    config_schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["path"],
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "description": "The log file to tail."},
            "pattern": {"type": "string", "default": "",
                        "description": "A regex with named groups: a record's payload becomes those fields. Empty: "
                                       "the payload is {\"line\": ...}."},
            "continuation": {"type": "string", "default": "",
                             "description": "A regex matching a CONTINUATION line (an indented stack-trace frame). "
                                            "Such a line joins the entry above it instead of starting a record."},
            "skip_unmatched": {"type": "boolean", "default": False,
                               "description": "With a pattern, drop lines it does not match instead of carrying them "
                                              "as {\"line\": ...}. Off by default: a dropped line is invisible."},
            "from_start": {"type": "boolean", "default": True,
                           "description": "With no cursor yet, read the file from its start (default) or skip what is "
                                          "already there and take only what arrives next."},
        },
    }

    _STATE_KEY = "logtail.cursor"

    def __init__(self, config: Mapping[str, Any], ctx: Any) -> None:
        super().__init__(config, ctx)
        self._path = str(config["path"])
        self._from_start = bool(config.get("from_start", True))
        self._skip_unmatched = bool(config.get("skip_unmatched", False))
        try:
            self._pattern = re.compile(str(config.get("pattern") or "")) if config.get("pattern") else None
            self._cont = re.compile(str(config.get("continuation") or "")) if config.get("continuation") else None
        except re.error as exc:
            raise PluginError(f"logtail: {exc}") from None
        if self._pattern is not None and not self._pattern.groupindex:
            raise PluginError("logtail: pattern needs named groups, e.g. (?P<level>\\w+), or no pattern at all")
        self._cursor: Dict[str, Any] = {}

    async def start(self) -> None:
        self._cursor = dict(await self.ctx.state.get(self._STATE_KEY, {}) or {})

    def _identity(self) -> Optional[Dict[str, Any]]:
        try:
            st = os.stat(self._path)
        except OSError:
            return None
        return {"inode": st.st_ino, "size": st.st_size}

    def _offset_for(self, ident: Dict[str, Any]) -> int:
        """Where to start: the cursor's offset, or 0 when this is a different or truncated file."""
        if self._cursor.get("inode") != ident["inode"]:
            return 0                                        # rotated: a new file, read from its start
        at = int(self._cursor.get("offset", 0))
        if ident["size"] < at:
            return 0                                        # truncated in place: also a new file
        return at

    def _entries(self, text: str, base: int) -> List[Dict[str, Any]]:
        """(offset, lines) per entry, stopping at the last newline: a partial last line is not a record."""
        out: List[Dict[str, Any]] = []
        at = base
        for raw in text.splitlines(keepends=True):
            if not raw.endswith("\n"):
                break                                       # the writer is mid-line; it waits for the rest of itself
            line = raw[:-1]
            if self._cont is not None and out and self._cont.match(line):
                out[-1]["lines"].append(line)
                out[-1]["bytes"] += len(raw.encode("utf-8"))
            else:
                out.append({"offset": at, "lines": [line], "bytes": len(raw.encode("utf-8"))})
            at += len(raw.encode("utf-8"))
        return out

    def _payload(self, entry_text: str) -> Optional[Dict[str, Any]]:
        if self._pattern is None:
            return {"line": entry_text}
        m = self._pattern.search(entry_text)
        if m is None:
            return None if self._skip_unmatched else {"line": entry_text}
        # The fields, over the raw text: a parsed record still carries the line it was parsed from, so a consumer that
        # finds a field empty can see what it was read out of. A pattern whose own group is named `line` wins — the
        # author asked for that name.
        return {"line": entry_text, **m.groupdict()}

    async def records(self) -> AsyncIterator[Record]:
        ident = self._identity()
        if ident is None:
            self.ctx.logger.warning(f"logtail: {self._path} is not there yet")
            return
        start = self._offset_for(ident)
        if start == 0 and not self._from_start and not self._cursor:
            # asked to take only what arrives next, and nothing has been read yet
            self._cursor = {"inode": ident["inode"], "offset": ident["size"]}
            await self.ctx.state.set(self._STATE_KEY, self._cursor)
            return
        try:
            with open(self._path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(start)
                text = fh.read()
        except OSError as exc:
            self.ctx.logger.warning(f"logtail: {self._path} could not be read ({type(exc).__name__}: {exc})")
            return
        for entry in self._entries(text, start):
            body = "\n".join(entry["lines"])
            payload = self._payload(body)
            if payload is None:
                continue                                    # unmatched and dropped on purpose; the cursor still moves
            yield Record(
                record_id=f"{ident['inode']}:{entry['offset']}:{hashlib.sha256(body.encode()).hexdigest()[:12]}",
                payload={**payload, "_offset": entry["offset"], "_inode": ident["inode"],
                         "_next": entry["offset"] + entry["bytes"]})

    async def committed(self, record: Record) -> None:
        p = record.payload or {}
        inode, nxt = p.get("_inode"), p.get("_next")
        if inode is None or nxt is None:
            return
        if self._cursor.get("inode") != inode or int(nxt) > int(self._cursor.get("offset", 0)):
            self._cursor = {"inode": inode, "offset": int(nxt)}
            await self.ctx.state.set(self._STATE_KEY, self._cursor)

    async def rewind(self, point: str) -> None:
        """`point` is a byte offset, or "start". The file's current identity is kept, so a rewind after a rotation
        reads the CURRENT file from that offset and not the rotated one."""
        ident = self._identity()
        if ident is None:
            raise PluginError(f"logtail: {self._path} is not there to read again")
        text = str(point or "").strip().lower()
        if text in ("start", "0", ""):
            at = 0
        else:
            try:
                at = int(text)
            except ValueError:
                raise PluginError(f"logtail: {point!r} is not a byte offset or 'start'") from None
        if at < 0 or at > ident["size"]:
            raise PluginError(f"logtail: offset {at} is outside {self._path} (size {ident['size']})")
        self._cursor = {"inode": ident["inode"], "offset": at}
        await self.ctx.state.set(self._STATE_KEY, self._cursor)
