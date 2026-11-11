"""The SFTP poll source: the export files a legacy system leaves on an SFTP server, read row by row.

V0659 (l).

    sources:
      orders:
        type: sftp
        config:
          host: sftp.erp.example
          username: proxy
          private_key: file:/run/secrets/sftp_key      # key-based login only; a reference, never the key itself
          known_hosts: /config/known_hosts             # the server's host key: an unknown or a changed key is refused
          path: /outbox/orders
          format: csv                                  # csv, json, jsonl or xml
          after_read: move                             # move (into move_to), mark (rename with mark_suffix) or leave
          move_to: done

A record is one ROW of a file, read as the file drop reads it (a CSV row, an element of a JSON array, a JSONL line, a
child of an XML root), so a 10,000-row export is 10,000 records with 10,000 ids.

**Ids that survive a name used again.** A row's id is `<file>@<instance>#<row>`: the instance is the first 16 hex
digits of the SHA-256 of the file's bytes as first read (with `id_field`, the id is the legacy system's own). The same
file read again (after a crash before its move, or by a replay) has the same ids, so the core keeps its rows once. A NEW
file under a name the system uses again (`orders.csv` every hour, which is why files are moved once read) has new ids,
so its rows are not taken for the last file's. The same bytes uploaded twice (an upload retried after a timeout) have
the same ids again, and are kept once.

**Moved or marked once read, and never before.** A file is moved into `move_to` (or renamed in place with
`mark_suffix`) only once every one of its rows is in the proxy's outbox, and never in a dry run. A name already taken
in the archive gets the instance as a tag (`done/orders.csv~3f2a9c1b04de0a11`), and the same bytes again a counter
after it (`~2`, `~3`, ...: a header-only export every quiet hour), found in a few looks however long the archive is:
the server's rename never replaces a name, and nothing archived is overwritten. A file that grew after it was first
read always carries its instance in its archive name, so a replay reads it under the ids it had. `move_to` may name
folders that do not exist yet. `leave` changes nothing on the server (a read-only account) and remembers each file's
digest instead.

**Resumption.** The cursor is the number of committed rows per file, with the file's digest, size and time, in
ctx.state. A restart mid-file continues at the file's next row. A file that grew after it was read (a writer the settle
wait did not catch) continues with its new rows under the same ids. A file replaced by other bytes is read as the new
file it is, and the rows of the old one that were never read are named in the log.

**A file still being written is not read.** An upload is not atomic, and a file read mid-write and then moved loses its
tail into the archive, which no cursor can repair. So a file is read only once its size and time have stayed the same
for `settle_seconds` on the proxy's own clock (the server's clock is not trusted), or, with `require_marker`, once its
marker file is there (the marker then travels with it, and a marker that cannot move keeps its file in place too).
Temporary names (`.part`, `.filepart`, `.tmp`, `.partial`, hidden files) are never read; a file that changes while it
is downloaded waits again; and a file is looked at once more just before its move. The safest writer uploads under a
temporary name and renames, or writes a marker last.

**A refusal is one file's problem.** A file the server will not let be read (written by another account without read
rights for this one, or still held by its writer on a Windows server, which answers a plain failure) is named in the
log once and passed over, and the files behind it are read; every later look tries it again, because a lock lifts
without the file's size or time changing. A replay of a refused file waits in the cursor the same way.

**The server is checked before anything is read.** Key-based login only: the key and nothing else (no password, no
agent, no other key), and an account that takes the key only as a first step and then asks for a password or a code
is refused, because the proxy runs unattended and never answers a prompt. The server's host key must be in
`known_hosts`: a server missing from it, or presenting another key, is refused, naming the key's fingerprint so it can
be checked with the system's operator; a key a `@revoked` line names is never accepted, and a `@cert-authority` line
trusts nothing here (this source checks host keys, not host certificates). A host key is never accepted blind.

XML is read through defusedxml (an entity declaration or an external reference is refused, never expanded), not by the
standard library's parser alone, because the file comes from another system. A CSV row with more fields than its
header (a delimiter at a line's end, a comma left unquoted in free text) keeps the extra ones as a list under `_extra`.

Needs `pip install "theprotocol-sdk[proxy-sftp]"` (paramiko, defusedxml). paramiko's calls block, and hashing and
parsing a large file take time, so each runs in a worker thread, and the proxy's other sources, its dispatcher and its
/health keep running meanwhile.
"""
from __future__ import annotations

import asyncio
import base64
import codecs
import csv
import hashlib
import importlib
import io
import os
import posixpath
import re
import stat as _stat
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, ClassVar, Dict, List, Mapping, Optional, Set, Tuple

from ..plugins import PluginError, Record, Source
from ..spec import is_ref
from .filedrop import _rows_json, _rows_jsonl

EXTRA = 'pip install "theprotocol-sdk[proxy-sftp]"'
FORMATS = ("csv", "json", "jsonl", "xml")
AFTER_READ = ("move", "mark", "leave")
TEMPORARY_SUFFIXES = (".tmp", ".part", ".partial", ".filepart")
EXTRA_FIELDS = "_extra"           # where a CSV row keeps the fields beyond its header
_TAG = re.compile(r"~([0-9a-f]{16})(?:~\d+)?$")
_ROW = re.compile(r"^\s*-?\d*\s*$")
_LOST = (ConnectionError, TimeoutError, EOFError)
_MAX_COPIES = 1 << 30             # how far the archive's counter search goes before it gives up


@dataclass(frozen=True)
class RemoteFile:
    """What the server says about one directory entry: its name, its size, its modification time in whole seconds (as
    SFTP v3 reports it) and whether it is a regular file."""
    name: str
    size: int
    mtime: int
    is_file: bool = True


class RemoteError(OSError):
    """The server refused an operation on a connection that is still up (an SFTP status other than "no such file" or
    "permission denied")."""


class _Unreadable(Exception):
    """A file whose rows cannot be read: not its format, not its encoding, or an XML entity refused."""


class _Refused(Exception):
    """The server would not let a file be read (permission denied, or a plain failure on a live connection, which is
    how a Windows server answers for a file its writer still holds). It is tried again on the next look."""


# ── reading a file's rows ────────────────────────────────────────────────────────────────────────────────────────────

def _rows_csv(text: str, delimiter: str) -> List[Any]:
    """The rows under the header. The fields beyond the header (a delimiter at a line's end, a comma left unquoted in
    free text) are kept as a list under `_extra`, so every key is a string: the core keeps a record as JSON with its
    keys sorted, which the csv module's default key for them (None) would stop."""
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter, restkey=EXTRA_FIELDS)
    return [dict(r) for r in reader]


def _digest(data: bytes, upto: Optional[int] = None) -> str:
    """The SHA-256 of the bytes (of the first `upto` of them), in hex."""
    return hashlib.sha256(data if upto is None else memoryview(data)[:upto]).hexdigest()


def _rows_xml(text: str) -> List[Any]:
    """The children of the root, as the file drop reads them (attributes and leaf texts), parsed by defusedxml."""
    from defusedxml import ElementTree as SafeET
    root = SafeET.fromstring(text)
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


def _fingerprint(key: Any) -> str:
    """A host key's fingerprint as `ssh-keygen -l` prints it (SHA256:...)."""
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def _norm(path: str) -> str:
    return posixpath.normpath(path) if path else path


# ── the transport: paramiko ──────────────────────────────────────────────────────────────────────────────────────────

class _Paramiko:
    """The SFTP calls the source makes, over paramiko. Every method blocks; the source runs each in a worker thread.

    A refusal the server gives on a live connection is FileNotFoundError, PermissionError, FileExistsError (a rename to
    a name that exists) or RemoteError; a connection that is gone is ConnectionError, which the source answers by
    connecting again."""

    def __init__(self, paramiko: Any, client: Any, sftp: Any) -> None:
        self._p, self._client, self._sftp = paramiko, client, sftp

    @staticmethod
    def _paramiko() -> Any:
        try:
            import paramiko
        except ImportError:
            raise PluginError(f"sftp: this source needs paramiko ({EXTRA})") from None
        return paramiko

    @classmethod
    def check(cls, src: "SftpSource") -> None:
        """What can be checked before a connection: the login key reads, and known_hosts holds the server's key."""
        paramiko = cls._paramiko()
        cls._key(paramiko, src)
        cls._known(paramiko, src, paramiko.HostKeys())

    @staticmethod
    def _key(paramiko: Any, src: "SftpSource") -> Any:
        text = src.ctx.secret(src.config["private_key"])
        if not text.endswith("\n"):
            text += "\n"
        phrase = src.ctx.secret(src.config["passphrase"]) if src.config.get("passphrase") else None
        for kind in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
            try:
                return kind.from_private_key(io.StringIO(text), password=phrase)
            except paramiko.PasswordRequiredException:
                raise PluginError("sftp: the login key is encrypted: name its passphrase (a reference)") from None
            except (paramiko.SSHException, ValueError, TypeError):
                continue
        raise PluginError("sftp: private_key is not a login key this source reads (OpenSSH or PEM: Ed25519, ECDSA or "
                          "RSA), or its passphrase is wrong")

    @staticmethod
    def _known(paramiko: Any, src: "SftpSource", into: Any) -> Set[bytes]:
        """Load known_hosts into `into` (a paramiko HostKeys) and answer the keys it marks @revoked.

        A key a @revoked line names is never accepted, even where another line lists it plainly (OpenSSH's rule). This
        source applies it whatever host the line names, because paramiko matches no host patterns (`@revoked *` is how
        a key is revoked everywhere). A @cert-authority line is passed over: this source checks host keys, not host
        certificates, so such a line trusts nothing here."""
        where = src.known_hosts
        if is_ref(where):
            text = src.ctx.secret(where)
        else:
            try:
                with open(where, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except OSError as e:
                raise PluginError(f"sftp: the known_hosts file {where} cannot be read ({e.strerror or e})") from None
        plain: List[Any] = []
        revoked: Set[bytes] = set()
        for line in text.splitlines():
            line = " ".join(line.split())               # paramiko splits on single spaces only
            if not line or line.startswith("#"):
                continue
            marker = None
            if line.startswith("@"):
                marker, _, line = line.partition(" ")
            try:
                entry = paramiko.hostkeys.HostKeyEntry.from_line(line)
            except Exception:  # noqa: BLE001 - a line paramiko cannot read (a key type it lacks) is passed over
                entry = None
            if entry is None or entry.key is None:
                continue
            if marker == "@revoked":
                revoked.add(entry.key.asbytes())
            elif marker is None:
                plain.append(entry)
        dropped = False
        for entry in plain:
            if entry.key.asbytes() in revoked:
                probe = paramiko.HostKeys()
                for name in entry.hostnames:
                    probe.add(name, entry.key.get_name(), entry.key)
                dropped = dropped or probe.lookup(src.host_key_name) is not None
                continue
            for name in entry.hostnames:
                into.add(name, entry.key.get_name(), entry.key)
        if into.lookup(src.host_key_name) is None:
            why = " that is not marked @revoked" if dropped else ""
            raise PluginError(
                f"sftp: known_hosts has no key for {src.host_key_name}{why}: ask the system's operator for the "
                f"server's host key fingerprint, then add the key (ssh-keyscan -p {src.port} {src.host} prints it; "
                f"compare the fingerprint before you trust it)")
        return revoked

    @classmethod
    def open(cls, src: "SftpSource") -> "_Paramiko":
        paramiko = cls._paramiko()
        key = cls._key(paramiko, src)
        client = paramiko.SSHClient()
        revoked = cls._known(paramiko, src, client.get_host_keys())   # never the system's known_hosts, nor added blind

        def named(presented: Any) -> str:
            withdrawn = presented.asbytes() in revoked
            return _fingerprint(presented) + (", a key known_hosts marks @revoked" if withdrawn else "")

        class Refuse(paramiko.MissingHostKeyPolicy):
            def missing_host_key(self, client: Any, hostname: str, key: Any) -> None:
                raise PluginError(f"sftp: {hostname} is not in known_hosts (it presented {named(key)}): refused; check "
                                  f"that fingerprint with the system's operator, then add the key")

        class KeyOnly(paramiko.AuthStrategy):
            """The login key and nothing else. paramiko's own login, after a key the server takes only as a first
            step, tries a second step itself, and for keyboard-interactive prints the server's prompt and reads an
            answer from the terminal; this strategy never does."""

            def get_sources(self):
                yield paramiko.InMemoryPrivateKey(src.username, key)

        client.set_missing_host_key_policy(Refuse())
        t = src.timeout
        try:
            # look_for_keys and allow_agent are off too, so no other key could ever be offered
            result = client.connect(src.host, port=src.port, username=src.username, look_for_keys=False,
                                    allow_agent=False, timeout=t, banner_timeout=t, auth_timeout=t,
                                    auth_strategy=KeyOnly(ssh_config=paramiko.SSHConfig()))
            transport = client.get_transport()
            if transport is None or not transport.is_authenticated():
                asks = [str(m) for r in (result or []) if isinstance(getattr(r, "result", None), (list, tuple))
                        for m in r.result]
                raise PluginError(
                    f"sftp: {src.username}@{src.host_key_name} takes the login key only as a first step and then asks "
                    f"for a second step ({', '.join(asks) or 'another method'}): this source logs in with its key "
                    f"alone and never answers a prompt, so it is refused. Ask the system's operator for a key-only "
                    f"login for this account")
            sftp = client.open_sftp()
            sftp.get_channel().settimeout(t)
        except PluginError:
            client.close()
            raise
        except paramiko.BadHostKeyException as e:
            client.close()
            if e.key.asbytes() in revoked:
                raise PluginError(f"sftp: {src.host_key_name} presented {named(e.key)}: refused. Its key was "
                                  f"withdrawn: ask the system's operator which key the server uses now") from None
            raise PluginError(
                f"sftp: {src.host_key_name} presented a host key that does not match known_hosts (it presented "
                f"{_fingerprint(e.key)}, known_hosts holds {_fingerprint(e.expected_key)}): refused. A rebuilt server, "
                f"or someone in between: check it with the system's operator before you change known_hosts") from None
        except paramiko.AuthenticationException:
            client.close()
            raise PluginError(f"sftp: {src.username}@{src.host_key_name} did not accept the login key (this source logs "
                              f"in with its key only)") from None
        except (paramiko.SSHException, OSError, EOFError) as e:
            client.close()
            raise ConnectionError(f"sftp: cannot reach {src.host_key_name}: {type(e).__name__}: {e}") from None
        return cls(paramiko, client, sftp)

    def _alive(self) -> bool:
        t = self._client.get_transport()
        return bool(t is not None and t.is_active() and not self._sftp.get_channel().closed)

    def _do(self, fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except (FileNotFoundError, PermissionError):
            raise                                           # an SFTP status: no such file, permission denied
        except OSError as e:
            if self._alive() and not isinstance(e, TimeoutError):
                raise RemoteError(str(e) or "the server refused") from None
            raise ConnectionError(f"sftp: the connection was lost ({type(e).__name__}: {e})") from None
        except (EOFError, self._p.SSHException) as e:
            raise ConnectionError(f"sftp: the connection was lost ({type(e).__name__}: {e})") from None

    @staticmethod
    def _entry(name: str, a: Any) -> RemoteFile:
        return RemoteFile(name, int(a.st_size or 0), int(a.st_mtime or 0), _stat.S_ISREG(a.st_mode or 0))

    def listdir(self, path: str) -> List[RemoteFile]:
        try:
            listed = self._do(self._sftp.listdir_attr, path)
        except UnicodeDecodeError as e:
            self.close()                                    # else the listing's handle stays open on the server
            raise PluginError(
                f"sftp: a file name in {path} is not UTF-8 ({bytes(e.object[:120])!r}), and names are read over SFTP "
                f"as UTF-8 only, so no file there can be listed: rename that file, or have its system name its files "
                f"in UTF-8") from None
        return [self._entry(a.filename, a) for a in listed]

    def stat(self, path: str) -> Optional[RemoteFile]:
        try:
            return self._entry(posixpath.basename(path), self._do(self._sftp.stat, path))
        except FileNotFoundError:
            return None

    def read(self, path: str) -> bytes:
        buf = io.BytesIO()
        self._do(self._sftp.getfo, path, buf)
        return buf.getvalue()

    def rename(self, old: str, new: str) -> None:
        try:
            self._do(self._sftp.rename, old, new)          # SSH_FXP_RENAME: the server never replaces a name
        except RemoteError:
            if self.stat(new) is not None:
                raise FileExistsError(new) from None
            raise

    def mkdir(self, path: str) -> None:
        self._do(self._sftp.mkdir, path)

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001 - closing what is already gone
            pass


# ── the source ───────────────────────────────────────────────────────────────────────────────────────────────────────

class SftpSource(Source):
    """Rows from the export files a legacy system leaves on an SFTP server, each file moved or marked once read."""

    name = "sftp"
    description = ("Rows from the export files a legacy system leaves on an SFTP server (CSV, JSON, JSONL, XML), each "
                   "file moved or marked once all its rows are in the outbox; key-based login, the host key checked.")
    config_schema: Mapping[str, Any] = {
        "type": "object",
        "required": ["host", "username", "private_key", "known_hosts", "path"],
        "additionalProperties": False,
        "properties": {
            "host": {"type": "string", "minLength": 1, "description": "The SFTP server."},
            "port": {"type": "integer", "minimum": 1, "maximum": 65535, "default": 22},
            "username": {"type": "string", "minLength": 1},
            "private_key": {"type": "string", "x-secret": True,
                            "description": "The login key (OpenSSH or PEM; Ed25519, ECDSA or RSA), a reference "
                                           "(file:/path or env:NAME). Key-based login only."},
            "passphrase": {"type": "string", "x-secret": True,
                           "description": "The login key's passphrase, a reference, when it has one."},
            "known_hosts": {"type": "string", "minLength": 1,
                            "description": "The server's host key, as an OpenSSH known_hosts file: its absolute path "
                                           "(or ~/...), or a reference to its text (file:known_hosts is read from the "
                                           "spec's folder). A server missing from it, or presenting another key, is "
                                           "refused; a key a @revoked line names is never accepted."},
            "path": {"type": "string", "minLength": 1,
                     "description": "The directory on the server the legacy system writes its exports into."},
            "format": {"enum": list(FORMATS), "default": "csv",
                       "description": "How one file's rows are read: csv, json, jsonl or xml. A CSV row with more "
                                      "fields than its header keeps the extra ones as a list under _extra."},
            "delimiter": {"type": "string", "minLength": 1, "maxLength": 1, "default": ",",
                          "description": "CSV only: the field separator (many exports use ';')."},
            "encoding": {"type": "string", "default": "utf-8-sig",
                         "description": "The files' text encoding (the default reads UTF-8, with or without a BOM)."},
            "suffix": {"type": "string", "default": "",
                       "description": "Only files ending in this are read (default: every file)."},
            "id_field": {"type": "string", "default": "",
                         "description": "A row field holding the legacy system's own id. Empty: the id is the file's "
                                        "name, its instance and the row's position."},
            "after_read": {"enum": list(AFTER_READ), "default": "move",
                           "description": "Once every row of a file is in the outbox: move it into move_to, mark it "
                                          "(rename it with mark_suffix), or leave it (a read-only account)."},
            "move_to": {"type": "string", "minLength": 1, "default": "done",
                        "description": "Where read files go: a directory relative to path, or an absolute one; the "
                                       "folders it names are made when they do not exist."},
            "mark_suffix": {"type": "string", "minLength": 1, "default": ".read",
                            "description": "What mark appends to a read file's name."},
            "settle_seconds": {"type": "number", "minimum": 0, "default": 5,
                               "description": "A file is read only once its size and time have stayed the same "
                                              "for this long: an upload is not atomic."},
            "require_marker": {"type": "string", "default": "",
                               "description": "If set (e.g. '.ok'), a file is read only once its marker file is "
                                              "beside it, and settle_seconds is not consulted."},
            "ignore_suffixes": {"type": "array", "items": {"type": "string"}, "default": list(TEMPORARY_SUFFIXES),
                                "description": "Names an upload in progress carries; such files are never read."},
            "poll_seconds": {"type": "number", "minimum": 0, "default": 60,
                             "description": "How often the directory is listed. 0: list it once (tp-proxy run "
                                            "--once, or a schedule) and finish."},
            "max_bytes": {"type": "integer", "minimum": 1, "default": 67108864,
                          "description": "A larger file is not read, and the log says so."},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "default": 30},
        },
    }

    transport: ClassVar[Any] = _Paramiko
    _STATE_KEY = "sftp.cursor"

    def __init__(self, config: Mapping[str, Any], ctx: Any) -> None:
        super().__init__(config, ctx)
        c = self.config
        missing = [k for k in ("host", "username", "private_key", "known_hosts", "path") if not str(c.get(k) or "").strip()]
        if missing:
            raise PluginError(f"sftp: {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required")
        self.host = str(c["host"]).strip()
        self.port = int(c.get("port") or 22)
        self.username = str(c["username"]).strip()
        self.host_key_name = self.host if self.port == 22 else f"[{self.host}]:{self.port}"
        self._server = f"{self.host}:{self.port}"
        known = str(c["known_hosts"]).strip()
        if not is_ref(known):
            known = os.path.expanduser(known)
            if not os.path.isabs(known):
                raise PluginError(f"sftp: known_hosts {c['known_hosts']!r} is a relative path, which would be read "
                                  f"from the folder the proxy runs in: write an absolute path, or file:{known} to read "
                                  f"it from the spec's folder")
        self.known_hosts = known
        self._dir = _norm(str(c["path"]).strip())
        self._format = str(c.get("format") or "csv")
        if self._format not in FORMATS:
            raise PluginError(f"sftp: format {self._format!r} is not one of {', '.join(FORMATS)}")
        self._delimiter = str(c.get("delimiter") or ",")
        if len(self._delimiter) != 1:
            raise PluginError(f"sftp: delimiter {self._delimiter!r} is not one character")
        self._encoding = str(c.get("encoding") or "utf-8-sig")
        try:
            codecs.lookup(self._encoding)
        except LookupError:
            raise PluginError(f"sftp: encoding {self._encoding!r} is not one Python knows") from None
        self._suffix = str(c.get("suffix") or "")
        self._id_field = str(c.get("id_field") or "")
        self._after = str(c.get("after_read") or "move")
        if self._after not in AFTER_READ:
            raise PluginError(f"sftp: after_read {self._after!r} is not one of {', '.join(AFTER_READ)}")
        move_to = str(c.get("move_to") or "done").strip()
        self._archive = _norm(move_to if move_to.startswith("/") else posixpath.join(self._dir, move_to))
        if self._after == "move" and self._archive == self._dir:
            raise PluginError("sftp: move_to names the directory being read; name another one (default: done)")
        self._mark = str(c.get("mark_suffix") or ".read")
        self._marker = str(c.get("require_marker") or "")
        ignore = c.get("ignore_suffixes")
        self._ignore = tuple(str(s) for s in (TEMPORARY_SUFFIXES if ignore is None else ignore) if s)
        self._settle = float(c.get("settle_seconds", 5))
        self._poll = float(c.get("poll_seconds", 60))
        if self._settle < 0 or self._poll < 0:
            raise PluginError("sftp: settle_seconds and poll_seconds are not negative")
        self._max = int(c.get("max_bytes") or 67108864)
        self.timeout = float(c.get("timeout_seconds") or 30)
        self._cursor: Dict[str, Dict[str, Any]] = {"files": {}, "replay": {}}
        self._seen: Dict[str, Tuple[int, int, float]] = {}      # name -> (size, mtime, first seen): the settle wait
        self._bad: Dict[str, Tuple[int, int]] = {}              # name -> (size, mtime): unreadable until it changes
        self._refused: Dict[str, str] = {}                      # path -> the server's answer, named once while it lasts
        self._conn: Any = None
        self._archive_ready = False
        self._clock = time.monotonic

    # ── the core's calls ──────────────────────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        saved = await self.ctx.state.get(self._STATE_KEY, None) or {}
        self._cursor = {"files": dict(saved.get("files") or {}), "replay": dict(saved.get("replay") or {})}
        if self._format == "xml":
            try:
                importlib.import_module("defusedxml.ElementTree")
            except ImportError:
                raise PluginError(f"sftp: XML from another system is read through defusedxml, which is not installed "
                                  f"({EXTRA})") from None
        await asyncio.to_thread(self.transport.check, self)

    async def stop(self) -> None:
        await self._drop()

    async def committed(self, record: Record) -> None:
        p, m = record.payload or {}, record.meta or {}
        try:
            index = int(p.get("row", -1))
        except (TypeError, ValueError):
            return
        if index < 0:
            return
        if m.get("replay"):
            entry = self._cursor["replay"].get(str(m.get("path") or ""))
        else:
            entry = self._cursor["files"].get(str(p.get("file") or ""))
        if entry is None or entry.get("sha256") != p.get("sha256"):
            return                                      # a row of a file this cursor no longer describes
        if index + 1 > int(entry.get("rows", 0)):
            entry["rows"] = index + 1
            await self._save()

    async def records(self) -> AsyncIterator[Record]:
        looked_again = False
        while True:
            listing = await self._listing()
            present = {f.name: f for f in listing if f.is_file}
            await self._forget_gone(present)
            waiting: List[float] = []

            # the files a replay asked for come first: they are the past
            for where in sorted(self._cursor["replay"]):
                job = self._cursor["replay"][where]
                rows = await self._fetch_replay(where, job)
                if rows is None:
                    continue
                for index in range(int(job["rows"]), len(rows)):
                    yield self._record(job["name"], job["instance"], job["sha256"], index, rows[index], where, True)
                if int(job["rows"]) >= len(rows) and not self.ctx.dry_run:
                    self._cursor["replay"].pop(where, None)
                    await self._save()
                    self.ctx.logger.info(f"sftp: {where} read again ({len(rows)} rows)")

            for name in sorted(present):
                f = present[name]
                if not self._candidate(name):
                    continue
                entry = self._cursor["files"].get(name)
                same = self._unchanged(entry, f)
                if same and int(entry["rows"]) >= int(entry["total"]):
                    await self._finish(f, entry, present)          # every row is in: move it (a crash came first)
                    continue
                if not same:
                    ready, wait = self._ready(f, present)
                    if not ready:
                        if wait is not None:
                            waiting.append(wait)
                        continue
                if self._bad.get(name) == (f.size, f.mtime):
                    continue
                if f.size > self._max:
                    self._bad[name] = (f.size, f.mtime)
                    self.ctx.logger.warning(f"sftp: {name} is {f.size} bytes, more than max_bytes ({self._max}): it is "
                                            f"not read, and stays where it is")
                    continue
                try:
                    got = await self._fetch(f, entry)
                except _Refused as e:
                    self._refusal(self._path(name), name, str(e))
                    continue                                # the files behind it are read; a later look tries again
                if got is None:
                    if self._settle > 0 and not self._marker:
                        waiting.append(self._settle)
                    continue
                rows, entry = got
                for index in range(int(entry["rows"]), len(rows)):
                    yield self._record(name, entry["instance"], entry["sha256"], index, rows[index], self._path(name))
                if int(entry["rows"]) >= int(entry["total"]):
                    await self._finish(f, entry, present)

            # one look at the server is over
            if self._poll <= 0 or self.ctx.dry_run:
                if waiting and not looked_again:
                    looked_again = True                     # a file that settles in time is read in this same run
                    await asyncio.sleep(min(waiting) + 0.05)
                    continue
                return
            looked_again = False
            await asyncio.sleep(min([self._poll] + [w + 0.05 for w in waiting]))

    async def rewind(self, point: str) -> None:
        """`point` names a file as it is on the server, relative to `path`, optionally with `#row`: a file in the
        directory (`orders.csv`, read again from that row, and every file after it in the read order read again whole),
        or one this source has already moved or marked (`done/orders.csv`, `orders.csv.read`), which is read again
        WHERE IT IS, under the ids it had, and not moved again. Records already in the outbox are not sent twice: their
        keys are there."""
        text = str(point or "").strip()
        name, sep, row = text.rpartition("#")
        if not sep or not _ROW.match(row):
            name, row = text, ""
        name = name.strip()
        if not name:
            raise PluginError("sftp: a replay point is a file name, optionally file#row (done/file for a moved one)")
        at = int(row) if row.strip() else 0
        if at < 0:
            raise PluginError(f"sftp: {point!r} names a negative row")
        path = _norm(name if name.startswith("/") else posixpath.join(self._dir, name))
        folder, base = posixpath.split(path)
        found = await self._io("stat", path)
        if found is None or not found.is_file:
            raise PluginError(f"sftp: there is no file {name!r} on {self._server} to read again")
        marked = self._after == "mark" and base.endswith(self._mark)
        if folder == self._dir and not marked:
            if not self._candidate(base):
                raise PluginError(f"sftp: {name!r} is a file this source does not read (its name is passed over)")
            entry = self._cursor["files"].get(base)
            if entry is not None and not entry.get("pending"):
                entry["rows"] = min(at, int(entry.get("total", at)))
            else:
                self._cursor["files"][base] = {"rows": at, "pending": True}
            for other, e in self._cursor["files"].items():
                if other > base and not e.get("pending"):
                    e["rows"] = 0
            await self._save()
            return
        if not ((self._after == "move" and folder == self._archive) or (marked and folder == self._dir)):
            raise PluginError(f"sftp: {name!r} is neither in {self._dir} nor where this source puts the files it has read")
        original, tag = self._original(base)
        job: Dict[str, Any] = {"name": original, "rows": at}
        if tag:
            job["instance"] = tag
        self._cursor["replay"][path] = job
        await self._save()

    # ── the connection ────────────────────────────────────────────────────────────────────────────────────────────

    async def _connected(self) -> Any:
        if self._conn is None:
            self._conn = await asyncio.to_thread(self.transport.open, self)
        return self._conn

    async def _drop(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await asyncio.to_thread(conn.close)
            except Exception:  # noqa: BLE001 - closing what is already gone
                pass

    async def _io(self, method: str, *args: Any) -> Any:
        conn = await self._connected()
        try:
            return await asyncio.to_thread(getattr(conn, method), *args)
        except _LOST:
            await self._drop()                      # the next call connects again
            raise
        except PluginError:
            await self._drop()                      # the transport gave this connection up (a listing it cannot read)
            raise

    async def _listing(self) -> List[RemoteFile]:
        for attempt in (1, 2):
            try:
                return await self._io("listdir", self._dir)
            except FileNotFoundError:
                raise PluginError(f"sftp: {self._dir} is not a directory on {self._server}") from None
            except _LOST:
                if attempt == 2:
                    raise
                # a connection that died while the source waited (an idle timeout, a server restart): once more
        raise AssertionError("unreachable")  # pragma: no cover

    # ── one file ──────────────────────────────────────────────────────────────────────────────────────────────────

    def _path(self, name: str) -> str:
        return posixpath.join(self._dir, name)

    def _candidate(self, name: str) -> bool:
        if name.startswith("."):
            return False                            # hidden: the temporary files of rsync and many editors
        if any(name.endswith(s) for s in self._ignore):
            return False
        if self._marker and name.endswith(self._marker):
            return False
        if self._after == "mark" and name.endswith(self._mark):
            return False
        if self._suffix and not name.endswith(self._suffix):
            return False
        return True

    @staticmethod
    def _unchanged(entry: Optional[Dict[str, Any]], f: RemoteFile) -> bool:
        return (entry is not None and not entry.get("pending") and entry.get("size") == f.size
                and entry.get("mtime") == f.mtime)

    def _ready(self, f: RemoteFile, present: Mapping[str, RemoteFile]) -> Tuple[bool, Optional[float]]:
        """Whether a file can be read now, and if not, how long until it may be (None: until its marker comes)."""
        if self._marker:
            return (f.name + self._marker) in present, None
        if self._settle <= 0:
            return True, None
        now = self._clock()
        seen = self._seen.get(f.name)
        if seen is None or (seen[0], seen[1]) != (f.size, f.mtime):
            self._seen[f.name] = (f.size, f.mtime, now)
            return False, self._settle
        left = self._settle - (now - seen[2])
        return (True, None) if left <= 0 else (False, left)

    def _id(self, name: str, instance: str, index: int, row: Any) -> str:
        if self._id_field and isinstance(row, Mapping):
            got = row.get(self._id_field)
            if got not in (None, ""):
                return str(got)
        return f"{name}@{instance}#{index}"

    def _record(self, name: str, instance: str, digest: str, index: int, row: Any, where: str,
                replay: bool = False) -> Record:
        meta: Dict[str, Any] = {"via": "sftp", "server": self._server, "path": where}
        if replay:
            meta["replay"] = True
        return Record(record_id=self._id(name, instance, index, row),
                      payload={"file": name, "sha256": digest, "row": index, "data": row}, meta=meta)

    def _refusal(self, path: str, what: str, said: str, *, replay: bool = False) -> None:
        """Name a refusal once while it lasts (the same answer on every look is not news), and again if it changes."""
        if self._refused.get(path) == said:
            return
        self._refused[path] = said
        if replay:
            self.ctx.logger.warning(f"sftp: {what}, asked to be read again, was refused by the server ({said}): the "
                                    f"replay waits and is tried again on every look; the inbox is read meanwhile")
        else:
            self.ctx.logger.warning(f"sftp: {what} was refused by the server ({said}): it is passed over and tried "
                                    f"again on every look, and the files behind it are read meanwhile")

    def _read_out(self, data: bytes) -> Tuple[str, List[Any]]:
        """A file's digest and its rows (or _Unreadable). Run in a worker thread: on a large file both take time, and
        on the event loop they would stall the proxy's other sources, its dispatcher and its /health."""
        return _digest(data), self._rows(data)

    def _rows(self, data: bytes) -> List[Any]:
        try:
            text = data.decode(self._encoding)
        except UnicodeDecodeError as e:
            raise _Unreadable(f"it is not {self._encoding} text ({e.reason} at byte {e.start})") from None
        try:
            if self._format == "csv":
                return _rows_csv(text, self._delimiter)
            if self._format == "json":
                return _rows_json(text)
            if self._format == "jsonl":
                return _rows_jsonl(text)
            return _rows_xml(text)
        except (ValueError, SyntaxError, RecursionError, csv.Error) as e:
            # ValueError: JSON, and defusedxml's refusals (an entity, a DTD, an external reference); SyntaxError: a
            # broken XML document (ParseError)
            raise _Unreadable(f"{type(e).__name__}: {e}") from None

    async def _download(self, path: str, f: RemoteFile) -> Optional[bytes]:
        """The file's bytes, or None when it changed while it was being read (it is still being written). _Refused when
        the server will not let it be read."""
        try:
            data = await self._io("read", path)
            after = await self._io("stat", path)
        except FileNotFoundError:
            return None
        except (PermissionError, RemoteError) as e:
            raise _Refused(f"{type(e).__name__}: {e}") from None
        if after is None or len(data) != f.size or (after.size, after.mtime) != (f.size, f.mtime):
            return None
        return data

    async def _fetch(self, f: RemoteFile, entry: Optional[Dict[str, Any]]):
        """Read a file and bring its cursor up to date: (rows, entry), or None when it is not to be read now; _Refused
        when the server will not let it be read."""
        data = await self._download(self._path(f.name), f)
        self._refused.pop(self._path(f.name), None)
        if data is None:
            self._seen.pop(f.name, None)
            self.ctx.logger.info(f"sftp: {f.name} changed while it was read: it is read once it settles")
            return None
        try:
            digest, rows = await asyncio.to_thread(self._read_out, data)
        except _Unreadable as e:
            self._bad[f.name] = (f.size, f.mtime)
            self.ctx.logger.warning(f"sftp: {f.name} could not be read ({e}): it stays where it is, and is read again "
                                    f"once it changes")
            return None
        if entry is not None and not entry.get("pending"):
            size = int(entry.get("size", 0))
            if entry.get("sha256") == digest:
                pass                                        # the same file: it continues at its cursor
            elif f.size > size and await asyncio.to_thread(_digest, data, size) == entry.get("sha256"):
                self.ctx.logger.warning(f"sftp: {f.name} grew after {entry.get('total')} rows of it were read (its "
                                        f"writer was not done): its new rows follow, under the same file's ids")
            else:
                done, total = int(entry.get("rows", 0)), int(entry.get("total", 0))
                if done < total:
                    self.ctx.logger.warning(f"sftp: {f.name} was replaced before all its rows were read ({done} of "
                                            f"{total}): the rest of the old file is lost; the new one is read whole")
                else:
                    self.ctx.logger.info(f"sftp: {f.name} holds other bytes now: it is read as a new file")
                entry = None
        if entry is None or entry.get("pending"):
            entry = {"instance": digest[:16], "rows": int(entry.get("rows", 0)) if entry else 0}
        entry.update({"sha256": digest, "size": f.size, "mtime": f.mtime, "total": len(rows)})
        entry["rows"] = min(int(entry["rows"]), len(rows))
        self._cursor["files"][f.name] = entry
        self._seen.pop(f.name, None)
        self._bad.pop(f.name, None)
        await self._save()
        return rows, entry

    async def _fetch_replay(self, where: str, job: Dict[str, Any]) -> Optional[List[Any]]:
        """The rows of a file a replay asked for, or None: not now (it changed while it was read, or the server refused
        it: the job waits), or never (the job is dropped, and the log says why)."""
        problem = None
        try:
            f = await self._io("stat", where)
            if f is None or not f.is_file:
                problem = "is gone"
            elif f.size > self._max:
                problem = f"is more than max_bytes ({self._max})"
            else:
                data = await self._download(where, f)
                if data is None:
                    return None                             # it changed while it was read: the next look
                try:
                    digest, rows = await asyncio.to_thread(self._read_out, data)
                except _Unreadable as e:
                    problem = f"could not be read ({e})"
        except _Refused as e:
            self._refusal(where, where, str(e), replay=True)
            return None
        except (PermissionError, RemoteError) as e:          # its folder, or its stat, refused
            self._refusal(where, where, f"{type(e).__name__}: {e}", replay=True)
            return None
        self._refused.pop(where, None)
        if problem is not None:
            self.ctx.logger.warning(f"sftp: {where}, asked to be read again, {problem}: the replay is dropped")
            self._cursor["replay"].pop(where, None)
            await self._save()
            return None
        job["sha256"] = digest
        job.setdefault("instance", digest[:16])
        job["rows"] = min(int(job.get("rows", 0)), len(rows))
        await self._save()
        return rows

    async def _forget_gone(self, present: Mapping[str, RemoteFile]) -> None:
        gone = [n for n in self._cursor["files"] if n not in present]
        for n in gone:
            e = self._cursor["files"].pop(n)
            done, total = int(e.get("rows", 0)), int(e.get("total", 0))
            if not e.get("pending") and done < total:
                self.ctx.logger.warning(f"sftp: {n} left {self._dir} with {done} of its {total} rows read: the rest "
                                        f"were not read (someone else moved or removed it)")
        if gone:
            await self._save()
        for known in (self._seen, self._bad):
            for n in [n for n in known if n not in present]:
                del known[n]
        here = {self._path(n) for n in present}
        for p in [p for p in self._refused if p not in here and p not in self._cursor["replay"]]:
            del self._refused[p]

    async def _finish(self, f: RemoteFile, entry: Dict[str, Any], present: Mapping[str, RemoteFile]) -> None:
        """Every row of the file is in the outbox: move it or mark it (never in a dry run, never with leave)."""
        if self._after == "leave" or self.ctx.dry_run:
            return
        verb = "moved" if self._after == "move" else "marked"
        try:
            now = await self._io("stat", self._path(f.name))
            if now is None:
                self._cursor["files"].pop(f.name, None)
                await self._save()
                return
            if (now.size, now.mtime) != (entry.get("size"), entry.get("mtime")):
                self.ctx.logger.info(f"sftp: {f.name} changed after it was read: it is read again, not moved")
                return
            target = await self._place(f.name, entry, present)
        except FileNotFoundError as e:
            try:
                gone = await self._io("stat", self._path(f.name)) is None
            except (PermissionError, RemoteError):
                gone = False
            if gone:
                self._cursor["files"].pop(f.name, None)     # someone else took it between the look and the move
                await self._save()
                return
            self._archive_ready = False                     # the archive went away: it is made again on the next look
            self.ctx.logger.error(f"sftp: {f.name} was read but could not be {verb} ({e}): it stays, is not read "
                                  f"again, and is {verb} on a later look")
            return
        except (PermissionError, FileExistsError, RemoteError) as e:
            self.ctx.logger.error(f"sftp: {f.name} was read but could not be {verb} ({type(e).__name__}: {e}): it stays, "
                                  f"is not read again, and is {verb} on a later look")
            return
        self._cursor["files"].pop(f.name, None)
        await self._save()
        self.ctx.logger.info(f"sftp: {f.name} read ({entry.get('total')} rows) and {verb}: {target}")

    async def _place(self, name: str, entry: Mapping[str, Any], present: Mapping[str, RemoteFile]) -> str:
        """Move or mark a read file, with its marker, under a name that is free; answer where it went.

        The name itself, then the name with the file's instance (`orders.csv~<instance>`), then with a counter after it
        (`~2`, `~3`, ...): an export that brings the same bytes every quiet hour takes the next counter each time. The
        counter is found by doubling until a free one, then halving back towards the taken ones, so a free name among
        a year of such copies costs about thirty looks at the server, not one per copy. A file that grew after it was
        first read skips the bare name: its bytes no longer give the instance its rows were read under, and a replay
        takes the instance from the name."""
        if self._after == "move":
            await self._ensure_archive()
            folder = self._archive
        else:
            folder = self._dir
        instance = str(entry["instance"])
        marker = name + self._marker if self._marker and (name + self._marker) in present else None

        def target(base: str) -> str:
            return posixpath.join(folder, base + self._mark if self._after == "mark" else base)

        async def free(base: str) -> bool:
            there = target(base)
            if await self._io("stat", there) is not None:
                return False
            return marker is None or await self._io("stat", there + self._marker) is None

        tagged = f"{name}~{instance}"
        grew = str(entry.get("sha256") or "")[:16] != instance
        chosen = None
        for base in ([] if grew else [name]) + [tagged]:
            if await free(base):
                chosen = base
                break
        if chosen is None:
            taken, maybe = 1, 2                             # 1 stands for the tagged name itself, which is taken
            while not await free(f"{tagged}~{maybe}"):
                if maybe >= _MAX_COPIES:
                    raise FileExistsError(f"every name for {name} in {folder} is taken")
                taken, maybe = maybe, maybe * 2
            while maybe - taken > 1:
                middle = (taken + maybe) // 2
                if await free(f"{tagged}~{middle}"):
                    maybe = middle
                else:
                    taken = middle
            chosen = f"{tagged}~{maybe}"
        final = target(chosen)
        if marker is not None:
            # the marker first: a marker left behind would release the next file of this name before it is whole, so
            # a marker that cannot move keeps its file where it is too (both go on a later look)
            try:
                await self._io("rename", self._path(marker), final + self._marker)
            except FileNotFoundError:
                pass                                        # it is gone already: nothing is left behind to release
            except (PermissionError, FileExistsError, RemoteError) as e:
                raise type(e)(f"its marker {marker} could not go with it: {e}") from None
        await self._io("rename", self._path(name), final)
        return final

    async def _ensure_archive(self) -> None:
        """The archive folder, made when it is not there, with the folders above it that are not there either."""
        if self._archive_ready:
            return
        missing: List[str] = []
        at = self._archive
        while at and await self._io("stat", at) is None:
            missing.append(at)
            up = posixpath.dirname(at)
            if up == at:
                break
            at = up
        for folder in reversed(missing):
            try:
                await self._io("mkdir", folder)
            except (FileExistsError, RemoteError):
                if await self._io("stat", folder) is None:
                    raise
        self._archive_ready = True

    def _original(self, base: str) -> Tuple[str, Optional[str]]:
        """A moved or marked file's name as it was read, and the instance tag its archive name carries, if any."""
        if self._after == "mark" and base.endswith(self._mark):
            base = base[: -len(self._mark)]
        m = _TAG.search(base)
        if m:
            return base[: m.start()], m.group(1)
        return base, None

    async def _save(self) -> None:
        await self.ctx.state.set(self._STATE_KEY, self._cursor)
