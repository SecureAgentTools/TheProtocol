"""V0651 (y) (2026-10-31, agentvault2-14): the chat's approval requests outside their room, and their notice.

Order gwo_6f197b1815662c025e8a8eb0, from the maintainer's bug report on his phone (the sessions' room, seq 234/235):
"I don't have approval popup in chat ... and under approvals in pocket it's also not there". Two server halves:

  * GET /api/v1/chat/approvals: every pending, unexpired request the caller may decide, in every organization room this
    registry hosts (Pocket's Approvals lists them). The rooms' own authority, read live: the org's owner or an active
    member the owner named an approver, and still an active member of the org. Agents never decide (403).
  * the notice of an approval card: its push said "[approval.request]" and opened the bare room; it names the ask or
    the decision now, carries the request's title, and opens the room on that request (?approval=<id>).

Run against a real SQLite database (tests/_sqlite_db.py): the filter is only proven where rows are actually filtered.
Each case fails on 48d07ecf2 (V0650), which has neither the route nor the notice.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.models import ChatApproval, Conversation, Organization, OrganizationMember
from tests._sqlite_db import sqlite_db

NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
OWNER, APPROVER, MEMBER, OUTSIDER = 6, 7, 8, 9
AGENT = "did:theprotocol:eu.example.test:00000000-0000-4000-8000-0000000a6e17"


def _seed():
    db = sqlite_db(Organization, OrganizationMember, Conversation, ChatApproval)
    s = db.sync
    s.connection().connection.dbapi_connection.create_function("now", 0, lambda: NOW.isoformat(sep=" "))
    for oid, name, owner in (("org-a", "TheProtocol Sessions", OWNER), ("org-b", "Other firm", OUTSIDER)):
        s.add(Organization(id=oid, name=name, slug=oid, owner_id=owner))
    for i, (org, dev, role, can) in enumerate((("org-a", OWNER, "owner", False), ("org-a", APPROVER, "member", True),
                                               ("org-a", MEMBER, "member", False), ("org-b", OUTSIDER, "owner", False),
                                               ("org-b", OWNER, "member", False))):
        s.add(OrganizationMember(id=f"m{i}", organization_id=org, developer_id=dev, role=role, is_active=True,
                                 can_approve=can))
    s.add(Conversation(id="room-a", kind="org", title="TheProtocol Sessions", org_id="org-a", created_by_ptype="system", created_by_id="genesis"))
    s.add(Conversation(id="room-b", kind="org", title=None, org_id="org-b", created_by_ptype="system", created_by_id="genesis"))
    s.add(Conversation(id="room-mirror", kind="org", title="a peer's room", org_id="org-a", host_registry="https://peer",
                     created_by_ptype="system", created_by_id="genesis"))

    def apr(aid, conv, *, status="pending", minutes=60, created=-10, prod=False):
        s.add(ChatApproval(id=aid, conversation_id=conv, org_id=None, requester_agent_did=AGENT, client_ref=aid,
                           title=f"Request {aid}", unlocks=f"step {aid}", production_impact=prod, facts={},
                           facts_digest="0" * 64, status=status, created_at=NOW + dt.timedelta(minutes=created),
                           expires_at=NOW + dt.timedelta(minutes=minutes)))
    apr("apr_" + "a1" * 16, "room-a", created=-20, prod=True)
    apr("apr_" + "a2" * 16, "room-a", created=-5)
    apr("apr_" + "a3" * 16, "room-a", status="approved")
    apr("apr_" + "a4" * 16, "room-a", minutes=-1)            # past its expiry: never listed
    apr("apr_" + "b1" * 16, "room-b")                          # another org: OWNER is only a member there
    apr("apr_" + "c1" * 16, "room-mirror")                     # a mirror of another registry's room
    s.commit()
    return db


@pytest.fixture()
def client(monkeypatch):
    from agentvault_registry.database import get_db
    from agentvault_registry.errors import register_error_handlers
    from agentvault_registry.routers import chat
    from agentvault_registry.services import chat_approvals as ca

    db = _seed()
    who = {"actor": None}

    async def _names(_db, rows):
        return ({AGENT: "session-lead"}, {})

    async def _now(_db):
        return NOW   # the database's clock (Postgres answers a timestamp; SQLite's stand-in answers text)

    monkeypatch.setattr(ca, "names_for", _names)
    monkeypatch.setattr(ca, "db_now", _now)
    monkeypatch.delenv("CHAT_APPROVALS_ENABLED", raising=False)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(chat.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[chat._approval_reader] = lambda: who["actor"]

    def get(actor, path="/api/v1/chat/approvals"):
        who["actor"] = actor
        return TestClient(app, raise_server_exceptions=False).get(path)
    get.db = db
    return get


def dev(i):
    return {"kind": "developer", "developer": SimpleNamespace(id=i, name=f"dev{i}")}


def test_the_owner_sees_the_pending_unexpired_requests_of_their_rooms_oldest_first(client):
    r = client(dev(OWNER))
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [i["id"] for i in body["items"]]
    assert ids == ["apr_" + "a1" * 16, "apr_" + "a2" * 16], ids          # not decided, not expired, not org-b, no mirror
    first = body["items"][0]
    assert first["room"] == {"conversation_id": "room-a", "title": "TheProtocol Sessions", "org_id": "org-a",
                             "org_name": "TheProtocol Sessions"}
    assert first["production_impact"] is True and first["requester"]["name"] == "session-lead"
    assert body["count"] == 2


def test_a_named_approver_sees_them_and_a_plain_member_sees_none(client):
    assert [i["id"] for i in client(dev(APPROVER)).json()["items"]] == ["apr_" + "a1" * 16, "apr_" + "a2" * 16]
    r = client(dev(MEMBER))
    assert r.status_code == 200 and r.json()["items"] == []


def test_an_owner_elsewhere_sees_their_own_org_only(client):
    assert [i["id"] for i in client(dev(OUTSIDER)).json()["items"]] == ["apr_" + "b1" * 16]


def test_a_decider_who_left_the_org_sees_nothing(client):
    db = client.db
    row = db.sync.get(OrganizationMember, "m1")   # the approver leaves org-a
    row.is_active = False
    db.sync.commit()
    assert client(dev(APPROVER)).json()["items"] == []


def test_an_agent_is_refused(client):
    r = client({"kind": "agent", "agent_did": AGENT, "agent": SimpleNamespace(name="session-lead")})
    assert r.status_code == 403
    assert "agents never decide" in r.text


def test_the_switch_turns_the_list_off(client, monkeypatch):
    monkeypatch.setenv("CHAT_APPROVALS_ENABLED", "false")
    assert client(dev(OWNER)).status_code == 501


def test_the_list_does_not_take_the_place_of_one_request(client):
    # control: /approvals/{id} still answers one request (its own route), the list answers at /approvals
    r = client(dev(OWNER), "/api/v1/chat/approvals?limit=1")
    assert r.status_code == 200 and len(r.json()["items"]) == 1


# ── the notice ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _card_message(ctype, **data):
    return {"id": "m1", "seq": 3, "kind": "card", "body": None,
            "card": {"v": 1, "type": ctype, "data": {"approval_id": "apr_" + "e5" * 16, **data}}}


def test_an_approval_request_notice_names_the_ask_and_opens_the_request():
    from agentvault_registry.services import chat_service as cs
    n = cs.approval_notice(_card_message("approval.request", title="Roll V0651", production_impact=True), "session-lead")
    assert n == {"approval_id": "apr_" + "e5" * 16, "title": "Approval requested by session-lead",
                 "message": "Roll V0651 (affects production)"}


def test_a_decision_notice_says_what_was_decided():
    from agentvault_registry.services import chat_service as cs
    n = cs.approval_notice(_card_message("approval.decided", title="Roll V0651", decision="denied",
                                         decided_by_name="maintainer"), "registry")
    assert n["title"] == "Denied" and n["message"] == "Roll V0651 (maintainer)"


def test_other_messages_and_made_up_ids_get_the_plain_notice():
    from agentvault_registry.services import chat_service as cs
    assert cs.approval_notice({"kind": "text", "body": "hello", "card": None}, "x") is None
    assert cs.approval_notice({"kind": "card", "card": {"v": 1, "type": "media", "data": {}}}, "x") is None
    bad = _card_message("approval.request", title="t")
    bad["card"]["data"]["approval_id"] = "apr_../../evil"
    assert cs.approval_notice(bad, "x") is None


def test_the_push_of_an_approval_request_opens_that_request(monkeypatch):
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.services import chat_service as cs
    sent = []

    async def _notify(event, devs, **kw):
        sent.append((event, devs, kw))

    monkeypatch.setattr(push_notify, "notify", _notify)
    asyncio.run(cs._notify_absent("room-a", _card_message("approval.request", title="Roll V0651"), [OWNER],
                                  "session-lead", False, None))
    (event, devs, kw), = sent
    assert devs == [OWNER] and kw["title"] == "Approval requested by session-lead"
    assert kw["message"] == "Roll V0651"
    assert kw["click"] == "/ui#/pocket/ourchat/room-a?approval=apr_" + "e5" * 16
    # control: a text message keeps the sender's name and the bare room
    sent.clear()
    asyncio.run(cs._notify_absent("room-a", {"kind": "text", "body": "hi"}, [OWNER], "maintainer", False, None))
    assert sent[0][2]["title"] == "maintainer" and sent[0][2]["click"] == "/ui#/pocket/ourchat/room-a"
