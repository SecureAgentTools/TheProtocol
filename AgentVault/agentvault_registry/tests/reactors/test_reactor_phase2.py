"""Tests for the Phase 2 reactors:
- FederationLicenseSuspendedReactor
- RegistryQuarantinedReactor

Both share the `remove_partner_on_teg` helper with the Phase 1 reactor.
The tests focus on dispatch-decision logic (when to call, when to skip).
"""
from __future__ import annotations

from typing import List, Optional

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks import reactor_helpers
from agentvault_registry.background_tasks import reactor_federation_license_suspended as r_lic
from agentvault_registry.background_tasks import reactor_registry_quarantined as r_quar


@pytest.fixture(autouse=True)
def reset_state():
    reactor_base._registered_leader_keys.clear()
    r_lic._instance = None
    r_quar._instance = None
    yield
    reactor_base._registered_leader_keys.clear()
    r_lic._instance = None
    r_quar._instance = None


@pytest.fixture
def patched_remove(monkeypatch):
    """Capture calls to the shared remove_partner_on_teg helper."""
    calls: List[dict] = []

    async def fake(teg_id: str, *, source_label: str = "?") -> Optional[dict]:
        calls.append({"teg_id": teg_id, "source": source_label})
        return {"status": "removed", "teg_id": teg_id, "total_partners": 0}

    monkeypatch.setattr(reactor_helpers, "remove_partner_on_teg", fake)
    # Also patch the import binding inside each reactor module (since the
    # `from .reactor_helpers import remove_partner_on_teg` style takes a copy)
    monkeypatch.setattr(r_lic, "remove_partner_on_teg", fake)
    monkeypatch.setattr(r_quar, "remove_partner_on_teg", fake)
    return calls


# ============================================================ FederationLicenseSuspended

@pytest.mark.asyncio
async def test_license_suspended_calls_remove_partner(patched_remove):
    reactor = r_lic.FederationLicenseSuspendedReactor()
    await reactor.handle_event(
        {
            "license_id": 42,
            "operator_did": "did:theprotocol:cloud:reactortestop",
            "operator_name": "reactortestop",
            "teg_id": "teg-reactortestop",
            "reason": "policy violation",
        }
    )
    assert patched_remove == [{"teg_id": "teg-reactortestop", "source": "FederationLicenseSuspended"}]


@pytest.mark.asyncio
async def test_license_suspended_skips_when_teg_id_null(patched_remove):
    reactor = r_lic.FederationLicenseSuspendedReactor()
    await reactor.handle_event(
        {"license_id": 99, "operator_name": "legacy-op", "teg_id": None}
    )
    assert patched_remove == []


@pytest.mark.asyncio
async def test_license_suspended_skips_when_teg_id_missing(patched_remove):
    reactor = r_lic.FederationLicenseSuspendedReactor()
    await reactor.handle_event({"license_id": 7, "operator_name": "no-teg-field"})
    assert patched_remove == []


@pytest.mark.asyncio
async def test_license_suspended_module_start(monkeypatch):
    async def noop(self):
        pass
    monkeypatch.setattr(reactor_base.EventStoreReactor, "_ws_loop", noop)
    await r_lic.start()
    assert isinstance(r_lic._instance, r_lic.FederationLicenseSuspendedReactor)
    await r_lic.stop()
    assert r_lic._instance is None


# ============================================================ RegistryQuarantined

@pytest.mark.asyncio
async def test_quarantine_calls_remove_partner(patched_remove):
    reactor = r_quar.RegistryQuarantinedReactor()
    await reactor.handle_event(
        {
            "peer_registry_id": 17,
            "peer_name": "drifty-peer",
            "teg_id": "teg-drifty-peer",
            "reason": "policy_hash_mismatch",
            "severity": "high",
        }
    )
    assert patched_remove == [{"teg_id": "teg-drifty-peer", "source": "RegistryQuarantined"}]


@pytest.mark.asyncio
async def test_quarantine_skips_when_teg_id_null(patched_remove):
    reactor = r_quar.RegistryQuarantinedReactor()
    await reactor.handle_event(
        {"peer_registry_id": 17, "peer_name": "frame-b", "teg_id": None}
    )
    assert patched_remove == []


@pytest.mark.asyncio
async def test_quarantine_skips_when_teg_id_missing(patched_remove):
    reactor = r_quar.RegistryQuarantinedReactor()
    await reactor.handle_event({"peer_registry_id": 17})
    assert patched_remove == []


@pytest.mark.asyncio
async def test_quarantine_module_start(monkeypatch):
    async def noop(self):
        pass
    monkeypatch.setattr(reactor_base.EventStoreReactor, "_ws_loop", noop)
    await r_quar.start()
    assert isinstance(r_quar._instance, r_quar.RegistryQuarantinedReactor)
    await r_quar.stop()
    assert r_quar._instance is None


# ============================================================ Cross-reactor: leader_key uniqueness

@pytest.mark.asyncio
async def test_all_three_reactors_have_unique_leader_keys():
    """The base class enforces this, but verify explicitly that the three
    Phase-1+2 reactors don't collide. If a future reactor copies a key by
    accident, this test would still pass — but instantiating both would
    raise. The intent here is documentation."""
    from agentvault_registry.background_tasks.reactor_peer_deactivated import (
        PeerRegistryDeactivatedReactor,
    )
    keys = {
        PeerRegistryDeactivatedReactor.leader_key,
        r_lic.FederationLicenseSuspendedReactor.leader_key,
        r_quar.RegistryQuarantinedReactor.leader_key,
    }
    assert len(keys) == 3, f"leader_key collision detected: {keys}"


@pytest.mark.asyncio
async def test_helper_has_correct_signature():
    """Smoke test: the helper module exports remove_partner_on_teg with the
    expected keyword-only `source_label` parameter."""
    import inspect
    sig = inspect.signature(reactor_helpers.remove_partner_on_teg)
    params = list(sig.parameters.values())
    assert params[0].name == "teg_id"
    assert "source_label" in sig.parameters
    assert sig.parameters["source_label"].kind == inspect.Parameter.KEYWORD_ONLY
