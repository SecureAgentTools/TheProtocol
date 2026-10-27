"""Tests for ACP ↔ A2A bridge — validates exact wire format translation."""

import datetime
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from theprotocol.models import Message, Task, TaskState, TextPart, DataPart, Artifact
from theprotocol.agent import BaseA2AAgent
from theprotocol.bridges.acp import (
    ACPBridge, acp_message_to_a2a, a2a_message_to_acp,
    a2a_task_to_acp_run, ACP_TO_A2A_STATE, A2A_TO_ACP_STATE,
)


# ── Test Agent ──

class EchoAgent(BaseA2AAgent):
    def __init__(self):
        super().__init__(agent_metadata={"description": "Test echo agent"})
        self.tasks = {}

    async def handle_task_send(self, task_id, message):
        tid = task_id or "task-1"
        text = ""
        for p in message.parts:
            if hasattr(p, 'content') and isinstance(p.content, str):
                text = p.content
        self.tasks[tid] = {"message": message, "response": f"Echo: {text}"}
        return tid

    async def handle_task_get(self, task_id):
        t = self.tasks.get(task_id)
        if not t:
            raise ValueError(f"Task {task_id} not found")
        now = datetime.datetime.now(datetime.timezone.utc)
        return Task(
            id=task_id, state=TaskState.COMPLETED,
            createdAt=now, updatedAt=now,
            messages=[
                t["message"],
                Message(role="assistant", parts=[TextPart(content=t["response"])]),
            ],
        )

    async def handle_task_cancel(self, task_id):
        return task_id in self.tasks

    async def handle_subscribe_request(self, task_id):
        return; yield


# ── Unit tests: message conversion ──

def test_acp_text_message_to_a2a():
    acp = {"role": "user", "parts": [{"content_type": "text/plain", "content": "hello"}]}
    msg = acp_message_to_a2a(acp)
    assert msg.role == "user"
    assert len(msg.parts) == 1
    assert msg.parts[0].content == "hello"


def test_acp_agent_role_maps_to_assistant():
    acp = {"role": "agent", "parts": [{"content_type": "text/plain", "content": "hi"}]}
    msg = acp_message_to_a2a(acp)
    assert msg.role == "assistant"


def test_acp_json_message_to_a2a():
    import json
    acp = {"role": "user", "parts": [{"content_type": "application/json", "content": json.dumps({"key": "val"})}]}
    msg = acp_message_to_a2a(acp)
    assert msg.parts[0].type == "data"
    assert msg.parts[0].content["key"] == "val"


def test_a2a_text_message_to_acp():
    msg = Message(role="user", parts=[TextPart(content="hello")])
    acp = a2a_message_to_acp(msg)
    assert acp["role"] == "user"
    assert acp["parts"][0]["content_type"] == "text/plain"
    assert acp["parts"][0]["content"] == "hello"


def test_a2a_assistant_maps_to_agent_role():
    msg = Message(role="assistant", parts=[TextPart(content="hi")])
    acp = a2a_message_to_acp(msg)
    assert acp["role"] == "agent"


def test_state_mapping_completeness():
    """Ensure all ACP states map to A2A states."""
    acp_states = ["created", "in-progress", "awaiting", "completed", "failed", "cancelled", "cancelling"]
    for s in acp_states:
        assert s in ACP_TO_A2A_STATE, f"ACP state '{s}' has no A2A mapping"

    for ts in TaskState:
        assert ts in A2A_TO_ACP_STATE, f"A2A state '{ts}' has no ACP mapping"


def test_task_to_run_conversion():
    now = datetime.datetime.now(datetime.timezone.utc)
    task = Task(
        id="t1", state=TaskState.COMPLETED, createdAt=now, updatedAt=now,
        messages=[
            Message(role="user", parts=[TextPart(content="query")]),
            Message(role="assistant", parts=[TextPart(content="answer")]),
        ],
        metadata={"agent_name": "test-agent"},
    )
    run = a2a_task_to_acp_run(task)
    assert run["run_id"] == "t1"
    assert run["status"] == "completed"
    assert run["agent_name"] == "test-agent"
    assert len(run["output"]) == 1  # Only assistant messages
    assert run["output"][0]["parts"][0]["content"] == "answer"


# ── Integration test: full REST roundtrip ──

def test_acp_bridge_create_run():
    agent = EchoAgent()
    bridge = ACPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/acp")

    client = TestClient(app)

    # Create run
    resp = client.post("/acp/runs", json={
        "agent_name": "echo",
        "input": [{"role": "user", "parts": [{"content_type": "text/plain", "content": "test message"}]}],
    })
    assert resp.status_code == 202
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "created"
    run_id = data["run_id"]

    # Get run
    resp = client.get(f"/acp/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert any("Echo: test message" in p.get("content", "") for m in data["output"] for p in m.get("parts", []))


def test_acp_bridge_list_agents():
    agent = EchoAgent()
    bridge = ACPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/acp")

    client = TestClient(app)
    resp = client.get("/acp/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["agents"][0]["name"] == "echoagent"


def test_acp_bridge_ping():
    agent = EchoAgent()
    bridge = ACPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/acp")

    client = TestClient(app)
    resp = client.get("/acp/ping")
    assert resp.status_code == 200
    assert resp.json() == {}


def test_acp_bridge_cancel_run():
    agent = EchoAgent()
    bridge = ACPBridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/acp")

    client = TestClient(app)

    # Create run first
    resp = client.post("/acp/runs", json={
        "agent_name": "echo",
        "input": [{"role": "user", "parts": [{"content_type": "text/plain", "content": "cancel me"}]}],
    })
    run_id = resp.json()["run_id"]

    # Cancel it
    resp = client.post(f"/acp/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelling"
