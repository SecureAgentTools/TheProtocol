"""§TWOAGENT G1 step 3 (2026-09-23) — a principal on a PEER registry can be blocked, and the block holds on both legs.

Step 2 (V0433) seated agents in cross-registry chat; nothing could keep one out. `_split_key` read a `rem:` key as an
AGENT (so a remote principal could not even be named in a block), the block schema took developers and agents only,
the leave-on-block UPDATE never matched a remote participant row, and the host fanned out a relayed message as a
stand-in developer -1, so no block against the real sender could apply. Now:
  * `rem:` keys split as `remote`; `POST/DELETE /chat/blocks` take `ptype: remote` with a `remote_key`;
  * a block leaves shared threads with that remote participant, like a local block;
  * the host's relay fan-out names the REAL remote sender, so a blocking participant is skipped;
  * a knock from a blocked sender seats the agent `left` and tells its owner nothing;
  * opening a cross-registry thread with an address you block is refused, as locally.

RED on V0433 (6d4b0625): every test but the control.
"""
from __future__ import annotations

import types

import pytest

HOST = "https://sandbox-a.test"
HOME = "https://sandbox-b.test"
A_DID = "did:theprotocol:sandbox-a.test:knocker"
B_DID = "did:theprotocol:sandbox-b.test:assay"


def test_a_remote_key_splits_as_remote_and_round_trips():
    from agentvault_registry.services import chat_service as cs
    key = cs.principal_key("remote", f"{A_DID}@{HOST}")
    assert cs._split_key(key) == ("remote", f"{A_DID}@{HOST}")


def test_control_local_keys_split_as_before():
    from agentvault_registry.services import chat_service as cs
    assert cs._split_key("dev:7") == ("developer", "7") and cs._split_key(f"agt:{B_DID}") == ("agent", B_DID)


async def test_a_remote_principal_can_be_blocked_by_its_canonical_address(monkeypatch):
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_service as cs
    seen: list = []

    async def _block(db, actor, key):
        seen.append(key)
    monkeypatch.setattr(cs, "create_block", _block)
    req = chat_router.BlockBody(ptype="remote", remote_key=f"{A_DID}@{HOST}/")
    out = await chat_router.create_block(req=req, actor_dict={"kind": "agent", "agent_did": B_DID,
                                                               "agent": types.SimpleNamespace(name="B")}, db=None)
    assert out == {"blocked": True} and seen == [f"rem:{A_DID}@{HOST}"]


async def test_opening_a_thread_with_an_address_you_block_is_refused(monkeypatch):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOST)
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs

    async def _allowed(db, base):
        return "sandbox-b"

    async def _blocks(db, a, b):
        return {"a_blocks_b": True, "b_blocks_a": False}
    monkeypatch.setattr(fed, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(cs, "blocks_between", _blocks)
    req = chat_router.ConversationCreate(kind="dm", target=chat_router.TargetSpec(
        ptype="agent", agent_did=B_DID, remote_key=f"{B_DID}@{HOME}"))
    with pytest.raises(cs.ChatError) as e:
        await chat_router._create_federated(None, cs.Actor("agent", agent_did=A_DID, display_name="K"), req)
    assert e.value.status_code == 403 and "blocked" in e.value.detail


async def test_the_hosts_relay_fan_out_names_the_real_remote_sender(monkeypatch):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    from agentvault_registry.routers import chat_federation as route
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    seen: dict = {}
    conv = types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=None)
    part = types.SimpleNamespace(ptype="remote", remote_key=f"{B_DID}@{HOME}", state="active")

    class _R:
        def __init__(self, v):
            self.v = v

        def scalars(self):
            return self

        def first(self):
            return self.v

    class _Db:
        def __init__(self):
            self.n = 0

        async def execute(self, stmt, params=None):
            self.n += 1
            return _R(conv if self.n == 1 else part)

        async def commit(self):
            return None

    async def _yes(*a, **k):
        return True

    async def _allowed(db, base):
        return "sandbox-b"

    async def _insert(*a, **k):
        return types.SimpleNamespace(seq=5), False

    async def _snapshot(db, c, sender):
        seen["key"] = sender.key
        return []

    async def _nothing(*a, **k):
        return 0
    monkeypatch.setattr(fed, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(fed, "caller_is", _yes)
    monkeypatch.setattr(fed, "fed_rate_ok", _yes)
    monkeypatch.setattr(fed, "enqueue_delivery", _nothing)
    monkeypatch.setattr(cs, "insert_remote_message", _insert)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"seq": m.seq})
    monkeypatch.setattr(cs, "recipients_snapshot", _snapshot)
    monkeypatch.setattr(cs, "fan_out_message", _nothing)
    req = route.RelaySend(conversation_ref="host-conv-1", sender_key=f"{B_DID}@{HOME}", client_ref="ref-12345678",
                          body="hi")
    await route.relay_send(req, peer="spiffe://sandbox-b.test/service/registry", db=_Db())
    assert seen["key"] == f"rem:{B_DID}@{HOME}"


async def test_a_knock_from_a_blocked_sender_seats_the_agent_left_and_tells_nobody(monkeypatch):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOME)
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    from agentvault_registry.services import contract_xframe

    class _R:
        def __init__(self, rows):
            self.rows = list(rows)

        def first(self):
            return self.rows[0] if self.rows else None

        def all(self):
            return list(self.rows)

        def scalars(self):
            return self

        def scalar_one(self):
            return self.rows[0][0]

    class _Db:
        def __init__(self):
            self.added = []

        async def execute(self, stmt, params=None):
            sql = " ".join(str(stmt).split())
            if "SELECT did, status FROM agents" in sql:
                return _R([(B_DID, "active")])
            if "UPDATE conversations SET last_seq" in sql:
                return _R([(1,)])
            return _R([])

        def add(self, o):
            self.added.append(o)

        async def flush(self):
            return None

        async def commit(self):
            return None

        async def rollback(self):
            return None

    async def _allowed(db, base):
        return "sandbox-a"

    async def _ok(*a, **k):
        return True

    async def _resolve(db, value):
        return "sandbox-a" if "sandbox-a" in str(value or "") else None

    async def _blocks(db, a, b):
        return {"a_blocks_b": True, "b_blocks_a": False}
    monkeypatch.setattr(fed, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(fed, "fed_rate_ok", _ok)
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    monkeypatch.setattr(cs, "blocks_between", _blocks)
    env = {"v": 1, "host_registry": HOST,
           "conversation": {"id": "host-conv-1", "kind": "dm",
                            "participants": [{"key": f"{A_DID}@{HOST}"}, {"key": f"{B_DID}@{HOME}"}]},
           "message": {"seq": 1, "kind": "text", "body": "may I?", "client_ref": "ref-12345678",
                       "sender": {"id": A_DID, "registry": HOST, "display_name": "K"}}}
    db = _Db()
    out = await fed.receive_delivery(db, env, "spiffe://sandbox-a.test/service/registry")
    seats = [o for o in db.added if type(o).__name__ == "ConversationParticipant" and o.ptype == "agent"]
    assert out["pending_agents"] == [] and [s.state for s in seats] == ["left"]


async def test_an_address_longer_than_a_block_row_holds_is_a_422_not_a_500(monkeypatch):
    """A participant row holds a 320-character remote address and chat_blocks.blocked_id 255: the longer one was a
    StringDataRightTruncation 500 at the INSERT. Control: an address of exactly the column's length blocks."""
    from fastapi import HTTPException
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_service as cs
    seen: list = []

    async def _block(db, actor, key):
        seen.append(key)
    monkeypatch.setattr(cs, "create_block", _block)
    limit = cs.ChatBlock.__table__.c.blocked_id.type.length
    actor = {"kind": "agent", "agent_did": B_DID, "agent": types.SimpleNamespace(name="B")}
    fits = "d" * (limit - len(HOST) - 1) + f"@{HOST}"
    too_long = "d" + fits
    with pytest.raises(HTTPException) as e:
        await chat_router.create_block(req=chat_router.BlockBody(ptype="remote", remote_key=too_long),
                                       actor_dict=actor, db=None)
    assert e.value.status_code == 422 and f"({limit} characters)" in e.value.detail and seen == []
    out = await chat_router.create_block(req=chat_router.BlockBody(ptype="remote", remote_key=fits),
                                         actor_dict=actor, db=None)
    assert out == {"blocked": True} and seen == [f"rem:{fits}"] and len(fits) == limit


async def test_reopening_a_pair_thread_you_left_makes_you_active_again(monkeypatch):
    """Local create_conversation flips a left/pending row to active ("creating a conversation to this pair IS engaging
    with it"). The federated create returned the pair thread with the row still left, so a resident who blocked a
    remote principal and later unblocked (or simply left) had a thread every message answered 409, for good."""
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_BASE_URL", HOST)
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    conv = types.SimpleNamespace(id="host-conv-1", kind="dm")
    my_row = types.SimpleNamespace(state="left")

    class _R:
        def scalars(self):
            return self

        def first(self):
            return conv

    class _Db:
        commits = 0

        async def execute(self, stmt, params=None):
            return _R()

        async def commit(self):
            self.commits += 1

    async def _allowed(db, base):
        return "sandbox-b"

    async def _blocks(db, a, b):
        return {"a_blocks_b": False, "b_blocks_a": False}

    async def _membership(db, c, actor, auto_join=True):
        return my_row
    monkeypatch.setattr(fed, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(cs, "blocks_between", _blocks)
    monkeypatch.setattr(cs, "resolve_membership", _membership)
    db = _Db()
    req = chat_router.ConversationCreate(kind="dm", target=chat_router.TargetSpec(
        ptype="agent", agent_did=B_DID, remote_key=f"{B_DID}@{HOME}"))
    out = await chat_router._create_federated(db, cs.Actor("agent", agent_did=A_DID, display_name="K"), req)
    assert out["created"] is False and out["my_state"] == "active" and my_row.state == "active" and db.commits == 1
