"""V0659 (l): the SFTP poll source: rows from the export files a legacy system leaves on an SFTP server.

These cases run the source's own logic on a local directory, through its transport seam (`SftpSource.transport`), so
they need no server and no network: the listing, the settle wait, the cursor, the ids, the move or mark once read, the
replay. `LocalServer` keeps the two server rules the logic leans on: a rename never replaces a name that exists, and
times are whole seconds (SFTP v3). The same source against a real OpenSSH server in a container (the key login, the
known-hosts check, a half-written upload, a restart mid-file) is tests/test_proxy_source_sftp_server.py, which skips
without that server.

Two properties are tested apart, as the file drop's tests do: stable ids (`check_source(twice=True)`, a FRESH context)
and resumption (a SHARED context across two source instances, which is what a restart looks like; `check_resume`).
"""
from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import logging
import os
import sys
import threading

import pytest

from theprotocol.proxy import plugins
from theprotocol.proxy.plugins import PluginError
from theprotocol.proxy.sources.sftp import RemoteError, RemoteFile, SftpSource
from theprotocol.proxy.testing import FakeContext, check_class, check_resume, check_source

CSV = "id,name\n1,ada\n2,grace\n3,edsger\n"


# ── a stand-in for the server ────────────────────────────────────────────────────────────────────────────────────────

class LocalServer:
    """The calls the source makes, on a local directory. `fail[method] = n` loses the connection on the next n calls of
    that method, as a server restart or a dropped network would; `refuse[(method, file name)] = error` answers that call
    on that file with a refusal on a live connection (permission denied, or a Windows server's sharing violation, which
    arrives as a plain SFTP failure); `on_read` runs after a download (a writer that was not done); `opened` counts the
    connections."""

    def __init__(self) -> None:
        self.opened = 0
        self.calls: list = []
        self.fail: dict = {}
        self.refuse: dict = {}
        self.on_read = None

    def check(self, src) -> None:
        pass

    def open(self, src) -> "_LocalConn":
        self.opened += 1
        return _LocalConn(self)


class _LocalConn:
    def __init__(self, server: LocalServer) -> None:
        self.server, self.closed = server, False

    def _call(self, what: str, path: str = "") -> None:
        if self.closed:
            raise ConnectionError("the connection is closed")
        self.server.calls.append(what)
        if self.server.fail.get(what, 0) > 0:
            self.server.fail[what] -= 1
            self.closed = True
            raise ConnectionError(f"the connection was lost during {what}")
        refusal = self.server.refuse.get((what, os.path.basename(path)))
        if refusal is not None:
            raise refusal

    @staticmethod
    def _entry(path: str, name: str) -> RemoteFile:
        st = os.lstat(path)
        import stat as _stat
        return RemoteFile(name, st.st_size, int(st.st_mtime), _stat.S_ISREG(st.st_mode))

    def listdir(self, path: str):
        self._call("listdir", path)
        return [self._entry(os.path.join(path, n), n) for n in os.listdir(path)]

    def stat(self, path: str):
        self._call("stat", path)
        if not os.path.lexists(path):
            return None
        return self._entry(path, os.path.basename(path))

    def read(self, path: str) -> bytes:
        self._call("read", path)
        with open(path, "rb") as fh:
            data = fh.read()
        if self.server.on_read is not None:
            self.server.on_read(path)
        return data

    def rename(self, old: str, new: str) -> None:
        self._call("rename", old)
        if os.path.lexists(new):
            raise FileExistsError(new)       # the server's rule: an existing name is never replaced
        os.rename(old, new)

    def mkdir(self, path: str) -> None:
        self._call("mkdir", path)
        os.mkdir(path)

    def close(self) -> None:
        self.closed = True


def _cls(server: LocalServer):
    return type("LocalSftp", (SftpSource,), {"transport": server})


@pytest.fixture
def server():
    return LocalServer()


def _inbox(tmp_path):
    p = tmp_path / "inbox"
    p.mkdir(exist_ok=True)
    return p


def _cfg(tmp_path, **kw):
    cfg = {"host": "legacy.example", "username": "proxy", "private_key": "env:NOT_READ_BY_THE_LOCAL_SERVER",
           "known_hosts": "/nonexistent/known_hosts", "path": str(_inbox(tmp_path)), "format": "csv",
           "settle_seconds": 0, "poll_seconds": 0}
    cfg.update(kw)
    return cfg


def _drop(tmp_path, name: str, body, *, at=None):
    p = _inbox(tmp_path) / name
    if isinstance(body, bytes):
        p.write_bytes(body)
    else:
        p.write_text(body, encoding="utf-8")
    if at is not None:
        os.utime(p, (at, at))
    return p


def _inst(body) -> str:
    data = body if isinstance(body, bytes) else body.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


async def _collect(src, *, commit: bool = True, take=None, after_each=None):
    out = []
    await src.start()
    try:
        async for r in src.records():
            out.append(r)
            if commit:
                await src.committed(r)
            if after_each is not None:
                after_each(r)
            if take is not None and len(out) >= take:
                break                           # as a crash or a stop would: the generator is not resumed
    finally:
        await src.stop()
    return out


def _ids(records):
    return [r.record_id for r in records]


def _names(path):
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


# ── the interface, the registration and the spec ─────────────────────────────────────────────────────────────────────

def test_the_class_keeps_the_interface():
    check_class(SftpSource)


def test_it_is_registered_and_loads_by_name():
    assert plugins.load("source", "sftp") is SftpSource
    assert plugins.available("source")["sftp"] == "theprotocol.proxy.sources.sftp:SftpSource"


def test_the_login_key_and_its_passphrase_are_secret_fields():
    props = SftpSource.config_schema["properties"]
    assert props["private_key"].get("x-secret") is True and props["passphrase"].get("x-secret") is True
    assert not props["known_hosts"].get("x-secret"), "a host key is public: known_hosts is not a secret"
    assert "password" not in props, "key-based login only"


def _spec(tmp_path, config):
    import proxy_fake as F
    return F.spec_doc(tmp_path, sources={"exports": {"type": "sftp", "config": config}},
                      mappings=[{"name": "m", "version": 1, "from": "exports", "to": "attest",
                                 "fields": {"row": "$.payload.data"}}])


def test_a_spec_refuses_a_login_key_written_out_and_takes_a_reference(tmp_path):
    from theprotocol.proxy.spec import SpecError, parse
    base = {"host": "sftp.erp.example", "username": "proxy", "known_hosts": "/config/known_hosts",
            "path": "/outbox"}
    with pytest.raises(SpecError) as e:                 # any value that is not a reference is a key written out
        parse(_spec(tmp_path, {**base, "private_key": "a-login-key-written-into-the-spec"}), base=tmp_path)
    assert "sources.exports.config.private_key" in e.value.problems
    spec = parse(_spec(tmp_path, {**base, "private_key": "file:/run/secrets/sftp_key",
                                  "passphrase": "env:SFTP_KEY_PASSPHRASE"}), base=tmp_path)
    assert spec.sources["exports"].type == "sftp"


def test_a_spec_refuses_a_config_the_source_does_not_know(tmp_path):
    from theprotocol.proxy.spec import SpecError, parse
    cfg = {"host": "h", "username": "u", "private_key": "env:K", "known_hosts": "/k", "path": "/o",
           "after_read": "delete"}
    with pytest.raises(SpecError) as e:
        parse(_spec(tmp_path, cfg), base=tmp_path)
    assert any(p.startswith("sources.exports.config.after_read") for p in e.value.problems)


@pytest.mark.parametrize("bad", [
    {"format": "yaml"}, {"after_read": "delete"}, {"delimiter": ";;"}, {"encoding": "no-such-codec"},
    {"host": ""}, {"username": ""}, {"private_key": ""}, {"known_hosts": ""}, {"path": ""},
    {"move_to": "."}, {"settle_seconds": -1}, {"poll_seconds": -1},
    # a relative path would be read from wherever the proxy runs, while a file: reference is read from the spec's folder
    {"known_hosts": "config/known_hosts"}, {"known_hosts": "known_hosts"},
])
def test_a_config_it_cannot_honour_is_refused_at_construction(tmp_path, bad):
    with pytest.raises(PluginError):
        SftpSource(_cfg(tmp_path, **bad), FakeContext())


@pytest.mark.parametrize("known_hosts", ["/config/known_hosts", "~/.ssh/known_hosts", "file:known_hosts",
                                         "env:SFTP_KNOWN_HOSTS"])
def test_known_hosts_is_an_absolute_path_a_home_path_or_a_reference(tmp_path, known_hosts):
    SftpSource(_cfg(tmp_path, known_hosts=known_hosts), FakeContext())


def test_without_paramiko_it_says_which_extra_to_install(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "paramiko", None)
    src = SftpSource(_cfg(tmp_path), FakeContext())
    with pytest.raises(PluginError, match=r"proxy-sftp"):
        asyncio.run(src.start())


def test_xml_is_never_read_without_defusedxml(tmp_path, monkeypatch, server):
    """The file comes from another system: no fallback to the standard library's parser alone."""
    monkeypatch.setitem(sys.modules, "defusedxml", None)
    monkeypatch.setitem(sys.modules, "defusedxml.ElementTree", None)
    src = _cls(server)(_cfg(tmp_path, format="xml"), FakeContext())
    with pytest.raises(PluginError, match=r"defusedxml"):
        asyncio.run(src.start())


# ── the shipped contracts ────────────────────────────────────────────────────────────────────────────────────────────

def test_it_passes_the_shipped_source_contract(tmp_path, server):
    """check_source reads the same input twice with fresh state, so the files stay where they are (leave)."""
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(check_source(_cls(server), _cfg(tmp_path, after_read="leave"), limit=10))
    i = _inst(CSV)
    assert _ids(got) == [f"a.csv@{i}#0", f"a.csv@{i}#1", f"a.csv@{i}#2"]
    assert got[0].payload["data"] == {"id": "1", "name": "ada"}


def test_it_passes_the_shipped_resume_contract(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ids = asyncio.run(check_resume(_cls(server), _cfg(tmp_path, after_read="leave"), first=2))
    assert len(ids) == 3 and len(set(ids)) == 3


def test_a_record_names_its_file_its_digest_and_its_server(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, port=2222), FakeContext())))
    assert got[1].payload == {"file": "a.csv", "sha256": hashlib.sha256(CSV.encode()).hexdigest(), "row": 1,
                              "data": {"id": "2", "name": "grace"}}
    assert got[1].meta["via"] == "sftp" and got[1].meta["server"] == "legacy.example:2222"
    json.dumps(dict(got[1].meta))                     # the core keeps a record's meta as JSON


# ── moved or marked once read, never before ──────────────────────────────────────────────────────────────────────────

def test_a_file_is_moved_once_every_row_is_committed(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert len(got) == 3
    inbox = _inbox(tmp_path)
    assert _names(inbox) == ["done"], "the read file stays in the inbox"
    assert (inbox / "done" / "a.csv").read_text(encoding="utf-8") == CSV, "the archive keeps the file as it was"


def test_a_file_is_not_moved_while_a_row_is_uncommitted(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext()), take=2))
    assert _names(_inbox(tmp_path)) == ["a.csv"], "a file was moved before all its rows were in the outbox"


def test_rows_read_but_never_committed_do_not_move_the_file(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext()), commit=False))
    assert len(got) == 3 and _names(_inbox(tmp_path)) == ["a.csv"]


def test_mark_renames_the_file_in_place_and_it_is_not_read_again(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()
    cfg = _cfg(tmp_path, after_read="mark")
    first = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert _names(_inbox(tmp_path)) == ["a.csv.read"]
    assert asyncio.run(_collect(_cls(server)(cfg, FakeContext()))) == [], "a marked file was read again"
    assert len(first) == 3


def test_leave_touches_nothing_and_still_reads_a_file_once(tmp_path, server):
    """For a read-only account: the cursor remembers each file's digest instead."""
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()
    cfg = _cfg(tmp_path, after_read="leave")
    first = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert len(first) == 3 and second == []
    assert _names(_inbox(tmp_path)) == ["a.csv"]
    assert "rename" not in server.calls and "mkdir" not in server.calls


def test_a_dry_run_moves_nothing(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext(dry_run=True)
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), ctx)))        # even with every row committed
    assert len(got) == 3
    assert _names(_inbox(tmp_path)) == ["a.csv"]
    assert "rename" not in server.calls and "mkdir" not in server.calls


def test_a_file_with_no_rows_is_moved_too(tmp_path, server):
    _drop(tmp_path, "empty.csv", "id,name\n")
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert got == [] and _names(_inbox(tmp_path) / "done") == ["empty.csv"]


def test_the_archive_lives_where_move_to_names_it(tmp_path, server):
    archive = tmp_path / "archive"
    _drop(tmp_path, "a.csv", CSV)
    asyncio.run(_collect(_cls(server)(_cfg(tmp_path, move_to=str(archive)), FakeContext())))
    assert _names(archive) == ["a.csv"] and _names(_inbox(tmp_path)) == []


def test_move_to_can_name_a_folder_whose_parents_do_not_exist_yet(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    asyncio.run(_collect(_cls(server)(_cfg(tmp_path, move_to="archive/2026/11"), FakeContext())))
    assert _names(_inbox(tmp_path) / "archive" / "2026" / "11") == ["a.csv"]
    assert _names(_inbox(tmp_path)) == ["archive"]


def test_an_export_with_the_same_bytes_every_hour_is_archived_every_time(tmp_path, server, caplog):
    """orders.csv every hour, and a quiet night: a header and no rows, the same bytes each hour, so the same instance.
    Each one is archived under a name of its own, however many there are, and none stays in the inbox."""
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    quiet = "id,name\n"
    with caplog.at_level(logging.ERROR):
        for _hour in range(12):
            _drop(tmp_path, "orders.csv", quiet)
            asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert _names(_inbox(tmp_path)) == ["done"], "an hourly export stayed in the inbox"
    i = _inst(quiet)
    assert _names(_inbox(tmp_path) / "done") == sorted(
        ["orders.csv", f"orders.csv~{i}"] + [f"orders.csv~{i}~{n}" for n in range(2, 12)])
    assert not [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_long_archive_is_searched_in_a_few_looks_not_one_per_name(tmp_path, server):
    """A year of quiet hours leaves thousands of archived copies of one name: finding a free name for the next one must
    not cost one look at the server per copy."""
    quiet = "id,name\n"
    i = _inst(quiet)
    done = _inbox(tmp_path) / "done"
    done.mkdir()
    for base in ["orders.csv", f"orders.csv~{i}"] + [f"orders.csv~{i}~{n}" for n in range(2, 200)]:
        (done / base).write_text(quiet, encoding="utf-8")
    _drop(tmp_path, "orders.csv", quiet)
    asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert (done / f"orders.csv~{i}~200").is_file() and _names(_inbox(tmp_path)) == ["done"]
    looks = server.calls.count("stat")
    assert looks <= 30, f"{looks} looks at the server to find a free name among 200 taken ones"


def test_a_marker_that_cannot_go_with_its_file_keeps_the_file_where_it_is(tmp_path, server, caplog):
    """The marker moves first because a marker left behind would release the next file of that name before it is
    whole. So a marker the server will not move keeps its file where it is too, and both go on a later look."""
    cfg = _cfg(tmp_path, settle_seconds=3600, require_marker=".ok")
    ctx = FakeContext()
    _drop(tmp_path, "a.csv", CSV)
    _drop(tmp_path, "a.csv.ok", "")
    server.refuse[("rename", "a.csv.ok")] = PermissionError(errno.EACCES, "Permission denied")
    with caplog.at_level(logging.WARNING):
        got = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert len(got) == 3
    assert _names(_inbox(tmp_path)) == ["a.csv", "a.csv.ok", "done"], "the file moved and its marker stayed behind"
    assert any("a.csv.ok" in r.getMessage() for r in caplog.records)
    del server.refuse[("rename", "a.csv.ok")]
    assert asyncio.run(_collect(_cls(server)(cfg, ctx))) == [], "the file was read again"
    assert _names(_inbox(tmp_path)) == ["done"] and _names(_inbox(tmp_path) / "done") == ["a.csv", "a.csv.ok"]


# ── resumption: no row twice, none skipped ───────────────────────────────────────────────────────────────────────────

def test_a_restart_mid_file_sends_no_row_twice_and_skips_none(tmp_path, server):
    body = "id\n" + "".join(f"{n}\n" for n in range(5))
    _drop(tmp_path, "a.csv", body)
    ctx = FakeContext()                     # ONE context across both runs: this is what a restart looks like
    cfg = _cfg(tmp_path)
    first = asyncio.run(_collect(_cls(server)(cfg, ctx), take=2))
    second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    i = _inst(body)
    assert _ids(first) == [f"a.csv@{i}#0", f"a.csv@{i}#1"]
    assert _ids(second) == [f"a.csv@{i}#2", f"a.csv@{i}#3", f"a.csv@{i}#4"], "a gap or a duplicate after the restart"
    assert _names(_inbox(tmp_path) / "done") == ["a.csv"]


def test_a_stop_between_the_last_row_and_the_move_finishes_the_file_and_sends_nothing(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    first = asyncio.run(_collect(_cls(server)(cfg, ctx), take=3))   # every row committed, the move never ran
    assert len(first) == 3 and _names(_inbox(tmp_path)) == ["a.csv"]
    assert asyncio.run(_collect(_cls(server)(cfg, ctx))) == []
    assert _names(_inbox(tmp_path)) == ["done"]


def test_files_that_arrived_while_it_was_down_are_read_after_the_restart(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    asyncio.run(_collect(_cls(server)(cfg, ctx)))
    _drop(tmp_path, "b.csv", "id,name\n4,barbara\n")
    second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert [r.payload["file"] for r in second] == ["b.csv"]


# ── stable ids, and a name used again ────────────────────────────────────────────────────────────────────────────────

def test_the_same_file_put_back_has_the_same_ids(tmp_path, server):
    """An operator moving an archived file back (or a crash before its move) reads it again under the ids it had, so
    the core keeps its rows once."""
    _drop(tmp_path, "a.csv", CSV, at=1_700_000_000)
    cfg = _cfg(tmp_path)
    first = asyncio.run(_collect(_cls(server)(cfg, FakeContext())))
    os.rename(_inbox(tmp_path) / "done" / "a.csv", _inbox(tmp_path) / "a.csv")
    again = asyncio.run(_collect(_cls(server)(cfg, FakeContext())))
    assert _ids(again) == _ids(first)


def test_a_name_used_again_after_its_move_is_a_new_file_with_new_ids(tmp_path, server):
    """`orders.csv` every hour: a new file under an old name must not be taken for the last one."""
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    one, two = "id\n1\n2\n", "id\n3\n4\n"
    _drop(tmp_path, "orders.csv", one)
    first = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    _drop(tmp_path, "orders.csv", two)
    second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert _ids(first) == [f"orders.csv@{_inst(one)}#0", f"orders.csv@{_inst(one)}#1"]
    assert _ids(second) == [f"orders.csv@{_inst(two)}#0", f"orders.csv@{_inst(two)}#1"]
    done = _inbox(tmp_path) / "done"
    assert _names(done) == ["orders.csv", f"orders.csv~{_inst(two)}"], "an archived file was overwritten"
    assert (done / "orders.csv").read_text() == one and (done / f"orders.csv~{_inst(two)}").read_text() == two


def test_the_same_bytes_uploaded_again_have_the_same_ids(tmp_path, server):
    """An upload retried after a timeout: the core sees ids it has, and keeps the rows once."""
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    _drop(tmp_path, "orders.csv", CSV)
    first = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    _drop(tmp_path, "orders.csv", CSV)
    second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert _ids(second) == _ids(first)
    assert _names(_inbox(tmp_path) / "done") == ["orders.csv", f"orders.csv~{_inst(CSV)}"]


def test_mark_keeps_the_mark_suffix_last_when_a_marked_name_is_taken(tmp_path, server):
    ctx = FakeContext()
    cfg = _cfg(tmp_path, after_read="mark")
    _drop(tmp_path, "orders.csv", "id\n1\n")
    asyncio.run(_collect(_cls(server)(cfg, ctx)))
    _drop(tmp_path, "orders.csv", "id\n2\n")
    asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert _names(_inbox(tmp_path)) == ["orders.csv.read", f"orders.csv~{_inst('id' + chr(10) + '2' + chr(10))}.read"]


def test_the_legacy_systems_own_id_is_used_when_named(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, id_field="id"), FakeContext())))
    assert _ids(got) == ["1", "2", "3"]


def test_a_file_replaced_before_it_was_finished_is_read_as_the_new_file(tmp_path, server, caplog):
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    _drop(tmp_path, "a.csv", CSV)
    asyncio.run(_collect(_cls(server)(cfg, ctx), take=1))
    new = "id,name\n7,barbara\n8,frances\n"
    _drop(tmp_path, "a.csv", new)
    with caplog.at_level(logging.WARNING):
        second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert _ids(second) == [f"a.csv@{_inst(new)}#0", f"a.csv@{_inst(new)}#1"]
    assert any("replaced" in r.getMessage() and "1 of 3" in r.getMessage() for r in caplog.records), \
        "the rows of the old file that were never read must be named, not lost silently"


def test_a_file_that_grew_after_it_was_read_continues_under_the_same_ids(tmp_path, server):
    """A writer the settle wait did not catch: its file is checked once more before the move, and its new rows follow
    the old ones under the same file's ids, with no row sent twice."""
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    head = "id\n1\n2\n"
    p = _drop(tmp_path, "a.csv", head)

    def resume_writing(rec):
        if rec.payload["row"] == 1:
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("3\n")

    first = asyncio.run(_collect(_cls(server)(cfg, ctx), after_each=resume_writing))
    assert _names(_inbox(tmp_path)) == ["a.csv"], "a file that changed after it was read was moved"
    second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    i = _inst(head)
    assert _ids(first) == [f"a.csv@{i}#0", f"a.csv@{i}#1"]
    assert _ids(second) == [f"a.csv@{i}#2"]
    assert second[0].payload["sha256"] == hashlib.sha256(b"id\n1\n2\n3\n").hexdigest()
    # its bytes no longer give the instance its rows were read under, so its archive name carries it
    assert _names(_inbox(tmp_path) / "done") == [f"a.csv~{i}"]


def test_a_grown_file_read_again_from_its_archive_keeps_the_ids_it_had(tmp_path, server):
    """A replay takes the instance from the archive name when it carries one, else from the bytes; a file that grew
    after it was first read must not get new ids for its first rows when it is read again."""
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    p = _drop(tmp_path, "a.csv", "id\n1\n2\n")

    def resume_writing(rec):
        if rec.payload["row"] == 1:
            with open(p, "a", encoding="utf-8") as fh:
                fh.write("3\n")

    first = asyncio.run(_collect(_cls(server)(cfg, ctx), after_each=resume_writing))
    second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    archived = _names(_inbox(tmp_path) / "done")
    assert len(archived) == 1
    again = asyncio.run(_rewind_then_collect(_cls(server), cfg, ctx, f"done/{archived[0]}"))
    assert _ids(again) == _ids(first) + _ids(second), "a replay gave a grown file's rows other ids"


def test_a_late_commit_of_a_replaced_files_row_does_not_move_the_new_files_cursor(tmp_path, server):
    """committed() checks the row's file digest: a row of the old bytes, committed after the file was replaced, says
    nothing about the new file's rows."""
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    _drop(tmp_path, "a.csv", CSV)
    old = asyncio.run(_collect(_cls(server)(cfg, ctx), commit=False))
    _drop(tmp_path, "a.csv", "id,name\n7,barbara\n8,frances\n9,ida\n")

    async def a_late_commit():
        src = _cls(server)(cfg, ctx)
        await src.start()
        try:
            gen = src.records()
            first = await gen.__anext__()           # the new file's first row: the cursor describes the new file now
            await src.committed(first)
            await src.committed(old[2])             # the old file's last row, committed late
            await gen.aclose()
        finally:
            await src.stop()

    asyncio.run(a_late_commit())
    rest = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert [r.payload["row"] for r in rest] == [1, 2], "a row of the old file moved the new file's cursor"


def test_a_vanished_file_with_rows_unread_is_named(tmp_path, server, caplog):
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    p = _drop(tmp_path, "a.csv", CSV)
    asyncio.run(_collect(_cls(server)(cfg, ctx), take=1))
    p.unlink()
    with caplog.at_level(logging.WARNING):
        asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert any("a.csv" in r.getMessage() and "1 of its 3" in r.getMessage() for r in caplog.records)
    assert asyncio.run(ctx.state.get("sftp.cursor"))["files"] == {}


# ── a file still being written is not read ───────────────────────────────────────────────────────────────────────────

def test_a_fresh_file_is_read_in_the_same_run_once_it_has_settled(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, settle_seconds=0.3), FakeContext())))
    assert len(got) == 3 and server.calls.count("listdir") == 2, "one look, the settle wait, one more look"


def test_a_file_still_being_written_is_not_read_until_it_settles(tmp_path, server):
    p = _drop(tmp_path, "a.csv", "id,name\n1,ada\n")
    cfg = _cfg(tmp_path, settle_seconds=0.3)

    async def scene():
        stop = asyncio.Event()

        async def writer():
            n = 2
            while not stop.is_set():
                with open(p, "a", encoding="utf-8") as fh:
                    fh.write(f"{n},x\n")
                n += 1
                await asyncio.sleep(0.05)

        task = asyncio.ensure_future(writer())
        try:
            during = await _collect(_cls(server)(cfg, FakeContext()))
        finally:
            stop.set()
            await task
        return during

    during = asyncio.run(scene())
    assert during == [], "a file read while it was still being written loses its tail"
    assert _names(_inbox(tmp_path)) == ["a.csv"]
    rows = p.read_text().count("\n") - 1
    after = asyncio.run(_collect(_cls(server)(cfg, FakeContext())))
    assert len(after) == rows and _names(_inbox(tmp_path)) == ["done"]


def test_a_file_that_changes_while_it_is_downloaded_is_not_read(tmp_path, server):
    p = _drop(tmp_path, "a.csv", CSV)

    def grow(path):
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("4,barbara\n")

    server.on_read = grow
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert got == [] and _names(_inbox(tmp_path)) == ["a.csv"]


def test_a_marker_file_replaces_the_settle_wait_and_travels_with_its_file(tmp_path, server):
    cfg = _cfg(tmp_path, settle_seconds=3600, require_marker=".ok")
    _drop(tmp_path, "a.csv", CSV)
    assert asyncio.run(_collect(_cls(server)(cfg, FakeContext()))) == []
    _drop(tmp_path, "a.csv.ok", "")
    got = asyncio.run(_collect(_cls(server)(cfg, FakeContext())))
    assert len(got) == 3 and all(r.payload["file"] == "a.csv" for r in got), "a marker was read as data"
    assert _names(_inbox(tmp_path)) == ["done"], "a marker left behind would release the next file of that name early"
    assert _names(_inbox(tmp_path) / "done") == ["a.csv", "a.csv.ok"]


def test_temporary_and_hidden_files_are_never_read(tmp_path, server):
    for name in ("b.csv.part", "c.csv.filepart", "d.csv.tmp", ".e.csv", "f.partial"):
        _drop(tmp_path, name, CSV)
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert {r.payload["file"] for r in got} == {"a.csv"}


def test_a_half_written_json_file_is_not_read_until_it_parses(tmp_path, server):
    ctx = FakeContext()
    cfg = _cfg(tmp_path, format="json")
    p = _drop(tmp_path, "a.json", '[{"id": 1}, {"i', at=1_700_000_000)
    assert asyncio.run(_collect(_cls(server)(cfg, ctx))) == []
    assert _names(_inbox(tmp_path)) == ["a.json"]
    saved = asyncio.run(ctx.state.get("sftp.cursor")) or {}
    assert not saved.get("files"), "a file that gave no rows left a cursor"
    p.write_text('[{"id": 1}, {"id": 2}]', encoding="utf-8")
    got = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert [r.payload["data"] for r in got] == [{"id": 1}, {"id": 2}]


# ── the formats ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fmt,name,body,first", [
    ("json", "a.json", '[{"id": 1}, {"id": 2}]', {"id": 1}),
    ("json", "b.json", '{"exported_at": "x", "items": [{"id": 1}, {"id": 2}]}', {"id": 1}),
    ("jsonl", "a.jsonl", '{"id": 1}\n{"id": 2}\n', {"id": 1}),
    ("xml", "a.xml", '<rows><row id="1"><name>ada</name></row><row id="2"><name>grace</name></row></rows>',
     {"id": "1", "name": "ada"}),
])
def test_each_format_gives_its_rows(tmp_path, server, fmt, name, body, first):
    _drop(tmp_path, name, body)
    got = asyncio.run(check_source(_cls(server), _cfg(tmp_path, format=fmt, after_read="leave"), limit=10))
    assert len(got) == 2 and got[0].payload["data"] == first


def test_csv_takes_a_delimiter(tmp_path, server):
    _drop(tmp_path, "a.csv", "id;name\n1;ada\n")
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, delimiter=";"), FakeContext())))
    assert got[0].payload["data"] == {"id": "1", "name": "ada"}


def test_a_byte_order_mark_is_not_part_of_the_first_column(tmp_path, server):
    _drop(tmp_path, "a.csv", "﻿id,name\n1,ada\n")
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert got[0].payload["data"] == {"id": "1", "name": "ada"}


def test_the_encoding_can_be_named(tmp_path, server):
    _drop(tmp_path, "a.csv", "id,name\n1,M\xfcller\n".encode("latin-1"))
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, encoding="latin-1"), FakeContext())))
    assert got[0].payload["data"]["name"] == "Müller"


@pytest.mark.parametrize("body", [
    # an entity declaration (the billion laughs): refused, never expanded
    '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    '<rows><row><v>&b;</v></row></rows>',
    # an external entity: refused, the file it names is never opened
    '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><rows><row><v>&x;</v></row></rows>',
])
def test_xml_with_an_entity_is_refused_and_left_where_it_is(tmp_path, server, body, caplog):
    _drop(tmp_path, "a.xml", body)
    with caplog.at_level(logging.WARNING):
        got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, format="xml"), FakeContext())))
    assert got == [] and _names(_inbox(tmp_path)) == ["a.xml"]
    assert any("a.xml" in r.getMessage() for r in caplog.records)


def test_an_unreadable_file_does_not_stop_the_files_behind_it(tmp_path, server):
    _drop(tmp_path, "b.json", "{this is not json")
    _drop(tmp_path, "c.json", '[{"id": 9}]')
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, format="json"), FakeContext())))
    assert [r.payload["data"] for r in got] == [{"id": 9}]
    assert _names(_inbox(tmp_path)) == ["b.json", "done"], "an unreadable file is left for a person, not archived"


def test_an_unreadable_file_is_downloaded_again_only_once_it_changes(tmp_path, server):
    p = _drop(tmp_path, "b.json", "{this is not json", at=1_700_000_000)
    src = _cls(server)(_cfg(tmp_path, format="json"), FakeContext())

    async def three_looks():
        await src.start()
        try:
            out = []
            for step in range(3):
                if step == 2:
                    p.write_text('[{"id": 1}]', encoding="utf-8")
                async for r in src.records():          # the runtime calls records() again after it ends
                    out.append(r)
                    await src.committed(r)
            return out
        finally:
            await src.stop()

    got = asyncio.run(three_looks())
    assert server.calls.count("read") == 2, "an unchanged unreadable file was downloaded on every look"
    assert [r.payload["data"] for r in got] == [{"id": 1}]


# ── a refusal from the server is one file's problem, not the source's ───────────────────────────────────────────────

REFUSALS = [pytest.param(lambda: PermissionError(errno.EACCES, "Permission denied"), id="permission-denied"),
            pytest.param(lambda: RemoteError("Failure"), id="sharing-violation")]


async def _looks(src, n, before_each=None):
    """n looks by ONE source, as the runtime calls records() again after it ends."""
    await src.start()
    out = []
    try:
        for look in range(n):
            if before_each is not None:
                before_each(look)
            async for r in src.records():
                out.append(r)
                await src.committed(r)
    finally:
        await src.stop()
    return out


@pytest.mark.parametrize("refusal", REFUSALS)
def test_a_file_the_server_refuses_does_not_stop_the_files_behind_it(tmp_path, server, refusal, caplog):
    """A file the server will not open (written 0600 by another account, or still held by its writer on a Windows
    server) is named in the log once and passed over; the files behind it are read. It is not given up on: a lock
    lifts without the file's size or time changing, so every later look tries it again."""
    _drop(tmp_path, "a.csv", CSV, at=1_700_000_000)
    _drop(tmp_path, "b.csv", "id,name\n4,barbara\n")
    server.refuse[("read", "a.csv")] = refusal()

    def lift_on_the_third_look(look):
        if look == 2:
            del server.refuse[("read", "a.csv")]

    with caplog.at_level(logging.WARNING):
        got = asyncio.run(_looks(_cls(server)(_cfg(tmp_path), FakeContext()), 3, lift_on_the_third_look))
    assert [r.payload["file"] for r in got] == ["b.csv", "a.csv", "a.csv", "a.csv"]
    assert _names(_inbox(tmp_path) / "done") == ["a.csv", "b.csv"] and _names(_inbox(tmp_path)) == ["done"]
    said = [r.getMessage() for r in caplog.records if "a.csv" in r.getMessage() and "refused" in r.getMessage()]
    assert len(said) == 1, f"a refusal must be named once while it lasts, not on every look: {said}"


@pytest.mark.parametrize("refusal", REFUSALS)
def test_a_replay_the_server_refuses_waits_and_the_inbox_is_read_meanwhile(tmp_path, server, refusal):
    """A replay asked for an archived file the server now refuses (its permissions changed): the replay waits, kept in
    the cursor, and the inbox is read meanwhile; once the server lets it be read, it is read under the ids it had."""
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    _drop(tmp_path, "a.csv", CSV)
    first = asyncio.run(_collect(_cls(server)(cfg, ctx)))              # read, and moved into done/

    async def rewind():
        src = _cls(server)(cfg, ctx)
        await src.start()
        try:
            await src.rewind("done/a.csv")
        finally:
            await src.stop()

    asyncio.run(rewind())
    server.refuse[("read", "a.csv")] = refusal()                       # done/a.csv is refused now
    _drop(tmp_path, "b.csv", "id,name\n4,barbara\n")
    meanwhile = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert [r.payload["file"] for r in meanwhile] == ["b.csv"]
    assert list(asyncio.run(ctx.state.get("sftp.cursor"))["replay"]) == [str(_inbox(tmp_path) / "done" / "a.csv")]
    del server.refuse[("read", "a.csv")]
    later = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    assert _ids(later) == _ids(first)


# ── what the core keeps, and where the work is done ──────────────────────────────────────────────────────────────────

def test_a_csv_row_with_more_fields_than_its_header_keeps_them_under_extra(tmp_path, server):
    """Legacy exports end a data line with a delimiter the header lacks ("1,ada," under "id,name"), or leave a comma
    unquoted in a free-text field. The fields beyond the header are kept, as a list under "_extra", so every key of a
    row is a string: the core keeps a record as JSON with its keys sorted, which a key of None stops."""
    from theprotocol.proxy.outbox import _dump
    from theprotocol.proxy.runtime import record_doc
    _drop(tmp_path, "a.csv", "id,name\n1,ada,\n2,grace,x,y\n3,edsger\n")
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert [r.payload["data"] for r in got] == [{"id": "1", "name": "ada", "_extra": [""]},
                                               {"id": "2", "name": "grace", "_extra": ["x", "y"]},
                                               {"id": "3", "name": "edsger"}]
    for r in got:
        assert json.loads(_dump(record_doc(r)))["payload"]["data"] == r.payload["data"]


class _ForTheCore(SftpSource):
    """The source as the core loads it by name, on the local stand-in (a test sets `transport`)."""


def test_the_running_proxy_takes_every_row_of_such_a_csv(tmp_path, server, monkeypatch):
    """The same file through the core's own loop (the fake registry of the core's tests): every row attested, and
    the source never failed."""
    import proxy_fake as F
    from theprotocol.proxy.runtime import Proxy
    from theprotocol.proxy.spec import parse
    monkeypatch.setattr(_ForTheCore, "transport", server)
    monkeypatch.setitem(plugins.BUILTINS["source"], "sftp", f"{__name__}:_ForTheCore")
    _drop(tmp_path, "a.csv", "id,name\n1,ada,\n2,grace,x,y\n3,edsger\n")
    doc = F.spec_doc(tmp_path, sources={"exports": {"type": "sftp", "config": _cfg(tmp_path)}},
                     mappings=[{"name": "m", "version": 1, "from": "exports", "to": "attest",
                                "fields": {"value": "$.payload.data.id", "id": "$.record_id"}}])
    reg = F.FakeRegistry()
    p = Proxy(parse(doc, base=tmp_path), transport=reg.transport, service=False, poll_s=0.01)

    async def drive():
        try:
            await asyncio.wait_for(p.run(until_idle=True), timeout=10)
        except asyncio.TimeoutError:
            pass                                    # a source that keeps failing never lets the proxy go idle

    try:
        asyncio.run(drive())
        errors = {k: v for k, v in p.counters.items() if k[0] == "tp_proxy_source_errors_total"}
    finally:
        p.close()
    assert not errors, f"the source failed in the core: {errors}"
    assert [e["attestation_data"]["claim"]["value"] for e in reg.effects] == ["1", "2", "3"]
    assert _names(_inbox(tmp_path) / "done") == ["a.csv"]


def test_a_files_rows_are_read_out_in_a_worker_thread_not_on_the_event_loop(tmp_path, server, monkeypatch):
    """A 64 MiB export takes seconds to hash and parse: on the event loop that would stall the proxy's other sources,
    its dispatcher and its /health for as long."""
    loop_thread = threading.get_ident()
    where = []
    real = SftpSource._rows

    def spy(self, data):
        where.append(threading.get_ident())
        return real(self, data)

    monkeypatch.setattr(SftpSource, "_rows", spy)
    _drop(tmp_path, "a.csv", CSV)
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert len(got) == 3 and where and loop_thread not in where, "the rows were parsed on the event loop's thread"


def test_a_file_larger_than_max_bytes_is_not_read_and_says_so(tmp_path, server, caplog):
    _drop(tmp_path, "a.csv", CSV)
    with caplog.at_level(logging.WARNING):
        got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, max_bytes=10), FakeContext())))
    assert got == [] and "read" not in server.calls and _names(_inbox(tmp_path)) == ["a.csv"]
    assert any("max_bytes" in r.getMessage() for r in caplog.records)


def test_the_suffix_filter_and_directories(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    _drop(tmp_path, "notes.txt", "ignore me")
    (_inbox(tmp_path) / "sub.csv").mkdir()
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path, suffix=".csv"), FakeContext())))
    assert {r.payload["file"] for r in got} == {"a.csv"}


# ── replay (Source.rewind) ───────────────────────────────────────────────────────────────────────────────────────────

async def _rewind_then_collect(cls, cfg, ctx, point):
    src = cls(cfg, ctx)
    await src.start()
    try:
        await src.rewind(point)
    finally:
        await src.stop()
    return await _collect(cls(cfg, ctx))


def test_rewind_reads_a_file_in_the_inbox_again_from_a_row(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()
    cfg = _cfg(tmp_path, after_read="leave")
    first = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    again = asyncio.run(_rewind_then_collect(_cls(server), cfg, ctx, "a.csv#1"))
    assert _ids(again) == _ids(first)[1:]


def test_rewind_reads_an_archived_file_again_where_it_is_with_the_same_ids(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    first = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    again = asyncio.run(_rewind_then_collect(_cls(server), cfg, ctx, "done/a.csv"))
    assert _ids(again) == _ids(first) and [r.payload for r in again] == [r.payload for r in first]
    assert _names(_inbox(tmp_path)) == ["done"] and _names(_inbox(tmp_path) / "done") == ["a.csv"]
    assert asyncio.run(_collect(_cls(server)(cfg, ctx))) == [], "a replay that ended was read a third time"


def test_rewind_of_a_tagged_archive_name_keeps_the_original_name_in_the_ids(tmp_path, server):
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    _drop(tmp_path, "orders.csv", "id\n1\n")
    asyncio.run(_collect(_cls(server)(cfg, ctx)))
    second_body = "id\n2\n3\n"
    _drop(tmp_path, "orders.csv", second_body)
    second = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    again = asyncio.run(_rewind_then_collect(_cls(server), cfg, ctx, f"done/orders.csv~{_inst(second_body)}#1"))
    assert _ids(again) == _ids(second)[1:]


def test_rewind_of_a_marked_file(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()
    cfg = _cfg(tmp_path, after_read="mark")
    first = asyncio.run(_collect(_cls(server)(cfg, ctx)))
    again = asyncio.run(_rewind_then_collect(_cls(server), cfg, ctx, "a.csv.read#2"))
    assert _ids(again) == _ids(first)[2:] and _names(_inbox(tmp_path)) == ["a.csv.read"]


@pytest.mark.parametrize("bad", ["", "   ", "a.csv#-1", "a.csv#x", "nosuch.csv", "done/nosuch.csv", "../a.csv"])
def test_rewind_refuses_a_point_it_cannot_honour(tmp_path, server, bad):
    _drop(tmp_path, "a.csv", CSV)
    src = _cls(server)(_cfg(tmp_path), FakeContext())
    with pytest.raises(PluginError):
        asyncio.run(src.rewind(bad))


@pytest.mark.parametrize("point", ["../outside.csv", "/{tmp}/outside.csv", "done/../../outside.csv"])
def test_rewind_refuses_a_file_outside_the_inbox_and_its_archive_even_when_it_exists(tmp_path, server, point):
    (tmp_path / "outside.csv").write_text(CSV, encoding="utf-8")       # beside the inbox, not in it
    ctx = FakeContext()
    src = _cls(server)(_cfg(tmp_path), ctx)
    with pytest.raises(PluginError):
        asyncio.run(src.rewind(point.replace("/{tmp}", str(tmp_path))))
    assert not (asyncio.run(ctx.state.get("sftp.cursor")) or {}).get("replay"), "a replay job was kept"


# ── the poll, and a connection that is lost ──────────────────────────────────────────────────────────────────────────

def test_it_keeps_polling_and_reads_a_file_that_arrives_later(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    cfg = _cfg(tmp_path, poll_seconds=0.05)

    async def scene():
        src = _cls(server)(cfg, FakeContext())
        await src.start()
        got = []
        gen = src.records()
        try:
            while len(got) < 4:
                r = await asyncio.wait_for(gen.__anext__(), timeout=10)
                got.append(r)
                await src.committed(r)
                if len(got) == 3:
                    _drop(tmp_path, "b.csv", "id,name\n4,barbara\n")
        finally:
            await gen.aclose()
            await src.stop()
        return got

    got = asyncio.run(scene())
    assert [r.payload["file"] for r in got] == ["a.csv"] * 3 + ["b.csv"]


def test_a_connection_lost_while_it_waited_is_opened_again(tmp_path, server):
    """An idle connection the server closed (or a server restart between polls) costs one more connection, not an
    error."""
    _drop(tmp_path, "a.csv", CSV)
    server.fail["listdir"] = 1
    got = asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))
    assert len(got) == 3 and server.opened == 2


def test_a_connection_that_stays_lost_is_an_error_the_core_retries(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    server.fail["listdir"] = 2
    with pytest.raises(ConnectionError):
        asyncio.run(_collect(_cls(server)(_cfg(tmp_path), FakeContext())))


def test_a_connection_lost_at_the_move_finishes_the_file_on_the_next_run_without_a_row_twice(tmp_path, server):
    _drop(tmp_path, "a.csv", CSV)
    ctx = FakeContext()
    cfg = _cfg(tmp_path)
    server.fail["rename"] = 1
    src = _cls(server)(cfg, ctx)
    got = []

    async def run_twice():
        await src.start()
        try:
            with pytest.raises(ConnectionError):
                async for r in src.records():
                    got.append(r)
                    await src.committed(r)
            async for r in src.records():                  # what the core does after a source fails: again, later
                got.append(r)
                await src.committed(r)
        finally:
            await src.stop()

    asyncio.run(run_twice())
    assert len(got) == 3 and len(set(_ids(got))) == 3
    assert _names(_inbox(tmp_path)) == ["done"]
