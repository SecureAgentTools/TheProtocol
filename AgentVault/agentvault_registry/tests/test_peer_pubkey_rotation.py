"""§PEERKEYROT (2026-09-05) — a peer's credential pubkey cache must survive the peer rotating its signer.
Measured: Sandbox Alpha's signer id changed three times in one morning (a recreate each), Beta's
per-worker trust-on-first-use cache never re-fetched, and every worker holding an old key refused
Alpha's cross-registry IronKey credentials with a deterministic 422."""
import os
import pathlib
import time

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

from agentvault_registry.routers import guild  # noqa: E402

SRC = pathlib.Path(os.environ.get("PEERKEY_SRC", str(pathlib.Path(__file__).resolve().parent.parent / "src/agentvault_registry")))


class _Resp:
    status_code = 200

    def __init__(self, pk):
        self._pk = pk

    def json(self):
        return dict(self._pk)


class _Client:
    calls: list = []
    next_pk: dict = {}

    def __init__(self, **cfg):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        _Client.calls.append(url)
        return _Resp(_Client.next_pk)


@pytest.fixture
def rig(monkeypatch):
    guild._peer_pubkey_cache.clear()
    _Client.calls.clear()

    async def resolve(db, host):
        return host

    monkeypatch.setattr(guild, "_resolve_peer_url", resolve)
    monkeypatch.setattr(guild, "_fed_client_config", lambda target: ({}, {}))
    monkeypatch.setattr(guild.httpx, "AsyncClient", _Client)
    yield _Client
    guild._peer_pubkey_cache.clear()


HOST = "https://peer.example:8443"


def _seed(pubkey_id, age=0.0):
    guild._peer_pubkey_cache[HOST] = {"pubkey_b64": "A" * 44, "pubkey_id": pubkey_id, "_fetched_at": time.time() - age}


@pytest.mark.asyncio
async def test_cache_hit_without_expectation_does_not_fetch(rig):
    _seed("aaaa")
    pk = await guild._fetch_peer_pubkey(None, HOST)
    assert pk["pubkey_id"] == "aaaa" and rig.calls == []


@pytest.mark.asyncio
async def test_matching_expectation_is_a_cache_hit(rig):
    _seed("aaaa")
    pk = await guild._fetch_peer_pubkey(None, HOST, expect_pubkey_id="aaaa")
    assert pk["pubkey_id"] == "aaaa" and rig.calls == []


@pytest.mark.asyncio
async def test_rotated_peer_is_refetched_once(rig):
    _seed("aaaa")
    rig.next_pk = {"pubkey_b64": "B" * 44, "pubkey_id": "bbbb"}
    pk = await guild._fetch_peer_pubkey(None, HOST, expect_pubkey_id="bbbb")
    assert pk["pubkey_id"] == "bbbb" and len(rig.calls) == 1
    assert guild._peer_pubkey_cache[HOST]["pubkey_id"] == "bbbb", "the rotated key replaces the cache entry"


@pytest.mark.asyncio
async def test_refetch_that_still_disagrees_returns_the_peers_key_without_looping(rig):
    _seed("aaaa")
    rig.next_pk = {"pubkey_b64": "A" * 44, "pubkey_id": "aaaa"}   # the peer really signs with aaaa
    pk = await guild._fetch_peer_pubkey(None, HOST, expect_pubkey_id="zzzz")  # a forged/foreign id
    assert pk["pubkey_id"] == "aaaa" and len(rig.calls) == 1, "one refetch, the caller then refuses"


@pytest.mark.asyncio
async def test_stale_cache_expires_by_ttl(rig):
    _seed("aaaa", age=guild._PEER_PUBKEY_TTL_SEC + 1)
    rig.next_pk = {"pubkey_b64": "C" * 44, "pubkey_id": "cccc"}
    pk = await guild._fetch_peer_pubkey(None, HOST)
    assert pk["pubkey_id"] == "cccc" and len(rig.calls) == 1


def test_both_verification_sites_pass_the_credentials_key_id():
    for rel in ("routers/guild.py", "routers/agent_delegation_api.py"):
        s = (SRC / rel).read_text()
        assert 'expect_pubkey_id=body.credential.get("signature_pubkey_id")' in s, rel
