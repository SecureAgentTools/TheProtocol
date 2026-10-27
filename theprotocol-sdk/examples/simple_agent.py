"""
Minimal A2A agent example.

Run: uvicorn simple_agent:app --port 8080
Then register on TheProtocol via MCP: createAgent(name="My Agent", ...)
"""

import uuid
import datetime
from fastapi import FastAPI

from theprotocol.agent import BaseA2AAgent, create_a2a_router
from theprotocol.models import Message, Task, TaskState, TextPart


class EchoAgent(BaseA2AAgent):
    """Simple agent that echoes back whatever you send it."""

    def __init__(self):
        super().__init__(agent_metadata={"name": "Echo Agent"})
        self.tasks = {}

    async def handle_task_send(self, task_id, message):
        tid = task_id or f"task-{uuid.uuid4().hex[:8]}"
        # Echo the first text part
        text = ""
        for part in message.parts:
            if hasattr(part, 'content') and isinstance(part.content, str):
                text = part.content
                break
        self.tasks[tid] = {
            "state": TaskState.COMPLETED,
            "response": f"Echo: {text}",
            "message": message,
        }
        return tid

    async def handle_task_get(self, task_id):
        t = self.tasks.get(task_id)
        if not t:
            raise ValueError(f"Task {task_id} not found")
        now = datetime.datetime.now(datetime.timezone.utc)
        return Task(
            id=task_id,
            state=t["state"],
            createdAt=now,
            updatedAt=now,
            messages=[t["message"]],
        )

    async def handle_task_cancel(self, task_id):
        if task_id in self.tasks:
            self.tasks[task_id]["state"] = TaskState.CANCELED
            return True
        return False

    async def handle_subscribe_request(self, task_id):
        # No streaming for this simple agent
        return
        yield  # Make it a generator


app = FastAPI(title="Echo Agent")
app.include_router(create_a2a_router(EchoAgent()), prefix="/a2a")
