"""Tests for agent base class and task store."""

import pytest
from theprotocol.agent import BaseA2AAgent, InMemoryTaskStore, a2a_method
from theprotocol.models import TaskState, Message, TextPart
from theprotocol.exceptions import InvalidStateTransitionError


class SimpleAgent(BaseA2AAgent):
    async def handle_task_send(self, task_id, message):
        return "task-1"

    async def handle_task_get(self, task_id):
        pass

    async def handle_task_cancel(self, task_id):
        return True

    async def handle_subscribe_request(self, task_id):
        yield  # Empty generator


def test_agent_init():
    agent = SimpleAgent()
    assert agent.agent_metadata == {}


def test_agent_with_metadata():
    agent = SimpleAgent(agent_metadata={"model": "gpt-4"})
    assert agent.agent_metadata["model"] == "gpt-4"


@pytest.mark.asyncio
async def test_task_store_create():
    store = InMemoryTaskStore()
    ctx = await store.create_task("t1")
    assert ctx.task_id == "t1"
    assert ctx.current_state == TaskState.SUBMITTED


@pytest.mark.asyncio
async def test_task_store_get():
    store = InMemoryTaskStore()
    await store.create_task("t1")
    ctx = await store.get_task("t1")
    assert ctx is not None
    assert ctx.task_id == "t1"


@pytest.mark.asyncio
async def test_task_store_update():
    store = InMemoryTaskStore()
    await store.create_task("t1")
    ctx = await store.update_task_state("t1", TaskState.WORKING)
    assert ctx is not None
    assert ctx.current_state == TaskState.WORKING


@pytest.mark.asyncio
async def test_task_store_invalid_transition():
    store = InMemoryTaskStore()
    await store.create_task("t1")
    result = await store.update_task_state("t1", TaskState.COMPLETED)
    assert result is None  # SUBMITTED → COMPLETED is not allowed


@pytest.mark.asyncio
async def test_task_store_delete():
    store = InMemoryTaskStore()
    await store.create_task("t1")
    assert await store.delete_task("t1") is True
    assert await store.get_task("t1") is None


def test_a2a_method_decorator():
    class TestAgent(BaseA2AAgent):
        @a2a_method("custom/hello")
        async def hello(self, name: str) -> str:
            return f"Hello {name}"

        async def handle_task_send(self, task_id, message):
            return "t1"
        async def handle_task_get(self, task_id):
            pass
        async def handle_task_cancel(self, task_id):
            return True
        async def handle_subscribe_request(self, task_id):
            yield

    agent = TestAgent()
    assert hasattr(agent.hello, '_a2a_method_name')
    assert agent.hello._a2a_method_name == "custom/hello"
