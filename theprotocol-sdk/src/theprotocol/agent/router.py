"""FastAPI router factory for A2A agents.
Accepts both A2A v1.0 and v0.3 wire formats. Responds in v1.0.

Payment enforcement (f045):
  When the REGISTRY_URL and AGENT_DID env vars are set, a PaymentVerifier is
  automatically injected into the router dependencies. This means every
  SDK-based agent gets payment verification by default when deployed to the
  network.

  - REGISTRY_URL and AGENT_DID set → payment verification ON: a call without a
    valid X-Payment-Token is refused (402)
  - PAYMENT_REQUIRED=false (or payment_required=False) → no PaymentVerifier:
    every call is served and the registry is never asked
  - REGISTRY_URL not set, or AGENT_DID missing → no verification (dev/testing
    mode; a missing AGENT_DID is logged as a warning)
  - A free agent sets PAYMENT_REQUIRED=false: the registry refuses a payment
    authorization whose amount is not greater than zero (400), so a caller
    cannot obtain a token for a price of 0
"""

import json
import inspect
import logging
import os
from typing import Any, Dict, Optional, Union, List, Callable, AsyncGenerator

import pydantic
from pydantic_core import ValidationError
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse, JSONResponse

from .base import BaseA2AAgent
from .task_store import BaseTaskStore, InMemoryTaskStore, TaskContext
from ..models import (
    Message, Task, TaskState, A2AEvent,
    TaskSendParams, TaskSendResult, TaskGetParams, GetTaskResult,
    TaskCancelParams, TaskCancelResult,
    TaskStatusUpdateEvent, TaskMessageEvent, TaskArtifactUpdateEvent,
)
from ..models.v1_compat import (
    method_from_v1, message_from_v1, task_to_v1, sse_event_to_v1,
    state_to_v1,
)
from ..exceptions import AgentServerError, TaskNotFoundError

logger = logging.getLogger(__name__)

# JSON-RPC error codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
JSONRPC_APP_ERROR = -32000
JSONRPC_TASK_NOT_FOUND = -32001


def _jsonrpc_error(req_id: Union[str, int, None], code: int, message: str, data: Optional[Any] = None) -> Dict:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "error": err, "id": req_id}


def _jsonrpc_success(req_id: Union[str, int, None], result: Any) -> Dict:
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


def _format_sse_bytes(event: A2AEvent) -> Optional[bytes]:
    # v1.0 SSE format: field name is the discriminator (statusUpdate, message, artifactUpdate)
    v1_data = sse_event_to_v1(event)
    if v1_data is None:
        return None
    try:
        # Determine event type for SSE event: field
        if "statusUpdate" in v1_data:
            event_type = "status_update"
        elif "message" in v1_data:
            event_type = "message"
        elif "artifactUpdate" in v1_data:
            event_type = "artifact_update"
        else:
            event_type = "event"
        json_str = json.dumps(v1_data)
        return f"event: {event_type}\ndata: {json_str}\n\n".encode("utf-8")
    except Exception:
        return None


async def _sse_wrapper(task_id: str, gen: AsyncGenerator[A2AEvent, None]) -> AsyncGenerator[bytes, None]:
    try:
        async for event in gen:
            data = _format_sse_bytes(event)
            if data:
                yield data
    except TaskNotFoundError as e:
        yield f'event: error\ndata: {json.dumps({"error": "task_not_found", "message": str(e)})}\n\n'.encode()
    except Exception as e:
        yield f'event: error\ndata: {json.dumps({"error": "stream_error", "message": str(e)})}\n\n'.encode()


def create_a2a_router(
    agent: BaseA2AAgent,
    prefix: str = "",
    tags: Optional[List[str]] = None,
    task_store: Optional[BaseTaskStore] = None,
    dependencies: Optional[list] = None,
    payment_required: Optional[bool] = None,
) -> APIRouter:
    """
    Create a FastAPI router that exposes an A2A agent via JSON-RPC 2.0.

    Payment enforcement is automatic when REGISTRY_URL and AGENT_DID are set:
    - REGISTRY_URL → PaymentVerifier injected (agents must receive payment tokens)
    - AGENT_DID → identifies this agent for token target validation (without
      it no PaymentVerifier is injected)
    - PAYMENT_REQUIRED=false → no PaymentVerifier is injected: calls are served
      without a payment token and the registry is not asked
    - TRUSTED_REGISTRIES → comma-separated URLs for cross-registry tokens

    Override with payment_required=False to explicitly disable. To verify a
    token when one is sent without requiring it, pass your own
    `PaymentVerifier(..., required=False)` in `dependencies` with
    payment_required=False.

    Example::

        from theprotocol.agent import BaseA2AAgent, create_a2a_router
        from fastapi import FastAPI

        class MyAgent(BaseA2AAgent):
            async def handle_task_send(self, task_id, message):
                return "task-1"
            ...

        app = FastAPI()
        # Payment verification is automatic if REGISTRY_URL is set
        app.include_router(create_a2a_router(MyAgent()))

        # Explicitly disable payment verification
        app.include_router(create_a2a_router(MyAgent(), payment_required=False))
    """
    if tags is None:
        tags = ["A2A Protocol"]
    if task_store is None:
        task_store = InMemoryTaskStore()
    store = task_store

    # Build dependencies list
    all_deps = list(dependencies or [])

    # Auto-inject PaymentVerifier if REGISTRY_URL is configured
    _registry_url = os.environ.get("REGISTRY_URL", "")
    _agent_did = os.environ.get("AGENT_DID", "")
    _pay_required = payment_required
    if _pay_required is None:
        _pay_required = os.environ.get("PAYMENT_REQUIRED", "true").lower() != "false"

    if _registry_url and _agent_did and _pay_required is not False:
        try:
            from ..payment.verifier import PaymentVerifier
            _trusted_raw = os.environ.get("TRUSTED_REGISTRIES", "")
            _trusted = [u.strip() for u in _trusted_raw.split(",") if u.strip()] if _trusted_raw else None
            _verifier = PaymentVerifier(
                registry_url=_registry_url,
                agent_did=_agent_did,
                required=bool(_pay_required),
                trusted_registries=_trusted,
            )
            all_deps.append(Depends(_verifier))
            logger.info(
                f"[A2A Router] PaymentVerifier auto-injected "
                f"(registry={_registry_url}, did={_agent_did[:30]}, required={_pay_required})"
            )
        except ImportError:
            logger.warning("[A2A Router] PaymentVerifier import failed — payment module not installed")
        except Exception as e:
            logger.warning(f"[A2A Router] PaymentVerifier setup failed: {e}")
    elif _registry_url and not _agent_did:
        logger.warning("[A2A Router] REGISTRY_URL set but AGENT_DID missing — payment verification disabled")

    # f052: Auto-inject A2AAuthenticator if SPIRE socket is available (IRONHAND)
    _spiffe_socket = os.environ.get("SPIFFE_ENDPOINT_SOCKET", "")
    _enable_mtls = os.environ.get("ENABLE_MTLS", "").lower() == "true"
    if _spiffe_socket and _enable_mtls:
        try:
            from ..payment.authenticator import A2AAuthenticator
            _authenticator = A2AAuthenticator(
                payment_verifier=_verifier if "_verifier" in dir() else None,
                required=False,
            )
            all_deps.append(Depends(_authenticator))
            logger.info(
                f"[A2A Router] A2AAuthenticator auto-injected (mTLS enabled, "
                f"socket={_spiffe_socket[:40]})"
            )
        except ImportError:
            logger.warning("[A2A Router] A2AAuthenticator import failed — mTLS module not installed")
        except Exception as e:
            logger.warning(f"[A2A Router] A2AAuthenticator setup failed: {e}")

    router = APIRouter(prefix=prefix, tags=tags, dependencies=all_deps)

    # Discover @a2a_method decorated handlers
    decorated: Dict[str, Callable] = {}
    for name, method in inspect.getmembers(agent, predicate=inspect.iscoroutinefunction):
        if hasattr(method, '_a2a_method_name'):
            decorated[getattr(method, '_a2a_method_name')] = method

    # Register on both the bare prefix and the trailing slash so `POST /a2a`
    # works without a 307 redirect (which drops the POST body for many clients).
    @router.post("", summary="A2A JSON-RPC Endpoint", include_in_schema=False)
    @router.post("/", summary="A2A JSON-RPC Endpoint")
    async def handle_request(request: Request) -> Response:
        req_id = None
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(_jsonrpc_error(None, JSONRPC_PARSE_ERROR, "Parse error"))

        if not isinstance(payload, dict):
            return JSONResponse(_jsonrpc_error(None, JSONRPC_INVALID_REQUEST, "Payload must be JSON object"))

        req_id = payload.get("id")
        raw_method = payload.get("method", "")
        method = method_from_v1(raw_method)  # v1.0 → v0.3 method name translation
        params = payload.get("params") or {}
        if isinstance(params, list):
            params = {}

        # v1.0 compat: if params contain v1.0 part format, translate message
        if "message" in params and isinstance(params["message"], dict):
            msg = params["message"]
            parts = msg.get("parts", [])
            if parts and isinstance(parts[0], dict) and "type" not in parts[0]:
                # v1.0 part format (no type field) — translate to v0.3
                params["message"] = message_from_v1(msg).model_dump(mode="json")

        if payload.get("jsonrpc") != "2.0":
            return JSONResponse(_jsonrpc_error(req_id, JSONRPC_INVALID_REQUEST, "'jsonrpc' must be '2.0'"))
        if not isinstance(method, str) or not method:
            return JSONResponse(_jsonrpc_error(req_id, JSONRPC_INVALID_REQUEST, "'method' is required"))

        try:
            # Check decorated methods first
            if method in decorated:
                handler = decorated[method]
                sig = inspect.signature(handler)
                param_fields: Dict[str, Any] = {}
                for pname, p in sig.parameters.items():
                    if pname in ('self', 'cls'):
                        continue
                    ann = Any if p.annotation is inspect.Parameter.empty else p.annotation
                    default = ... if p.default is inspect.Parameter.empty else p.default
                    param_fields[pname] = (ann, default)

                mapped = dict(params)
                if "task_id" in [p for p in sig.parameters if p not in ('self', 'cls')] and "id" in params:
                    mapped['task_id'] = params['id']

                ParamsModel = pydantic.create_model(f'{handler.__name__}Params', **param_fields)
                validated = ParamsModel.model_validate(mapped).model_dump()
                result = await handler(**validated)
                return JSONResponse(_jsonrpc_success(req_id, result))

            elif method == "tasks/send":
                vp = TaskSendParams.model_validate(params)
                task_id = await agent.handle_task_send(task_id=vp.id, message=vp.message)
                # v1.0: try to return full task with v1.0 state format
                try:
                    task = await agent.handle_task_get(task_id)
                    return JSONResponse(_jsonrpc_success(req_id, task_to_v1(task)))
                except Exception:
                    return JSONResponse(_jsonrpc_success(req_id, {"id": task_id}))

            elif method == "tasks/get":
                vp = TaskGetParams.model_validate(params)
                task = await agent.handle_task_get(task_id=vp.id)
                return JSONResponse(_jsonrpc_success(req_id, task_to_v1(task)))

            elif method == "tasks/cancel":
                vp = TaskCancelParams.model_validate(params)
                ok = await agent.handle_task_cancel(task_id=vp.id)
                result = TaskCancelResult(success=ok).model_dump(mode='json')
                if ok:
                    result["status"] = {"state": state_to_v1(TaskState.CANCELED)}
                return JSONResponse(_jsonrpc_success(req_id, result))

            elif method == "tasks/sendSubscribe":
                task_id = params.get("id", "")
                if not task_id:
                    return JSONResponse(_jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, "'id' is required"))
                gen = agent.handle_subscribe_request(task_id=task_id)
                return StreamingResponse(content=_sse_wrapper(task_id, gen), media_type="text/event-stream")

            else:
                return JSONResponse(_jsonrpc_error(req_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}"))

        except TaskNotFoundError as e:
            return JSONResponse(_jsonrpc_error(req_id, JSONRPC_TASK_NOT_FOUND, str(e)))
        except (ValueError, TypeError, pydantic.ValidationError, ValidationError) as e:
            return JSONResponse(_jsonrpc_error(req_id, JSONRPC_INVALID_PARAMS, f"Invalid parameters: {e}"))
        except AgentServerError as e:
            return JSONResponse(_jsonrpc_error(req_id, JSONRPC_APP_ERROR, f"Agent error: {e}"))
        except Exception as e:
            logger.exception(f"Unhandled error in A2A handler: {e}")
            return JSONResponse(
                _jsonrpc_error(req_id, JSONRPC_INTERNAL_ERROR, f"Internal error: {type(e).__name__}"),
                status_code=500,
            )

    return router
