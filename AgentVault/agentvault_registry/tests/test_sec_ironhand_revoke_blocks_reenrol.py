"""D6-802 (2026-10-17): after an administrator's IRONHAND revoke the agent cannot enroll itself again.

The admin revoke (POST /api/v1/admin/ironhand/revoke/{did}) cleared the agent's mTLS state exactly as the agent's own
unenrol does and left the agent active, so the agent's own POST /api/v1/agent/enable-mtls (which asks only for an active
agent and identity.mtls) enrolled it again at once. The revoke is now recorded on the agent (agents.mtls_revoked_at,
migration 0192), enable-mtls refuses while it stands, a coordinated reinstate does not restore it, and an administrator's
enrolment (either admin path) ends it.

Through FastAPI on the real routers. Doubles: the database session (it answers the agent), the SPIRE calls, the agent
card patch and the event emitter; the admin and agent dependencies run for real on an administrator and the agent.
RED on b49fc6ad: the two revoke cases (the base enrolls the agent again) and the reinstate case.
"""
from __future__ import annotations

import asyncio
import types
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import admin_agents
from agentvault_registry.routers import agent_mtls as am
from tests._doubles import StrictEmitter  # noqa: E402

DID = "did:theprotocol:7d3c2b1a-0f9e-4d8c-b7a6-5e4d3c2b1a0f"
SPIFFE = "spiffe://eu.theprotocol.cloud/agent/did-theprotocol-7d3c2b1a-0f9e-4d8c-b7a6-5e4d3c2b1a0f"
ADMIN = types.SimpleNamespace(id=1, email="admin@example.test", name="Admin", is_admin=True,
                              must_change_password=False, admin_treasury=False, admin_support=False,
                              admin_enforcement=False, admin_federation=False, admin_platform=True)


def _agent(enrolled=True):
    return types.SimpleNamespace(
        id=42, did=DID, status="active", mtls_enabled=enrolled, spiffe_id=SPIFFE if enrolled else None,
        mtls_enrolled_at=datetime(2026, 10, 1, tzinfo=timezone.utc), mtls_revoked_at=None)


class _Res:
    def __init__(self, one):
        self._one = one

    def scalar_one_or_none(self):
        return self._one


class _Db:
    def __init__(self, agent):
        self.agent, self.commits = agent, 0

    async def execute(self, _stmt):
        return _Res(self.agent)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def spire(monkeypatch):
    """SPIRE, the card patch, the emitter and the post-commit fan-out, recorded."""
    out = {"registered": [], "deleted": [], "em": StrictEmitter()}

    def register(did, fingerprint=None):
        out["registered"].append(did)
        return SPIFFE

    def delete(did):
        out["deleted"].append(did)
        return True

    async def no_card(db, did, spiffe_id, enabled):
        return None

    async def quiet(*a, **k):
        return None

    import agentvault_registry.event_emitter as ee
    from agentvault_registry.services import agent_spire
    from agentvault_registry.background_tasks import push_notify, reactor_helpers
    monkeypatch.setattr(am, "register_agent_spire_entry", register)
    monkeypatch.setattr(agent_spire, "register_agent_spire_entry", register)   # admin_agents imports it lazily
    monkeypatch.setattr(am, "delete_agent_spire_entry", delete)
    monkeypatch.setattr(am, "check_agent_spire_entry", lambda did: "entry-1")
    monkeypatch.setattr(am, "_parent_fingerprint_for_self", lambda: "fp")
    monkeypatch.setattr(am, "_detect_deployment", lambda request, did: ("onbox", "test"))
    monkeypatch.setattr(am, "_patch_agent_card_mtls", no_card)
    monkeypatch.setattr(ee, "get_event_emitter", lambda: out["em"])
    monkeypatch.setattr(admin_agents, "get_event_emitter", lambda: out["em"])
    monkeypatch.setattr(push_notify, "notify_agent_owners", quiet)
    monkeypatch.setattr(reactor_helpers, "dispatch_webhook_for_agents", quiet)
    return out


def _client(agent):
    app = FastAPI()
    app.include_router(am.router)
    app.include_router(am.admin_router)
    app.include_router(admin_agents.router)
    db = _Db(agent)

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = lambda: ADMIN
    app.dependency_overrides[security.get_current_agent] = lambda: agent
    app.dependency_overrides[security.verify_agent_token] = lambda: {}
    return TestClient(app, raise_server_exceptions=False)


def test_after_an_admin_revoke_the_agent_cannot_enroll_itself_again(spire):
    agent = _agent(enrolled=True)
    c = _client(agent)
    r = c.post(f"/api/v1/admin/ironhand/revoke/{DID}")
    assert r.status_code == 200 and r.json()["status"] == "revoked", (r.status_code, r.text[:300])
    assert agent.mtls_enabled is False and agent.spiffe_id is None and spire["deleted"] == [DID]
    r = c.post("/api/v1/agent/enable-mtls")
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert "administrator" in r.json()["detail"]
    assert spire["registered"] == [] and agent.mtls_enabled is False and agent.spiffe_id is None


def test_an_admin_revoke_of_an_agent_not_enrolled_now_blocks_it_too(spire):
    agent = _agent(enrolled=False)
    c = _client(agent)
    r = c.post(f"/api/v1/admin/ironhand/revoke/{DID}")
    assert r.status_code == 200 and r.json()["status"] == "not_enrolled", (r.status_code, r.text[:300])
    r = c.post("/api/v1/agent/enable-mtls")
    assert r.status_code == 403, (r.status_code, r.text[:300])
    assert spire["registered"] == []


@pytest.mark.parametrize("enrol_path", ["/api/v1/admin/ironhand/enroll/{did}",
                                        "/api/v1/admin/agents/{did}/force-mtls-enrol"])
def test_an_administrators_enrolment_ends_the_revoke(spire, enrol_path):
    agent = _agent(enrolled=True)
    c = _client(agent)
    assert c.post(f"/api/v1/admin/ironhand/revoke/{DID}").status_code == 200
    r = c.post(enrol_path.format(did=DID))
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert agent.mtls_enabled is True and agent.mtls_revoked_at is None
    # the agent turns it off itself and back on: nothing blocks it any more
    assert c.post("/api/v1/agent/disable-mtls").json()["status"] == "unenrolled"
    r = c.post("/api/v1/agent/enable-mtls")
    assert r.status_code == 200 and r.json()["status"] == "enrolled", (r.status_code, r.text[:300])


def test_control_the_agents_own_unenrol_does_not_block_it(spire):
    agent = _agent(enrolled=True)
    c = _client(agent)
    assert c.post("/api/v1/agent/disable-mtls").json()["status"] == "unenrolled"
    r = c.post("/api/v1/agent/enable-mtls")
    assert r.status_code == 200 and r.json()["status"] == "enrolled", (r.status_code, r.text[:300])
    assert spire["registered"] == [DID]


def test_a_reinstate_does_not_restore_an_identity_an_administrator_revoked(spire):
    from agentvault_registry.services import coordinated_suspension as cs
    # suspended with mTLS on: the suspension kept spiffe_id as its restore marker; an admin revoked the identity since
    agent = _agent(enrolled=False)
    agent.spiffe_id, agent.mtls_revoked_at = SPIFFE, datetime(2026, 10, 17, tzinfo=timezone.utc)
    assert asyncio.run(cs._ironhand_enroll(_Db(agent), agent)) == "not_enrolled"
    assert spire["registered"] == [] and agent.mtls_enabled is False


def test_control_a_reinstate_restores_what_the_suspension_took(spire):
    from agentvault_registry.services import coordinated_suspension as cs
    agent = _agent(enrolled=False)
    agent.spiffe_id = SPIFFE
    assert asyncio.run(cs._ironhand_enroll(_Db(agent), agent)) == "enrolled"
    assert spire["registered"] == [DID] and agent.mtls_enabled is True
