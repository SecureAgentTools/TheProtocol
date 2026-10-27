"""§TWOAGENT #35 (2026-09-23) — a coordinated reinstate restores what the suspension took, and grants nothing else.

Measured on production (V0428), on both sessions' agents: the coordinated bulk suspend reported `mtls=not_enrolled`
(neither agent had ever enrolled), and the coordinated reinstate reported `mtls=enrolled`. Each agent came back with a
SPIRE registration entry, a SPIFFE id, mtls_enabled=true and an agent card saying mTLS enabled, none of which its
owner asked for. `_ironhand_enroll` enrolled ANY reinstated agent. The suspend's revoke also cleared the only trace of
what it had taken away (spiffe_id), so the reinstate could not tell "the suspension revoked it" from "never had it".

Now the suspension keeps spiffe_id (with mtls_enabled false it grants nothing: every reader that treats an agent as
enrolled also requires mtls_enabled), and the reinstate restores only when it is there. The owner's disable and the
admin revoke clear it, so neither is ever undone by a reinstate.

RED on the pre-change tree: the first three tests. The round trip and the already-enrolled case are controls.
"""
from __future__ import annotations

import asyncio
import importlib
import types
from datetime import datetime, timezone

import pytest

cs = importlib.import_module("agentvault_registry.services.coordinated_suspension")
DID = "did:theprotocol:eu.theprotocol.cloud:950eadac-6787-4302-a3b9-4d66d944015b"
SVID = "spiffe://eu.theprotocol.cloud/agent/did-theprotocol-eu.theprotocol.cloud-950eadac-6787-4302-a3b9-4d66d944015b"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Emitter:
    """Records what the mTLS lever tells the ledger; every test asserts what it RECEIVED (tests/test_doubles_assert_receipt)."""
    def __init__(self):
        self.received = []

    async def emit_agent_mtls_revoked(self, **kw):
        self.received.append(("revoked", kw))

    async def emit_agent_mtls_enrolled(self, *a, **kw):
        self.received.append(("enrolled", a, kw))


@pytest.fixture
def spire(monkeypatch):
    rec = {"register": [], "delete": [], "card": []}
    spire_mod = importlib.import_module("agentvault_registry.services.agent_spire")
    mtls_mod = importlib.import_module("agentvault_registry.routers.agent_mtls")
    em_mod = importlib.import_module("agentvault_registry.event_emitter")

    def _register(did, *a, **k):
        rec["register"].append(did)
        return SVID

    def _delete(did, *a, **k):
        rec["delete"].append(did)

    async def _card(db, did, spiffe_id, enabled):
        rec["card"].append((did, spiffe_id, enabled))
    emitter = _Emitter()
    monkeypatch.setattr(spire_mod, "register_agent_spire_entry", _register)
    monkeypatch.setattr(spire_mod, "delete_agent_spire_entry", _delete)
    monkeypatch.setattr(mtls_mod, "_patch_agent_card_mtls", _card)
    monkeypatch.setattr(em_mod, "get_event_emitter", lambda: emitter)
    rec["emitter"] = emitter
    return rec


def _agent(**kw):
    d = dict(did=DID, spiffe_id=None, mtls_enabled=False, mtls_enrolled_at=None, status="suspended")
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_a_never_enrolled_agent_is_not_enrolled_by_a_reinstate(spire):
    a = _agent()
    assert _run(cs._ironhand_enroll(None, a)) == "not_enrolled"
    assert spire["register"] == [] and spire["card"] == []
    assert a.mtls_enabled is False and a.spiffe_id is None
    assert spire["emitter"].received == [], "no enrollment event for an identity nobody got"


def test_an_owner_disabled_agent_is_not_re_enrolled_by_a_reinstate(spire):
    # disable_mtls: spiffe_id cleared, mtls_enabled false, mtls_enrolled_at KEPT as the revocation marker
    a = _agent(mtls_enrolled_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    assert _run(cs._ironhand_enroll(None, a)) == "not_enrolled"
    assert spire["register"] == [] and spire["emitter"].received == []


def test_the_suspend_keeps_its_restore_marker(spire):
    a = _agent(spiffe_id=SVID, mtls_enabled=True, mtls_enrolled_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
               status="active")
    assert _run(cs._ironhand_revoke(None, a, actor_email="admin@frame.example")) == "revoked"
    assert spire["delete"] == [DID] and a.mtls_enabled is False
    assert a.spiffe_id == SVID, "the suspension keeps what it took, so the reinstate can restore exactly that"
    assert spire["card"] == [(DID, None, False)], "the card still says disabled"
    assert [e[0] for e in spire["emitter"].received] == ["revoked"]
    assert spire["emitter"].received[0][1]["spiffe_id"] == SVID, "the blocklists still hear which identity was revoked"


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_round_trip_restores_what_the_suspend_took(spire):
    a = _agent(spiffe_id=SVID, mtls_enabled=True, mtls_enrolled_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
               status="active")
    assert _run(cs._ironhand_revoke(None, a, actor_email="admin@frame.example")) == "revoked"
    assert _run(cs._ironhand_enroll(None, a)) == "enrolled"
    assert spire["register"] == [DID] and a.mtls_enabled is True and a.spiffe_id == SVID
    assert [e[0] for e in spire["emitter"].received] == ["revoked", "enrolled"]


def test_control_an_already_enrolled_agent_is_left_alone(spire):
    a = _agent(spiffe_id=SVID, mtls_enabled=True, status="active")
    assert _run(cs._ironhand_enroll(None, a)) == "already_enrolled"
    assert spire["register"] == []


def test_control_the_suspend_of_a_never_enrolled_agent_revokes_nothing(spire):
    a = _agent(status="active")
    assert _run(cs._ironhand_revoke(None, a, actor_email="admin@frame.example")) == "not_enrolled"
    assert spire["delete"] == [] and a.spiffe_id is None
