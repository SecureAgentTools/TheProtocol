"""
Minimal TheProtocol Agent — A2A v1.0 with automatic payment verification.

This is your starting point. Edit handle_task_send() to add your agent's logic.
The SDK handles: A2A protocol, payment tokens, auth, and streaming.
"""
import os
from fastapi import FastAPI
from theprotocol.agent import BaseA2AAgent, create_a2a_router

AGENT_NAME = os.getenv("AGENT_NAME", "My Agent")


class MyAgent(BaseA2AAgent):
    """Your agent. Implement handle_task_send with your logic."""

    async def handle_task_send(self, task_id, message):
        """Called when someone sends an A2A task to your agent.

        Args:
            task_id: Unique task ID (auto-generated if None)
            message: The message with parts (text + data)

        Returns:
            task_id string — the SDK handles the JSON-RPC response.
        """
        # Extract text from message parts
        text = ""
        data = {}
        for part in (message.parts if hasattr(message, "parts") else []):
            if hasattr(part, "text") and part.text:
                text = part.text
            if hasattr(part, "data") and part.data:
                data = part.data

        # --- YOUR LOGIC HERE ---
        # Example: echo the input back
        result = {
            "message": f"Hello from {AGENT_NAME}! You said: {text}",
            "input_data": data,
        }

        # Store result as task artifact
        self._tasks[task_id] = {
            "state": "TASK_STATE_COMPLETED",
            "artifacts": [{"type": "application/json", "name": "result", "data": result}],
        }
        return task_id

    async def handle_task_get(self, task_id):
        """Return task status. The SDK calls this for polling."""
        task = self._tasks.get(task_id, {"state": "TASK_STATE_FAILED", "error": "Task not found"})
        from theprotocol.models import Task, TaskState
        return Task(id=task_id, state=TaskState(task.get("state", "TASK_STATE_FAILED")))

    async def handle_task_cancel(self, task_id):
        return True

    def __init__(self):
        self._tasks = {}


# Create app with automatic payment verification
# Set REGISTRY_URL + AGENT_DID env vars to enable payment enforcement
app = FastAPI(title=AGENT_NAME)
agent = MyAgent()
app.include_router(create_a2a_router(agent), prefix="/a2a")


@app.get("/health")
async def health():
    return {
        "status": "operational",
        "agent": AGENT_NAME,
        "did": os.getenv("AGENT_DID", "not set"),
        "payment_required": os.getenv("PAYMENT_REQUIRED", "true"),
    }
