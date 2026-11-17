"""The `file_out` writer: each mapped record is a line of a CSV or JSONL file in a folder, for a system that loads files.

    sinks:
      export:
        type: file_out
        config:
          path: /data/export            # the folder
          format: csv                   # csv (columns required: their order) or jsonl
          columns: [id, name, email]
          file: "customers-{n:05d}.csv" # default data-{n:05d}.csv or .jsonl
          rows_per_file: 100000
          sftp: {host: files.example.org, user: tp, key: env:SFTP_KEY, path: /incoming, known_hosts: /config/known_hosts}

Rows go to a `.part` file. A file is CLOSED on rotation (rows_per_file) and on stop: the part is fsynced and RENAMED, so a
closed file is whole or absent, and the folder's manifest.json is rewritten atomically: {"files": [{"name", "rows",
"sha256"}], "rows": n}. A closed file is then uploaded over SFTP when configured; an upload that fails is tried again at the
next closing and at the next start (the file is kept here either way). A csv file begins with its header line.

Exactly once. The proxy's state keeps, per key, the byte offset after its line, and where the open file stands (its number,
rows and offset). A key seen again writes nothing. At start the open part is cut back to the recorded offset: a crash
between a write and its state leaves at most the stray lines after it, which are cut, and the record is delivered again by
the outbox and written once. A crash between the rename and the state is repaired at start from the closed file itself.

A csv row has the configured columns in order: a field that is not a column refuses the record (naming the field, never its
value), a missing one is an empty cell; a dict or a list is written as compact JSON text. A dry run writes nothing, not even
the folder. Values are written as they are: this is a writer for a migration, not a sanitiser (a cell that starts with = or @
is a spreadsheet's to read, not this file's to change; the load is the next system's).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..plugins import Event, Outcome, PluginError, Refused, Retry, Sink
from ._json import dumps as _dumps

FORMATS = ("csv", "jsonl")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .$-]{0,127}$")
_PART = ".part"


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return _dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return str(v)                                   # a Decimal's str is its exact digits


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_json(path: Path, doc: Any) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class FileOutSink(Sink):
    name = "file_out"
    description = "Write each mapped record as a line of a CSV or JSONL file in a folder, with a manifest and an optional SFTP upload"
    config_schema = {
        "type": "object",
        "required": ["path"],
        "additionalProperties": False,
        "properties": {
            "path": {"type": "string", "minLength": 1, "description": "The folder."},
            "format": {"enum": list(FORMATS), "default": "csv"},
            "columns": {"type": "array", "items": {"type": "string"}, "minItems": 1, "uniqueItems": True,
                        "description": "csv: the columns, in order (required)."},
            "file": {"type": "string", "description": "A file name with {n}, e.g. data-{n:05d}.csv."},
            "rows_per_file": {"type": "integer", "minimum": 1, "default": 100000},
            "sftp": {
                "type": "object", "required": ["host", "user", "path"], "additionalProperties": False,
                "properties": {
                    "host": {"type": "string"}, "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                    "user": {"type": "string"}, "path": {"type": "string"},
                    "key": {"type": "string", "x-secret": True},
                    "password": {"type": "string", "x-secret": True},
                    "known_hosts": {"type": "string",
                                    "description": "The file that knows the server's host key; an unknown key is refused."},
                },
            },
        },
    }

    def __init__(self, config: Mapping[str, Any], ctx: Any) -> None:
        super().__init__(config, ctx)
        cfg = self.config
        self.dir = Path(str(cfg["path"]))
        self.format = str(cfg.get("format") or "csv")
        if self.format not in FORMATS:
            raise PluginError(f"file_out: format {self.format!r} is not one of {', '.join(FORMATS)}")
        cols = cfg.get("columns")
        if cols is not None:
            if not isinstance(cols, (list, tuple)) or not cols or not all(isinstance(c, str) and _COLUMN.match(c) for c in cols) \
                    or len(set(cols)) != len(cols):
                raise PluginError("file_out: columns is a list of distinct column names")
        if self.format == "csv" and not cols:
            raise PluginError("file_out: a csv file needs its columns (their order is the file's)")
        self.columns: Optional[List[str]] = list(cols) if cols else None
        ext = "csv" if self.format == "csv" else "jsonl"
        self.pattern = str(cfg.get("file") or f"data-{{n:05d}}.{ext}")
        try:
            sample = self.pattern.format(n=1)
        except (KeyError, IndexError, ValueError):
            raise PluginError("file_out: file is a name with {n} in it, e.g. data-{n:05d}.csv") from None
        if not _NAME.match(sample) or sample.endswith(_PART) or self.pattern.format(n=1) == self.pattern.format(n=2):
            raise PluginError("file_out: file must be a plain file name that changes with {n} (letters, digits . _ -)")
        self.rows_per_file = int(cfg.get("rows_per_file") or 100000)
        if self.rows_per_file < 1:
            raise PluginError("file_out: rows_per_file is at least 1")
        self._cur: Dict[str, Any] = {"n": 1, "rows": 0, "offset": 0}
        self._closed: List[Dict[str, Any]] = []
        self._ready = False

    # ── names ─────────────────────────────────────────────────────────────────────────────────────────────────

    def _name(self, n: int) -> str:
        return self.pattern.format(n=n)

    def _final(self, n: int) -> Path:
        return self.dir / self._name(n)

    def _part(self, n: int) -> Path:
        return self.dir / (self._name(n) + _PART)

    # ── the life of the sink ──────────────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self.ctx.dry_run or self._ready:
            return
        self._ready = True
        self.dir.mkdir(parents=True, exist_ok=True)
        if self.config.get("sftp"):
            self._paramiko()                          # a missing driver is said now, not at the first closing
        self._cur = dict(await self.ctx.state.get("cur") or self._cur)
        self._closed = list(await self.ctx.state.get("closed") or [])
        n, rows, offset = int(self._cur["n"]), int(self._cur["rows"]), int(self._cur["offset"])
        part, final = self._part(n), self._final(n)
        if not part.exists() and rows > 0 and final.exists():
            await self._adopt(n, rows)                # the rename happened, the state did not hear of it
        elif part.exists():
            size = part.stat().st_size
            if size < offset:
                raise PluginError(f"file_out: {part.name} holds {size} bytes and the state says {offset}: the open file was "
                                  f"changed outside the proxy; keep it and start a new folder")
            if size > offset:
                with open(part, "r+b") as f:
                    f.truncate(offset)                # the stray lines after the last recorded key
        elif rows > 0:
            raise PluginError(f"file_out: the open file {part.name} is missing and the state says it holds {rows} rows")
        await self._upload_pending()

    async def stop(self) -> None:
        if self.ctx.dry_run or not self._ready:
            return
        if int(self._cur["rows"]) > 0 and self._part(int(self._cur["n"])).exists():
            await self._close()
        await self._upload_pending(quiet=True)

    # ── a record ──────────────────────────────────────────────────────────────────────────────────────────────

    def _line(self, data: Mapping[str, Any], first: bool) -> bytes:
        if self.format == "jsonl":
            return (_dumps(dict(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        assert self.columns is not None
        extra = sorted(set(data) - set(self.columns))
        if extra:
            raise Refused(f"file_out: the record carries {', '.join(extra)}, which is not among the columns")
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        if first:
            w.writerow(self.columns)
        w.writerow([_cell(data.get(c)) for c in self.columns])
        return buf.getvalue().encode("utf-8")

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        data = dict(event.data)
        cols = self.columns if self.format == "csv" else sorted(data)
        n = int(self._cur["n"])
        if dry_run:
            self._line(data, True)                    # the same checks as a real write
            return Outcome.dry(f"would write a line to {self._name(n)} in {self.dir}", file=self._name(n),
                               format=self.format, columns=list(cols or []))
        if await self.ctx.state.get(f"off:{key}") is not None:
            return Outcome.done(self._name(n), "already written")
        await self.start()                            # a sink used without start() (a contract test) opens on first use
        n = int(self._cur["n"])
        first = int(self._cur["rows"]) == 0
        line = self._line(data, first)
        part = self._part(n)
        with open(part, "ab") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
            offset = f.tell()
        self._cur = {"n": n, "rows": int(self._cur["rows"]) + 1, "offset": offset}
        await self.ctx.state.set(f"off:{key}", offset)
        await self.ctx.state.set("cur", self._cur)
        done = self._name(n)
        if self._cur["rows"] >= self.rows_per_file:
            await self._close()
            await self._upload_pending(quiet=True)
        return Outcome.done(done, f"written to {done}")

    # ── closing ───────────────────────────────────────────────────────────────────────────────────────────────

    async def _close(self) -> None:
        n, rows = int(self._cur["n"]), int(self._cur["rows"])
        part, final = self._part(n), self._final(n)
        with open(part, "rb+") as f:
            f.flush()
            os.fsync(f.fileno())
        os.replace(part, final)
        await self._adopt(n, rows)

    async def _adopt(self, n: int, rows: int) -> None:
        final = self._final(n)
        self._closed = [c for c in self._closed if c["name"] != final.name] + [
            {"name": final.name, "rows": rows, "sha256": _sha(final)}]
        self._cur = {"n": n + 1, "rows": 0, "offset": 0}
        await self.ctx.state.set("closed", self._closed)
        await self.ctx.state.set("cur", self._cur)
        _atomic_json(self.dir / "manifest.json", {"files": self._closed, "rows": sum(int(c["rows"]) for c in self._closed)})

    # ── the upload ────────────────────────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _paramiko() -> Any:
        try:
            import paramiko
        except ImportError:
            raise PluginError("file_out's sftp upload needs paramiko (pip install 'theprotocol-sdk[proxy-sftp]')") from None
        return paramiko

    async def _upload_pending(self, quiet: bool = False) -> None:
        cfg = self.config.get("sftp")
        if not cfg or self.ctx.dry_run:
            return
        done = set(await self.ctx.state.get("uploaded") or [])
        todo = [c["name"] for c in self._closed if c["name"] not in done]
        if not todo:
            return
        try:
            self._put(cfg, todo)
        except PluginError:
            raise
        except Exception as e:  # noqa: BLE001 - the files are kept here; the next closing tries again
            if quiet:
                self.ctx.logger.warning("file_out: the sftp upload of %s failed (%s); it is tried again at the next closing",
                                        ", ".join(todo), type(e).__name__)
                return
            raise Retry(f"file_out: the sftp upload failed: {type(e).__name__}") from None
        await self.ctx.state.set("uploaded", sorted(done | set(todo)))

    def _put(self, cfg: Mapping[str, Any], names: List[str]) -> None:
        paramiko = self._paramiko()
        client = paramiko.SSHClient()
        if cfg.get("known_hosts"):
            client.load_host_keys(str(cfg["known_hosts"]))
        else:
            client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())     # an unknown host key is refused, never added blind
        kw: Dict[str, Any] = {"hostname": cfg["host"], "port": int(cfg.get("port") or 22), "username": cfg["user"]}
        if cfg.get("key"):
            text = self.ctx.secret(cfg["key"])
            for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
                try:
                    kw["pkey"] = cls.from_private_key(io.StringIO(text))
                    break
                except Exception:  # noqa: BLE001 - the next key type
                    continue
            else:
                raise PluginError("file_out: the sftp key is not a private key paramiko reads (Ed25519, ECDSA, RSA)")
        if cfg.get("password"):
            kw["password"] = self.ctx.secret(cfg["password"])
        client.connect(**kw)
        try:
            sftp = client.open_sftp()
            remote = str(cfg["path"]).rstrip("/")
            for name in names:
                sftp.put(str(self.dir / name), f"{remote}/{name}")
        finally:
            client.close()
