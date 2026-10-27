"""§MCPTEST30 (V0548) — a guild amount that is not a number is the caller's error, never the server's.

guildPostOrder, guildBid and guildCrossRegistryBid take their amounts as text and called float() on it, so a bounty of
"phase6" raised ValueError inside the tool and the dispatcher answered an internal error (the request survey's RAISED
class, V0546). They answer "<name> must be a number" before any request, and a finite number passes as before.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.mcp import tools_guild as G
from agentvault_registry.mcp.auth_bridge import MCPAuthContext

AGENT = MCPAuthContext(auth_type="agent", agent_did="did:theprotocol:phase6-self", agent_id=1, raw_token="phase6-agent-token")


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def _post(path, payload, token):
        calls.append((path, payload))
        return {"ok": True}
    monkeypatch.setattr(G, "_guild_post", _post)
    return calls


@pytest.mark.parametrize("call", [
    lambda: G.guild_post_order(AGENT, title="t", bounty="phase6"),
    lambda: G.guild_post_order(AGENT, title="t", bounty="5", stake_required="lots"),
    lambda: G.guild_post_order(AGENT, title="t", bounty="nan"),
    lambda: G.guild_bid(AGENT, order_id="o1", price="inf"),
    lambda: G.guild_bid(AGENT, order_id="o1", price="ten"),
])
def test_text_that_is_not_a_number_is_refused_before_any_request(sent, call):
    out = asyncio.run(call())
    assert "must be a" in out["error"] and sent == []


def test_a_number_given_as_text_is_sent_as_a_number(sent):
    assert asyncio.run(G.guild_post_order(AGENT, title="t", bounty="12.5", stake_required="2", min_reputation="0.4")) == {"ok": True}
    assert sent[-1][1]["bounty"] == 12.5 and sent[-1][1]["stake_required"] == 2.0 and sent[-1][1]["min_reputation"] == 0.4
    assert asyncio.run(G.guild_bid(AGENT, order_id="o1", price="3")) == {"ok": True}
    assert sent[-1][1]["price"] == 3.0


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
