"""The public card read carries the card's agent DID (schemas.AgentCardRead.agent_did was declared and never set)."""
from unittest.mock import MagicMock

from agentvault_registry.routers.agent_cards import _build_agent_card_read_dict


def _card(did):
    c = MagicMock()
    c.id = "adbb7cbf-24b2-43a0-b4f3-0492461c112c"
    c.agent_did = did
    c.card_data = {"name": "x"}
    c.unlisted = False
    return c


def test_read_dict_carries_agent_did():
    assert _build_agent_card_read_dict(_card("did:theprotocol:eu.theprotocol.cloud:392e1ff0-60a7-4e2a-a0c6-c8078fcfd77c"))["agent_did"] == (
        "did:theprotocol:eu.theprotocol.cloud:392e1ff0-60a7-4e2a-a0c6-c8078fcfd77c"
    )


def test_read_dict_agent_did_none_for_an_unlinked_card():
    d = _build_agent_card_read_dict(_card(None))
    assert "agent_did" in d and d["agent_did"] is None
