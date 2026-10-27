"""
MCP (Model Context Protocol) ↔ A2A Bridge.

MCP spec: https://modelcontextprotocol.io (Anthropic)
Wire format: JSON-RPC 2.0 over stdio or Streamable HTTP

Translates MCP tool calls into A2A tasks:
  MCP tools/call → A2A tasks/send (tool name + args become a DataPart)
  A2A Task result → MCP content[] response

This bridge exposes an A2A agent as an MCP tool server,
allowing Claude Desktop or any MCP client to call A2A agents.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from ..models import (
    Message, Task, TaskState, TextPart, DataPart, Artifact,
)
from ..agent.base import BaseA2AAgent
from .base import BaseBridge

logger = logging.getLogger(__name__)


def mcp_tool_call_to_a2a_message(tool_name: str, arguments: Dict) -> Message:
    """Convert an MCP tools/call request into an A2A Message."""
    return Message(
        role="user",
        parts=[DataPart(content={
            "tool": tool_name,
            "arguments": arguments,
        })],
        metadata={"mcp_tool": tool_name},
    )


def a2a_task_to_mcp_content(task: Task) -> List[Dict]:
    """Convert an A2A Task's output to MCP content array."""
    content = []

    # Extract text from assistant messages
    for msg in task.messages:
        if msg.role in ("assistant", "system"):
            for part in msg.parts:
                if hasattr(part, 'content') and isinstance(part.content, str):
                    content.append({"type": "text", "text": part.content})
                elif hasattr(part, 'content') and isinstance(part.content, dict):
                    content.append({"type": "text", "text": json.dumps(part.content, indent=2)})

    # Extract from artifacts
    for artifact in task.artifacts:
        if artifact.content is not None:
            if isinstance(artifact.content, str):
                content.append({"type": "text", "text": artifact.content})
            elif isinstance(artifact.content, dict):
                content.append({"type": "text", "text": json.dumps(artifact.content, indent=2)})
        elif artifact.url is not None:
            content.append({
                "type": "resource",
                "resource": {
                    "uri": str(artifact.url),
                    "mimeType": artifact.media_type or "application/octet-stream",
                },
            })

    # Fallback: if no content extracted, return state info
    if not content:
        content.append({"type": "text", "text": f"Task {task.id}: {task.state.value}"})

    return content


def a2a_card_to_mcp_tools(card: Any, default_tool_name: str = "send_message") -> List[Dict]:
    """Convert A2A AgentCard skills to MCP tool definitions."""
    tools = []
    if hasattr(card, 'skills') and card.skills:
        for skill in card.skills:
            tool = {
                "name": skill.id.replace("/", "_").replace("-", "_"),
                "description": skill.description,
                "inputSchema": skill.input_schema or {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Message to send to the agent"},
                    },
                },
            }
            tools.append(tool)
    else:
        # Default: single tool to send messages
        tools.append({
            "name": default_tool_name,
            "description": f"Send a message to {getattr(card, 'name', 'the agent')}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Your message to the agent"},
                },
                "required": ["message"],
            },
        })
    return tools


class MCPBridge(BaseBridge):
    """
    Bridge that exposes an A2A agent as an MCP tool server.

    Allows MCP clients (Claude Desktop, Claude Code) to call A2A agents
    via standard MCP tools/call requests.
    """

    protocol_name = "mcp"

    def __init__(self, server_name: str = "a2a-agent", server_version: str = "1.0.0"):
        self.server_name = server_name
        self.server_version = server_version

    async def external_to_a2a(self, request: Any) -> Message:
        """Convert MCP tools/call params to A2A Message."""
        tool_name = request.get("name", "unknown")
        arguments = request.get("arguments", {})
        # If there's a simple "message" argument, use it as text
        if "message" in arguments and len(arguments) == 1:
            return Message(role="user", parts=[TextPart(content=arguments["message"])])
        return mcp_tool_call_to_a2a_message(tool_name, arguments)

    async def a2a_to_external(self, task: Task) -> Any:
        """Convert A2A Task to MCP tools/call result."""
        content = a2a_task_to_mcp_content(task)
        is_error = task.state in (TaskState.FAILED, TaskState.CANCELED)
        return {"content": content, "isError": is_error}

    def create_external_router(self, agent: BaseA2AAgent) -> Any:
        """
        Create FastAPI routes implementing MCP Streamable HTTP transport.

        Routes:
          POST /   → MCP JSON-RPC (initialize, tools/list, tools/call)
          GET  /   → MCP SSE keepalive stream
        """
        from fastapi import APIRouter, Request
        from fastapi.responses import JSONResponse, StreamingResponse
        import asyncio

        router = APIRouter(tags=["MCP Bridge"])
        bridge = self

        # Track active tasks for this session
        tasks: Dict[str, str] = {}  # tool_call_id → a2a_task_id

        tools = [{
            "name": "send_message",
            "description": agent.agent_metadata.get("description", "Send a message to this A2A agent"),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Your message"},
                },
                "required": ["message"],
            },
        }]

        @router.post("/")
        async def mcp_post(request: Request):
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})

            if not isinstance(body, dict):
                return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}})

            rid = body.get("id")
            method = body.get("method", "")
            params = body.get("params") or {}

            if method == "initialize":
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": bridge.server_name, "version": bridge.server_version},
                }})

            if method == "ping":
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}})

            if method.startswith("notifications/"):
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {}}) if rid else JSONResponse({})

            if method == "tools/list":
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}})

            if method == "resources/list":
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"resources": []}})

            if method == "prompts/list":
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"prompts": []}})

            if method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})

                a2a_msg = await bridge.external_to_a2a({"name": tool_name, "arguments": arguments})
                task_id = await agent.handle_task_send(task_id=None, message=a2a_msg)

                # Try to get the completed task
                try:
                    task = await agent.handle_task_get(task_id)
                    result = await bridge.a2a_to_external(task)
                except Exception as e:
                    result = {"content": [{"type": "text", "text": f"Task {task_id} created. Error getting result: {e}"}], "isError": False}

                return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})

            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}})

        @router.get("/")
        async def mcp_sse(request: Request):
            async def stream():
                yield f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'notifications/serverInfo', 'params': {'name': bridge.server_name, 'version': bridge.server_version}})}\n\n"
                try:
                    while True:
                        await asyncio.sleep(30)
                        yield "event: ping\ndata: {}\n\n"
                except Exception:
                    pass
            return StreamingResponse(stream(), media_type="text/event-stream", headers={
                "Cache-Control": "no-cache", "Connection": "keep-alive",
            })

        return router
