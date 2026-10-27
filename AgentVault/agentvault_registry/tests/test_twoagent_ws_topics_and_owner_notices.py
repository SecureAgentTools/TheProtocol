"""§TWOAGENT (2026-09-24): a socket topic is read by whoever holds it, and one tenant's activity is not every tenant's news.

Found in the webhook-events pass, read from the code and fixed without exercising it against anyone's data:
  * the main socket's `subscribe` added ANY topic a connected developer named, including another developer's
    `chat:dev:<id>`, the channel their chat messages travel on (holding a topic is reading it);
  * the agent-card notices on `agent:<id>` (a topic anyone may hold) carried the owner's email and developer id;
  * five owner-private broadcasts (an agent's heartbeat, its self-delete, an export, an import, a clone) and the
    presence notice went to every connected user, without an audience: the #34 class.

RED on d9d094cc: every test (the rule and the helper do not exist there, and the source checks find the old calls).
"""
from __future__ import annotations

import ast
import pathlib
import types

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def test_a_topic_is_readable_only_by_whom_it_belongs_to():
    from agentvault_registry.routers.websocket import topic_allowed
    dev = {"id": "7", "is_admin": False}
    admin = {"id": "1", "is_admin": True}
    assert topic_allowed(dev, "chat:dev:7")
    assert not topic_allowed(dev, "chat:dev:8")          # another developer's chat channel
    assert not topic_allowed(admin, "chat:dev:8")        # not even an admin reads someone's chat by subscribing
    assert not topic_allowed({"id": ""}, "chat:dev:")
    assert not topic_allowed(dev, "docker_stats") and topic_allowed(admin, "docker_stats")
    for public in ("system.events", "event:TokensTransferred", "agent:did:theprotocol:x"):
        assert topic_allowed(dev, public)
    for unknown in ("chat:conv:1", "private:anything", "", "agentx"):
        assert not topic_allowed(dev, unknown)


async def test_a_refused_subscription_holds_nothing_and_says_so(monkeypatch):
    from agentvault_registry.routers import websocket as ws
    subs, sent = [], []
    fake = types.SimpleNamespace(subscribe=lambda u, t: subs.append((u, t)))

    async def _send(msg, uid):
        sent.append((uid, msg["type"], msg["data"].get("topic")))
    fake.send_personal_message = _send
    monkeypatch.setattr(ws, "manager", fake)
    assert await ws._subscribe_checked("7", {"id": "7"}, "chat:dev:8") is False
    assert subs == [] and sent == [("7", "error", "chat:dev:8")]
    assert await ws._subscribe_checked("7", {"id": "7"}, "agent:did:theprotocol:x") is True
    assert subs == [("7", "agent:did:theprotocol:x")] and sent[-1] == ("7", "subscribed", "agent:did:theprotocol:x")


def _calls(path: pathlib.Path, attr: str):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            if name == attr:
                yield node


def _dict_const(node: ast.AST, key: str):
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == key:
                return v
    return None


OWNER_PRIVATE = {"agent.heartbeat", "agent.deleted", "agent.exported", "agent.imported", "agent.cloned",
                 "user.disconnected"}


def test_owner_private_broadcasts_carry_an_audience():
    seen = set()
    for f in ("routers/agents.py", "routers/agents_export_import.py", "routers/websocket.py"):
        for call in _calls(SRC / f, "broadcast"):
            typ = _dict_const(call.args[0], "type") if call.args else None
            if isinstance(typ, ast.Constant) and typ.value in OWNER_PRIVATE:
                seen.add(typ.value)
                assert any(k.arg == "audience" for k in call.keywords), f"{f}: {typ.value} goes to every tenant"
    assert seen == OWNER_PRIVATE, f"not found, so not checked: {OWNER_PRIVATE - seen}"


def test_agent_notices_carry_no_owner_identity():
    calls = list(_calls(SRC / "routers/agent_cards.py", "notify_agent_update"))
    assert len(calls) == 3
    for call in calls:
        payload = call.args[1]
        assert _dict_const(payload, "developer") is None and _dict_const(payload, "developer_id") is None
