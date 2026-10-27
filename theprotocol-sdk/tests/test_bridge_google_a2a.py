"""Tests for Google A2A ↔ TheProtocol A2A bridge."""

import datetime
import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from theprotocol.models import Message, Task, TaskState, TextPart, DataPart
from theprotocol.agent import BaseA2AAgent
from theprotocol.bridges.google_a2a import (
    GoogleA2ABridge, google_part_to_tp_part, tp_part_to_google_part,
    google_message_to_tp, tp_message_to_google, tp_task_to_google_task,
    GOOGLE_TO_TP_STATE, TP_TO_GOOGLE_STATE,
)


class EchoAgent(BaseA2AAgent):
    def __init__(self):
        super().__init__()
        self.tasks = {}

    async def handle_task_send(self, task_id, message):
        tid = task_id or "task-g1"
        text = ""
        for p in message.parts:
            if hasattr(p, 'content') and isinstance(p.content, str):
                text = p.content
        self.tasks[tid] = {"message": message, "response": f"Google echo: {text}"}
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


# ── Part conversion tests ──

def test_google_text_part():
    tp = google_part_to_tp_part({"text": "hello"})
    assert tp.type == "text"
    assert tp.content == "hello"


def test_google_data_part():
    tp = google_part_to_tp_part({"data": {"key": "val"}})
    assert tp.type == "data"
    assert tp.content["key"] == "val"


def test_google_url_part():
    tp = google_part_to_tp_part({"url": "https://example.com/file.pdf", "media_type": "application/pdf"})
    assert tp.type == "file"
    assert "example.com" in str(tp.url)


def test_tp_text_to_google():
    gp = tp_part_to_google_part(TextPart(content="hi"))
    assert gp["text"] == "hi"


def test_tp_data_to_google():
    gp = tp_part_to_google_part(DataPart(content={"x": 1}))
    assert gp["data"]["x"] == 1


# ── Message conversion tests ──

def test_google_user_message():
    gmsg = {"role": "user", "parts": [{"text": "query"}], "message_id": "m1"}
    msg = google_message_to_tp(gmsg)
    assert msg.role == "user"
    assert msg.parts[0].content == "query"


def test_google_agent_role_maps_to_assistant():
    gmsg = {"role": "agent", "parts": [{"text": "response"}]}
    msg = google_message_to_tp(gmsg)
    assert msg.role == "agent"


def test_tp_to_google_message():
    msg = Message(role="assistant", parts=[TextPart(content="answer")])
    gmsg = tp_message_to_google(msg)
    assert gmsg["role"] == "agent"
    assert gmsg["parts"][0]["text"] == "answer"
    assert "message_id" in gmsg


# ── State mapping tests ──

def test_state_mapping_covers_all_google_states():
    google_states = ["submitted", "working", "completed", "failed", "canceled", "input-required", "rejected", "auth-required"]
    for s in google_states:
        assert s in GOOGLE_TO_TP_STATE, f"Google state '{s}' unmapped"


def test_state_mapping_covers_all_tp_states():
    for ts in TaskState:
        assert ts in TP_TO_GOOGLE_STATE, f"TP state '{ts}' unmapped"


# ── Task conversion ──

def test_task_to_google_task():
    now = datetime.datetime.now(datetime.timezone.utc)
    task = Task(
        id="t1", state=TaskState.COMPLETED, createdAt=now, updatedAt=now,
        messages=[Message(role="assistant", parts=[TextPart(content="done")])],
    )
    gt = tp_task_to_google_task(task)
    assert gt["id"] == "t1"
    assert gt["status"]["state"] == "completed"
    assert gt["history"][0]["role"] == "agent"
    assert gt["history"][0]["parts"][0]["text"] == "done"


# ── Integration: REST roundtrip ──

def test_google_a2a_send_message():
    agent = EchoAgent()
    bridge = GoogleA2ABridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/g")

    client = TestClient(app)
    resp = client.post("/g/tasks", json={
        "message": {"role": "user", "parts": [{"text": "hello google"}]},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "task-g1"
    assert data["status"]["state"] == "completed"


def test_google_a2a_get_task():
    agent = EchoAgent()
    bridge = GoogleA2ABridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/g")

    client = TestClient(app)
    # Create first
    client.post("/g/tasks", json={"message": {"role": "user", "parts": [{"text": "get test"}]}})
    # Then get
    resp = client.get("/g/tasks/task-g1")
    assert resp.status_code == 200
    assert resp.json()["status"]["state"] == "completed"


def test_google_a2a_cancel():
    agent = EchoAgent()
    bridge = GoogleA2ABridge()
    app = FastAPI()
    app.include_router(bridge.create_external_router(agent), prefix="/g")

    client = TestClient(app)
    client.post("/g/tasks", json={"message": {"role": "user", "parts": [{"text": "cancel"}]}})
    resp = client.post("/g/tasks/task-g1:cancel")
    assert resp.status_code == 200
    assert resp.json()["status"]["state"] == "canceled"
