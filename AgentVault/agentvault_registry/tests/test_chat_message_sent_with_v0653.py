"""V0653 (w) (session-lead, the sessions' room seq 880; agentvault2-14, 2026-11-02): each chat message records the
credential it was sent with, and the read returns it.

From V0653 a developer key posts in the chat (an MCP connector's, the personal bridge's), so a line from a developer no
longer proves his own hand. The auth dependency names the credential it resolved ("session", "api_key", "agent"), the
Actor carries it, insert_message stores it (mig 0208, `chat_messages.sent_with`) and serialize_message returns it; a
principal the registry builds itself carries none (NULL). The route-level cases are in test_chat_write_keys_v0653.py.
Each case fails on 18ee29f22.
"""
from __future__ import annotations

import importlib.util
import inspect
import pathlib
import types

from agentvault_registry.models import ChatMessage
from agentvault_registry.services import chat_service as cs

DID = "did:theprotocol:eu.theprotocol.cloud:19c1aa48"
DEV = types.SimpleNamespace(id=6, name="maintainer", email="x@example.org")


def test_the_actor_carries_the_credential_the_dependency_named():
    agent = types.SimpleNamespace(name="session-tester")
    assert cs.actor_from_auth({"kind": "developer", "developer": DEV, "credential": "session"}).sent_with == "session"
    assert cs.actor_from_auth({"kind": "developer", "developer": DEV, "credential": "api_key"}).sent_with == "api_key"
    assert cs.actor_from_auth({"kind": "agent", "agent_did": DID, "agent": agent, "credential": "agent"}).sent_with == "agent"
    # a dict that names nothing (a caller built elsewhere) records nothing, never a guess
    assert cs.actor_from_auth({"kind": "developer", "developer": DEV}).sent_with is None
    # a principal the registry builds itself
    assert cs.Actor("system", system_id="support-desk").sent_with is None


def test_the_message_stores_it_and_the_read_returns_it():
    assert 'sent_with=getattr(sender, "sent_with", None)' in inspect.getsource(cs.insert_message)
    m = ChatMessage(id="m1", conversation_id="c1", seq=1, sender_ptype="developer", sender_id="6", kind="text",
                    body="approved", client_ref="r1", sent_with="api_key")
    assert cs.serialize_message(m)["sent_with"] == "api_key"
    m.sent_with = None
    assert cs.serialize_message(m)["sent_with"] is None


def test_the_migration_adds_one_nullable_column():
    p = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0208_chat_message_sent_with.py"
    spec = importlib.util.spec_from_file_location("m0208", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (mod.revision, mod.down_revision) == ("0208_chat_message_sent_with", "0207_chat_room_board")
    assert len(mod.revision) <= 32
    calls = []
    mod.op = types.SimpleNamespace(add_column=lambda t, c: calls.append(("add", t, c.name, c.nullable, c.type.length)),
                                   drop_column=lambda t, c: calls.append(("drop", t, c)))
    mod.upgrade()
    mod.downgrade()
    assert calls == [("add", "chat_messages", "sent_with", True, 16), ("drop", "chat_messages", "sent_with")]
