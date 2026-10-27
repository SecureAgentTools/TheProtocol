"""Tests for Phase 10 #4 cross-frame blocklist propagation helpers.

`block_agent_on_remote_frames` and `unblock_agent_on_remote_frames` walk
ACTIVE peer registries and POST to each peer's federation blocklist proxy
endpoint over Mode 2 federation auth. These tests mock the DB session and
the per-peer HTTP call so they don't need a live registry stack.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentvault_registry.background_tasks import reactor_helpers


class _FakePeer:
    def __init__(self, peer_id, name, base_url, status="ACTIVE"):
        self.id = peer_id
        self.name = name
        self.base_url = base_url
        self.status = status


@pytest.fixture
def peers():
    return [
        _FakePeer(1, "Sandbox B", "http://sandbox-b:8000"),
        _FakePeer(2, "Frame B", "https://frame-b.example.com"),
        _FakePeer(3, "Stale Peer", ""),  # empty base_url — should be skipped
    ]


def _patch_db_returning(peers):
    """Patch get_db_context to yield a fake session whose .execute() returns
    a fake result with .scalars().all() == peers."""
    fake_scalars = MagicMock()
    fake_scalars.all.return_value = peers
    fake_result = MagicMock()
    fake_result.scalars.return_value = fake_scalars
    fake_db = AsyncMock()
    fake_db.execute = AsyncMock(return_value=fake_result)

    class _FakeCtx:
        async def __aenter__(self):
            return fake_db
        async def __aexit__(self, *a):
            return False

    return patch(
        "agentvault_registry.database.get_db_context",
        return_value=_FakeCtx(),
    )


@pytest.mark.asyncio
async def test_fanout_walks_active_peers_with_base_url(peers):
    """Helper queries ACTIVE peers, filters out empty base_urls, calls each."""
    seen_calls = []

    async def fake_post(peer_base_url, path, body, *, source_label, op_name):
        seen_calls.append({
            "peer_base_url": peer_base_url,
            "path": path,
            "body": body,
        })
        return {"status": "blocked", "blocklist_size": 1}

    with _patch_db_returning(peers), \
         patch.object(reactor_helpers, "_post_federation_admin", new=fake_post):
        result = await reactor_helpers.block_agent_on_remote_frames(
            "did:theprotocol:victim",
            reason="unit test",
            source_label="UnitTest",
        )

    # Stale Peer (no base_url) should NOT be called
    assert result["attempted"] == 2
    assert result["successful"] == 2
    assert len(seen_calls) == 2
    assert seen_calls[0]["path"] == "/api/v1/federation/admin/agents/did:theprotocol:victim/block"
    assert seen_calls[0]["body"] == {"reason": "unit test", "actor": "UnitTest"}
    assert {c["peer_base_url"] for c in seen_calls} == {
        "http://sandbox-b:8000",
        "https://frame-b.example.com",
    }


@pytest.mark.asyncio
async def test_fanout_unblock_uses_unblock_path(peers):
    seen_paths = []

    async def fake_post(peer_base_url, path, body, *, source_label, op_name):
        seen_paths.append(path)
        return {"status": "unblocked", "blocklist_size": 0}

    with _patch_db_returning(peers), \
         patch.object(reactor_helpers, "_post_federation_admin", new=fake_post):
        await reactor_helpers.unblock_agent_on_remote_frames(
            "did:theprotocol:happy",
            source_label="UnitTest",
        )

    assert all(p.endswith("/unblock") for p in seen_paths)


@pytest.mark.asyncio
async def test_fanout_handles_per_peer_failure_gracefully(peers):
    """If one peer is unreachable, the helper still reports successful for
    the others. Result.successful counts only OK peers."""
    async def fake_post(peer_base_url, path, body, *, source_label, op_name):
        if "sandbox-b" in peer_base_url:
            return None  # simulate network/auth error
        return {"status": "blocked", "blocklist_size": 1}

    with _patch_db_returning(peers), \
         patch.object(reactor_helpers, "_post_federation_admin", new=fake_post):
        result = await reactor_helpers.block_agent_on_remote_frames(
            "did:theprotocol:half-blocked",
        )

    assert result["attempted"] == 2
    assert result["successful"] == 1
    by_name = {r["peer_name"]: r for r in result["results"]}
    assert by_name["Sandbox B"]["ok"] is False
    assert by_name["Frame B"]["ok"] is True


@pytest.mark.asyncio
async def test_fanout_returns_empty_when_no_peers():
    with _patch_db_returning([]), \
         patch.object(reactor_helpers, "_post_federation_admin", new=AsyncMock(return_value=None)):
        result = await reactor_helpers.block_agent_on_remote_frames("did:x:y")
    assert result == {"attempted": 0, "successful": 0, "results": []}


@pytest.mark.asyncio
async def test_fanout_runs_peers_in_parallel(peers):
    """asyncio.gather should mean all per-peer calls overlap, not serialize."""
    import asyncio
    call_starts = []
    call_ends = []

    async def slow_post(peer_base_url, path, body, *, source_label, op_name):
        call_starts.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.05)
        call_ends.append(asyncio.get_event_loop().time())
        return {"status": "blocked", "blocklist_size": 1}

    with _patch_db_returning(peers), \
         patch.object(reactor_helpers, "_post_federation_admin", new=slow_post):
        t0 = asyncio.get_event_loop().time()
        await reactor_helpers.block_agent_on_remote_frames("did:x:y")
        elapsed = asyncio.get_event_loop().time() - t0

    # If parallel: ~50ms. If serial: ~100ms+. Threshold 90ms is conservative.
    assert elapsed < 0.090, f"fanout took {elapsed:.3f}s — likely serial"
    assert len(call_starts) == 2


@pytest.mark.asyncio
async def test_post_federation_admin_skips_when_no_secret(monkeypatch):
    """Mode 2 auth requires both the shared secret AND a SPIFFE ID. If
    the secret env is unset, the helper returns None silently."""
    monkeypatch.delenv("FEDERATION_INTERNAL_SECRET", raising=False)
    result = await reactor_helpers._post_federation_admin(
        "http://peer:8000",
        "/api/v1/federation/admin/agents/did/block",
        {"reason": "x", "actor": "y"},
        source_label="UnitTest",
        op_name="block(did)",
    )
    assert result is None


@pytest.mark.asyncio
async def test_post_federation_admin_uses_svid_client_spiffe_id(monkeypatch):
    """Helper resolves SPIFFE ID via svid_client.get_spiffe_id() (the
    standard pattern, mirrors compliance_poller). When that returns a
    value, the secret + spiffe headers are sent."""
    monkeypatch.setenv("FEDERATION_INTERNAL_SECRET", "secret-xyz")

    fake_svid = MagicMock()
    fake_svid.get_spiffe_id.return_value = "spiffe://sandbox-a.test/registry"

    sent_headers = {}
    sent_url = None

    class FakeResp:
        status = 200
        async def text(self):
            return ""
        async def json(self):
            return {"status": "blocked", "blocklist_size": 1}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    fake_session = MagicMock()
    def post(url, headers=None, json=None):
        nonlocal sent_url
        sent_url = url
        sent_headers.update(headers or {})
        return FakeResp()
    fake_session.post = post

    with patch("agentvault_registry.identity.svid_client.svid_client", fake_svid), \
         patch.object(reactor_helpers, "_get_session", return_value=fake_session):
        result = await reactor_helpers._post_federation_admin(
            "http://peer:8000",
            "/api/v1/federation/admin/agents/did/block",
            {"reason": "x", "actor": "y"},
            source_label="UnitTest",
            op_name="block(did)",
        )

    assert result == {"status": "blocked", "blocklist_size": 1}
    assert sent_headers["X-Federation-Secret"] == "secret-xyz"
    assert sent_headers["X-Federation-SPIFFE-ID"] == "spiffe://sandbox-a.test/registry"
    assert sent_url == "http://peer:8000/api/v1/federation/admin/agents/did/block"
