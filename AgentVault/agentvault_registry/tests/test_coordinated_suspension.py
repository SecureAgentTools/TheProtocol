"""Tests for the Phase 6 coordinated suspension service.

Mocks IRONHAND (SPIRE deletion + emit) and TEG (httpx call) so the test
verifies the lever-by-lever orchestration without touching real services.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentvault_registry.services import coordinated_suspension as cs


class _FakeAgent:
    """Lightweight stand-in for models.Agent — only the attributes the service touches."""

    def __init__(
        self,
        did: str = "did:theprotocol:abc",
        status: str = "active",
        mtls_enabled: bool = True,
        spiffe_id: str | None = "spiffe://agentvault.com/agent/abc",
        creator_developer_id: int = 1,
    ) -> None:
        self.did = did
        self.status = status
        self.enforcement_status = "active"
        self.mtls_enabled = mtls_enabled
        self.spiffe_id = spiffe_id
        self.mtls_enrolled_at: datetime | None = (
            datetime.now(timezone.utc) if mtls_enabled else None
        )
        self.creator_developer_id = creator_developer_id


class _FakeAdmin:
    def __init__(self) -> None:
        self.id = 99
        self.email = "admin@test"


# Fake SQLAlchemy session — most calls go through helpers we monkeypatch
class _FakeSession:
    async def execute(self, *args, **kwargs) -> Any:
        return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))


# ---------------------------------------------------------------------------- helpers

@pytest.fixture
def patched_dependencies(monkeypatch):
    """Stub out SPIRE + TEG + emitter + agent-card patch — pure unit tests."""
    spire_calls: List[str] = []
    teg_calls: List[Dict[str, Any]] = []
    emitter_calls: List[Dict[str, Any]] = []
    card_patch_calls: List[Dict[str, Any]] = []

    # SPIRE delete/register — sync functions
    def fake_delete_spire(did: str) -> bool:
        spire_calls.append(f"delete:{did}")
        return True

    def fake_register_spire(did: str) -> str:
        spire_calls.append(f"register:{did}")
        return f"spiffe://test/agent/{did}"

    monkeypatch.setattr(
        "agentvault_registry.services.agent_spire.delete_agent_spire_entry",
        fake_delete_spire,
    )
    monkeypatch.setattr(
        "agentvault_registry.services.agent_spire.register_agent_spire_entry",
        fake_register_spire,
    )

    # Agent card patch (async)
    async def fake_patch_card(db, did, spiffe_id, *, enabled):
        card_patch_calls.append(
            {"did": did, "spiffe_id": spiffe_id, "enabled": enabled}
        )

    monkeypatch.setattr(
        "agentvault_registry.routers.agent_mtls._patch_agent_card_mtls",
        fake_patch_card,
    )

    # Emitter
    fake_emitter = MagicMock()
    fake_emitter.emit_agent_mtls_revoked = AsyncMock(
        side_effect=lambda **kw: emitter_calls.append({"type": "revoked", **kw}) or True
    )
    fake_emitter.emit_agent_mtls_enrolled = AsyncMock(
        side_effect=lambda *a, **kw: emitter_calls.append({"type": "enrolled", "args": a, "kw": kw}) or True
    )
    monkeypatch.setattr(
        "agentvault_registry.event_emitter.get_event_emitter",
        lambda: fake_emitter,
    )

    # TEG suspend/reinstate
    async def fake_teg_suspend(agent_did: str, reason: str, duration_hours: int = 8760) -> bool:
        teg_calls.append({"action": "suspend", "did": agent_did, "reason": reason, "hours": duration_hours})
        return True

    async def fake_teg_reinstate(agent_did: str) -> bool:
        teg_calls.append({"action": "reinstate", "did": agent_did})
        return True

    monkeypatch.setattr(cs, "_teg_suspend", fake_teg_suspend)
    monkeypatch.setattr(cs, "_teg_reinstate", fake_teg_reinstate)

    return {
        "spire_calls": spire_calls,
        "teg_calls": teg_calls,
        "emitter_calls": emitter_calls,
        "card_patch_calls": card_patch_calls,
    }


# ============================================================ suspend happy path

@pytest.mark.asyncio
async def test_full_suspend_flips_all_three_levers(patched_dependencies):
    agent = _FakeAgent(mtls_enabled=True)
    db = _FakeSession()
    admin = _FakeAdmin()

    result = await cs.coordinated_agent_suspend(
        db, agent, reason="test abuse case", actor=admin, soft=False
    )

    assert result.registry is True
    assert result.mtls == "revoked"
    assert result.teg == "suspended"
    assert agent.status == "suspended"
    assert agent.enforcement_status == "suspended"
    assert agent.mtls_enabled is False
    # §TWOAGENT #35 (V0429): the suspension KEEPS spiffe_id as its restore marker (with mtls_enabled False it grants
    # nothing, and the SPIRE entry is deleted just below), so the reinstate restores exactly what was taken.
    assert agent.spiffe_id == "spiffe://agentvault.com/agent/abc"
    assert "delete:did:theprotocol:abc" in patched_dependencies["spire_calls"]
    assert any(t["action"] == "suspend" for t in patched_dependencies["teg_calls"])
    assert any(e["type"] == "revoked" for e in patched_dependencies["emitter_calls"])


@pytest.mark.asyncio
async def test_suspend_skips_mtls_when_not_enrolled(patched_dependencies):
    agent = _FakeAgent(mtls_enabled=False, spiffe_id=None)
    db = _FakeSession()
    admin = _FakeAdmin()

    result = await cs.coordinated_agent_suspend(
        db, agent, reason="cooldown after dispute", actor=admin
    )

    assert result.mtls == "not_enrolled"
    assert result.teg == "suspended"
    assert "delete:did:theprotocol:abc" not in patched_dependencies["spire_calls"]


@pytest.mark.asyncio
async def test_soft_suspend_skips_mtls_and_teg(patched_dependencies):
    agent = _FakeAgent(mtls_enabled=True)
    db = _FakeSession()
    admin = _FakeAdmin()

    result = await cs.coordinated_agent_suspend(
        db, agent, reason="soft cooldown", actor=admin, soft=True
    )

    assert result.registry is True
    assert result.mtls == "skipped"
    assert result.teg == "skipped"
    assert agent.mtls_enabled is True  # untouched
    assert agent.spiffe_id is not None  # untouched
    assert patched_dependencies["spire_calls"] == []
    assert patched_dependencies["teg_calls"] == []


@pytest.mark.asyncio
async def test_suspend_captures_teg_failure(monkeypatch, patched_dependencies):
    """If TEG is unreachable, registry + mTLS still flip but TEG marked failed."""
    async def fake_teg_fail(*args, **kwargs):
        return False
    monkeypatch.setattr(cs, "_teg_suspend", fake_teg_fail)

    agent = _FakeAgent()
    result = await cs.coordinated_agent_suspend(
        _FakeSession(), agent, reason="abuse", actor=_FakeAdmin()
    )

    assert result.registry is True
    assert result.mtls == "revoked"
    assert result.teg == "failed"
    assert "teg" in (result.error or "")


# ============================================================ reinstate happy path

@pytest.mark.asyncio
async def test_full_reinstate_flips_all_three_levers(patched_dependencies):
    # Agent currently suspended + mTLS revoked BY the suspension, which keeps spiffe_id as its restore marker
    # (§TWOAGENT #35, V0429). A never-enrolled agent is NOT enrolled by a reinstate: test_twoagent_reinstate_restores_only.
    agent = _FakeAgent(status="suspended", mtls_enabled=False, spiffe_id="spiffe://agentvault.com/agent/abc")
    agent.enforcement_status = "suspended"

    result = await cs.coordinated_agent_reinstate(
        _FakeSession(), agent, actor=_FakeAdmin(), soft=False
    )

    assert result.registry is True
    assert result.mtls == "enrolled"
    assert result.teg == "reinstated"
    assert agent.status == "active"
    assert agent.mtls_enabled is True
    assert agent.spiffe_id is not None  # fresh SVID
    assert any("register:" in c for c in patched_dependencies["spire_calls"])


@pytest.mark.asyncio
async def test_reinstate_when_already_enrolled_skips_register(patched_dependencies):
    """Idempotent: if agent's mTLS state is already enrolled (e.g., admin reinstated
    twice), the function reports 'already_enrolled' and doesn't touch SPIRE."""
    agent = _FakeAgent(status="suspended", mtls_enabled=True, spiffe_id="spiffe://x/y")
    agent.enforcement_status = "suspended"
    result = await cs.coordinated_agent_reinstate(
        _FakeSession(), agent, actor=_FakeAdmin()
    )
    assert result.mtls == "already_enrolled"


@pytest.mark.asyncio
async def test_soft_reinstate_skips_mtls_and_teg(patched_dependencies):
    agent = _FakeAgent(status="suspended", mtls_enabled=False, spiffe_id=None)
    agent.enforcement_status = "suspended"
    result = await cs.coordinated_agent_reinstate(
        _FakeSession(), agent, actor=_FakeAdmin(), soft=True
    )
    assert result.registry is True
    assert result.mtls == "skipped"
    assert result.teg == "skipped"
    assert patched_dependencies["spire_calls"] == []
