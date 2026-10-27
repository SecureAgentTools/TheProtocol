"""D6-017 (2026-10-16): unlockUnits releases the position it names, and only that position.

The tool took a stake_id, looked up that position's AMOUNT and posted only the amount to /staking/unstake, which then
released it from the agent's unlocked positions oldest first: a different position than the one named could go, and a
named position still under its lock did not stop that. The route has named a position since §FESUITE (`position_id`:
a locked one is refused with its unlock date, nothing else is touched, tests/test_staking_unstake_position.py); the
tool now sends it. A position my-positions lists as already released is no position to release.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.mcp import tools_agent

POSITIONS = [
    {"id": 11, "agent_did": "did:theprotocol:me", "amount": "5", "status": "active", "canUnstake": True},
    {"id": 12, "agent_did": "did:theprotocol:me", "amount": "7", "status": "unstaked", "canUnstake": False},
    {"id": 13, "agent_did": "did:theprotocol:me", "amount": "9", "status": "active", "canUnstake": False},
]


class _Auth:
    raw_token = "agent-jwt"
    agent_did = "did:theprotocol:me"
    auth_type = "agent"


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.headers, self.text = {"content-type": "application/json"}, "{}"

    def json(self):
        return self._body


class _Client:
    posts: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, **k):
        assert url.endswith("/api/v1/staking/my-positions")
        return _Resp(200, POSITIONS)

    async def post(self, url, json=None, headers=None, **k):
        _Client.posts.append((url, json))
        return _Resp(200, {"transaction_id": "tx-1", "stake_id": str(json.get("position_id")), "amount": json["amount"]})


@pytest.fixture
def posts(monkeypatch):
    _Client.posts = []
    monkeypatch.setattr(tools_agent.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(tools_agent, "require_agent_auth", lambda auth: None)
    return _Client.posts


def test_the_release_names_the_position_and_its_whole_amount(posts):
    out = asyncio.run(tools_agent.unstake_tokens(_Auth(), stake_id="13"))
    assert posts == [(f"{tools_agent.REGISTRY_SELF_URL}/api/v1/staking/unstake", {"amount": "9", "position_id": "13"})]
    assert out["status"] == "unstaked" and out["stake_id"] == "13" and out["unstaked_amount"] == "9"


def test_the_body_is_one_the_route_reads_whole(posts):
    """position_id is a field of the route's own model, so pydantic keeps it (a dropped field would answer 200)."""
    from agentvault_registry.schemas_enhanced import UnstakeRequest
    asyncio.run(tools_agent.unstake_tokens(_Auth(), stake_id="11"))
    req = UnstakeRequest(**posts[-1][1])
    assert req.position_id == "11" and str(req.amount) == "5"


def test_a_released_position_is_not_released_again_and_nothing_is_posted(posts):
    out = asyncio.run(tools_agent.unstake_tokens(_Auth(), stake_id="12"))
    assert "already unlocked" in out["error"] and posts == []


def test_control_an_unknown_id_posts_nothing(posts):
    out = asyncio.run(tools_agent.unstake_tokens(_Auth(), stake_id="99"))
    assert "not found" in out["error"] and posts == []
