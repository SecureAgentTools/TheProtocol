"""Tests for MCP ↔ A2A bridge — validates JSON-RPC 2.0 translation."""

import datetime
import json
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from theprotocol.models import Message, Task, TaskState, TextPart, DataPart, Artifact
from theprotocol.agent import BaseA2AAgent
from theprotocol.bridges.mcp import (
    MCPBridge, mcp_tool_call_to_a2a_message, a2a_task_to_mcp_content,
)


class EchoAgent(BaseA2AAgent):
    def __init__(self):
        super().__init__(agent_metadata={"description": "MCP bridge test agent"})
        self.tasks = {}

    async def handle_task_send(self, task_id, message):
        tid = task_id or "task-mcp-1"
        text = ""
        for p in message.parts:
            if hasattr(p, 'content') and isinstance(p.content, str):
                text = p.content
            elif hasattr(p, 'content') and isinstance(p.content, dict):
                text = json.dumps(p.content)
        self.tasks[tid] = {"message": message, "response": f"MCP echo: {text}"}
        return tid

    async def handle_task_get(self, task_id):
        t = self.tasks.get(task_id)
        if not t:
            raise ValueError("not found")
        now = datetime.datetime.now(datetime.timezone.utc)
        return Task(
            id=task_id, state=TaskState.COMPLETED, createdAt=now, updatedAt=now,
            messages=[
                t["message"],
                Message(role="assistant", parts=[TextPart(content=t["response"])]),
            ],
        )

    async def handle_task_cancel(self, task_id):
        return True

    async def handle_subscribe_request(self, task_id):
        return; yield


# ── Unit tests: conversion functions ──

def test_tool_call_to_message_simple():
    msg = mcp_tool_call_to_a2a_message("greet", {"name": "Alice"})
    assert msg.role == "user"
    assert msg.parts[0].type == "data"
    assert msg.parts[0].content["tool"] == "greet"
    assert msg.parts[0].content["arguments"]["name"] == "Alice"


def test_task_to_mcp_content_text():
    now = datetime.datetime.now(datetime.timezone.utc)
    task = Task(
        id="t1", state=TaskState.COMPLETED, createdAt=now, updatedAt=now,
        messages=[Message(role="assistant", parts=[TextPart(content="result data")])],
    )
    content = a2a_task_to_mcp_content(task)
    assert len(content) >= 1
    assert content[0]["type"] == "text"
    assert "result data" in content[0]["text"]


def test_task_to_mcp_content_with_artifacts():
    now = datetime.datetime.now(datetime.timezone.utc)
    task = Task(
        id="t1", state=TaskState.COMPLETED, createdAt=now, updatedAt=now,
        messages=[], artifacts=[Artifact(id="a1", type="file", content="artifact data")],
    )
    content = a2a_task_to_mcp_content(task)
    assert any("artifact data" in c.get("text", "") for c in content)


def test_task_to_mcp_content_fallback():
    now = datetime.datetime.now(datetime.timezone.utc)
    task = Task(id="t1", state=TaskState.WORKING, createdAt=now, updatedAt=now)
    content = a2a_task_to_mcp_content(task)
    assert len(content) == 1
    assert "WORKING" in content[0]["text"]


# ── Integration: MCP JSON-RPC roundtrip ──

def _mcp_call(client, method, params=None, rid=1):
    resp = client.post("/mcp/", json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
    return resp.json()


def test_mcp_initialize():
    agent = EchoAgent()
    bridge = MCPBridge(server_name="test-agent")
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/mcp")

    client = TestClient(app)
    data = _mcp_call(client, "initialize", {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    })
    assert data["result"]["protocolVersion"] == "2025-03-26"
    assert data["result"]["serverInfo"]["name"] == "test-agent"


def test_mcp_tools_list():
    agent = EchoAgent()
    bridge = MCPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/mcp")

    client = TestClient(app)
    data = _mcp_call(client, "tools/list")
    assert "tools" in data["result"]
    assert len(data["result"]["tools"]) >= 1
    assert data["result"]["tools"][0]["name"] == "send_message"
    assert "inputSchema" in data["result"]["tools"][0]


def test_mcp_tools_call():
    agent = EchoAgent()
    bridge = MCPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/mcp")

    client = TestClient(app)
    data = _mcp_call(client, "tools/call", {"name": "send_message", "arguments": {"message": "hello from MCP"}})
    assert "result" in data
    assert "content" in data["result"]
    assert data["result"]["isError"] is False
    # Check the response contains our echo
    texts = [c["text"] for c in data["result"]["content"] if c.get("type") == "text"]
    assert any("MCP echo" in t for t in texts)


def test_mcp_ping():
    agent = EchoAgent()
    bridge = MCPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/mcp")

    client = TestClient(app)
    data = _mcp_call(client, "ping")
    assert data["result"] == {}


def test_mcp_unknown_method():
    agent = EchoAgent()
    bridge = MCPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/mcp")

    client = TestClient(app)
    data = _mcp_call(client, "nonexistent/method")
    assert "error" in data
    assert data["error"]["code"] == -32601


def test_mcp_resources_list():
    agent = EchoAgent()
    bridge = MCPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/mcp")

    client = TestClient(app)
    data = _mcp_call(client, "resources/list")
    assert data["result"]["resources"] == []


def test_mcp_notification_passthrough():
    agent = EchoAgent()
    bridge = MCPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/mcp")

    client = TestClient(app)
    data = _mcp_call(client, "notifications/initialized", rid=None)
    # Notifications should not error
    assert "error" not in data or data.get("error") is None
