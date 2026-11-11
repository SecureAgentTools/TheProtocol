"""V0659 (l): the SFTP poll source against a real OpenSSH server.

Skipped unless TP_SFTP_TEST_HOST names one, so the default suite stays hermetic. The driver beside this file runs
them, on a host with docker (from theprotocol-sdk/):

    sh tests/sftp_server/run.sh 3.10        # or 3.14; any further arguments go to pytest

It starts atmoz/sftp (OpenSSH's internal-sftp) in a container on a docker network of its own, with a host key and a
login key it makes at run time (tests/sftp_server/sshd_config is the server's configuration), runs these tests in
python:<version>-bookworm, and removes everything it made at the end. It passes:

    TP_SFTP_TEST_HOST, TP_SFTP_TEST_PORT (default 22), TP_SFTP_TEST_USER
    TP_SFTP_TEST_KEY          the login key's private half (a file)
    TP_SFTP_TEST_KNOWN_HOSTS  a known_hosts file holding the server's host key
    TP_SFTP_TEST_DIR          a directory on the server the user can write
    TP_SFTP_TEST_RESTART      optional: a file a supervisor watches. The test writes "restart" into it; the supervisor
                              restarts the server and writes "restarted" once the server answers again.
    TP_SFTP_TEST_2FA_USER     optional: an account the same key logs in to only as a first step (the server then asks
                              for a password: AuthenticationMethods publickey,password).

Each test works in a directory of its own under TP_SFTP_TEST_DIR and writes its files as the legacy system would: over
SFTP, on a connection of its own.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid

import pytest

from theprotocol.proxy.sources.sftp import SftpSource   # first: on a tree without the source, this file is red

paramiko = pytest.importorskip("paramiko")

from theprotocol.proxy.plugins import PluginError  # noqa: E402
from theprotocol.proxy.testing import FakeContext, check_source  # noqa: E402

ENV = os.environ
pytestmark = pytest.mark.skipif(not ENV.get("TP_SFTP_TEST_HOST"),
                                reason="no SFTP server: set TP_SFTP_TEST_HOST and the rest (see the module docstring)")

KEY_REF = "env:TP_SFTP_TEST_LOGIN_KEY"          # a reference, resolved by the FakeContext, never by the environment
KNOWN_REF = "env:TP_SFTP_TEST_KNOWN_HOSTS_TEXT"


def _env():
    return {"host": ENV["TP_SFTP_TEST_HOST"], "port": int(ENV.get("TP_SFTP_TEST_PORT") or 22),
            "user": ENV.get("TP_SFTP_TEST_USER") or "proxy", "key": ENV["TP_SFTP_TEST_KEY"],
            "known_hosts": ENV["TP_SFTP_TEST_KNOWN_HOSTS"], "dir": (ENV.get("TP_SFTP_TEST_DIR") or "inbox").rstrip("/")}


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class Legacy:
    """The legacy system's side: its own SFTP connection, writing the files the source reads."""

    def __init__(self) -> None:
        e = _env()
        self.dir = f"{e['dir']}/t-{uuid.uuid4().hex[:10]}"
        self._open()
        self.sftp.mkdir(self.dir)

    def _open(self) -> None:
        e = _env()
        self.client = paramiko.SSHClient()
        self.client.load_host_keys(e["known_hosts"])
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
        self.client.connect(e["host"], port=e["port"], username=e["user"], key_filename=e["key"],
                            look_for_keys=False, allow_agent=False, timeout=20)
        self.sftp = self.client.open_sftp()

    def reopen(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            pass
        self._open()

    def put(self, name: str, body) -> None:
        with self.sftp.open(f"{self.dir}/{name}", "wb") as fh:
            fh.write(body.encode("utf-8") if isinstance(body, str) else body)

    def ls(self, sub: str = ""):
        return sorted(self.sftp.listdir(f"{self.dir}/{sub}".rstrip("/")))

    def get(self, rel: str) -> bytes:
        with self.sftp.open(f"{self.dir}/{rel}", "rb") as fh:
            return fh.read()

    def close(self) -> None:
        def wipe(path: str) -> None:
            import stat
            for a in self.sftp.listdir_attr(path):
                p = f"{path}/{a.filename}"
                if stat.S_ISDIR(a.st_mode or 0):
                    wipe(p)
                    self.sftp.rmdir(p)
                else:
                    self.sftp.remove(p)
        try:
            wipe(self.dir)
            self.sftp.rmdir(self.dir)
        except Exception:  # noqa: BLE001 - a test directory left behind is the driver's to clean
            pass
        self.client.close()


@pytest.fixture
def legacy():
    lg = Legacy()
    try:
        yield lg
    finally:
        lg.close()


def _cfg(legacy: Legacy, **kw):
    e = _env()
    cfg = {"host": e["host"], "port": e["port"], "username": e["user"], "private_key": KEY_REF,
           "known_hosts": e["known_hosts"], "path": legacy.dir, "format": "csv", "settle_seconds": 0,
           "poll_seconds": 0, "timeout_seconds": 20}
    cfg.update(kw)
    return cfg


def _ctx(**secrets) -> FakeContext:
    return FakeContext(secrets={KEY_REF: _read(_env()["key"]), **secrets})


def _inst(body) -> str:
    return hashlib.sha256(body.encode("utf-8") if isinstance(body, str) else body).hexdigest()[:16]


async def _collect(src, *, take=None):
    out = []
    await src.start()
    try:
        async for r in src.records():
            out.append(r)
            await src.committed(r)
            if take is not None and len(out) >= take:
                break
    finally:
        await src.stop()
    return out


def _ids(records):
    return [r.record_id for r in records]


def _fresh_openssh_key():
    """A login key no server knows, made now (never written to the repository)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    key = ed25519.Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    return private, public


def _host_name() -> str:
    e = _env()
    return e["host"] if e["port"] == 22 else f"[{e['host']}]:{e['port']}"


# ── the rows, and the file moved once read ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fmt,name,body,rows", [
    ("csv", "orders.csv", "id,qty\n1,5\n2,7\n", [{"id": "1", "qty": "5"}, {"id": "2", "qty": "7"}]),
    ("json", "orders.json", '[{"id": 1, "qty": 5}, {"id": 2, "qty": 7}]', [{"id": 1, "qty": 5}, {"id": 2, "qty": 7}]),
    ("xml", "orders.xml", '<orders><order id="1"><qty>5</qty></order><order id="2"><qty>7</qty></order></orders>',
     [{"id": "1", "qty": "5"}, {"id": "2", "qty": "7"}]),
])
def test_server_rows_from_each_format_and_the_file_moved_once_read(legacy, fmt, name, body, rows):
    legacy.put(name, body)
    got = asyncio.run(check_source(SftpSource, _cfg(legacy, format=fmt), ctx=_ctx(), limit=10, twice=False))
    assert _ids(got) == [f"{name}@{_inst(body)}#0", f"{name}@{_inst(body)}#1"]
    assert [r.payload["data"] for r in got] == rows
    assert legacy.ls() == ["done"] and legacy.ls("done") == [name]
    assert legacy.get(f"done/{name}") == body.encode("utf-8")


def test_server_mark_renames_the_file_in_place(legacy):
    legacy.put("orders.csv", "id\n1\n")
    got = asyncio.run(_collect(SftpSource(_cfg(legacy, after_read="mark"), _ctx())))
    assert len(got) == 1 and legacy.ls() == ["orders.csv.read"]


# ── the server is checked before anything is read ────────────────────────────────────────────────────────────────────

def test_server_missing_from_known_hosts_is_refused_before_a_connection(legacy):
    legacy.put("orders.csv", "id\n1\n")
    lines = [ln for ln in _read(_env()["known_hosts"]).splitlines() if ln.strip() and not ln.startswith("#")]
    elsewhere = "\n".join("someone-else.example " + ln.split(None, 1)[1] for ln in lines) + "\n"
    src = SftpSource(_cfg(legacy, known_hosts=KNOWN_REF), _ctx(**{KNOWN_REF: elsewhere}))
    with pytest.raises(PluginError, match="known_hosts has no key"):
        asyncio.run(_collect(src))
    assert legacy.ls() == ["orders.csv"]


def test_server_presenting_another_host_key_is_refused(legacy):
    """A rebuilt server, or someone in between: the same name with another key is never accepted."""
    legacy.put("orders.csv", "id\n1\n")
    _, other_public = _fresh_openssh_key()
    src = SftpSource(_cfg(legacy, known_hosts=KNOWN_REF), _ctx(**{KNOWN_REF: f"{_host_name()} {other_public}\n"}))
    with pytest.raises(PluginError, match="does not match"):
        asyncio.run(_collect(src))
    assert legacy.ls() == ["orders.csv"]


def test_server_refuses_a_login_key_it_does_not_know(legacy):
    legacy.put("orders.csv", "id\n1\n")
    private, _ = _fresh_openssh_key()
    src = SftpSource(_cfg(legacy), FakeContext(secrets={KEY_REF: private}))
    with pytest.raises(PluginError, match="login key"):
        asyncio.run(_collect(src))
    assert legacy.ls() == ["orders.csv"]


@pytest.mark.skipif(not ENV.get("TP_SFTP_TEST_2FA_USER"), reason="no account that asks for a second step")
def test_server_an_account_that_asks_for_a_password_after_the_key_is_refused_and_nobody_is_prompted(legacy,
                                                                                                    monkeypatch):
    prompted = []
    monkeypatch.setattr("builtins.input", lambda *a: prompted.append(a) or "")
    src = SftpSource(_cfg(legacy, username=ENV["TP_SFTP_TEST_2FA_USER"]), _ctx())
    with pytest.raises(PluginError, match="second step") as e:
        asyncio.run(_collect(src))
    assert "password" in str(e.value) and prompted == []


def test_server_a_file_name_that_is_not_utf8_is_named_as_the_cause(legacy):
    """A legacy system on an ISO-8859-1 box names a file Müller.csv in latin-1 bytes; paramiko reads listed names as
    UTF-8 only, so the listing cannot be read until the file is renamed. The source says that, not a codec error."""
    legacy.put("a.csv", "id\n1\n")
    latin1 = legacy.dir.encode() + b"/M\xfcller.csv"
    with legacy.sftp.open(latin1, "wb") as fh:
        fh.write(b"id\n2\n")
    try:
        with pytest.raises(PluginError, match="UTF-8"):
            asyncio.run(_collect(SftpSource(_cfg(legacy), _ctx())))
    finally:
        legacy.sftp.remove(latin1)                  # the fixture's own listing reads names as UTF-8 too
    got = asyncio.run(_collect(SftpSource(_cfg(legacy), _ctx())))
    assert [r.payload["file"] for r in got] == ["a.csv"]


# ── a file still being written is not read ───────────────────────────────────────────────────────────────────────────

def test_server_a_half_written_upload_is_not_read_until_it_is_complete(legacy):
    fh = legacy.sftp.open(f"{legacy.dir}/orders.csv", "wb")
    fh.write(b"id,qty\n1,5\n2,")                    # the writer is in the middle of a row
    fh.flush()
    cfg = _cfg(legacy, settle_seconds=1.0)

    async def during():
        stop = asyncio.Event()

        async def writer():                          # a large upload over a slow line: it keeps coming
            n = 3
            while not stop.is_set():
                await asyncio.to_thread(fh.write, f"7\n{n},".encode())
                await asyncio.to_thread(fh.flush)
                n += 1
                await asyncio.sleep(0.25)

        task = asyncio.ensure_future(writer())
        try:
            return await _collect(SftpSource(cfg, _ctx()))
        finally:
            stop.set()
            await task

    got = asyncio.run(during())
    assert got == [], "rows of a file still being written were read"
    assert legacy.ls() == ["orders.csv"], "a file still being written was moved: its tail would land in the archive"
    fh.write(b"9\n")
    fh.close()
    after = asyncio.run(_collect(SftpSource(cfg, _ctx())))
    body = legacy.get("done/orders.csv").decode()
    assert len(after) == body.count("\n") - 1 and len(set(_ids(after))) == len(after)
    assert after[-1].payload["data"]["qty"] == "9", "the last row was read before it was complete"
    assert legacy.ls() == ["done"]


def test_server_a_half_written_json_upload_is_not_read_until_it_parses(legacy):
    ctx = _ctx()
    cfg = _cfg(legacy, format="json")
    legacy.put("orders.json", '[{"id": 1}, {"i')
    assert asyncio.run(_collect(SftpSource(cfg, ctx))) == []
    assert legacy.ls() == ["orders.json"]
    legacy.put("orders.json", '[{"id": 1}, {"id": 2}]')
    got = asyncio.run(_collect(SftpSource(cfg, ctx)))
    assert [r.payload["data"] for r in got] == [{"id": 1}, {"id": 2}] and legacy.ls() == ["done"]


def test_server_a_marker_upload_releases_its_file(legacy):
    cfg = _cfg(legacy, require_marker=".ok", settle_seconds=3600)
    legacy.put("orders.csv", "id\n1\n2\n")
    assert asyncio.run(_collect(SftpSource(cfg, _ctx()))) == []
    legacy.put("orders.csv.ok", "")
    got = asyncio.run(_collect(SftpSource(cfg, _ctx())))
    assert len(got) == 2 and legacy.ls() == ["done"] and legacy.ls("done") == ["orders.csv", "orders.csv.ok"]


# ── resumption: no row twice, none skipped ───────────────────────────────────────────────────────────────────────────

BODY5 = "id\n" + "".join(f"{n}\n" for n in range(5))


def _five(inst):
    return [f"orders.csv@{inst}#{n}" for n in range(5)]


def test_server_a_proxy_restart_mid_file_sends_no_row_twice_and_skips_none(legacy):
    legacy.put("orders.csv", BODY5)
    ctx = _ctx()
    first = asyncio.run(_collect(SftpSource(_cfg(legacy), ctx), take=2))
    assert legacy.ls() == ["orders.csv"]
    second = asyncio.run(_collect(SftpSource(_cfg(legacy), ctx)))
    assert _ids(first) + _ids(second) == _five(_inst(BODY5))
    assert legacy.ls() == ["done"]


def test_server_a_connection_lost_mid_file_resumes_without_a_gap(legacy):
    legacy.put("orders.csv", BODY5)
    src = SftpSource(_cfg(legacy), _ctx())
    got = []

    async def scene():
        await src.start()
        try:
            gen = src.records()
            for _ in range(2):
                r = await gen.__anext__()
                got.append(r)
                await src.committed(r)
            dropped = src._conn
            dropped.close()                         # the connection drops under the source mid-file
            with pytest.raises(ConnectionError):
                while True:
                    r = await gen.__anext__()       # the rest of the file is in hand; its move needs the server
                    got.append(r)
                    await src.committed(r)
            async for r in src.records():           # what the core does after a source fails: again, later
                got.append(r)
                await src.committed(r)
            assert src._conn is not None and src._conn is not dropped, "no new connection was opened"
        finally:
            await src.stop()

    asyncio.run(scene())
    assert _ids(got) == _five(_inst(BODY5))
    assert legacy.ls() == ["done"]


@pytest.mark.skipif(not ENV.get("TP_SFTP_TEST_RESTART"), reason="no supervisor to restart the server")
def test_server_restarted_mid_file_resumes_without_a_gap(legacy):
    legacy.put("orders.csv", BODY5)
    src = SftpSource(_cfg(legacy), _ctx())
    got, conns = [], []

    async def before():
        await src.start()
        gen = src.records()
        for _ in range(2):
            r = await gen.__anext__()
            got.append(r)
            await src.committed(r)
        await gen.aclose()                          # the source stops mid-file, its connection still open
        conns.append(src._conn)

    async def after():
        try:
            async for r in src.records():           # the old connection is dead: the source opens a new one
                got.append(r)
                await src.committed(r)
            conns.append(src._conn)
        finally:
            await src.stop()

    asyncio.run(before())
    sig = ENV["TP_SFTP_TEST_RESTART"]
    with open(sig, "w", encoding="utf-8") as fh:
        fh.write("restart\n")
    deadline = time.time() + 120
    while _read(sig).strip() != "restarted":
        if time.time() > deadline:
            pytest.fail("the supervisor did not restart the SFTP server within 120 s")
        time.sleep(0.5)
    legacy.reopen()
    asyncio.run(after())
    assert conns[0] is not None and conns[1] is not None and conns[1] is not conns[0], "no new connection was opened"
    assert _ids(got) == _five(_inst(BODY5))
    assert legacy.ls() == ["done"]


# ── a name used again, and the replay ────────────────────────────────────────────────────────────────────────────────

def test_server_a_name_used_again_after_its_move_is_a_new_file(legacy):
    ctx = _ctx()
    one, two = "id\n1\n", "id\n2\n"
    legacy.put("orders.csv", one)
    first = asyncio.run(_collect(SftpSource(_cfg(legacy), ctx)))
    legacy.put("orders.csv", two)
    second = asyncio.run(_collect(SftpSource(_cfg(legacy), ctx)))
    assert _ids(first) == [f"orders.csv@{_inst(one)}#0"] and _ids(second) == [f"orders.csv@{_inst(two)}#0"]
    assert legacy.ls("done") == ["orders.csv", f"orders.csv~{_inst(two)}"]
    assert legacy.get("done/orders.csv") == one.encode(), "an archived file was overwritten"


def test_server_rewind_reads_an_archived_file_again_where_it_is(legacy):
    ctx = _ctx()
    legacy.put("orders.csv", BODY5)
    first = asyncio.run(_collect(SftpSource(_cfg(legacy), ctx)))

    async def rewind_then_read():
        src = SftpSource(_cfg(legacy), ctx)
        await src.start()
        try:
            await src.rewind("done/orders.csv#3")
        finally:
            await src.stop()
        return await _collect(SftpSource(_cfg(legacy), ctx))

    again = asyncio.run(rewind_then_read())
    assert _ids(again) == _ids(first)[3:]
    assert legacy.ls() == ["done"] and legacy.ls("done") == ["orders.csv"]
