"""V0650 (l) (2026-10-31, agentvault2-14): approvals in the chat, pinned above the history.

Order gwo_dafb543e979a689b21ae69de. The acceptance asked for: an agent cannot decide, approve-all decides only the
pending ones, an expired request cannot be approved. Beside those: only the org's owner or a named approver decides,
a decision is final and idempotent, presence is OFF unless switched on and then asks for an enrolled device only (a
challenge answered with an authenticator code is refused and not spent), deny never asks, the decision repeats the
artifact's sha256 and the request's digest, the two cards are rail-only, and the request route is the asking agent's.

Pure rules are tested directly; the routes through FastAPI on the real chat router, with only the database, the
conversation lookup and the post-commit card writer replaced. Each case marked BASE fails on 6c1f036b (V0649), where
neither the routes, the service nor the card types exist.
"""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

NOW = dt.datetime(2026, 10, 31, 4, 0, 0, tzinfo=dt.timezone.utc)
ORG = "org-sessions"
CONV = "conv-room-1"
OWNER = 6
APPROVER = 7
MEMBER = 8
AGENT = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-000000000001"


def _row(aid, status="pending", minutes=60, production=False, sha=None, title=None):
    return SimpleNamespace(
        id=aid, conversation_id=CONV, org_id=ORG, requester_agent_did=AGENT, client_ref=f"ref-{aid}",
        request_message_id=f"msg-{aid}", title=title or f"Request {aid}", reason=None, unlocks=None,
        artifact_sha256=sha, artifact_label=None, production_impact=production,
        facts={"approval_id": aid}, facts_digest="d" * 64, status=status,
        created_at=NOW - dt.timedelta(minutes=5), expires_at=NOW + dt.timedelta(minutes=minutes),
        decided_at=None, decided_by_developer_id=None, decided_by_role=None, decision_note=None, decision_via=None,
        presence_method=None, presence_challenge_id=None, decision_statement=None)


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------

def test_approve_all_partition_decides_only_pending_unexpired_requests():
    from agentvault_registry.services import chat_approvals as ca
    rows = [_row("apr_p1"), _row("apr_p2"), _row("apr_ok", status="approved"), _row("apr_no", status="denied"),
            _row("apr_old", minutes=-1)]
    ids = ["apr_p1", "apr_ok", "apr_no", "apr_old", "apr_p2", "apr_ghost", "apr_p1"]
    decidable, skipped = ca.partition_for_decision(rows, ids, NOW)
    assert [r.id for r in decidable] == ["apr_p1", "apr_p2"]
    assert skipped == {"apr_ok": "already_approved", "apr_no": "already_denied", "apr_old": "expired",
                       "apr_ghost": "not_found"}


def test_a_pending_row_past_its_expiry_reads_as_expired():
    from agentvault_registry.services import chat_approvals as ca
    assert ca.effective_status("pending", NOW - dt.timedelta(seconds=1), NOW) == "expired"
    assert ca.effective_status("pending", NOW + dt.timedelta(seconds=1), NOW) == "pending"
    assert ca.effective_status("approved", NOW - dt.timedelta(days=1), NOW) == "approved"


@pytest.mark.parametrize("skipped,decision,want", [
    ({"a": "not_found"}, "approve", (404, False)),
    ({"a": "expired", "b": "not_found"}, "approve", (410, False)),
    ({"a": "already_approved"}, "approve", (200, True)),
    ({"a": "already_approved", "b": "expired"}, "approve", (200, True)),
    ({"a": "already_denied"}, "approve", (409, False)),
    ({"a": "already_approved"}, "deny", (409, False)),
])
def test_what_a_decision_that_decided_nothing_answers(skipped, decision, want):
    from agentvault_registry.services import chat_approvals as ca
    code, _sentence, already = ca.refusal_when_nothing_decided(skipped, decision)
    assert (code, already) == want


def test_presence_is_off_by_default_and_an_org_can_only_add_a_floor(monkeypatch):
    from agentvault_registry.services import chat_approvals as ca
    monkeypatch.delenv("CHAT_APPROVAL_PRESENCE", raising=False)
    assert ca.registry_presence() == "off"
    assert ca.presence_policy("off", {}) == "off"
    assert ca.presence_policy("off", {"chat_approvals": {"presence": "production"}}) == "production"
    assert ca.presence_policy("all", {"chat_approvals": {"presence": "off"}}) == "all"     # never loosened
    monkeypatch.setenv("CHAT_APPROVAL_PRESENCE", "of")                                      # a typo is never off
    assert ca.registry_presence() == "production"


def test_deny_never_asks_for_presence_and_production_asks_only_when_flagged():
    from agentvault_registry.services import chat_approvals as ca
    assert ca.presence_required("all", "deny", True) is False
    assert ca.presence_required("off", "approve", True) is False
    assert ca.presence_required("production", "approve", False) is False
    assert ca.presence_required("production", "approve", True) is True
    assert ca.presence_required("all", "approve", False) is True


def test_the_artifact_hash_is_normalized_or_refused():
    from agentvault_registry.services import chat_approvals as ca
    h = "ab" * 32
    assert ca.normalize_sha256("sha256:" + h.upper()) == h
    assert ca.normalize_sha256("") is None
    with pytest.raises(ca.ApprovalError) as e:
        ca.normalize_sha256("not-a-hash")
    assert e.value.status_code == 422


@pytest.mark.parametrize("ctype", ["approval.request", "approval.decided"])
def test_both_approval_cards_are_rail_only(ctype):
    # BASE: "unknown card type ... the vocabulary is closed"
    from agentvault_registry.services import chat_service as cs
    reason = cs.validate_card({"v": 1, "type": ctype, "data": {}}, rail_author=False)
    assert reason and reason.startswith(f"card type {ctype!r} is written only by the chat approval rail"), reason


def test_the_rail_writes_well_formed_approval_cards_and_refuses_malformed_ones():
    from agentvault_registry.services import chat_approvals as ca
    from agentvault_registry.services import chat_service as cs
    row = _row("apr_" + "1" * 32, sha="c" * 64, title="Roll V0649 to production")
    assert cs.validate_card(ca.request_card(row), rail_author=True) is None
    stmt = {"decision": "approved", "decided_at": ca.iso(NOW),
            "decided_by": {"developer_id": OWNER, "name": "Commander", "role": "owner"}}
    card = ca.decided_card(row, stmt)
    assert cs.validate_card(card, rail_author=True) is None
    assert card["data"]["artifact_sha256"] == "c" * 64 and card["data"]["request_digest"] == row.facts_digest
    bad = json.loads(json.dumps(card))
    bad["data"]["decision"] = "maybe"
    assert "approved or denied" in (cs.validate_card(bad, rail_author=True) or "")
    assert cs.preview_for("card", None, ca.request_card(row)) == "Asks for approval: Roll V0649 to production"
    assert cs.preview_for("card", None, card) == "Approved: Roll V0649 to production"


def test_a_federated_peer_cannot_deliver_an_approval_card():
    """The relay receiving a peer's message validates with rail_author=False: a rail-only type is refused there too."""
    from agentvault_registry.services import chat_service as cs
    card = {"v": 1, "type": "approval.decided", "data": {"approval_id": "apr_x", "title": "t",
                                                        "decision": "approved", "decided_by_developer_id": 6}}
    assert "written only by the chat approval rail" in (cs.validate_card(card) or "")


def test_the_statement_repeats_the_artifact_and_the_request_digest_and_verifies():
    from agentvault_registry.services import chat_approvals as ca
    row = _row("apr_s1", sha="e" * 64)
    via = ca.via_record(api_key_id=None, api_key_scopes=None, mcp_relay=False, surface="console")
    stmt = ca.build_statement(row, decision="approve", decided_at=NOW, decider_id=OWNER, decider_name="Commander",
                              role="owner", via=via, presence=None, registry="EU")
    assert stmt["artifact_sha256"] == "e" * 64 and stmt["request_digest"] == row.facts_digest
    assert stmt["decision"] == "approved" and stmt["decided_by"] == {"developer_id": OWNER, "name": "Commander",
                                                                     "role": "owner"}
    assert stmt["via"]["credential"] == "session" and stmt["via"]["surface_is"] == "client_asserted"
    if stmt.get("signature"):
        from agentvault_registry.services.attestation_signer import verify_bundle_signature
        ok, why = verify_bundle_signature(dict(stmt))
        assert ok, why
    else:
        assert stmt.get("unsigned_reason"), "an unsigned statement must say why"


# ---------------------------------------------------------------------------
# The routes, through FastAPI on the real chat router
# ---------------------------------------------------------------------------

class _R:
    def __init__(self, first=None, scalar=None, rows=None):
        self._first, self._scalar, self._rows = first, scalar, rows

    def first(self):
        return self._first

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        rows = list(self._rows or [])
        return SimpleNamespace(all=lambda: rows, first=lambda: rows[0] if rows else None)


class _DB:
    """Answers the statements the decide path sends, by their text; anything else fails the test loudly."""

    def __init__(self, rows, members=None, challenge=None):
        self.rows = {r.id: r for r in rows}
        self.members = members or {}
        self.challenge = challenge
        self.updated, self.spent, self.added = [], [], []
        self.commits = self.rollbacks = 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        if sql.startswith("SELECT now()"):
            return _R(scalar=NOW)
        if "FROM organization_members" in sql:
            return _R(first=self.members.get(int(p["d"])))
        if sql.startswith("SELECT chat_approvals.") and "FOR UPDATE" in sql:
            bound = stmt.compile().params
            ids = next(v for k, v in bound.items() if k.startswith("id_"))
            return _R(rows=[r for i, r in self.rows.items() if i in ids])
        if sql.startswith("UPDATE chat_approvals"):
            r = self.rows.get(p["id"])
            if r is None or r.status != "pending" or r.expires_at <= NOW:
                return _R(first=None)
            r.status, r.decided_at, r.decided_by_developer_id = p["st"], p["t"], p["d"]
            r.decided_by_role, r.decision_note = p["role"], p["n"]
            r.decision_via, r.decision_statement = json.loads(p["via"]), json.loads(p["stmt"])
            r.presence_method, r.presence_challenge_id = p["pm"], p["pc"]
            self.updated.append(p["id"])
            return _R(first=(p["id"],))
        if sql.startswith("UPDATE liability_challenges SET status='spent'"):
            self.spent.append(p["c"])
            return _R(first=(p["c"],))
        raise AssertionError(f"unexpected statement: {sql[:120]}")

    async def get(self, model, key):
        if self.challenge is not None and key == self.challenge.id:
            return self.challenge
        return None

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture()
def room(monkeypatch):
    """The chat router with the room, the org and the card writer replaced; returns a caller."""
    from agentvault_registry.database import get_db
    from agentvault_registry.errors import register_error_handlers
    from agentvault_registry.routers import chat
    from agentvault_registry.security import get_current_developer
    from agentvault_registry.services import admin_audit, governance_presence, stepup
    from agentvault_registry.services import chat_approvals as ca
    from agentvault_registry.services import chat_service as cs

    state = {"org_settings": {}, "kind": "org", "device": False, "cards": [], "audit": []}

    async def _conv(db, cid):
        return SimpleNamespace(id=cid, kind=state["kind"], org_id=ORG, host_registry=None, mode="open")

    async def _membership(db, conv, actor, **kw):
        return SimpleNamespace(state="active", can_post=True)

    async def _org(db, org_id):
        return {"owner_id": OWNER, "chat_enabled": True, "settings": state["org_settings"]}

    async def _fetch(db, aid, fresh=False):
        return db.rows.get(aid)

    async def _names(db, rows):
        return ({AGENT: "session-release"}, {})

    async def _insert(db, conv, my_row, sender, kind, body, card, client_ref, reply_to=None, **kw):
        state["cards"].append((card, client_ref, reply_to, kw.get("rail_author")))
        return SimpleNamespace(id="m-" + client_ref), False

    async def _recipients(db, conv, sender):
        return []

    async def _audit(db, **kw):
        state["audit"].append(kw)

    async def _factors(db, dev):
        return {"totp": True, "device": state["device"], "any": True}

    async def _announce(*a, **kw):
        state.setdefault("cues", []).append(a)

    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _membership)
    monkeypatch.setattr(cs, "insert_message", _insert)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"id": m.id})
    monkeypatch.setattr(cs, "recipients_snapshot", _recipients)
    monkeypatch.setattr(cs, "deliver", lambda *a, **kw: None)
    monkeypatch.setattr(ca, "org_facts", _org)
    monkeypatch.setattr(ca, "fetch", _fetch)
    monkeypatch.setattr(ca, "names_for", _names)
    monkeypatch.setattr(admin_audit, "log_chat_action", _audit)
    monkeypatch.setattr(stepup, "available_factors", _factors)
    monkeypatch.setattr(governance_presence, "announce_challenge", _announce)
    monkeypatch.delenv("CHAT_APPROVAL_PRESENCE", raising=False)
    monkeypatch.delenv("CHAT_APPROVALS_ENABLED", raising=False)

    def call(db, dev_id, body, *, real_auth=False, headers=None):
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(chat.router)
        app.dependency_overrides[get_db] = lambda: db
        if not real_auth:
            app.dependency_overrides[get_current_developer] = lambda: SimpleNamespace(id=dev_id, name=f"dev{dev_id}")
        r = TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/chat/conversations/{CONV}/approvals/decide", json=body, headers=headers or {})
        return r
    call.state = state
    return call


def test_an_agent_cannot_decide_even_with_a_valid_agent_token(room):
    # BASE: 404 (no route)
    import jwt
    from agentvault_registry.security import ALGORITHM, SECRET_KEY
    token = jwt.encode({"sub": AGENT, "type": "agent", "exp": int(NOW.timestamp()) + 10 ** 9},
                       SECRET_KEY, algorithm=ALGORITHM)
    db = _DB([_row("apr_a1")], members={OWNER: ("owner", False)})
    r = room(db, None, {"decision": "approve", "approval_ids": ["apr_a1"]}, real_auth=True,
             headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401, (r.status_code, r.text)
    assert db.updated == [] and db.rows["apr_a1"].status == "pending"


def test_the_decide_route_takes_a_developer_credential_and_the_request_route_an_agent_only():
    from agentvault_registry.routers import chat
    from agentvault_registry.security import get_current_agent, get_current_developer
    paths = {(tuple(sorted(r.methods)), r.path): r for r in chat.router.routes}
    decide = paths[(("POST",), "/api/v1/chat/conversations/{conversation_id}/approvals/decide")]
    ask = paths[(("POST",), "/api/v1/chat/conversations/{conversation_id}/approvals")]

    def calls(route):
        out, todo = set(), list(route.dependant.dependencies)
        while todo:
            d = todo.pop()
            out.add(d.call)
            todo.extend(d.dependencies)
        return out
    assert get_current_developer in calls(decide) and get_current_agent not in calls(decide)
    assert get_current_agent in calls(ask) and get_current_developer not in calls(ask)


@pytest.mark.parametrize("dev_id,member,want", [
    (OWNER, None, 200),                          # the org's owner (organizations.owner_id)
    (APPROVER, ("member", True), 200),           # a named approver
    (MEMBER, ("member", False), 403),            # a plain member
    (9, ("admin", False), 403),                  # an admin is not an approver
    (APPROVER, None, 403),                       # an approver whose membership ended (no active row)
])
def test_only_the_owner_or_a_named_approver_decides(room, dev_id, member, want):
    db = _DB([_row("apr_w1")], members={dev_id: member} if member else {})
    r = room(db, dev_id, {"decision": "approve", "approval_ids": ["apr_w1"]})
    assert r.status_code == want, (r.status_code, r.text)
    assert (db.updated == ["apr_w1"]) == (want == 200)


def test_approve_all_decides_only_the_pending_ones_and_posts_one_card_each(room):
    # BASE: 404 (no route)
    rows = [_row("apr_1"), _row("apr_2"), _row("apr_3", status="denied"), _row("apr_4", minutes=-5)]
    db = _DB(rows, members={OWNER: ("owner", False)})
    r = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_1", "apr_2", "apr_3", "apr_4", "apr_x"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert sorted(d["id"] for d in body["decided"]) == ["apr_1", "apr_2"]
    assert body["skipped"] == {"apr_3": "already_denied", "apr_4": "expired", "apr_x": "not_found"}
    assert sorted(db.updated) == ["apr_1", "apr_2"] and rows[3].status == "pending"
    cards = room.state["cards"]
    assert [c[0]["type"] for c in cards] == ["approval.decided", "approval.decided"]
    assert {c[1] for c in cards} == {"aprdec-apr_1", "aprdec-apr_2"} and all(c[3] for c in cards)
    assert {c[2] for c in cards} == {"msg-apr_1", "msg-apr_2"}            # a reply to each request
    assert room.state["audit"] and room.state["audit"][0]["action"] == "approval.approved"


def test_an_expired_request_cannot_be_approved(room):
    # BASE: 404 (no route)
    db = _DB([_row("apr_late", minutes=-1)], members={OWNER: ("owner", False)})
    r = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_late"]})
    assert r.status_code == 410, r.text
    assert db.updated == [] and room.state["cards"] == []


def test_a_decision_is_idempotent_and_final(room):
    db = _DB([_row("apr_d", status="approved")], members={OWNER: ("owner", False)})
    again = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_d"]})
    assert again.status_code == 200 and again.json()["already"] is True, again.text
    other = room(db, OWNER, {"decision": "deny", "approval_ids": ["apr_d"]})
    assert other.status_code == 409, other.text
    assert db.updated == []


def test_the_decision_records_who_how_and_the_artifact(room):
    db = _DB([_row("apr_r", sha="f" * 64)], members={OWNER: ("owner", False)})
    r = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_r"], "surface": "console", "note": "go"})
    assert r.status_code == 200, r.text
    row = db.rows["apr_r"]
    assert row.status == "approved" and row.decided_by_developer_id == OWNER and row.decided_by_role == "owner"
    assert row.decision_via["credential"] == "session" and row.decision_via["mcp_relay"] is False
    assert row.decision_statement["artifact_sha256"] == "f" * 64
    assert row.decision_statement["request_digest"] == row.facts_digest and row.presence_method is None
    dec = r.json()["decided"][0]["decision"]
    assert dec["presence_method"] is None and "proves the account" in dec["what_it_proves"]


def test_presence_on_asks_for_a_device_and_refuses_an_authenticator_code(room):
    from agentvault_registry.services import chat_approvals as ca
    room.state["org_settings"] = {"chat_approvals": {"presence": "all"}}
    room.state["device"] = True
    db = _DB([_row("apr_pr")], members={OWNER: ("owner", False)})
    first = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_pr"]})
    assert first.status_code == 428, first.text
    step = first.json()["step_up"]
    assert step["methods"] == ["device"] and db.updated == []
    minted = [o for o in db.added if getattr(o, "action_type", None) == ca.ACTION_TYPE]
    assert minted and minted[0].action_ref == ca.action_ref_for("approve", ["apr_pr"], CONV)
    # The phone answered with TOTP: refused, NOT spent, a fresh challenge minted.
    db.challenge = SimpleNamespace(id=step["challenge_id"], developer_id=OWNER, action_type=ca.ACTION_TYPE,
                                   action_ref=minted[0].action_ref, status="approved", method="totp",
                                   # the step-up rail reads the wall clock for its own 120-second expiry
                                   expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=2),
                                   challenge_hash="h" * 64,
                                   nonce="n" * 32, device_id=None, signature=None, facts={})
    again = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_pr"], "challenge_id": step["challenge_id"]})
    assert again.status_code == 428 and "authenticator" not in again.json()["step_up"]["methods"], again.text
    assert "totp" in again.json()["reason"] and db.spent == [] and db.updated == []
    # Answered on the enrolled device with user verification: spent once, decided, the method recorded.
    db.challenge.method = "webauthn_uv"
    ok = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_pr"], "challenge_id": step["challenge_id"]})
    assert ok.status_code == 200, ok.text
    assert db.spent == [step["challenge_id"]] and db.rows["apr_pr"].presence_method == "webauthn_uv"


def test_presence_on_without_an_enrolled_device_is_refused_by_name_and_deny_still_works(room):
    room.state["org_settings"] = {"chat_approvals": {"presence": "all"}}
    room.state["device"] = False
    db = _DB([_row("apr_nd"), _row("apr_nd2")], members={OWNER: ("owner", False)})
    r = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_nd"]})
    assert r.status_code == 403 and "device_required" in r.text, r.text
    deny = room(db, OWNER, {"decision": "deny", "approval_ids": ["apr_nd2"]})
    assert deny.status_code == 200 and db.rows["apr_nd2"].status == "denied", deny.text


def test_presence_is_not_asked_by_default(room):
    db = _DB([_row("apr_def", production=True)], members={OWNER: ("owner", False)})
    r = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_def"]})
    assert r.status_code == 200 and db.rows["apr_def"].presence_method is None, r.text


def test_approvals_live_only_in_an_org_room(room):
    room.state["kind"] = "dm"
    db = _DB([_row("apr_dm")], members={OWNER: ("owner", False)})
    r = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_dm"]})
    assert r.status_code == 409 and "organization's room" in r.text, r.text


def test_the_switch_turns_the_rail_off(room, monkeypatch):
    monkeypatch.setenv("CHAT_APPROVALS_ENABLED", "false")
    db = _DB([_row("apr_off")], members={OWNER: ("owner", False)})
    r = room(db, OWNER, {"decision": "approve", "approval_ids": ["apr_off"]})
    assert r.status_code == 501, r.text


# ---------------------------------------------------------------------------
# The request route (the asking agent)
# ---------------------------------------------------------------------------

@pytest.fixture()
def ask(monkeypatch):
    from agentvault_registry.database import get_db
    from agentvault_registry.errors import register_error_handlers
    from agentvault_registry.routers import chat
    from agentvault_registry.security import get_current_agent
    from agentvault_registry.services import admin_audit
    from agentvault_registry.services import chat_approvals as ca
    from agentvault_registry.services import chat_service as cs

    state = {"kind": "org", "can_post": True, "saved": None, "sent": [], "pending": 0}

    async def _conv(db, cid):
        return SimpleNamespace(id=cid, kind=state["kind"], org_id=ORG, host_registry=None, mode="open")

    async def _membership(db, conv, actor, **kw):
        return SimpleNamespace(state="active", can_post=state["can_post"])

    async def _org(db, org_id):
        return {"owner_id": OWNER, "chat_enabled": True, "settings": {}}

    async def _by_ref(db, did, ref):
        return state["saved"]

    async def _pending(db, cid, did):
        return state["pending"]

    async def _now(db):
        return NOW

    async def _named(db, actor):
        return actor

    async def _audit(db, **kw):
        state.setdefault("audit", []).append(kw)

    class _Session:
        def add(self, obj):
            state["saved"] = obj

        async def flush(self):
            pass

    async def _send(db, conv, my_row, actor, kind, body, card, client_ref, reply_to=None, **kw):
        state["sent"].append((card, client_ref, kw.get("rail_author")))
        msg = SimpleNamespace(id="msg-1")
        await kw["extra_before_commit"](msg)
        return {"id": "msg-1", "card": card}

    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _membership)
    monkeypatch.setattr(ca, "org_facts", _org)
    monkeypatch.setattr(ca, "by_client_ref", _by_ref)
    monkeypatch.setattr(ca, "pending_count", _pending)
    monkeypatch.setattr(ca, "db_now", _now)
    monkeypatch.setattr(chat, "_named_sender", _named)
    monkeypatch.setattr(chat, "_send_and_fan_out", _send)
    monkeypatch.setattr(admin_audit, "log_chat_action", _audit)

    def call(body):
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(chat.router)
        app.dependency_overrides[get_db] = lambda: _Session()
        app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=AGENT, name="session-release")
        return TestClient(app, raise_server_exceptions=False).post(
            f"/api/v1/chat/conversations/{CONV}/approvals", json=body)
    call.state = state
    return call


def test_an_agent_asks_and_the_record_and_its_card_commit_together(ask):
    # BASE: 404 (no route)
    body = {"client_ref": "ref-000001", "title": "Roll V0649 to production", "unlocks": "prod_chain_v0649.sh",
            "artifact_sha256": "sha256:" + "9" * 64, "production_impact": True, "expires_in_seconds": 1800}
    r = ask(body)
    assert r.status_code == 201, r.text
    saved = ask.state["saved"]
    assert saved is not None and saved.request_message_id == "msg-1" and saved.status == "pending"
    assert saved.artifact_sha256 == "9" * 64 and saved.expires_at == NOW + dt.timedelta(seconds=1800)
    card, msg_ref, rail = ask.state["sent"][0]
    assert card["type"] == "approval.request" and rail is True and msg_ref.startswith("aprq-")
    assert card["data"]["approval_id"] == saved.id and r.json()["approval"]["status"] == "pending"
    assert ask.state["audit"][0]["action"] == "approval.requested"


def test_a_repeat_client_ref_returns_the_original_and_asks_nothing(ask):
    ask.state["saved"] = _row("apr_orig")
    r = ask({"client_ref": "ref-apr_orig", "title": "Again"})
    assert r.status_code == 201 and r.json()["duplicate"] is True and r.json()["approval"]["id"] == "apr_orig"
    assert ask.state["sent"] == []


def test_a_muted_agent_cannot_ask(ask):
    ask.state["can_post"] = False
    r = ask({"client_ref": "ref-000002", "title": "Let me"})
    assert r.status_code == 403 and "muted" in r.text and ask.state["sent"] == [], r.text


def test_an_agent_asks_only_in_an_org_room_and_within_its_pending_cap(ask):
    ask.state["kind"] = "dm"
    assert ask({"client_ref": "ref-000003", "title": "x"}).status_code == 409
    ask.state["kind"] = "org"
    ask.state["pending"] = 10 ** 6
    r = ask({"client_ref": "ref-000004", "title": "x"})
    assert r.status_code == 429 and ask.state["sent"] == [], r.text


def test_a_malformed_artifact_hash_is_refused(ask):
    r = ask({"client_ref": "ref-000005", "title": "x", "artifact_sha256": "abc"})
    assert r.status_code == 422 and ask.state["sent"] == [], r.text


# ---------------------------------------------------------------------------
# The MCP tools
# ---------------------------------------------------------------------------

def _mcp_resp(status, body):
    import httpx
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://x"))


def test_the_three_tools_are_wired_in_every_place_and_listed_once():
    from agentvault_registry.mcp import audit, server, server_admin, tool_categories as tc
    names = [t["name"] for t in server.ALL_TOOL_SCHEMAS]
    agent_side = {"theprotocol_requestChatApproval", "theprotocol_getChatApprovalStatus"}
    for n in agent_side | {"theprotocol_decideChatApproval"}:
        assert names.count(n) == 1 and n in server.TOOL_DISPATCH and n in server.AUTH_REQUIRED_TOOLS, n
        assert n not in server_admin.ADMIN_TOOL_DISPATCH and tc.get_category(n) == "account"
    assert agent_side <= server.TIER2_TOOLS and agent_side <= audit._TIER_2_TOOLS
    assert "theprotocol_decideChatApproval" in server.TIER3_TOOLS and "theprotocol_decideChatApproval" in audit._TIER_3_TOOLS
    by = {t["name"]: t for t in server.ALL_TOOL_SCHEMAS}
    assert by["theprotocol_decideChatApproval"]["annotations"]["destructiveHint"] is True
    assert by["theprotocol_getChatApprovalStatus"]["annotations"]["readOnlyHint"] is True


def test_an_agent_context_cannot_decide_through_mcp(monkeypatch):
    import asyncio
    from agentvault_registry.mcp import tools_chat_approvals as T
    from agentvault_registry.mcp.auth_bridge import MCPAuthContext, MCPAuthError
    called = []

    async def _call(*a, **kw):
        called.append(a)
        return _mcp_resp(200, {}), None
    monkeypatch.setattr(T, "_call", _call)
    agent = MCPAuthContext(auth_type="agent", agent_did=AGENT, agent_id=3, raw_token="agent-jwt")
    with pytest.raises(MCPAuthError):
        asyncio.run(T.decide_chat_approval(agent, CONV, "approve", ["apr_1"]))
    assert called == []


def test_decide_without_ids_decides_the_pending_set_it_read_and_passes_a_step_up_through(monkeypatch):
    import asyncio
    from agentvault_registry.mcp import tools_chat_approvals as T
    from agentvault_registry.mcp.auth_bridge import MCPAuthContext
    calls = []

    async def _call(method, path, *, token, params=None, body=None, timeout=None):
        calls.append((method, path, params, body))
        if method == "GET":
            return _mcp_resp(200, {"items": [{"id": "apr_a", "status": "pending"},
                                             {"id": "apr_b", "status": "pending"}]}), None
        return _mcp_resp(428, {"error": "step_up_required", "message": "Confirm", "step_up": {"challenge_id": "lch_1"}}), None
    monkeypatch.setattr(T, "_call", _call)
    dev = MCPAuthContext(auth_type="developer", developer_id=OWNER, raw_token="dev-key")
    out = asyncio.run(T.decide_chat_approval(dev, CONV, "approve"))
    assert out["status"] == "step_up_required" and "error" not in out and out["step_up"]["challenge_id"] == "lch_1"
    assert calls[1][3]["approval_ids"] == ["apr_a", "apr_b"] and calls[1][3]["surface"] == "mcp"


def test_the_status_tool_waits_at_most_twenty_seconds(monkeypatch):
    import asyncio
    from agentvault_registry.mcp import tools_chat_approvals as T
    from agentvault_registry.mcp.auth_bridge import MCPAuthContext
    seen = []

    async def _call(method, path, *, token, params=None, body=None, timeout=None):
        seen.append((params, timeout))
        return _mcp_resp(200, {"id": "apr_w", "status": "approved"}), None
    monkeypatch.setattr(T, "_call", _call)
    agent = MCPAuthContext(auth_type="agent", agent_did=AGENT, agent_id=3, raw_token="agent-jwt")
    out = asyncio.run(T.get_chat_approval_status(agent, "apr_w", wait_seconds=300))
    assert out["status"] == "approved" and seen == [({"wait": 20}, 30.0)]
