"""
ACP (Agent Communication Protocol) ↔ A2A Bridge.

DEPRECATED: ACP merged into A2A under Linux Foundation (Aug 2025).
BeeAI now speaks A2A natively. Use GoogleA2ABridge for BeeAI agents.
This bridge is preserved for backward compatibility with pre-merger ACP deployments.

ACP spec: https://github.com/i-am-bee/acp (IBM/BeeAI)
Wire format: REST (HTTP + JSON), no JSON-RPC
"""

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from ..models import (
    Message, Task, TaskState, TextPart, DataPart, Artifact, AgentCard,
)
from ..agent.base import BaseA2AAgent
from .base import BaseBridge

logger = logging.getLogger(__name__)

# ACP RunStatus → A2A TaskState
ACP_TO_A2A_STATE = {
    "created": TaskState.SUBMITTED,
    "in-progress": TaskState.WORKING,
    "awaiting": TaskState.INPUT_REQUIRED,
    "completed": TaskState.COMPLETED,
    "failed": TaskState.FAILED,
    "cancelled": TaskState.CANCELED,
    "cancelling": TaskState.WORKING,  # Still working on cancellation
}

# A2A TaskState → ACP RunStatus
A2A_TO_ACP_STATE = {
    TaskState.SUBMITTED: "created",
    TaskState.WORKING: "in-progress",
    TaskState.INPUT_REQUIRED: "awaiting",
    TaskState.COMPLETED: "completed",
    TaskState.FAILED: "failed",
    TaskState.CANCELED: "cancelled",
    TaskState.REJECTED: "failed",       # v1.0: map to ACP failed
    TaskState.AUTH_REQUIRED: "awaiting", # v1.0: map to ACP awaiting
}


def acp_message_to_a2a(acp_msg: Dict) -> Message:
    """Convert an ACP Message to an A2A Message."""
    role = acp_msg.get("role", "user")
    # ACP roles: "user", "agent", "agent/{name}" → A2A roles: "user", "assistant"
    a2a_role = "user" if role == "user" else "assistant"

    parts = []
    for part in acp_msg.get("parts", []):
        content_type = part.get("content_type", "text/plain")
        content = part.get("content", "")
        content_url = part.get("content_url")

        if content_type == "text/plain" or content_type.startswith("text/"):
            parts.append(TextPart(content=content or ""))
        elif content_type == "application/json":
            import json
            try:
                data = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                data = {"raw": content}
            parts.append(DataPart(content=data))
        else:
            # Binary/other content → DataPart with metadata
            parts.append(DataPart(content={
                "content_type": content_type,
                "content": content,
                "content_url": content_url,
            }))

    if not parts:
        parts = [TextPart(content="")]

    return Message(role=a2a_role, parts=parts)


def a2a_message_to_acp(msg: Message) -> Dict:
    """Convert an A2A Message to an ACP Message."""
    role = "user" if msg.role == "user" else "agent"
    parts = []
    for part in msg.parts:
        if hasattr(part, 'content') and isinstance(part.content, str):
            parts.append({
                "content_type": "text/plain",
                "content": part.content,
            })
        elif hasattr(part, 'content') and isinstance(part.content, dict):
            import json
            parts.append({
                "content_type": "application/json",
                "content": json.dumps(part.content),
            })
        elif hasattr(part, 'url'):
            parts.append({
                "content_type": getattr(part, 'media_type', None) or "application/octet-stream",
                "content_url": str(part.url),
            })
    if not parts:
        parts = [{"content_type": "text/plain", "content": ""}]
    return {"role": role, "parts": parts}


def a2a_task_to_acp_run(task: Task) -> Dict:
    """Convert an A2A Task to an ACP Run."""
    output = [a2a_message_to_acp(m) for m in task.messages if m.role == "assistant"]
    return {
        "run_id": task.id,
        "agent_name": task.metadata.get("agent_name", "unknown") if task.metadata else "unknown",
        "status": A2A_TO_ACP_STATE.get(task.state, "in-progress"),
        "output": output,
        "await_request": None,
        "error": None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.updated_at.isoformat() if task.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED) else None,
    }


def a2a_card_to_acp_manifest(card: AgentCard) -> Dict:
    """Convert an A2A AgentCard to an ACP AgentManifest."""
    return {
        "name": card.human_readable_id.replace("/", "-").lower()[:63],
        "description": card.description,
        "input_content_types": ["text/plain", "application/json"],
        "output_content_types": ["text/plain", "application/json"],
        "metadata": {
            "documentation": card.description,
            "tags": [{"name": t} for t in (card.tags or [])],
        },
    }


class ACPBridge(BaseBridge):
    """
    Bidirectional bridge between ACP and A2A protocols.

    Inbound:  ACP client → ACPBridge → A2A agent
    Outbound: A2A client ← ACPBridge ← ACP server (future)
    """

    protocol_name = "acp"

    def __init__(self, task_map: Optional[Dict[str, str]] = None):
        # Maps ACP run_id → A2A task_id (they may differ)
        self._run_to_task: Dict[str, str] = task_map or {}

    async def external_to_a2a(self, request: Any) -> Message:
        """Convert ACP RunCreateRequest input messages to a single A2A Message."""
        inputs = request.get("input", [])
        if not inputs:
            return Message(role="user", parts=[TextPart(content="")])
        # Use the last input message
        return acp_message_to_a2a(inputs[-1])

    async def a2a_to_external(self, task: Task) -> Any:
        """Convert A2A Task to ACP Run response."""
        return a2a_task_to_acp_run(task)

    def create_external_router(self, agent: BaseA2AAgent) -> Any:
        """
        Create FastAPI routes that expose the A2A agent via ACP REST endpoints.

        Routes created:
          GET  /ping          → health check
          GET  /agents        → list agents (returns this agent)
          GET  /agents/{name} → agent manifest
          POST /runs          → create run (→ A2A tasks/send)
          GET  /runs/{run_id} → get run (→ A2A tasks/get)
          POST /runs/{run_id}/cancel → cancel run (→ A2A tasks/cancel)
        """
        from fastapi import APIRouter
        from fastapi.responses import JSONResponse

        router = APIRouter(tags=["ACP Bridge"])
        bridge = self

        @router.get("/ping")
        async def ping():
            return {}

        @router.get("/agents")
        async def list_agents():
            manifest = {
                "name": agent.__class__.__name__.lower(),
                "description": agent.agent_metadata.get("description", "A2A agent exposed via ACP bridge"),
                "input_content_types": ["text/plain", "application/json"],
                "output_content_types": ["text/plain", "application/json"],
            }
            return {"agents": [manifest], "count": 1}

        @router.get("/agents/{name}")
        async def get_agent(name: str):
            return {
                "name": name,
                "description": agent.agent_metadata.get("description", "A2A agent exposed via ACP bridge"),
                "input_content_types": ["text/plain", "application/json"],
                "output_content_types": ["text/plain", "application/json"],
            }

        @router.post("/runs", status_code=202)
        async def create_run(request_body: Dict[str, Any]):
            a2a_message = await bridge.external_to_a2a(request_body)
            task_id = await agent.handle_task_send(task_id=None, message=a2a_message)
            run_id = str(uuid.uuid4())
            bridge._run_to_task[run_id] = task_id
            return {
                "run_id": run_id,
                "agent_name": request_body.get("agent_name", agent.__class__.__name__.lower()),
                "status": "created",
                "output": [],
                "await_request": None,
                "error": None,
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }

        @router.get("/runs/{run_id}")
        async def get_run(run_id: str):
            task_id = bridge._run_to_task.get(run_id, run_id)
            try:
                task = await agent.handle_task_get(task_id)
                return await bridge.a2a_to_external(task)
            except Exception as e:
                return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": str(e)}})

        @router.post("/runs/{run_id}/cancel")
        async def cancel_run(run_id: str):
            task_id = bridge._run_to_task.get(run_id, run_id)
            try:
                await agent.handle_task_cancel(task_id)
                return {"run_id": run_id, "status": "cancelling"}
            except Exception as e:
                return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": str(e)}})

        return router
