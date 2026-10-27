"""Tests for Phase 6 reactors:
- AgentSuspendedReactor
- AgentReinstatedReactor
- DeveloperSuspendedReactor

Inline coupling (registry status / IRONHAND mTLS / TEG suspend) is exercised
in the sandbox integration test and in test_coordinated_suspension.py — these
tests focus on the reactor's webhook propagation logic.
"""
from __future__ import annotations

from typing import List

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks import reactor_helpers
from agentvault_registry.background_tasks import reactor_agent_suspended as r_as
from agentvault_registry.background_tasks import reactor_agent_reinstated as r_ar
from agentvault_registry.background_tasks import reactor_developer_suspended as r_ds


@pytest.fixture(autouse=True)
def reset_state():
    reactor_base._registered_leader_keys.clear()
    r_as._instance = None
    r_ar._instance = None
    r_ds._instance = None
    yield
    reactor_base._registered_leader_keys.clear()
    r_as._instance = None
    r_ar._instance = None
    r_ds._instance = None


@pytest.fixture
def patched_dispatch(monkeypatch):
    """Capture every webhook dispatch across the 3 reactor modules, in call order.

    §TWOAGENT #34 (V0429): the agent lifecycle goes out OWNER-scoped (dispatch_webhook_for_agents) and the developer
    lifecycle to that developer (dispatch_webhook_event with developer_id); the unscoped broadcast, which delivered
    every tenant's suspension to every subscriber on the frame and the peer frame, is gone. Each record says its scope.
    """
    calls: List[dict] = []

    async def fake_event(event_type: str, event_data: dict, *, source_label: str = "?", developer_id=None) -> int:
        calls.append({"event_type": event_type, "event_data": event_data, "source": source_label,
                      "scope": "broadcast" if developer_id is None else "developer", "developer_id": developer_id})
        return 1  # pretend 1 webhook subscription matched

    async def fake_for_agents(event_type: str, event_data: dict, agent_dids, *, source_label: str = "?") -> int:
        calls.append({"event_type": event_type, "event_data": event_data, "source": source_label,
                      "scope": "owner", "agent_dids": list(agent_dids)})
        return 1

    for mod in (r_as, r_ar, r_ds):
        monkeypatch.setattr(mod, "dispatch_webhook_event", fake_event, raising=False)
        monkeypatch.setattr(mod, "dispatch_webhook_for_agents", fake_for_agents, raising=False)
    return calls


# ============================================================ AgentSuspended

@pytest.mark.asyncio
async def test_agent_suspended_dispatches_webhook(patched_dispatch):
    reactor = r_as.AgentSuspendedReactor()
    await reactor.handle_event({
        "target_agent_did": "did:theprotocol:abc",
        "reason": "abuse",
        "soft_suspend": False,
    })
    assert len(patched_dispatch) == 1
    assert patched_dispatch[0]["event_type"] == "agent.suspended"
    assert patched_dispatch[0]["event_data"]["target_agent_did"] == "did:theprotocol:abc"
    assert patched_dispatch[0]["scope"] == "owner" and patched_dispatch[0]["agent_dids"] == ["did:theprotocol:abc"]


@pytest.mark.asyncio
async def test_agent_suspended_handles_minimal_payload(patched_dispatch):
    """Backwards-compat: events emitted before the new fields existed should still dispatch."""
    reactor = r_as.AgentSuspendedReactor()
    await reactor.handle_event({"agent_did": "did:foo"})
    assert len(patched_dispatch) == 1
    assert patched_dispatch[0]["agent_dids"] == ["did:foo"]


# ============================================================ AgentReinstated

@pytest.mark.asyncio
async def test_agent_reinstated_dispatches_webhook(patched_dispatch):
    reactor = r_ar.AgentReinstatedReactor()
    await reactor.handle_event({
        "agent_did": "did:theprotocol:xyz",
        "actor_email": "admin@test",
    })
    assert len(patched_dispatch) == 1
    assert patched_dispatch[0]["event_type"] == "agent.reinstated"
    assert patched_dispatch[0]["scope"] == "owner" and patched_dispatch[0]["agent_dids"] == ["did:theprotocol:xyz"]


# ============================================================ DeveloperSuspended (cascade)

@pytest.mark.asyncio
async def test_developer_suspended_fans_out_per_cascade_agent(patched_dispatch):
    reactor = r_ds.DeveloperSuspendedReactor()
    await reactor.handle_event({
        "target_developer_id": 42,
        "target_email": "evil@example.com",
        "reason": "policy violation",
        "cascade_count": 3,
        "cascade_results": [
            {"agent_did": "did:agent:1", "registry": True, "mtls": "revoked", "teg": "suspended"},
            {"agent_did": "did:agent:2", "registry": True, "mtls": "not_enrolled", "teg": "suspended"},
            {"agent_did": "did:agent:3", "registry": True, "mtls": "revoked", "teg": "failed"},
        ],
    })
    # 1 dev-level webhook + 3 per-agent webhooks
    assert len(patched_dispatch) == 4
    event_types = [c["event_type"] for c in patched_dispatch]
    assert event_types[0] == "developer.suspended"
    assert event_types[1:] == ["agent.suspended"] * 3
    assert patched_dispatch[0]["scope"] == "developer" and patched_dispatch[0]["developer_id"] == 42
    assert [c["agent_dids"] for c in patched_dispatch[1:]] == [["did:agent:1"], ["did:agent:2"], ["did:agent:3"]]
    assert not any(c["scope"] == "broadcast" for c in patched_dispatch)
    # cascade_source threaded through
    for c in patched_dispatch[1:]:
        assert c["event_data"]["cascade_source"] == "developer.suspended"
        assert c["event_data"]["developer_id"] == 42


@pytest.mark.asyncio
async def test_developer_suspended_no_cascade_only_dev_event(patched_dispatch):
    """If cascade_results is empty, only the dev webhook fires."""
    reactor = r_ds.DeveloperSuspendedReactor()
    await reactor.handle_event({
        "target_developer_id": 7,
        "target_email": "x@y.z",
        "cascade_count": 0,
        "cascade_results": [],
    })
    assert len(patched_dispatch) == 1
    assert patched_dispatch[0]["event_type"] == "developer.suspended"
    assert patched_dispatch[0]["developer_id"] == 7


@pytest.mark.asyncio
async def test_developer_suspended_handles_missing_cascade_field(patched_dispatch):
    """Defensive: legacy DeveloperSuspended payloads predate cascade_results."""
    reactor = r_ds.DeveloperSuspendedReactor()
    await reactor.handle_event({
        "target_developer_id": 9,
        "target_email": "legacy@old",
        "reason": "legacy event",
    })
    # Just the dev webhook — no cascade list to iterate
    assert len(patched_dispatch) == 1
    assert patched_dispatch[0]["event_type"] == "developer.suspended"
    assert patched_dispatch[0]["developer_id"] == 9


# ============================================================ Module API + leader keys

@pytest.mark.asyncio
async def test_module_start_creates_singletons(monkeypatch):
    async def noop(self):
        pass
    monkeypatch.setattr(reactor_base.EventStoreReactor, "_ws_loop", noop)
    await r_as.start()
    await r_ar.start()
    await r_ds.start()
    assert isinstance(r_as._instance, r_as.AgentSuspendedReactor)
    assert isinstance(r_ar._instance, r_ar.AgentReinstatedReactor)
    assert isinstance(r_ds._instance, r_ds.DeveloperSuspendedReactor)
    await r_as.stop()
    await r_ar.stop()
    await r_ds.stop()


def test_phase6_reactors_have_unique_leader_keys():
    """All Phase 1-6 reactors must have distinct leader_keys."""
    from agentvault_registry.background_tasks.reactor_peer_deactivated import PeerRegistryDeactivatedReactor
    from agentvault_registry.background_tasks.reactor_federation_license_suspended import FederationLicenseSuspendedReactor
    from agentvault_registry.background_tasks.reactor_registry_quarantined import RegistryQuarantinedReactor
    from agentvault_registry.background_tasks.reactor_supply_invariant_breach import SupplyInvariantBreachReactor
    keys = {
        PeerRegistryDeactivatedReactor.leader_key,
        FederationLicenseSuspendedReactor.leader_key,
        RegistryQuarantinedReactor.leader_key,
        SupplyInvariantBreachReactor.leader_key,
        r_as.AgentSuspendedReactor.leader_key,
        r_ar.AgentReinstatedReactor.leader_key,
        r_ds.DeveloperSuspendedReactor.leader_key,
    }
    assert len(keys) == 7, f"leader_key collision detected: {keys}"
