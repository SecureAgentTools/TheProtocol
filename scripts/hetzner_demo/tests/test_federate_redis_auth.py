"""§MTLSHOPS G3 (2026-09-15): the federation step's Redis calls authenticate as the registry's ACL user.

The frame's Redis answers an unauthenticated client only PING, so clear_parked_pulls reads the registry's password from the
frame's env file and hands it to redis-cli on stdin (never on a command line, where `ps` and docker's exec record would show
it), and an ACL refusal raises instead of reading as "nothing parked". A frame from an older template keeps the plain call.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import standup_federate as sf  # noqa: E402

PW = "c" * 64


def _frame(tmp_path, url):
    (tmp_path / ".env.frame-test").write_text(f"FT_REG_REDIS_URL={url}\n")
    return {"name": "labframe", "stack_dir": str(tmp_path)}


def test_the_password_rides_stdin_and_never_an_argument(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, input=None, **kw):
        calls.append((argv, input))
        out = "registry:federation:cardpull_backoff:peer\n" if "--scan" in argv else "1\n"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(sf.subprocess, "run", fake_run)
    assert sf.clear_parked_pulls(_frame(tmp_path, f"redis://registry:{PW}@labframe-redis:6379/0")) == 1
    assert len(calls) == 2   # the scan, then one delete
    for argv, stdin in calls:
        assert not any(PW in a for a in argv)
        assert stdin == PW + "\n"
        assert "--user registry" in " ".join(argv) and argv[:3] == ["docker", "exec", "-i"]


def test_an_acl_refusal_raises_instead_of_reading_as_nothing_parked(tmp_path, monkeypatch):
    def fake_run(argv, input=None, **kw):
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="NOPERM User registry has no permissions\n")

    monkeypatch.setattr(sf.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        sf.clear_parked_pulls(_frame(tmp_path, f"redis://registry:{PW}@labframe-redis:6379/0"))


def test_a_frame_from_an_older_template_keeps_the_plain_call(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, input=None, **kw):
        calls.append((argv, input))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(sf.subprocess, "run", fake_run)
    assert sf.clear_parked_pulls(_frame(tmp_path, "redis://labframe-redis:6379/0")) == 0
    assert calls and "--user" not in " ".join(calls[0][0]) and not calls[0][1]


def _as_the_container_shell_runs_it(tmp_path, monkeypatch, with_socket):
    """§MTLSHOPS T3: runs the script clear_parked_pulls hands `docker exec -i <redis> sh -c`, on this host, with a redis-cli
    that prints its arguments, and returns what that shell ran (with and without the Redis socket)."""
    import socket as _socket
    sock = tmp_path / "redis.sock"
    srv = _socket.socket(_socket.AF_UNIX) if with_socket else None
    if srv:
        srv.bind(str(sock))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "redis-cli").write_text('#!/bin/sh\necho "ARGS $*"\n')
    (bindir / "redis-cli").chmod(0o755)
    monkeypatch.setattr(sf, "REDIS_SOCKET", str(sock))
    real_run, ran = subprocess.run, []

    def fake_run(argv, input=None, **kw):
        r = real_run(argv[argv.index("sh"):], input=input, capture_output=True, text=True,
                     env={"PATH": f"{bindir}:/usr/bin:/bin"})
        ran.append(r.stdout.strip())
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(sf.subprocess, "run", fake_run)
    try:
        sf.clear_parked_pulls(_frame(tmp_path, f"rediss://registry:{PW}@labframe-redis:6379/0?ssl_cert_reqs=required"))
    finally:
        if srv:
            srv.close()
    return ran[0], str(sock)


def test_a_tls_only_redis_is_asked_over_its_socket(tmp_path, monkeypatch):
    """--port 0 closes the plain port, so redis-cli asks the container's unix socket, which takes the same ACL users."""
    ran, sock = _as_the_container_shell_runs_it(tmp_path, monkeypatch, with_socket=True)
    assert ran == f"ARGS --no-auth-warning --user registry -s {sock} --scan --pattern registry:federation:cardpull_*"


def test_a_redis_with_no_socket_keeps_its_port(tmp_path, monkeypatch):
    ran, _ = _as_the_container_shell_runs_it(tmp_path, monkeypatch, with_socket=False)
    assert ran == "ARGS --no-auth-warning --user registry --scan --pattern registry:federation:cardpull_*"
