"""
Google A2A Protocol ↔ TheProtocol A2A Bridge.

Google A2A spec: https://a2a-protocol.org (Linux Foundation)
Wire format: JSON-RPC 2.0 over HTTP or REST binding

Both protocols are called "A2A" but differ in wire format details:
- Google A2A uses REST paths (/tasks, /tasks/{id}) with different field names
- TheProtocol A2A uses JSON-RPC 2.0 (tasks/send, tasks/get)
- Part format differs (Google uses unified Part, ours uses TextPart/DataPart/FilePart)
- State enum values differ (Google: lowercase with hyphens, ours: UPPERCASE)

This bridge translates Google A2A REST → TheProtocol A2A JSON-RPC.
"""

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from ..models import (
    Message, Task, TaskState, TextPart, DataPart, FilePart, Artifact,
)
from ..agent.base import BaseA2AAgent
from .base import BaseBridge

logger = logging.getLogger(__name__)

# Google A2A REST binding state (lowercase-hyphen) → internal TaskState (v1.0)
GOOGLE_TO_TP_STATE = {
    "submitted": TaskState.SUBMITTED,
    "working": TaskState.WORKING,
    "completed": TaskState.COMPLETED,
    "failed": TaskState.FAILED,
    "canceled": TaskState.CANCELED,
    "input-required": TaskState.INPUT_REQUIRED,
    "rejected": TaskState.REJECTED,
    "auth-required": TaskState.AUTH_REQUIRED,
}

TP_TO_GOOGLE_STATE = {
    TaskState.SUBMITTED: "submitted",
    TaskState.WORKING: "working",
    TaskState.COMPLETED: "completed",
    TaskState.FAILED: "failed",
    TaskState.CANCELED: "canceled",
    TaskState.INPUT_REQUIRED: "input-required",
    TaskState.REJECTED: "rejected",
    TaskState.AUTH_REQUIRED: "auth-required",
}


def google_part_to_tp_part(gpart: Dict) -> Any:
    """Convert a Google A2A Part (unified) to a TheProtocol Part (typed)."""
    if gpart.get("text") is not None:
        return TextPart(content=gpart["text"])
    elif gpart.get("data") is not None:
        return DataPart(content=gpart["data"] if isinstance(gpart["data"], dict) else {"value": gpart["data"]})
    elif gpart.get("url") is not None:
        return FilePart(
            url=gpart["url"],
            mediaType=gpart.get("media_type"),
            filename=gpart.get("filename"),
        )
    elif gpart.get("raw") is not None:
        return DataPart(content={"raw_base64": gpart["raw"], "media_type": gpart.get("media_type")})
    else:
        return TextPart(content="")


def tp_part_to_google_part(part: Any) -> Dict:
    """Convert a TheProtocol Part to a Google A2A Part."""
    if hasattr(part, 'content') and isinstance(part.content, str):
        return {"text": part.content}
    elif hasattr(part, 'content') and isinstance(part.content, dict):
        return {"data": part.content, "media_type": "application/json"}
    elif hasattr(part, 'url'):
        return {
            "url": str(part.url),
            "media_type": getattr(part, 'media_type', None),
            "filename": getattr(part, 'filename', None),
        }
    return {"text": ""}


def google_message_to_tp(gmsg: Dict) -> Message:
    """Convert Google A2A Message to TheProtocol Message."""
    role = gmsg.get("role", "user")
    # Google roles: "user", "agent" → TP roles: "user", "agent"
    tp_role = "user" if role == "user" else "agent"
    parts = [google_part_to_tp_part(p) for p in gmsg.get("parts", [])]
    if not parts:
        parts = [TextPart(content="")]
    metadata = gmsg.get("metadata")
    return Message(role=tp_role, parts=parts, metadata=metadata)


def tp_message_to_google(msg: Message) -> Dict:
    """Convert TheProtocol Message to Google A2A Message."""
    role = "user" if msg.role == "user" else "agent"  # v1.0: "agent" (not "assistant")
    return {
        "message_id": str(uuid.uuid4()),
        "role": role,
        "parts": [tp_part_to_google_part(p) for p in msg.parts],
        "metadata": msg.metadata,
    }


def tp_task_to_google_task(task: Task) -> Dict:
    """Convert TheProtocol Task to Google A2A Task."""
    return {
        "id": task.id,
        "status": {
            "state": TP_TO_GOOGLE_STATE.get(task.state, "working"),
            "timestamp": task.updated_at.isoformat() if task.updated_at else None,
        },
        "history": [tp_message_to_google(m) for m in task.messages],
        "artifacts": [
            {
                "artifact_id": a.id,
                "name": a.type,
                "parts": [{"text": str(a.content)}] if a.content else [{"url": str(a.url)}] if a.url else [],
            }
            for a in task.artifacts
        ],
        "metadata": task.metadata,
    }


class GoogleA2ABridge(BaseBridge):
    """
    Bridge between Google A2A (REST binding) and TheProtocol A2A (JSON-RPC).

    Exposes a TheProtocol agent via Google A2A REST endpoints.
    """

    protocol_name = "google-a2a"

    async def external_to_a2a(self, request: Any) -> Message:
        """Convert Google A2A SendMessageRequest to TheProtocol Message."""
        gmsg = request.get("message", {})
        return google_message_to_tp(gmsg)

    async def a2a_to_external(self, task: Task) -> Any:
        """Convert TheProtocol Task to Google A2A Task."""
        return tp_task_to_google_task(task)

    def create_external_router(self, agent: BaseA2AAgent) -> Any:
        """
        Create FastAPI routes matching Google A2A REST binding.

        Routes:
          POST /tasks              → SendMessage (→ A2A tasks/send)
          GET  /tasks/{id}         → GetTask (→ A2A tasks/get)
          POST /tasks/{id}:cancel  → CancelTask (→ A2A tasks/cancel)
        """
        from fastapi import APIRouter
        from fastapi.responses import JSONResponse

        router = APIRouter(tags=["Google A2A Bridge"])
        bridge = self

        @router.post("/tasks")
        async def send_message(request_body: Dict[str, Any]):
            a2a_message = await bridge.external_to_a2a(request_body)
            task_id = await agent.handle_task_send(task_id=None, message=a2a_message)
            try:
                task = await agent.handle_task_get(task_id)
                return tp_task_to_google_task(task)
            except Exception:
                # Return minimal task if get fails
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                return {
                    "id": task_id,
                    "status": {"state": "submitted", "timestamp": now},
                    "history": [tp_message_to_google(a2a_message)],
                    "artifacts": [],
                }

        @router.get("/tasks/{task_id}")
        async def get_task(task_id: str):
            try:
                task = await agent.handle_task_get(task_id)
                return tp_task_to_google_task(task)
            except Exception as e:
                return JSONResponse(status_code=404, content={"error": str(e)})

        @router.post("/tasks/{task_id}:cancel")
        async def cancel_task(task_id: str):
            try:
                ok = await agent.handle_task_cancel(task_id)
                return {"id": task_id, "status": {"state": "canceled" if ok else "failed"}}
            except Exception as e:
                return JSONResponse(status_code=404, content={"error": str(e)})

        return router
