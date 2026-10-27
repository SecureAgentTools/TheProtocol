"""§TWOAGENT #5 (2026-09-23) — a message an agent sends is signed with the agent's NAME, not its raw DID.

Measured on EU and ASIA: every `chat.message.received` delivery from an agent carried `message.sender_name` = the raw
DID (e.g. `did:theprotocol:asia.theprotocol.cloud:011dbd40-…`), while the conversation list showed the same agent by its
card name. `actor_from_auth` falls back to the DID because the agents table has no name column; the send path never
looked the card up. `chat_service.display_names` (the message list's own resolver) now names the sender before the send.

RED on V0429: `_named_sender` does not exist and the sent payload's sender_name is the DID. The controls (a developer
keeps its name; an agent with no card keeps its DID) pass wherever the helper exists.
"""
from __future__ import annotations

import pytest

from agentvault_registry.services import chat_service as cs

DID = "did:theprotocol:asia.test:assay"


async def test_an_agent_sender_is_named_by_its_card(monkeypatch):
    from agentvault_registry.routers import chat as chat_router

    async def _names(db, keys):
        return {cs.principal_key("agent", DID): "Straits Assay"}
    monkeypatch.setattr(cs, "display_names", _names)
    named = await chat_router._named_sender(None, cs.Actor("agent", agent_did=DID, display_name=DID))
    assert named.display_name == "Straits Assay" and named.agent_did == DID


async def test_control_a_developer_keeps_its_name(monkeypatch):
    from agentvault_registry.routers import chat as chat_router
    dev = cs.Actor("developer", developer_id=11, display_name="Straits Assay Desk")
    assert (await chat_router._named_sender(None, dev)) is dev


async def test_control_an_agent_without_a_card_keeps_its_did(monkeypatch):
    from agentvault_registry.routers import chat as chat_router

    async def _names(db, keys):
        return {k: DID for k in keys}           # display_names' own fallback: the DID
    monkeypatch.setattr(cs, "display_names", _names)
    named = await chat_router._named_sender(None, cs.Actor("agent", agent_did=DID, display_name=DID))
    assert named.display_name == DID
