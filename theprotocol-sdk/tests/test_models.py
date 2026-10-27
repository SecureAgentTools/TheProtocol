"""Tests for A2A protocol models."""

import datetime
from theprotocol.models import (
    TaskState, TextPart, DataPart, FilePart, Message, Task, Artifact,
    AgentCard, AgentProvider, AgentAuthentication, AgentCapabilities,
    TaskSendParams, TaskSendResult, TaskStatusUpdateEvent,
)


def test_task_state_enum():
    assert TaskState.SUBMITTED == "TASK_STATE_SUBMITTED"
    assert TaskState.COMPLETED == "TASK_STATE_COMPLETED"


def test_text_part():
    p = TextPart(content="hello")
    assert p.type == "text"
    assert p.content == "hello"


def test_data_part():
    p = DataPart(content={"key": "value"})
    assert p.type == "data"
    assert p.content["key"] == "value"


def test_message():
    m = Message(role="user", parts=[TextPart(content="hi")])
    assert m.role == "user"
    assert len(m.parts) == 1


def test_task():
    now = datetime.datetime.now(datetime.timezone.utc)
    t = Task(id="t1", state=TaskState.SUBMITTED, createdAt=now, updatedAt=now)
    assert t.id == "t1"
    assert t.state == TaskState.SUBMITTED


def test_artifact():
    a = Artifact(id="a1", type="file", content="data")
    assert a.id == "a1"


def test_agent_card():
    card = AgentCard(
        protocolVersion="0.3.0",
        humanReadableId="test/agent",
        agentVersion="1.0.0",
        name="Test Agent",
        description="A test agent",
        url="https://example.com/a2a",
        provider=AgentProvider(name="Test"),
        capabilities=AgentCapabilities(streaming=True),
        authSchemes=[AgentAuthentication(scheme="none")],
    )
    assert card.name == "Test Agent"
    assert card.capabilities.streaming is True


def test_agent_card_backcompat_schema_version():
    card = AgentCard(
        schemaVersion="0.3.0",  # Legacy field
        humanReadableId="test/agent",
        agentVersion="1.0.0",
        name="Test",
        description="Test",
        url="https://example.com/a2a",
        provider=AgentProvider(name="Test"),
        capabilities=AgentCapabilities(streaming=False),
        authSchemes=[AgentAuthentication(scheme="none")],
    )
    assert card.protocol_version == "0.3.0"


def test_task_send_params():
    p = TaskSendParams(message=Message(role="user", parts=[TextPart(content="go")]))
    assert p.id is None
    assert p.message.role == "user"


def test_status_update_event():
    now = datetime.datetime.now(datetime.timezone.utc)
    e = TaskStatusUpdateEvent(taskId="t1", state=TaskState.WORKING, timestamp=now)
    assert e.task_id == "t1"
    assert e.state == TaskState.WORKING
