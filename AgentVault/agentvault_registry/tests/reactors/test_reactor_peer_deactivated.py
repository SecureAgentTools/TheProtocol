"""Tests for the PeerRegistryDeactivated reactor (handle_event branching).

The actual HTTP call to TEG is exercised in the sandbox integration test;
here we monkeypatch `_remove_partner_on_teg` and verify the dispatcher's
decision logic (when to call, when to skip).
"""
from __future__ import annotations

import logging
from typing import List, Optional

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks import reactor_peer_deactivated as r_pd


@pytest.fixture(autouse=True)
def reset_leader_keys():
    """Avoid leader_key collisions across tests since the module-level instance
    is created lazily and we may instantiate it via different paths."""
    reactor_base._registered_leader_keys.clear()
    r_pd._instance = None
    yield
    reactor_base._registered_leader_keys.clear()
    r_pd._instance = None


@pytest.fixture
def patched_remove(monkeypatch):
    """Replace the network call with an in-memory recorder."""
    calls: List[str] = []
    response: dict = {"status": "removed", "teg_id": None, "total_partners": 0}

    async def fake_remove(teg_id: str, *, source_label: str = "?") -> Optional[dict]:
        calls.append(teg_id)
        return {**response, "teg_id": teg_id} if response is not None else None

    monkeypatch.setattr(r_pd, "_remove_partner_on_teg", fake_remove)
    return calls


# ---------------------------------------------------------------------------- happy path

@pytest.mark.asyncio
async def test_handle_event_calls_remove_partner_with_teg_id(patched_remove):
    reactor = r_pd.PeerRegistryDeactivatedReactor()
    await reactor.handle_event(
        {
            "peer_id": "peer-123",
            "peer_name": "test-op",
            "teg_id": "teg-testop",
            "trigger": "cloud_teardown",
        }
    )
    assert patched_remove == ["teg-testop"]


# ---------------------------------------------------------------------------- skip branches

@pytest.mark.asyncio
async def test_handle_event_skips_when_teg_id_is_null(patched_remove, caplog):
    """Frame federation revoke path: payload has teg_id=None. No HTTP call."""
    reactor = r_pd.PeerRegistryDeactivatedReactor()
    with caplog.at_level(logging.INFO, logger=r_pd.__name__):
        await reactor.handle_event(
            {
                "peer_id": "peer-frame-b",
                "peer_name": "Frame B",
                "trust_domain": "frame-b.theprotocol.cloud",
                "teg_id": None,
                "trigger": "frame_federation_revoke",
            }
        )
    assert patched_remove == []
    assert any("Skipped" in rec.message and "no teg_id" in rec.message
               for rec in caplog.records)


@pytest.mark.asyncio
async def test_handle_event_skips_when_teg_id_missing(patched_remove):
    """Defensive: payload doesn't include teg_id at all (legacy events). Skip."""
    reactor = r_pd.PeerRegistryDeactivatedReactor()
    await reactor.handle_event(
        {
            "peer_id": "peer-legacy",
            "peer_name": "old-op",
            "trigger": "manual_deactivation",
        }
    )
    assert patched_remove == []


@pytest.mark.asyncio
async def test_handle_event_skips_when_teg_id_empty_string(patched_remove):
    reactor = r_pd.PeerRegistryDeactivatedReactor()
    await reactor.handle_event({"peer_id": "p", "teg_id": ""})
    assert patched_remove == []


# ---------------------------------------------------------------------------- TEG response handling

@pytest.mark.asyncio
async def test_handle_event_logs_teg_status(monkeypatch, caplog):
    async def fake(teg_id: str, *, source_label: str = "?"):
        return {"status": "not_found", "teg_id": teg_id, "total_partners": 3}
    monkeypatch.setattr(r_pd, "_remove_partner_on_teg", fake)

    reactor = r_pd.PeerRegistryDeactivatedReactor()
    with caplog.at_level(logging.INFO, logger=r_pd.__name__):
        await reactor.handle_event({"teg_id": "teg-gone", "peer_name": "gone-op"})

    assert any("not_found" in rec.message and "teg-gone" in rec.message
               for rec in caplog.records)


@pytest.mark.asyncio
async def test_handle_event_tolerates_network_error(monkeypatch):
    """When TEG is unreachable, _remove_partner_on_teg returns None. The
    reactor must not crash — drift_monitor is the safety net."""
    async def fake(teg_id: str, *, source_label: str = "?"):
        return None
    monkeypatch.setattr(r_pd, "_remove_partner_on_teg", fake)

    reactor = r_pd.PeerRegistryDeactivatedReactor()
    # Should not raise
    await reactor.handle_event({"teg_id": "teg-unreachable"})


# ---------------------------------------------------------------------------- module API

@pytest.mark.asyncio
async def test_module_start_creates_singleton_instance(monkeypatch):
    async def noop_loop(self):
        pass
    monkeypatch.setattr(reactor_base.EventStoreReactor, "_ws_loop", noop_loop)

    assert r_pd._instance is None
    await r_pd.start()
    assert isinstance(r_pd._instance, r_pd.PeerRegistryDeactivatedReactor)
    await r_pd.stop()
    assert r_pd._instance is None
