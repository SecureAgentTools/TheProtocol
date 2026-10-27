"""frame-doctor's DNS check (§LEGALKIT 2026-09-20): with --edge-tls internal (a test frame on Caddy's own CA) a public
name that does not resolve is a NOTE, because nothing needs it until the frame federates; with acme it stays a
refusal (Let's Encrypt cannot issue for a name that does not point here). The tools, the daemon, the ports and the
memory are patched out: this pins the one decision, not the host."""
import importlib.util
import os
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frame_doctor", os.path.join(HERE, "..", "frame-doctor.py"))
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)


def _quiet_host(monkeypatch, answers):
    monkeypatch.setattr(fd.shutil, "which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr(fd, "run", lambda *a, **k: (0, "27.0.0\n", ""))
    monkeypatch.setattr(fd, "port_free", lambda p: True)
    monkeypatch.setattr(fd, "host_ipv4s", lambda: {"203.0.113.10"})
    monkeypatch.setattr(fd, "resolve_public", lambda name: answers)
    for name in ("mem_gib", "disk_gb", "free_gb", "mem_total_gib"):
        if hasattr(fd, name):
            monkeypatch.setattr(fd, name, lambda *a, **k: 10_000)


def _args(tls):
    return SimpleNamespace(name="zz", public_name="zz.example.invalid", stack_root="/nonexistent-zz", images_prefix="theprotocol",
                           version="0", federation_port=8463, bundle_port=8464, ledger_port=8466, edge_https_port=8543,
                           edge_http_port=8580, edge_tls=tls, min_mem_gib=0, min_disk_gb=0, edge_via=None)


def _dns_lines(items):
    return [s for s in items if "A record" in s or "resolves to" in s]


def test_internal_tls_makes_a_missing_record_a_note(monkeypatch):
    _quiet_host(monkeypatch, answers=[])
    problems, notes = fd.checks(_args("internal"))
    assert _dns_lines(problems) == [], problems
    assert len(_dns_lines(notes)) == 1 and "internal TLS" in _dns_lines(notes)[0]


def test_internal_tls_makes_a_foreign_record_a_note(monkeypatch):
    _quiet_host(monkeypatch, answers=["198.51.100.7"])
    problems, notes = fd.checks(_args("internal"))
    assert _dns_lines(problems) == []
    assert len(_dns_lines(notes)) == 1 and "federates" in _dns_lines(notes)[0]


def test_acme_keeps_the_refusal(monkeypatch):
    """The control: the decision is on the TLS mode, not a loosening of the check."""
    _quiet_host(monkeypatch, answers=[])
    problems, notes = fd.checks(_args("acme"))
    assert len(_dns_lines(problems)) == 1 and "create one" in _dns_lines(problems)[0]
    assert _dns_lines(notes) == []


def test_a_record_pointing_here_is_quiet_either_way(monkeypatch):
    _quiet_host(monkeypatch, answers=["203.0.113.10"])
    for tls in ("acme", "internal"):
        problems, notes = fd.checks(_args(tls))
        assert _dns_lines(problems) == [] and _dns_lines(notes) == []


def test_the_compose_version_is_held_to_the_minimum_its_message_names():
    """CB-076: the check compared the major version only, so docker compose 2.20 passed a check that asks for 2.24."""
    for ok in ("2.24.0", "2.24", "v2.29.7", "2.40.3\n", "3.0.0"):
        assert fd.compose_version_problem(ok) is None, ok
    for old in ("2.20.2", "v2.23.9", "1.29.2"):
        assert "2.24 or newer" in fd.compose_version_problem(old), old
    assert "not a version" in fd.compose_version_problem("garbage")


def test_checks_refuses_a_compose_older_than_2_24(monkeypatch):
    _quiet_host(monkeypatch, answers=["203.0.113.10"])
    monkeypatch.setattr(fd, "run", lambda argv, **k: (0, "2.20.2", "") if argv[:3] == ["docker", "compose", "version"]
                        else (0, "27.0.0\n", ""))
    problems, _ = fd.checks(_args("internal"))
    assert [p for p in problems if "docker compose 2.20.2 is too old" in p]
