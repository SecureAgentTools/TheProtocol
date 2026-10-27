"""
ANP ↔ A2A Translation — Convert between ANP and TheProtocol message formats.

ANP uses:
  - Agent Description (ad.json) for agent metadata
  - OpenRPC interface.json for method definitions
  - JSON-RPC 2.0 for method calls

TheProtocol uses:
  - AgentCard for agent metadata
  - A2A Message/Task for communication
"""

import datetime
import json
from typing import Any, Dict, List, Optional

from ...models import (
    Message, Task, TaskState, TextPart, DataPart, Artifact,
    AgentCard, AgentProvider, AgentCapabilities, AgentAuthentication, AgentSkill,
)


def agent_card_to_anp_description(card: AgentCard, did_wba: str) -> Dict[str, Any]:
    """
    Convert a TheProtocol AgentCard to an ANP Agent Description (ad.json).
    """
    return {
        "protocolType": "ANP",
        "protocolVersion": "1.0.0",
        "type": "AgentDescription",
        "name": card.name,
        "did": did_wba,
        "url": str(card.url),
        "owner": {
            "type": "Organization",
            "name": card.provider.name,
            "url": str(card.provider.url) if card.provider.url else None,
        },
        "description": card.description,
        "created": card.last_updated or datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "securityDefinitions": {
            "didwba_sc": {
                "scheme": "didwba",
                "in": "header",
                "name": "Authorization",
            }
        },
        "security": "didwba_sc",
        "interfaces": [
            {
                "type": "StructuredInterface",
                "protocol": "JSON-RPC 2.0",
                "version": "1.0.0",
                "url": str(card.url).rstrip("/") + "/interface.json",
                "description": f"A2A interface for {card.name}",
            }
        ],
    }


def agent_card_to_openrpc_interface(card: AgentCard) -> Dict[str, Any]:
    """
    Convert AgentCard skills to an OpenRPC interface.json document.
    """
    methods = [
        {
            "name": "tasks/send",
            "description": "Send a message to the agent to initiate or continue a task",
            "params": [
                {"name": "id", "schema": {"type": "string"}, "description": "Task ID (null for new task)"},
                {"name": "message", "schema": {"type": "object"}, "description": "A2A Message object"},
            ],
            "result": {"name": "result", "schema": {"type": "object"}},
        },
        {
            "name": "tasks/get",
            "description": "Get the current state of a task",
            "params": [{"name": "id", "schema": {"type": "string"}, "description": "Task ID"}],
            "result": {"name": "task", "schema": {"type": "object"}},
        },
        {
            "name": "tasks/cancel",
            "description": "Cancel an active task",
            "params": [{"name": "id", "schema": {"type": "string"}, "description": "Task ID"}],
            "result": {"name": "result", "schema": {"type": "object"}},
        },
    ]

    # Add skills as custom methods
    if card.skills:
        for skill in card.skills:
            methods.append({
                "name": f"skills/{skill.id}",
                "description": skill.description,
                "params": [
                    {"name": "input", "schema": skill.input_schema or {"type": "object"}},
                ],
                "result": {"name": "output", "schema": skill.output_schema or {"type": "object"}},
            })

    return {
        "openrpc": "1.3.2",
        "info": {
            "title": f"{card.name} API",
            "version": card.agent_version,
            "description": card.description,
        },
        "methods": methods,
    }


def anp_description_to_agent_card(ad: Dict[str, Any]) -> AgentCard:
    """
    Convert an ANP Agent Description (ad.json) to a TheProtocol AgentCard.
    """
    owner = ad.get("owner", {})
    interfaces = ad.get("interfaces", [])
    url = ad.get("url", "")
    if interfaces:
        url = interfaces[0].get("url", url)

    return AgentCard(
        protocolVersion="0.3.0",
        humanReadableId=ad.get("did", "").replace("did:wba:", "").replace(":", "/"),
        agentVersion=ad.get("protocolVersion", "1.0.0"),
        name=ad.get("name", "Unknown ANP Agent"),
        description=ad.get("description", ""),
        url=url or "https://example.com",
        provider=AgentProvider(
            name=owner.get("name", "Unknown"),
            url=owner.get("url"),
        ),
        capabilities=AgentCapabilities(streaming=False),
        authSchemes=[AgentAuthentication(scheme="none")],
        tags=["anp"],
    )


def anp_rpc_to_a2a_message(method: str, params: Dict) -> Message:
    """Convert an ANP JSON-RPC call to an A2A Message."""
    # ANP uses JSON-RPC 2.0 — params can be anything
    if method == "tasks/send":
        msg_data = params.get("message")
        if isinstance(msg_data, dict):
            role = msg_data.get("role", "user")
            parts = []
            for p in msg_data.get("parts", []):
                if isinstance(p, dict):
                    if "text" in p:
                        parts.append(TextPart(content=p["text"]))
                    elif "data" in p:
                        parts.append(DataPart(content=p["data"]))
                    else:
                        parts.append(DataPart(content=p))
            if not parts:
                parts = [TextPart(content=json.dumps(params))]
            return Message(role="user" if role == "user" else "assistant", parts=parts)

    # Generic: wrap the entire params as a DataPart
    return Message(
        role="user",
        parts=[DataPart(content={"anp_method": method, "params": params})],
        metadata={"anp_method": method},
    )


def a2a_task_to_anp_response(task: Task) -> Dict[str, Any]:
    """Convert an A2A Task to an ANP JSON-RPC result."""
    messages = []
    for msg in task.messages:
        parts = []
        for p in msg.parts:
            if hasattr(p, 'content') and isinstance(p.content, str):
                parts.append({"text": p.content})
            elif hasattr(p, 'content') and isinstance(p.content, dict):
                parts.append({"data": p.content})
        messages.append({"role": msg.role, "parts": parts})

    return {
        "task_id": task.id,
        "state": task.state.value.lower(),
        "messages": messages,
        "artifacts": [
            {"id": a.id, "type": a.type, "content": a.content}
            for a in task.artifacts
        ],
    }
