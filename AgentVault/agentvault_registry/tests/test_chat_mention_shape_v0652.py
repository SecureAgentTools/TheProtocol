"""V0652 (x) (2026-11-01, agentvault2-14; the sessions' room seq 596-599): the console reads a mention the way the server
stores it.

Order gwo_cedd900e6d50be18ce4eecf1. The server stores a resolved mention as {key, ptype, developer_id, agent_did, token}
(services/chat_mentions.resolve_mentions; V0650 (h)) and ships that list as it is in every serialized message
(chat_service's message dicts). The console's ChatMessageBody read `label`, a field nothing sends, so no mention the server
resolved was ever marked: only the viewer's own handle or name, from the signed-in account, stood out (session-tester's check
142 on sbx-beta, seq 596). Its unit tests fed a hand-made {key, label}.

The shape now has one copy both sides test against: src/services/chat/__fixtures__/serverMentions.json in the console tree.
This file compares it with the real resolver (the fixture's body, a roster of the principals it names), so the fixture cannot
drift from what the server writes; the console's ChatMessageBody.mentions.test.ts mounts the component with it. A field
renamed on either side fails one of the two. Neither case reads a database.
"""
from __future__ import annotations

import json
from pathlib import Path

from agentvault_registry.services import chat_service as cs
from agentvault_registry.services.chat_mentions import resolve_mentions

FIXTURE = (Path(__file__).resolve().parents[1] / "src/agentvault_registry/static/new_registry_frontend/src"
           / "services/chat/__fixtures__/serverMentions.json")
SCOUT = "did:theprotocol:eu.test:Scout-AGENT-1"
LEAD = "did:theprotocol:eu.test:session-lead"


def _roster():
    """The thread the fixture's message was posted in: the maintainer by handle, two agents by card name (one is the sender)."""
    return [
        {"key": cs.principal_key("developer", 6), "ptype": "developer", "developer_id": 6, "agent_did": None,
         "aliases": [("handle", "maintainer")]},
        {"key": cs.principal_key("agent", SCOUT), "ptype": "agent", "developer_id": None, "agent_did": SCOUT,
         "aliases": [("did", SCOUT), ("name", "Scout")]},
        {"key": cs.principal_key("agent", LEAD), "ptype": "agent", "developer_id": None, "agent_did": LEAD,
         "aliases": [("did", LEAD), ("name", "session-lead")]},
    ]


def _fixture():
    return json.loads(FIXTURE.read_text())


def test_the_consoles_fixture_is_exactly_what_the_resolver_returns():
    fx = _fixture()
    assert fx["sender_key"] == cs.principal_key("agent", LEAD)
    assert resolve_mentions(fx["body"], _roster(), fx["sender_key"]) == fx["mentions"]


def test_a_stored_mention_names_its_text_by_token_and_carries_no_label():
    # the field the console marks by: each mention's token is the name as typed after its "@" in the body
    fx = _fixture()
    assert len(fx["mentions"]) == 2                     # @maintainer and @Scout; @nobody names no one
    for m in fx["mentions"]:
        assert set(m) == {"key", "ptype", "developer_id", "agent_did", "token"}
        assert "@" + m["token"] in fx["body"]
    assert "@nobody" in fx["body"] and all(m["token"] != "nobody" for m in fx["mentions"])


def test_control_a_renamed_field_would_not_pass_the_comparison():
    # the comparison is strict: the {key, label} the console's tests used to feed is not what the server writes
    fx = _fixture()
    hand_made = [{"key": m["key"], "label": m["token"]} for m in fx["mentions"]]
    assert resolve_mentions(fx["body"], _roster(), fx["sender_key"]) != hand_made
