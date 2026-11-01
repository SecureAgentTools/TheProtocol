"""V0652 (aj) (order gwo_9fa441b938ff31f95662243f, agentvault2-14, 2026-10-31), item (4): a message an agent's owner sent
as the agent says so in the thread ("sent by its owner").

The registry knows it when, and only when, the agent token was minted from the owner's own session (an owner session
token, `via: "owner"`, accepted by owner_token_refusal: the owner is the agent's creator, in a live session). The console
signs in as an owned agent that way. A token from the agent's own credential says nothing about who typed, so the
message claims nothing. Mig 0203 holds the fact (`chat_messages.sent_by_developer_id`). Each case fails on 05441be31.
"""
from __future__ import annotations

import asyncio
import inspect
import types

from agentvault_registry import security
from agentvault_registry.services import chat_service as cs


def run(coro):
    return asyncio.run(coro)


DID = "did:theprotocol:eu.theprotocol.cloud:19c1aa48"


def test_an_owner_session_names_its_owner_on_the_actor():
    agent = types.SimpleNamespace(name="session-tester")
    a = cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": agent, "owner_session": 6})
    assert (a.ptype, a.agent_did, a.sent_by) == ("agent", DID, 6)
    # an agent's own credential: nobody is named
    assert cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": agent}).sent_by is None
    # a developer is never "sent by its owner"
    dev = types.SimpleNamespace(id=6, name="maintainer", email="x@example.org")
    assert cs.actor_from_auth({"kind": "developer", "developer": dev}).sent_by is None


def test_the_resolver_reads_the_owner_only_from_an_owner_token():
    src = inspect.getsource(security.get_current_actor_for_read)
    # read after agent_token_refusal accepted the token (the owner is the creator, in a live session)
    i, j = src.index("agent_token_refusal(db, payload, agent)"), src.index('if payload.get("via") == "owner":')
    assert i < j
    assert '"owner_session": owner_session' in src


def test_the_message_records_it_and_the_thread_says_so():
    src = inspect.getsource(cs)
    assert 'sent_by_developer_id=getattr(sender, "sent_by", None)' in src
    from agentvault_registry.models import ChatMessage
    m = ChatMessage(id="m1", conversation_id="c1", seq=1, sender_ptype="agent", sender_id=DID, kind="text", body="hi",
                    client_ref="r1", sent_by_developer_id=6)
    assert cs.serialize_message(m)["sent_by_owner"] is True
    m.sent_by_developer_id = None
    assert cs.serialize_message(m)["sent_by_owner"] is False


def test_the_migration_adds_one_nullable_column():
    import importlib.util
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0203_chat_message_sent_by.py"
    spec = importlib.util.spec_from_file_location("m0203", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (mod.revision, mod.down_revision) == ("0203_chat_message_sent_by", "0202_chat_approval_consumed")
    assert len(mod.revision) <= 32
    calls = []
    mod.op = types.SimpleNamespace(add_column=lambda t, c: calls.append(("add", t, c.name, c.nullable)),
                                   drop_column=lambda t, c: calls.append(("drop", t, c)))
    mod.upgrade()
    mod.downgrade()
    assert calls == [("add", "chat_messages", "sent_by_developer_id", True),
                     ("drop", "chat_messages", "sent_by_developer_id")]
