"""§HELLOFRAME (2026-09-18): the mTLS trust list follows the ACTIVE frame peer rows, not only TRUSTED_SPIFFE_DOMAINS.
Measured on a runner-built frame federated with the sandbox: every handshake passed and both registries answered 401
"untrusted domain" to each other, because the env list is static and nobody edits it at an approve."""
import asyncio

import pytest

from agentvault_registry.core import mtls_auth as m


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(m, "_PEER_TRUST_DOMAINS", frozenset())
    monkeypatch.setattr(m, "_PEER_TRUST_READ_AT", 0.0)
    monkeypatch.setattr(m, "TRUSTED_SPIFFE_DOMAINS", ["own.example.org"])
    yield


def test_domains_from_peer_rows_keeps_active_frames_only():
    rows = [("frame", "ACTIVE", "peer.example.org"), ("frame", "INACTIVE", "gone.example.org"),
            ("cloud_operator", "ACTIVE", "own.example.org"), ("discovered", "ACTIVE", "far.example.org"),
            ("frame", "active", "spiffe://Lower.Example.org/"), ("frame", "ACTIVE", None)]
    assert m.domains_from_peer_rows(rows) == frozenset({"peer.example.org", "lower.example.org"})


def test_env_only_refuses_a_peer_nobody_approved():
    assert m.is_trusted_spiffe_id("spiffe://own.example.org/service/registry")
    assert not m.is_trusted_spiffe_id("spiffe://peer.example.org/service/registry")


def test_an_active_frame_row_is_trusted_and_a_revoked_one_is_not():
    calls = []

    async def fetch():
        calls.append(1)
        return [("frame", "ACTIVE", "peer.example.org")] if len(calls) == 1 else [("frame", "INACTIVE", "peer.example.org")]

    clock = [100.0]
    asyncio.run(m.refresh_peer_trust_domains(fetch=fetch, now=lambda: clock[0]))
    assert m.is_trusted_spiffe_id("spiffe://peer.example.org/service/registry")
    assert m.trusted_spiffe_domains() == ("own.example.org", "peer.example.org")
    # within the TTL nothing is re-read
    asyncio.run(m.refresh_peer_trust_domains(fetch=fetch, now=lambda: clock[0] + 5))
    assert len(calls) == 1
    # after the TTL the revoke (INACTIVE) is seen and the peer is no longer trusted
    asyncio.run(m.refresh_peer_trust_domains(fetch=fetch, now=lambda: clock[0] + m.PEER_TRUST_TTL_SECONDS + 1))
    assert len(calls) == 2
    assert not m.is_trusted_spiffe_id("spiffe://peer.example.org/service/registry")


def test_a_failed_read_keeps_the_last_set():
    async def good():
        return [("frame", "ACTIVE", "peer.example.org")]

    async def bad():
        raise RuntimeError("database away")

    asyncio.run(m.refresh_peer_trust_domains(fetch=good, now=lambda: 10.0))
    asyncio.run(m.refresh_peer_trust_domains(fetch=bad, now=lambda: 10.0 + m.PEER_TRUST_TTL_SECONDS + 1))
    assert m.is_trusted_spiffe_id("spiffe://peer.example.org/service/registry")
    assert "RuntimeError" in m._PEER_TRUST_LAST_ERROR


def test_no_other_site_asks_the_old_question():
    """the env list is read through the predicate everywhere a SPIFFE id is admitted"""
    import pathlib
    src = pathlib.Path(m.__file__).resolve().parents[0]
    fed = (src / "federation_auth.py").read_text()
    assert "for d in TRUSTED_SPIFFE_DOMAINS" not in fed
    assert "for d in TRUSTED_SPIFFE_DOMAINS" not in (src / "mtls_auth.py").read_text()
