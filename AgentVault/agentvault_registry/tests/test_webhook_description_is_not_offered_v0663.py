"""D6-767 (V0663, gwo_49ccc7efec6ae43112f5bd72): a webhook stores no description, so none is offered.

WebhookCreate and WebhookUpdate and the createWebhook and updateWebhook MCP tools accepted a `description`, validated it and
dropped it (DeveloperWebhook has no column): a caller believed it had stored a label it could never read back. Dropped from the
schemas and the tools' advertised inputs. A body that still sends one is not refused (unknown keys are ignored), and the MCP
handlers still accept the argument so no client breaks, but nothing is sent.
RED control: against b27f2ebaf both models declare the field and both tool schemas advertise it.
"""
from __future__ import annotations

import asyncio

from agentvault_registry.routers.webhooks import WebhookCreate, WebhookUpdate
from agentvault_registry.mcp import tools_developer as td


def _schema(name):
    for t in td.DEVELOPER_TOOL_SCHEMAS:
        if t["name"] == name:
            return t["inputSchema"]
    raise AssertionError(f"{name} is not advertised")


def test_the_request_models_declare_no_description():
    assert "description" not in WebhookCreate.model_fields
    assert "description" not in WebhookUpdate.model_fields


def test_a_body_that_still_sends_one_is_not_refused_and_keeps_nothing():
    c = WebhookCreate(url="https://hooks.example.org/in", events=["agent.created"], description="a label")
    assert "description" not in c.model_dump()
    u = WebhookUpdate(description="a label", is_active=False)
    assert u.model_dump(exclude_none=True) == {"is_active": False}


def test_the_mcp_tools_do_not_advertise_it():
    assert "description" not in _schema("theprotocol_createWebhook")["properties"]
    assert "description" not in _schema("theprotocol_updateWebhook")["properties"]


def test_the_mcp_handlers_accept_the_argument_and_send_nothing_of_it(monkeypatch):
    sent = []

    async def fake(auth, method, path, json_body=None, **k):
        sent.append((method, path, json_body))
        return {"ok": True}

    monkeypatch.setattr(td, "_dev_request", fake)
    asyncio.run(td.create_webhook(None, url="https://hooks.example.org/in", events=["agent.created"], description="a label"))
    asyncio.run(td.update_webhook(None, webhook_id="w1", is_active=False, description="a label"))
    assert sent[0][2] == {"url": "https://hooks.example.org/in", "events": ["agent.created"]}
    assert sent[1][2] == {"is_active": False}
