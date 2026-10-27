"""§TWOAGENT G1 step 2 (2026-09-23) — AGENTS in cross-registry chat, with consent on the wire and a loop guard.

Step 1 (V0432) completed the first cross-registry round trip for developers. Agents were still refused at every layer:
a dm to a MIRRORED agent answered FOREIGN_AGENT_DM_REFUSAL, `_create_federated` was developer-only, a resident was a
developer by handle, the deliver fan-out named developers only, and the relay refused an agent sender.

Now, where CHAT_FEDERATION_ENABLED is on:
  * an agent's dm to a mirrored agent goes to its home (`home_key_for_mirror`: `did@https://its.home`);
  * the host seats the target agent PENDING; its home seats it pending too (its Requests lane) and tells its owner of
    the knock (`chat.request.received`); an accept there travels to the host (`POST /federation/chat/state`, only
    from the participant's own home), which tells the knocker's owner (`chat.request.accepted`); a decline stays local;
  * a resident agent's reply is relayed like a developer's; its echo comes home as ITS OWN message and wakes nobody;
  * caps per thread and per peer on relay, deliver and create, and a tighter one for an agent sender (the loop guard).
The household seat (item 7) is unchanged: his decision.

RED on V0433's base (twoagent/a-next a5b52905): every test but the controls.
"""
from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import HTTPException

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"
A_DID = "did:theprotocol:sandbox-a.test:knocker"
B_DID = "did:theprotocol:sandbox-b.test:assay"


class _R:
    def __init__(self, rows):
        self.rows = list(rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)

    def scalar(self):
        r = self.first()
        return r[0] if isinstance(r, (tuple, list)) else r

    def scalars(self):
        return self

    def scalar_one(self):
        return self.rows[0][0]


class _Db:
    def __init__(self, handlers=()):
        self.handlers = list(handlers)
        self.added = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        for needle, rows in self.handlers:
            if needle in sql:
                return _R(rows(params) if callable(rows) else rows)
        return _R([])

    def add(self, obj):
        self.added.append(obj)

    def add_all(self, objs):
        self.added.extend(objs)

    async def flush(self):
        for o in self.added:
            if getattr(o, "id", None) is None and type(o).__name__ == "Conversation":
                o.id = "host-conv-1"

    async def commit(self):
        return None

    async def rollback(self):
        return None


async def _drain():
    for _ in range(6):
        await asyncio.sleep(0)


@pytest.fixture
def fed_on(monkeypatch):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import contract_xframe

    async def _resolve(db, value):
        v = str(value or "")
        return "sandbox-a" if "sandbox-a" in v else ("sandbox-b" if "sandbox-b" in v or v.upper() == "EU-B" else None)
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    return fed


# ─────────────────────────────── addressing ───────────────────────────────

async def test_a_mirrored_agent_is_addressed_at_its_home(fed_on):
    db = _Db([("SELECT 1 FROM agents WHERE did", []),
              ("FROM agent_cards WHERE agent_did", [({"federation_metadata": {"origin_registry_name": "sandbox-b"}},)]),
              ("SELECT base_url FROM peer_registries", [(f"{HOME}:8443",)])])
    assert await fed_on.home_key_for_mirror(db, B_DID) == f"{B_DID}@{HOME}"


async def test_control_a_native_agent_is_not_a_federated_target(fed_on):
    assert await fed_on.home_key_for_mirror(_Db([("SELECT 1 FROM agents WHERE did", [(1,)])]), B_DID) is None


async def test_an_agent_dm_to_a_mirror_goes_to_its_home(fed_on, monkeypatch):
    from agentvault_registry.routers import chat as chat_router
    seen: list = []

    async def _home(db, did):
        return f"{did}@{HOME}"

    async def _fed_create(db, actor, req):
        seen.append(req.target.remote_key)
        return {"federated": True}
    monkeypatch.setattr(fed_on, "home_key_for_mirror", _home, raising=False)
    monkeypatch.setattr(chat_router, "_create_federated", _fed_create)
    req = chat_router.ConversationCreate(kind="dm", target=chat_router.TargetSpec(ptype="agent", agent_did=B_DID))
    out = await chat_router.create_conversation(
        req=req, actor_dict={"kind": "agent", "agent_did": A_DID, "agent": types.SimpleNamespace(name="K")}, db=None)
    assert out == {"federated": True} and seen == [f"{B_DID}@{HOME}"]


# ─────────────────────────────── the host ───────────────────────────────

async def test_an_agent_opens_a_cross_registry_thread_and_the_target_is_a_knock(fed_on, monkeypatch):
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_service as cs

    async def _allowed(db, base):
        return "sandbox-b"

    async def _ok(*a, **k):
        return True
    monkeypatch.setenv("PUBLIC_BASE_URL", HOST)
    monkeypatch.setattr(fed_on, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(fed_on, "fed_rate_ok", _ok, raising=False)
    db = _Db()
    req = chat_router.ConversationCreate(kind="dm", target=chat_router.TargetSpec(
        ptype="agent", agent_did=B_DID, remote_key=f"{B_DID}@{HOME}"))
    out = await chat_router._create_federated(db, cs.Actor("agent", agent_did=A_DID, display_name="K"), req)
    rows = [o for o in db.added if type(o).__name__ == "ConversationParticipant"]
    mine = next(r for r in rows if r.ptype == "agent")
    theirs = next(r for r in rows if r.ptype == "remote")
    assert out["federated"] is True and mine.agent_did == A_DID and mine.state == "active"
    assert theirs.remote_key == f"{B_DID}@{HOME}" and theirs.state == "pending"


def _state_db(part_state="pending", host_registry=None):
    conv = types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=host_registry, created_by_ptype="agent",
                                 created_by_id=A_DID)
    part = types.SimpleNamespace(ptype="remote", remote_key=f"{B_DID}@{HOME}", state=part_state,
                                 agent_did=None, developer_id=None)

    class _Db2(_Db):
        async def execute(self, stmt, params=None):
            sql = " ".join(str(stmt).split())
            if "FROM conversations" in sql:
                return _R([conv])
            if "FROM conversation_participants" in sql:
                return _R([part])
            return _R([])
    return _Db2(), part


async def test_the_host_applies_an_accept_from_the_participants_home_and_tells_the_knocker(fed_on, monkeypatch):
    from agentvault_registry.services import chat_service as cs
    told: list = []

    async def _notify(notice, name):
        told.append((notice["knocker_id"], notice["accepted_by"]))
        return 1
    monkeypatch.setattr(cs, "notify_request_accepted", _notify)
    db, part = _state_db()
    out = await fed_on.apply_remote_state(db, "host-conv-1", f"{B_DID}@{HOME}", "active",
                                          "spiffe://sandbox-b.test/service/registry")
    await _drain()
    assert out == {"state": "active", "changed": True} and part.state == "active"
    assert told == [(A_DID, f"{B_DID}@{HOME}")]


async def test_only_the_participants_own_home_may_change_its_state(fed_on):
    from agentvault_registry.services import chat_service as cs
    db, part = _state_db()
    with pytest.raises(cs.ChatError) as e:
        await fed_on.apply_remote_state(db, "host-conv-1", f"{B_DID}@{HOME}", "active",
                                        "spiffe://sandbox-a.test/service/registry")
    assert e.value.status_code == 403 and part.state == "pending"


async def test_a_decline_never_travels(fed_on):
    from agentvault_registry.services import chat_service as cs
    db, _ = _state_db()
    with pytest.raises(cs.ChatError) as e:
        await fed_on.apply_remote_state(db, "host-conv-1", f"{B_DID}@{HOME}", "declined",
                                        "spiffe://sandbox-b.test/service/registry")
    assert e.value.status_code == 422


# ─────────────────────────────── the resident ───────────────────────────────

class _ReceiveDb(_Db):
    def __init__(self, agent_status="active"):
        super().__init__()
        self.agent_status = agent_status

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if "SELECT did, status FROM agents" in sql:
            return _R([(B_DID, self.agent_status)])
        if "SELECT did FROM agents" in sql:
            return _R([(B_DID,)])
        if "UPDATE conversations SET last_seq" in sql:
            return _R([(1,)])
        return _R([])


def _envelope(sender_id=A_DID, registry=HOST, client_ref="ref-12345678"):
    return {"v": 1, "host_registry": HOST,
            "conversation": {"id": "host-conv-1", "kind": "dm",
                             "participants": [{"key": f"{A_DID}@{HOST}"}, {"key": f"{B_DID}@{HOME}"}]},
            "message": {"seq": 1, "kind": "text", "body": "may I?", "client_ref": client_ref,
                        "sender": {"id": sender_id, "registry": registry, "display_name": "K"}}}


@pytest.fixture
def resident(fed_on, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)

    async def _allowed(db, base):
        return "sandbox-a"

    async def _ok(*a, **k):
        return True
    monkeypatch.setattr(fed_on, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(fed_on, "fed_rate_ok", _ok, raising=False)
    return fed_on


async def test_a_cross_registry_first_contact_lands_the_agent_in_its_requests_lane(resident):
    db = _ReceiveDb()
    out = await resident.receive_delivery(db, _envelope(), "spiffe://sandbox-a.test/service/registry")
    seats = [o for o in db.added if type(o).__name__ == "ConversationParticipant" and o.ptype == "agent"]
    assert out["pending_agents"] == [B_DID] and [s.state for s in seats] == ["pending"]
    convs = [o for o in db.added if type(o).__name__ == "Conversation"]
    assert convs[0].created_by_ptype == "remote" and convs[0].created_by_id == f"{A_DID}@{HOST}"


async def test_a_suspended_agent_is_no_resident(resident):
    from agentvault_registry.services import chat_service as cs
    with pytest.raises(cs.ChatError) as e:
        await resident.receive_delivery(_ReceiveDb("suspended"), _envelope(), "spiffe://sandbox-a.test/service/registry")
    assert e.value.status_code == 404


async def test_an_agents_own_relayed_reply_comes_home_as_its_own(resident, monkeypatch):
    from agentvault_registry.background_tasks import leader

    class _Redis:
        def __init__(self):
            self.kv = {}

        async def set(self, key, value, ex=None, nx=False):
            self.kv[key] = value
            return True

        async def get(self, key):
            return self.kv.get(key)
    redis = _Redis()

    async def _get_redis():
        return redis
    monkeypatch.setattr(leader, "get_redis", _get_redis)
    await resident._record_relay(HOST, "host-conv-1", "ref-reply-001", f"{B_DID}@{HOME}")
    db = _ReceiveDb()
    out = await resident.receive_delivery(db, _envelope(sender_id=B_DID, registry=HOME, client_ref="ref-reply-001"),
                                          "spiffe://sandbox-a.test/service/registry")
    assert (out["sender_ptype"], out["sender_local"]) == ("agent", B_DID)


async def test_the_deliver_fan_out_never_wakes_the_sender_and_announces_a_knock(fed_on, monkeypatch):
    from agentvault_registry.routers import chat_federation as route
    from agentvault_registry.services import chat_service as cs
    seen: dict = {"notified": []}

    async def _receive(db, envelope, peer):
        return {"conversation_id": "mirror-1", "duplicate": False, "residents": [], "resident_agents": [B_DID],
                "pending_agents": [B_DID], "sender_ptype": "agent", "sender_local": B_DID, "sender_display": "B",
                "message_id": "m1", "seq": 2}

    async def _conv(db, cid):
        return types.SimpleNamespace(id=cid)

    async def _snapshot(db, conv, sender):
        seen["sender_key"] = sender.key
        return []

    async def _fan(*a, **k):
        return None

    async def _knock(conv_id, kind, did, message, sender_name):
        seen["notified"].append(did)
        return 1
    monkeypatch.setattr(fed_on, "receive_delivery", _receive)
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "recipients_snapshot", _snapshot)
    monkeypatch.setattr(cs, "fan_out_message", _fan)
    monkeypatch.setattr(cs, "notify_request_received", _knock)
    await route.deliver({"message": {"kind": "text", "body": "x"}}, peer="spiffe://sandbox-a.test/service/registry",
                        db=None)
    await _drain()
    assert seen["sender_key"] == f"agt:{B_DID.lower()}" and seen["notified"] == [B_DID]


# ─────────────────────────────── the loop guard ───────────────────────────────

async def test_an_agent_senders_relay_is_capped_tighter(fed_on, monkeypatch):
    from agentvault_registry.routers import chat_federation as route

    async def _allowed(db, base):
        return "sandbox-b"

    async def _cap(kind, *parts):
        return kind != "relay_agent_thread"
    monkeypatch.setattr(fed_on, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(fed_on, "fed_rate_ok", _cap, raising=False)
    req = route.RelaySend(conversation_ref="host-conv-1", sender_key=f"{B_DID}@{HOME}", client_ref="ref-12345678",
                          body="again")
    with pytest.raises(HTTPException) as e:
        await route.relay_send(req, peer="spiffe://sandbox-b.test/service/registry", db=None)
    assert e.value.status_code == 429 and "agent" in e.value.detail


async def test_a_mirror_accept_travels_to_the_host_and_a_decline_does_not(fed_on, monkeypatch):
    from agentvault_registry.services import chat_service as cs
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    sent: list = []

    async def _announce(host, remote_ref, key, state):
        sent.append((host, remote_ref, key, state))
        return True

    async def _names(db, keys):
        return {}
    monkeypatch.setattr(fed_on, "announce_state_to_host", _announce, raising=False)
    monkeypatch.setattr(cs, "display_names", _names)
    for action, expect in (("accept", [(HOST, "host-conv-1", f"{B_DID}@{HOME}", "active")]), ("decline", [])):
        sent.clear()
        conv = types.SimpleNamespace(id="mirror-1", kind="dm", host_registry=HOST, remote_ref="host-conv-1",
                                     created_by_ptype="remote", created_by_id=f"{A_DID}@{HOST}")
        row = types.SimpleNamespace(ptype="agent", agent_did=B_DID, developer_id=None, state="pending")

        async def _get(db, cid, _conv=conv):
            return _conv

        async def _member(db, c, actor, _row=row, **kw):
            return _row
        monkeypatch.setattr(cs, "_get_conversation", _get)
        monkeypatch.setattr(cs, "resolve_membership", _member)
        await cs.set_state(_Db(), "mirror-1", cs.Actor("agent", agent_did=B_DID, display_name=B_DID), action)
        await _drain()
        assert sent == expect, (action, sent)
