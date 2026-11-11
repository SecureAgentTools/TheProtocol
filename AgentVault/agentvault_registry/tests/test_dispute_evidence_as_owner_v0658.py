"""V0658 (d), polish 15 of the disputes discovery: an owner adds evidence for either of their agents from the dispute.

Before: POST /api/v1/disputes/{id}/evidence took an AGENT token only (get_current_agent), so the owner of a party,
reading the dispute in the console as a developer, could not add a word to it without first acting as that agent; on
a frame where the owner has no saved agent credentials, not at all.

Now: POST /api/v1/disputes/{id}/evidence/as-owner takes the owner's developer credential and files the evidence AS the
owned party (its DID is the submitter, as if the agent had sent it), through the same recording as the agent's route:
the same open-dispute rule and the same per-submitter cap. Who may: the owner of a party, for that party only. An owner
of both parties names which one (agent_did); an owner of neither, or a DID that is no party or not theirs, is refused.

The route runs through FastAPI on the real router over real (SQLite) rows; only the session and the caller are given.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.routers import disputes
from tests._doubles import StrictEmitter
from tests._sqlite_db import sqlite_db

OWNER_A, OWNER_B, OWNER_BOTH, NOBODY = 2, 3, 4, 5
A1, B1, X1, Y1 = ("did:theprotocol:aaaaaaaa-0000-4000-8000-000000000001",
                  "did:theprotocol:bbbbbbbb-0000-4000-8000-000000000002",
                  "did:theprotocol:cccccccc-0000-4000-8000-000000000003",
                  "did:theprotocol:dddddddd-0000-4000-8000-000000000004")
T0 = dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc)
EV = {"type": "text", "content": "the delivery missed the agreed format"}


def _seed():
    db = sqlite_db(models.Developer, models.Agent, models.Dispute, models.Evidence)
    s = db.sync
    db.devs = {}
    for i in (OWNER_A, OWNER_B, OWNER_BOTH, NOBODY):
        db.devs[i] = models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x")
        s.add(db.devs[i])
    for n, (did, owner) in enumerate(((A1, OWNER_A), (B1, OWNER_B), (X1, OWNER_BOTH), (Y1, OWNER_BOTH)), start=1):
        s.add(models.Agent(id=n, did=did, client_id=f"c{n}", hashed_client_secret="x", creator_developer_id=owner))
    s.add_all([
        models.Dispute(id=1, complainant_did=A1, defendant_did=B1, status="OPEN", created_at=T0, updated_at=T0),
        models.Dispute(id=2, complainant_did=X1, defendant_did=Y1, status="OPEN", created_at=T0, updated_at=T0),
        models.Dispute(id=3, complainant_did=A1, defendant_did=B1, status="CLOSED", created_at=T0, updated_at=T0),
    ])
    s.commit()
    return db


@pytest.fixture()
def post(monkeypatch):
    db = _seed()
    app = FastAPI()
    app.include_router(disputes.router)
    who = {}

    # the strict double: every call is bound to EventEmitter's real signature, and the test asserts receipt
    emitter = StrictEmitter()

    async def _no_webhook(*a, **kw):
        return None

    monkeypatch.setattr(disputes, "get_event_emitter", lambda: emitter)
    from agentvault_registry.background_tasks import reactor_helpers
    monkeypatch.setattr(reactor_helpers, "dispatch_webhook_for_agents", _no_webhook)

    async def _db():
        yield db

    async def _dev_dep():
        return db.devs[who["dev"]]

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = _dev_dep

    async def _post(dispute_id, dev, body):
        who["dev"] = dev
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.post(f"/api/v1/disputes/{dispute_id}/evidence/as-owner", json=body)

    _post.db = db
    _post.who = who
    _post.emitter = emitter
    return _post


async def test_the_complainants_owner_files_evidence_as_the_complainant(post):
    r = await post(1, OWNER_A, {"evidence_data": EV})
    assert r.status_code == 201, r.text
    assert r.json()["submitter_did"] == A1
    assert r.json()["evidence_data"] == EV
    got = post.emitter.assert_received("EvidenceSubmitted", via="emit")
    assert got["data"]["submitter_did"] == A1 and len(post.emitter.of_type("EvidenceSubmitted")) == 1


async def test_the_defendants_owner_files_as_the_defendant(post):
    r = await post(1, OWNER_B, {"evidence_data": EV})
    assert r.status_code == 201, r.text
    assert r.json()["submitter_did"] == B1


async def test_an_owner_of_no_party_is_refused(post):
    r = await post(1, NOBODY, {"evidence_data": EV})
    assert r.status_code == 403, r.text
    r = await post(1, OWNER_BOTH, {"evidence_data": EV})      # owns agents, none of them in this dispute
    assert r.status_code == 403, r.text


async def test_an_owner_of_both_parties_names_which_one(post):
    r = await post(2, OWNER_BOTH, {"evidence_data": EV})
    assert r.status_code == 422, r.text
    assert "agent_did" in r.text
    r = await post(2, OWNER_BOTH, {"evidence_data": EV, "agent_did": Y1})
    assert r.status_code == 201, r.text
    assert r.json()["submitter_did"] == Y1


async def test_a_named_agent_must_be_a_party_the_caller_owns(post):
    r = await post(1, OWNER_A, {"evidence_data": EV, "agent_did": B1})    # a party, but not theirs
    assert r.status_code == 403, r.text
    r = await post(1, OWNER_BOTH, {"evidence_data": EV, "agent_did": X1})  # theirs, but no party here
    assert r.status_code == 403, r.text


async def test_a_closed_dispute_takes_no_evidence(post):
    r = await post(3, OWNER_A, {"evidence_data": EV})
    assert r.status_code == 400, r.text


async def test_an_unknown_dispute_is_404(post):
    r = await post(99, OWNER_A, {"evidence_data": EV})
    assert r.status_code == 404, r.text
