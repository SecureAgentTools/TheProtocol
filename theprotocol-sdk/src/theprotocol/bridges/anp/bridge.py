"""
ANPBridge — Expose TheProtocol A2A agents via ANP endpoints.

Creates routes for:
  GET  /agent/ad.json          — Agent Description
  GET  /agent/interface.json   — OpenRPC interface
  POST /agent/rpc              — JSON-RPC 2.0 proxy
  GET  /did.json               — DID Document (W3C)
"""

import json
import logging
from typing import Any, Dict, Optional

from ..base import BaseBridge
from ...models import Message, Task, AgentCard
from ...agent.base import BaseA2AAgent
from .did_wba import DIDDocument, KeyPair, create_did_wba, did_wba_from_cos
from .translation import (
    agent_card_to_anp_description,
    agent_card_to_openrpc_interface,
    anp_rpc_to_a2a_message,
    a2a_task_to_anp_response,
)

logger = logging.getLogger(__name__)


class ANPBridge(BaseBridge):
    """
    Bridge between ANP (Agent Network Protocol) and TheProtocol A2A.

    Exposes a TheProtocol agent via ANP-compatible endpoints,
    including DID Document hosting and DIDWba authentication.
    """

    protocol_name = "anp"

    def __init__(
        self,
        agent_did_cos: str,
        keypair: KeyPair,
        agent_card: Optional[AgentCard] = None,
        domain: str = "api.theprotocol.cloud",
    ):
        """
        Args:
            agent_did_cos: The agent's did:cos identifier
            keypair: Ed25519 keypair for DID authentication
            agent_card: Optional AgentCard (used for ad.json generation)
            domain: The domain hosting the agent
        """
        self.agent_did_cos = agent_did_cos
        self.keypair = keypair
        self.domain = domain
        self.did_wba = did_wba_from_cos(agent_did_cos, domain)
        self.agent_card = agent_card
        self.did_document = create_did_wba(agent_did_cos, keypair, domain)

    async def external_to_a2a(self, request: Any) -> Message:
        """Convert ANP JSON-RPC request to A2A Message."""
        method = request.get("method", "")
        params = request.get("params", {})
        return anp_rpc_to_a2a_message(method, params)

    async def a2a_to_external(self, task: Task) -> Any:
        """Convert A2A Task to ANP JSON-RPC response."""
        return a2a_task_to_anp_response(task)

    def create_external_router(self, agent: BaseA2AAgent) -> Any:
        """
        Create FastAPI routes implementing ANP agent endpoints.

        Routes:
          GET  /did.json               — W3C DID Document
          GET  /agent/ad.json          — ANP Agent Description
          GET  /agent/interface.json   — OpenRPC interface definition
          POST /agent/rpc              — JSON-RPC 2.0 execution
        """
        from fastapi import APIRouter, Request
        from fastapi.responses import JSONResponse

        router = APIRouter(tags=["ANP Bridge"])
        bridge = self

        @router.get("/did.json")
        async def did_document():
            """W3C DID Document for this agent."""
            return JSONResponse(
                content=bridge.did_document.to_dict(),
                media_type="application/did+json",
            )

        @router.get("/agent/ad.json")
        async def agent_description():
            """ANP Agent Description."""
            if bridge.agent_card:
                ad = agent_card_to_anp_description(bridge.agent_card, bridge.did_wba)
            else:
                ad = {
                    "protocolType": "ANP",
                    "protocolVersion": "1.0.0",
                    "type": "AgentDescription",
                    "name": agent.__class__.__name__,
                    "did": bridge.did_wba,
                    "description": agent.agent_metadata.get("description", "TheProtocol A2A Agent"),
                    "securityDefinitions": {
                        "didwba_sc": {"scheme": "didwba", "in": "header", "name": "Authorization"}
                    },
                    "security": "didwba_sc",
                    "interfaces": [{
                        "type": "StructuredInterface",
                        "protocol": "JSON-RPC 2.0",
                        "version": "1.0.0",
                        "description": "A2A interface",
                    }],
                }
            return ad

        @router.get("/agent/interface.json")
        async def interface():
            """OpenRPC interface definition."""
            if bridge.agent_card:
                return agent_card_to_openrpc_interface(bridge.agent_card)
            return {
                "openrpc": "1.3.2",
                "info": {"title": agent.__class__.__name__, "version": "1.0.0"},
                "methods": [
                    {"name": "tasks/send", "params": [{"name": "message", "schema": {"type": "object"}}],
                     "result": {"name": "result", "schema": {"type": "object"}}},
                    {"name": "tasks/get", "params": [{"name": "id", "schema": {"type": "string"}}],
                     "result": {"name": "task", "schema": {"type": "object"}}},
                ],
            }

        @router.post("/agent/rpc")
        async def rpc(request: Request):
            """ANP JSON-RPC 2.0 execution endpoint."""
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})

            if not isinstance(body, dict):
                return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}})

            rid = body.get("id")
            method = body.get("method", "")
            params = body.get("params") or {}

            try:
                if method == "tasks/send":
                    a2a_msg = await bridge.external_to_a2a(body)
                    task_id = await agent.handle_task_send(task_id=params.get("id"), message=a2a_msg)
                    try:
                        task = await agent.handle_task_get(task_id)
                        result = await bridge.a2a_to_external(task)
                    except Exception:
                        result = {"task_id": task_id, "state": "submitted"}
                    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})

                elif method == "tasks/get":
                    task_id = params.get("id", "")
                    task = await agent.handle_task_get(task_id)
                    result = await bridge.a2a_to_external(task)
                    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})

                elif method == "tasks/cancel":
                    task_id = params.get("id", "")
                    ok = await agent.handle_task_cancel(task_id)
                    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"success": ok}})

                else:
                    # Try as custom method → wrap into A2A message
                    a2a_msg = await bridge.external_to_a2a(body)
                    task_id = await agent.handle_task_send(task_id=None, message=a2a_msg)
                    try:
                        task = await agent.handle_task_get(task_id)
                        result = await bridge.a2a_to_external(task)
                    except Exception:
                        result = {"task_id": task_id, "state": "submitted"}
                    return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result})

            except Exception as e:
                logger.exception(f"ANP RPC error: {e}")
                return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(e)}})

        return router
