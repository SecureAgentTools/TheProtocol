"""V0659 (l): the SFTP poll source's transport over paramiko, with no SFTP server.

What the source leans on paramiko for, tested where it lives (`sources/sftp.py::_Paramiko`):

* The checks before anything is read: the host key against known_hosts (a missing host, a changed key, a key that
  known_hosts marks @revoked), and the login, key only. These run against a real SSH server in this process
  (paramiko's own server mode, on a loopback port, with keys made now): it speaks the SSH protocol and no SFTP, which
  is all these checks need.
* How the server's answers become the exceptions the source acts on: "no such file", "permission denied" and a plain
  failure on a live connection are refusals of one file; a connection that is gone is a ConnectionError, which the
  source answers by connecting again. These run on a fake SFTP client.

Needs paramiko (the proxy-sftp extra); without it the file is skipped. The same transport against OpenSSH in a
container is tests/test_proxy_source_sftp_server.py.
"""
from __future__ import annotations

import asyncio
import errno
import io
import socket
import threading
from types import SimpleNamespace

import pytest

from theprotocol.proxy.plugins import PluginError
from theprotocol.proxy.sources.sftp import RemoteError, SftpSource, _Paramiko
from theprotocol.proxy.testing import FakeContext

paramiko = pytest.importorskip("paramiko")

KEY_REF = "env:TP_TEST_LOGIN_KEY"
KNOWN_REF = "env:TP_TEST_KNOWN_HOSTS"


def _new_key():
    """An Ed25519 key made now: (its private half in OpenSSH form, the paramiko key)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    text = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode()
    return text, paramiko.Ed25519Key.from_private_key(io.StringIO(text))


def _line(names: str, key) -> str:
    return f"{names} {key.get_name()} {key.get_base64()}"


# ── a real SSH server in this process ────────────────────────────────────────────────────────────────────────────────

class _Interface(paramiko.ServerInterface):
    """Takes the one login key it knows; with `second`, the key is only the first step and the account then asks for
    keyboard-interactive or a password, as OpenSSH's AuthenticationMethods publickey,<second> does."""

    def __init__(self, server: "_SshServer") -> None:
        self.server = server

    def get_allowed_auths(self, username):
        return self.server.second or "publickey"

    def check_auth_publickey(self, username, key):
        if key.asbytes() != self.server.login_key.asbytes():
            return paramiko.AUTH_FAILED
        return paramiko.AUTH_PARTIALLY_SUCCESSFUL if self.server.second else paramiko.AUTH_SUCCESSFUL

    def check_auth_interactive(self, username, submethods):
        if self.server.second != "keyboard-interactive":
            return paramiko.AUTH_FAILED
        self.server.asked.append("keyboard-interactive")
        return paramiko.InteractiveQuery("A one-time code", "", ("Code: ", False))

    def check_auth_interactive_response(self, responses):
        return paramiko.AUTH_FAILED

    def check_auth_password(self, username, password):
        self.server.asked.append("password")
        return paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _SshServer:
    def __init__(self, host_key, login_key, second=None) -> None:
        self.host_key, self.login_key, self.second = host_key, login_key, second
        self.asked: list = []
        self._transports: list = []
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(self.host_key)
            self._transports.append(t)
            try:
                t.start_server(server=_Interface(self))
            except (paramiko.SSHException, EOFError, OSError):
                t.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._sock.close()
        for t in self._transports:
            t.close()


@pytest.fixture
def ssh():
    servers = []

    def start(**kw):
        host_text, host_key = _new_key()
        login_text, login_key = _new_key()
        srv = _SshServer(host_key, login_key, **kw)
        srv.login_text = login_text
        srv.host_name = f"[127.0.0.1]:{srv.port}"
        servers.append(srv)
        return srv

    yield start
    for s in servers:
        s.close()


def _source(srv, *, known_hosts=None, login=None) -> SftpSource:
    known = _line(srv.host_name, srv.host_key) if known_hosts is None else known_hosts
    cfg = {"host": "127.0.0.1", "port": srv.port, "username": "proxy", "private_key": KEY_REF,
           "known_hosts": KNOWN_REF, "path": "/outbox", "timeout_seconds": 10}
    return SftpSource(cfg, FakeContext(secrets={KEY_REF: login or srv.login_text, KNOWN_REF: known + "\n"}))


def _open(src):
    conn = _Paramiko.open(src)
    conn.close()
    return conn


# ── the server is checked before anything is read ────────────────────────────────────────────────────────────────────

def test_a_host_missing_from_known_hosts_is_refused_before_a_connection(ssh):
    srv = ssh()
    src = _source(srv, known_hosts=_line("someone-else.example", srv.host_key))
    with pytest.raises(PluginError, match="known_hosts has no key"):
        _Paramiko.check(src)
    with pytest.raises(PluginError, match="known_hosts has no key"):
        _open(src)


def test_a_server_presenting_another_host_key_is_refused_naming_both_fingerprints(ssh):
    srv = ssh()
    _, other = _new_key()
    with pytest.raises(PluginError, match="does not match") as e:
        _open(_source(srv, known_hosts=_line(srv.host_name, other)))
    assert str(e.value).count("SHA256:") == 2


def test_a_login_key_the_server_does_not_know_is_refused(ssh):
    srv = ssh()
    stranger, _ = _new_key()
    with pytest.raises(PluginError, match="did not accept the login key"):
        _open(_source(srv, login=stranger))


@pytest.mark.parametrize("second", ["keyboard-interactive", "password"])
def test_an_account_that_asks_for_a_second_step_is_refused_and_nobody_is_prompted(ssh, monkeypatch, second):
    """Key-based login only: the proxy runs unattended, so a server that takes the key and then asks for a code or a
    password is refused with that reason, and nothing is ever read from the terminal (paramiko's own fallback for a
    second step prints the server's prompt and reads an answer from stdin)."""
    prompted = []
    monkeypatch.setattr("builtins.input", lambda *a: prompted.append(a) or "")
    srv = ssh(second=second)
    with pytest.raises(PluginError, match="second step") as e:
        _open(_source(srv))
    assert second in str(e.value)
    assert prompted == [] and srv.asked == [], "the proxy answered a second step"


def test_a_key_known_hosts_marks_revoked_is_never_accepted(ssh):
    """OpenSSH never accepts a key a @revoked line names, even where another line lists it plainly."""
    srv = ssh()
    known = "\n".join([f"@revoked * {srv.host_key.get_name()} {srv.host_key.get_base64()}",
                       _line(srv.host_name, srv.host_key)])
    with pytest.raises(PluginError, match="revoked"):
        _open(_source(srv, known_hosts=known))


def test_a_revoked_key_presented_beside_a_trusted_one_is_refused_as_revoked(ssh):
    srv = ssh()
    _, trusted = _new_key()
    known = "\n".join([f"@revoked {srv.host_name} {srv.host_key.get_name()} {srv.host_key.get_base64()}",
                       _line(srv.host_name, trusted)])
    with pytest.raises(PluginError, match="revoked"):
        _open(_source(srv, known_hosts=known))


def test_a_cert_authority_line_is_not_taken_for_a_host_key(ssh):
    """This source checks host keys, not host certificates: a @cert-authority line trusts nothing here."""
    srv = ssh()
    known = f"@cert-authority {srv.host_name} {srv.host_key.get_name()} {srv.host_key.get_base64()}"
    with pytest.raises(PluginError, match="known_hosts has no key"):
        _Paramiko.check(_source(srv, known_hosts=known))


@pytest.mark.parametrize("form", ["plain", "hashed", "in-a-list"])
def test_known_hosts_names_a_server_on_a_port_plainly_hashed_or_in_a_list(form):
    """`[host]:port` (as ssh-keyscan -p prints it), its hashed form (HashKnownHosts yes), and one name of several."""
    _, key = _new_key()
    name = "[sftp.erp.example]:2222"
    names = {"plain": name, "hashed": paramiko.HostKeys.hash_host(name), "in-a-list": f"old.example,{name}"}[form]
    cfg = {"host": "sftp.erp.example", "port": 2222, "username": "u", "private_key": KEY_REF,
           "known_hosts": KNOWN_REF, "path": "/o"}
    src = SftpSource(cfg, FakeContext(secrets={KNOWN_REF: _line(names, key) + "\n"}))
    into = paramiko.HostKeys()
    _Paramiko._known(paramiko, src, into)
    assert into.lookup(name)[key.get_name()].asbytes() == key.asbytes()


# ── how the server's answers become the source's exceptions ──────────────────────────────────────────────────────────

class _Sftp:
    """A fake SFTP client: every call answers `error` (raised) or `result`."""

    def __init__(self, error=None, result=None, exists=()):
        self.error, self.result, self.exists = error, result, set(exists)
        self.channel = SimpleNamespace(closed=False)

    def get_channel(self):
        return self.channel

    def _answer(self):
        if self.error is not None:
            raise self.error
        return self.result

    def listdir_attr(self, path):
        return self._answer()

    def getfo(self, path, buf):
        return self._answer()

    def rename(self, old, new):
        return self._answer()

    def mkdir(self, path):
        return self._answer()

    def stat(self, path):
        if path in self.exists:
            return SimpleNamespace(st_size=1, st_mtime=1, st_mode=0o100644)
        raise IOError(errno.ENOENT, "No such file")


def _conn(sftp, *, alive=True) -> _Paramiko:
    transport = SimpleNamespace(is_active=lambda: alive)
    client = SimpleNamespace(get_transport=lambda: transport, close=lambda: None)
    return _Paramiko(paramiko, client, sftp)


@pytest.mark.parametrize("error,alive,expected", [
    (IOError(errno.ENOENT, "No such file"), True, FileNotFoundError),
    (IOError(errno.EACCES, "Permission denied"), True, PermissionError),
    (IOError("Failure"), True, RemoteError),                      # a plain SFTP failure on a live connection
    (IOError("Failure"), False, ConnectionError),                 # the same, once the connection is gone
    (socket.timeout("timed out"), True, ConnectionError),
    (EOFError(), True, ConnectionError),
    (paramiko.SSHException("Server connection dropped"), True, ConnectionError),
])
def test_a_servers_answer_becomes_the_exception_the_source_acts_on(error, alive, expected):
    with pytest.raises(expected):
        _conn(_Sftp(error=error), alive=alive).read("/outbox/a.csv")


def test_stat_answers_none_for_a_file_that_is_not_there():
    assert _conn(_Sftp()).stat("/outbox/gone.csv") is None


def test_a_rename_onto_a_name_that_exists_is_file_exists():
    """SFTP v3 never replaces a name on rename; the server says only "Failure", so the target is looked at."""
    sftp = _Sftp(error=IOError("Failure"), exists={"/outbox/done/a.csv"})
    with pytest.raises(FileExistsError):
        _conn(sftp).rename("/outbox/a.csv", "/outbox/done/a.csv")
    with pytest.raises(RemoteError):
        _conn(_Sftp(error=IOError("Failure"))).rename("/outbox/a.csv", "/outbox/done/b.csv")


def test_a_file_name_that_is_not_utf8_is_named_as_the_cause():
    """paramiko reads the names in a listing as UTF-8 only; a file a latin-1 system named Müller.csv stops the
    listing. The source says so, rather than a bare codec error."""
    bad = UnicodeDecodeError("utf-8", b"M\xfcller.csv", 1, 2, "invalid start byte")
    with pytest.raises(PluginError, match="UTF-8"):
        _conn(_Sftp(error=bad)).listdir("/outbox")


def test_the_source_reports_a_refusal_through_the_transport_seam(tmp_path):
    """The whole path once, through SftpSource with this transport: a refused file is passed over, the listing goes on."""
    entry = SimpleNamespace(filename="a.csv", st_size=4, st_mtime=1, st_mode=0o100644)

    class _Listing(_Sftp):
        def listdir_attr(self, path):
            return [entry]

        def stat(self, path):
            return entry

    conn = _conn(_Listing(error=IOError(errno.EACCES, "Permission denied")))
    transport = SimpleNamespace(check=lambda src: None, open=lambda src: conn)
    cls = type("FakeTransportSftp", (SftpSource,), {"transport": transport})
    cfg = {"host": "h", "username": "u", "private_key": KEY_REF, "known_hosts": "/k", "path": "/outbox",
           "settle_seconds": 0, "poll_seconds": 0}

    async def one_look():
        src = cls(cfg, FakeContext())
        await src.start()
        try:
            return [r async for r in src.records()]
        finally:
            await src.stop()

    assert asyncio.run(one_look()) == []
