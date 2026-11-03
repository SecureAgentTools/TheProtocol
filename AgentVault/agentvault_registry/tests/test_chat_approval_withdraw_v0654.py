"""V0654 (aq), item 18 (sessionlogs2026/PLAN_2026-11-01_V0653_CANDIDATES.md): the agent that asked for an approval can take
the request back while it waits. V0653's first card apr_258805bb stayed pinned after the recut voided it: no route did.

POST /api/v1/chat/approvals/{id}/withdraw (agent JWT, the agent that asked): the record turns "withdrawn" in one UPDATE
that repeats every condition (the asker, pending, unexpired), the request's card reads withdrawn (updated in place by the
approval rail, then closed) and it leaves the pinned list (which lists the pending ones); deciding and using it are
refused from then on. A decided or expired request is not withdrawn; a repeat answers as done.

Pure rules directly; the route through FastAPI on the real chat router with the database, the conversation lookup and the
card writer replaced (test_chat_approval_consume.py's pattern). BASE (V0653, f8f1993fb): no route, no rule, no state.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

NOW = dt.datetime(2026, 11, 2, 16, 0, 0, tzinfo=dt.timezone.utc)
ORG = "org-sessions"
CONV = "conv-room-1"
OWNER = 6
AGENT = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-000000000001"
OTHER = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-000000000002"


def _row(aid="apr_w1", status="pending", minutes=60):
    return SimpleNamespace(
        id=aid, conversation_id=CONV, org_id=ORG, requester_agent_did=AGENT, client_ref=f"ref-{aid}",
        request_message_id=f"msg-{aid}", title=f"Roll {aid}", reason=None, unlocks=None, artifact_sha256="ab" * 32,
        artifact_label="run_prod653.sh", production_impact=True, facts={"approval_id": aid}, facts_digest="d" * 64,
        status=status, created_at=NOW - dt.timedelta(minutes=5), expires_at=NOW + dt.timedelta(minutes=minutes),
        decided_at=NOW - dt.timedelta(minutes=1) if status != "pending" else None,
        decided_by_developer_id=OWNER if status in ("approved", "denied") else None,
        decided_by_role="owner" if status in ("approved", "denied") else None, decision_note=None, decision_via=None,
        presence_method=None, presence_challenge_id=None, decision_statement=None,
        consumed_at=None, consumed_by_agent_did=None, consumed_act=None, consumed_act_sha256=None)


# ── the rules ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _refuse(row, agent=AGENT):
    from agentvault_registry.services import chat_approvals as ca
    return ca.withdraw_refusal(row, agent_did=agent, now=NOW)


def test_a_waiting_request_of_its_asker_may_be_withdrawn_and_a_repeat_is_no_refusal():
    assert _refuse(_row()) is None
    assert _refuse(_row(), agent=AGENT.upper()) is None                  # a DID compares case-insensitively
    assert _refuse(_row(status="withdrawn")) is None                     # the route answers it as done


def test_only_the_agent_that_asked_and_only_while_it_waits():
    code, sentence = _refuse(_row(), agent=OTHER)
    assert code == 403 and AGENT in sentence
    for st in ("approved", "denied", "chosen"):
        code, sentence = _refuse(_row(status=st))
        assert code == 409 and f"already {st}" in sentence
    code, sentence = _refuse(_row(minutes=-1))
    assert code == 410 and "expired at" in sentence
    assert _refuse(None) == (404, "approval request not found")


def test_a_withdrawn_request_is_neither_decided_nor_used():
    from agentvault_registry.services import chat_approvals as ca
    decidable, skipped = ca.partition_for_decision([_row(status="withdrawn")], ["apr_w1"], NOW)
    assert decidable == [] and skipped == {"apr_w1": "already_withdrawn"}
    code, sentence, already = ca.refusal_when_nothing_decided(skipped, "approve")
    assert (code, already) == (409, False) and "withdrew this request" in sentence
    code, sentence = ca.consume_refusal(_row(status="withdrawn"), agent_did=AGENT, act_sha256="ab" * 32, now=NOW,
                                        role="owner")
    assert code == 409 and "is withdrawn, not approved" in sentence


def test_the_record_says_withdrawn_and_when():
    from agentvault_registry.services import chat_approvals as ca
    out = ca.serialize(_row(status="withdrawn"), NOW)
    assert out["status"] == "withdrawn" and out["withdrawn"]["at"] == (NOW - dt.timedelta(minutes=1)).isoformat()
    assert "decision" not in out and ca.serialize(_row(), NOW).get("withdrawn") is None


def test_the_request_card_takes_one_update_by_its_rail_then_is_closed():
    from agentvault_registry.services import chat_live_cards as lc
    assert lc.UPDATABLE["approval.request"] == "rail" and lc.UPDATABLE["choice.request"] == "rail"
    card = {"v": 1, "type": "approval.request", "data": {"approval_id": "apr_w1", "title": "t", "expires_at": "x"}}
    assert lc.closed_reason(card) is None
    card["data"]["withdrawn"] = {"at": NOW.isoformat(), "by_agent_did": AGENT}
    assert lc.closed_reason(card) == "the request was withdrawn"


# ── the route ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class _R:
    def __init__(self, first=None, scalar=None):
        self._first, self._scalar = first, scalar

    def first(self):
        return self._first

    def scalar_one(self):
        return self._scalar


class _DB:
    """The statements the withdraw path sends, by their text. `race` makes the UPDATE find the request decided first."""

    def __init__(self, rows, race=False):
        self.rows = {r.id: r for r in rows}
        self.race = race
        self.updated = []
        self.commits = self.rollbacks = 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        if sql.startswith("SELECT now()"):
            return _R(scalar=NOW)
        if sql.startswith("UPDATE chat_approvals SET status = 'withdrawn'"):
            assert "status = 'pending'" in sql and "expires_at > now()" in sql
            assert "lower(requester_agent_did) = lower(:a)" in sql
            r = self.rows.get(p["id"])
            if self.race and r is not None:
                r.status, r.decided_at, r.decided_by_developer_id, r.decided_by_role = "approved", NOW, OWNER, "owner"
            if r is None or r.status != "pending" or r.expires_at <= NOW or r.requester_agent_did.lower() != p["a"].lower():
                return _R(first=None)
            r.status, r.decided_at = "withdrawn", NOW
            self.updated.append(p["id"])
            return _R(first=(NOW,))
        raise AssertionError(f"unexpected statement: {sql[:120]}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture()
def withdraw(monkeypatch):
    from agentvault_registry.database import get_db
    from agentvault_registry.errors import register_error_handlers
    from agentvault_registry.routers import chat
    from agentvault_registry.security import get_current_agent
    from agentvault_registry.services import admin_audit
    from agentvault_registry.services import chat_approvals as ca
    from agentvault_registry.services import chat_service as cs

    state = {"cards": [], "audit": []}

    async def _conv(db, cid):
        return SimpleNamespace(id=cid, kind="org", org_id=ORG, host_registry=None, mode="open")

    async def _fetch(db, aid, fresh=False):
        return db.rows.get(aid)

    async def _names(db, rows):
        return ({AGENT: "session-release"}, {OWNER: "maintainer"})

    async def _card(db, conv, row, actor, at):
        state["cards"].append((row.id, actor.agent_did, at))

    async def _audit(db, **kw):
        state["audit"].append(kw)

    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(ca, "fetch", _fetch)
    monkeypatch.setattr(ca, "names_for", _names)
    monkeypatch.setattr(chat, "_request_card_shows_withdrawn", _card)
    monkeypatch.setattr(admin_audit, "log_chat_action", _audit)
    monkeypatch.delenv("CHAT_APPROVALS_ENABLED", raising=False)

    def call(db, *, agent=AGENT, aid="apr_w1"):
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(chat.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=agent, name="session-release")
        return TestClient(app, raise_server_exceptions=False).post(f"/api/v1/chat/approvals/{aid}/withdraw")
    call.state = state
    return call


def test_the_asker_withdraws_a_waiting_request_and_its_card_says_so(withdraw):
    db = _DB([_row()])
    r = withdraw(db)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already"] is False and body["approval"]["status"] == "withdrawn"
    assert db.updated == ["apr_w1"] and db.commits == 1
    assert withdraw.state["cards"] == [("apr_w1", AGENT, NOW)]
    assert withdraw.state["audit"][0]["action"] == "approval.withdrawn"


def test_a_repeat_answers_as_done_and_writes_nothing(withdraw):
    db = _DB([_row(status="withdrawn")])
    r = withdraw(db)
    assert r.status_code == 200 and r.json()["already"] is True, r.text
    assert db.updated == [] and withdraw.state["cards"] == []


@pytest.mark.parametrize("row,agent,code", [(_row(), OTHER, 403), (_row(status="approved"), AGENT, 409),
                                            (_row(minutes=-1), AGENT, 410)], ids=["another-agent", "decided", "expired"])
def test_refusals_change_nothing(withdraw, row, agent, code):
    db = _DB([row])
    r = withdraw(db, agent=agent)
    assert r.status_code == code, r.text
    assert db.updated == [] and withdraw.state["cards"] == [] and withdraw.state["audit"] == []


def test_a_decision_that_lands_first_wins_and_the_route_says_so(withdraw):
    db = _DB([_row()], race=True)
    r = withdraw(db)
    assert r.status_code == 409 and "already approved" in r.text, r.text
    assert db.rollbacks == 1 and withdraw.state["cards"] == []


def test_the_route_takes_an_agent_credential_only():
    from agentvault_registry.routers import chat
    route = next(rt for rt in chat.router.routes if getattr(rt, "path", "").endswith("/approvals/{approval_id}/withdraw"))
    deps = [d.call.__name__ for d in route.dependant.dependencies]
    assert "get_current_agent" in deps and "get_current_actor_for_read_or_key" not in deps


async def test_the_request_card_reads_withdrawn_in_place_by_the_rail(monkeypatch):
    from agentvault_registry.routers import chat
    from agentvault_registry.services import chat_service as cs
    card = {"v": 1, "type": "approval.request", "data": {"approval_id": "apr_w1", "title": "Roll", "expires_at": "x"},
            "refs": {"approval_id": "apr_w1"}}
    seen = []

    class _Db:
        async def execute(self, stmt, params=None):
            return _R(first=("msg-apr_w1", card))

    async def _update(db, conv_id, mid, actor, new, *, rail_author=False):
        seen.append((conv_id, mid, new, rail_author))
        return {"id": mid}, SimpleNamespace(id=conv_id), True

    async def _deliver(db, conv, msg, actor):
        seen.append(("delivered", msg["id"]))

    monkeypatch.setattr(cs, "update_card", _update)
    monkeypatch.setattr(cs, "deliver_card_update", _deliver)
    actor = cs.Actor("agent", agent_did=AGENT, display_name="session-release")
    await chat._request_card_shows_withdrawn(_Db(), SimpleNamespace(id=CONV), _row(), actor, NOW)
    (conv_id, mid, new, rail), delivered = seen
    assert (conv_id, mid, rail) == (CONV, "msg-apr_w1", True) and delivered == ("delivered", "msg-apr_w1")
    assert new["data"]["withdrawn"] == {"at": NOW.isoformat(), "by_agent_did": AGENT}
    assert "withdrawn" not in card["data"]                                # the stored value is not edited in place
