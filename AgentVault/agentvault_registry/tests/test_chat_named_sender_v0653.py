"""V0653's recut (the pair proof of 2026-11-02 09:02Z, session-tester's read in the sessions' room seq 962; session-lead seq
966): an agent with a card keeps how its line was sent and who sent it.

routers/chat._named_sender puts an agent's card name on its messages (the agents table has no name; an agent token's actor
carries its DID as its name). It rebuilt the Actor from the DID and the card's name alone, so it dropped V0653 (w)'s
sent_with (on the pair, the agent's line stored NULL while the session's and the key's lines were right) and V0652 (aj)'s
sent_by: "sent by its owner" was never stored for an agent with a card, production included. The tests that shipped both
fields went around it ((w)'s route test replaces _send_and_fan_out; (aj)'s agent had a name of its own).

The send path from the authenticated actor to the insert, with only the rate gate, the card-name read and the insert
replaced; the stored row on a real Postgres (MEMBERSHIP_TEST_DB, a throwaway one it may WIPE). BASE (the cut, 1d92f4882):
sent_with None and sent_by None on the resolved sender.
"""
from __future__ import annotations

import asyncio
import os
import types

import pytest

from agentvault_registry.routers import chat
from agentvault_registry.services import chat_service as cs

DID = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-0000000000c4"
NAMELESS = types.SimpleNamespace()          # an Agent row: no name of its own (names live on agent_cards)


def run(coro):
    return asyncio.run(coro)


def _card_named(monkeypatch, name="session-tester"):
    async def _names(db, keys):
        return {k: name for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)


def test_an_agent_token_s_actor_carries_its_did_as_its_name():
    # the condition _named_sender acts on (control: as on the cut)
    a = cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": NAMELESS, "credential": "agent"})
    assert (a.display_name, a.sent_with) == (DID, "agent")


def test_the_card_name_keeps_how_the_line_was_sent(monkeypatch):
    # BASE: sent_with None
    _card_named(monkeypatch)
    a = cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": NAMELESS, "credential": "agent"})
    s = run(chat._named_sender(None, a))
    assert (s.ptype, s.agent_did, s.display_name, s.sent_with, s.sent_by) == ("agent", DID, "session-tester", "agent", None)


def test_the_card_name_keeps_the_owner_who_sent_it(monkeypatch):
    # BASE: sent_by None (the owner's post through their session lost "sent by its owner")
    _card_named(monkeypatch)
    a = cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": NAMELESS, "owner_session": 6, "credential": "agent"})
    s = run(chat._named_sender(None, a))
    assert (s.display_name, s.sent_by, s.sent_with) == ("session-tester", 6, "agent")


def test_the_send_path_hands_the_insert_that_sender(monkeypatch):
    # BASE: the insert received sent_with None, sent_by None
    _card_named(monkeypatch)
    seen = []

    class _Stop(Exception):
        pass

    async def _gate(*a, **k):
        return True

    async def _insert(db, conv, my_row, sender, kind, body, card, client_ref, reply_to=None, **kw):
        seen.append(sender)
        raise _Stop()

    from agentvault_registry.services import chat_federation as fed
    monkeypatch.setattr(cs, "_rate_gate", _gate)
    monkeypatch.setattr(cs, "insert_message", _insert)
    monkeypatch.setattr(fed, "federation_enabled", lambda: False)
    a = cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": NAMELESS, "owner_session": 6, "credential": "agent"})
    conv = types.SimpleNamespace(id="c1", kind="dm", host_registry=None)
    with pytest.raises(_Stop):
        run(chat._send_and_fan_out(None, conv, None, a, "text", "the ticket test is done", None, "ref-00000001"))
    assert [(s.display_name, s.sent_with, s.sent_by) for s in seen] == [("session-tester", "agent", 6)]


def test_a_named_agent_or_a_developer_passes_through_unchanged(monkeypatch):
    # control: nothing to resolve, the same object
    _card_named(monkeypatch)
    named = cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": types.SimpleNamespace(name="mine"),
                                "credential": "agent"})
    assert run(chat._named_sender(None, named)) is named
    dev = cs.actor_from_auth({"kind": "developer", "developer": types.SimpleNamespace(id=6, name="maintainer", email="x@e.t"),
                              "credential": "session"})
    assert run(chat._named_sender(None, dev)) is dev


# ── the stored row, on a real Postgres ───────────────────────────────────────────────────────────────────────────────

DB = os.environ.get("MEMBERSHIP_TEST_DB")


@pytest.mark.skipif(not DB, reason="needs a REAL Postgres it may wipe: set MEMBERSHIP_TEST_DB. Skipped, never silently passed.")
def test_the_stored_line_says_agent_and_sent_by_its_owner():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from agentvault_registry.models import AgentCard, Base, Conversation, ConversationParticipant, Developer

    async def go():
        engine = create_async_engine(DB)
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            owner = Developer(name="maintainer", email="owner@test.local", hashed_password="x", is_verified=True)
            other = Developer(name="reader", email="reader@test.local", hashed_password="x", is_verified=True)
            s.add_all([owner, other])
            await s.flush()
            s.add(AgentCard(developer_id=owner.id, agent_did=DID, name="session-tester", description="t",
                            card_data={"name": "session-tester"}, is_active=True))
            conv = Conversation(kind="dm", created_by_ptype="developer", created_by_id=str(other.id), last_seq=0)
            s.add(conv)
            await s.flush()
            me = ConversationParticipant(conversation_id=conv.id, ptype="agent", agent_did=DID)
            s.add_all([me, ConversationParticipant(conversation_id=conv.id, ptype="developer", developer_id=other.id)])
            await s.commit()
            out = []
            for ref, owner_session in (("ref-agent-00001", None), ("ref-owner-00001", owner.id)):
                a = cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": NAMELESS, "credential": "agent",
                                        **({"owner_session": owner_session} if owner_session else {})})
                sender = await chat._named_sender(s, a)
                msg, _dup = await cs.insert_message(s, conv, me, sender, "text", f"line {ref}", None, ref)
                out.append(cs.serialize_message(msg))
        await engine.dispose()
        return out

    by_agent, by_owner = run(go())
    assert (by_agent["sent_with"], by_agent["sent_by_owner"]) == ("agent", False)
    assert (by_owner["sent_with"], by_owner["sent_by_owner"]) == ("agent", True)
