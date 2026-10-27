"""
A2A v0.3 Backward Compatibility Layer.

Internal models are now native v1.0.
This module translates v0.3 wire format INPUT to v1.0 internal types,
so old clients (tasks/send, {type:"text"}, COMPLETED) still work.
"""

import json
from typing import Any, Dict, List, Optional, Union
from .a2a_protocol import (
    TaskState, Message, TextPart, FilePart, DataPart, Part,
    Task, Artifact, TaskStatusUpdateEvent, TaskMessageEvent, TaskArtifactUpdateEvent,
)

# ─── State Translation ──────────────────────────────────────────────────────

# Accept both v1.0 and v0.3 state strings → internal TaskState (now v1.0 native)
STATE_STRING_TO_INTERNAL: Dict[str, TaskState] = {
    # v1.0 values (native)
    "TASK_STATE_SUBMITTED": TaskState.SUBMITTED,
    "TASK_STATE_WORKING": TaskState.WORKING,
    "TASK_STATE_INPUT_REQUIRED": TaskState.INPUT_REQUIRED,
    "TASK_STATE_COMPLETED": TaskState.COMPLETED,
    "TASK_STATE_FAILED": TaskState.FAILED,
    "TASK_STATE_CANCELED": TaskState.CANCELED,
    "TASK_STATE_REJECTED": TaskState.REJECTED,
    "TASK_STATE_AUTH_REQUIRED": TaskState.AUTH_REQUIRED,
    # v0.3 values (backward compat)
    "SUBMITTED": TaskState.SUBMITTED,
    "WORKING": TaskState.WORKING,
    "INPUT_REQUIRED": TaskState.INPUT_REQUIRED,
    "COMPLETED": TaskState.COMPLETED,
    "FAILED": TaskState.FAILED,
    "CANCELED": TaskState.CANCELED,
    "REJECTED": TaskState.REJECTED,
    "AUTH_REQUIRED": TaskState.AUTH_REQUIRED,
}


def state_from_v1(v1_state: str) -> TaskState:
    """Convert any state string (v0.3 or v1.0) to internal TaskState."""
    return STATE_STRING_TO_INTERNAL.get(v1_state, TaskState.WORKING)


def state_to_v1(state: TaskState) -> str:
    """Return the v1.0 wire value (TaskState is already v1.0 native)."""
    return state.value


# ─── Role Translation ───────────────────────────────────────────────────────

# Accept all role variants → internal v1.0 role (user/agent)
ROLE_TO_INTERNAL = {"user": "user", "agent": "agent", "assistant": "agent", "ROLE_USER": "user", "ROLE_AGENT": "agent", "system": "user", "tool": "user"}
INTERNAL_ROLE_TO_WIRE = {"user": "user", "agent": "agent", "assistant": "agent"}


def role_from_v1(v1_role: str) -> str:
    """Convert any role string (v0.3 or v1.0) to internal v1.0 role."""
    return ROLE_TO_INTERNAL.get(v1_role, "user")


def role_to_v1(role: str) -> str:
    """Return v1.0 wire role."""
    return INTERNAL_ROLE_TO_WIRE.get(role, "user")


# ─── Part Translation ────────────────────────────────────────────────────────

def part_from_v1(v1_part: Dict[str, Any]) -> Part:
    """Convert v1.0 unified Part to internal typed Part.

    Per A2A v1.0 §4.7, Parts use a ``kind`` discriminator field:
      {"kind": "text", "text": "hello"}
      {"kind": "file", "file": {"url": "...", "mediaType": "..."}}
      {"kind": "data", "data": {...}}

    Also accepts legacy presence-of-field shape (Google A2A SDK style) and
    v0.3 ``type`` field for backwards compatibility:
      v1.0 alt: {"text": "hello"} | {"url": "..."} | {"data": {...}}
      v0.3:     {"type": "text", "content": "hello"} | ...

    Q-C W3 (2026-05-12): explicit ``kind`` recognition added per Commander Q9
    + A2A v1.0 §4.7 alignment.
    """
    # A2A v1.0 §4.7 — explicit `kind` discriminator
    kind = v1_part.get("kind")
    if kind == "text":
        return TextPart(content=v1_part.get("text", ""))
    elif kind == "file":
        file_obj = v1_part.get("file") or {}
        if isinstance(file_obj, dict):
            # FilePart uses `mediaType` alias (pydantic v2 requires alias on construct).
            return FilePart(
                url=file_obj.get("url") or v1_part.get("url", ""),
                mediaType=file_obj.get("mediaType") or file_obj.get("media_type"),
                filename=file_obj.get("name") or file_obj.get("filename") or v1_part.get("filename"),
            )
        return FilePart(
            url=v1_part.get("url", ""),
            mediaType=v1_part.get("mediaType") or v1_part.get("media_type"),
            filename=v1_part.get("filename"),
        )
    elif kind == "data":
        data = v1_part.get("data") or {}
        if not isinstance(data, dict):
            data = {"value": data}
        return DataPart(
            content=data,
            mediaType=v1_part.get("media_type") or v1_part.get("mediaType") or "application/json",
        )

    # v1.0 legacy presence-of-field shape (Google A2A SDK style)
    if "text" in v1_part:
        return TextPart(content=v1_part["text"])
    elif "url" in v1_part:
        return FilePart(
            url=v1_part["url"],
            media_type=v1_part.get("media_type") or v1_part.get("mediaType"),
            filename=v1_part.get("filename"),
        )
    elif "data" in v1_part:
        data = v1_part["data"]
        if not isinstance(data, dict):
            data = {"value": data}
        return DataPart(
            content=data,
            media_type=v1_part.get("media_type") or v1_part.get("mediaType") or "application/json",
        )
    elif "raw" in v1_part:
        # v1.0 raw bytes → store as DataPart with base64
        return DataPart(
            content={"raw_base64": v1_part["raw"], "media_type": v1_part.get("media_type")},
            media_type=v1_part.get("media_type") or "application/octet-stream",
        )
    # Fallback: v0.3 ``type`` field
    elif "type" in v1_part:
        ptype = v1_part["type"]
        if ptype == "text":
            return TextPart(content=v1_part.get("content", ""))
        elif ptype == "file":
            return FilePart(
                url=v1_part.get("url", ""),
                media_type=v1_part.get("mediaType") or v1_part.get("media_type"),
                filename=v1_part.get("filename"),
            )
        elif ptype == "data":
            return DataPart(
                content=v1_part.get("content", {}),
                media_type=v1_part.get("mediaType") or v1_part.get("media_type") or "application/json",
            )
    return TextPart(content="")


def part_to_v1(part: Part, *, kind_discriminator: bool = False) -> Dict[str, Any]:
    """Convert internal typed Part to v1.0 unified Part.

    Default: presence-of-field shape (matches existing wire callers + Google A2A SDK).
    When ``kind_discriminator=True``: emit canonical A2A v1.0 §4.7 shape with
    explicit ``kind`` field. Q-C W3 (2026-05-12) per Commander Q9.
    """
    if isinstance(part, TextPart):
        if kind_discriminator:
            return {"kind": "text", "text": part.content}
        return {"text": part.content}
    elif isinstance(part, FilePart):
        if kind_discriminator:
            file_obj: Dict[str, Any] = {"url": str(part.url)}
            if part.media_type:
                file_obj["mediaType"] = part.media_type
            if part.filename:
                file_obj["name"] = part.filename
            return {"kind": "file", "file": file_obj}
        r: Dict[str, Any] = {"url": str(part.url)}
        if part.media_type:
            r["media_type"] = part.media_type
        if part.filename:
            r["filename"] = part.filename
        return r
    elif isinstance(part, DataPart):
        if kind_discriminator:
            out: Dict[str, Any] = {"kind": "data", "data": part.content}
            if part.media_type and part.media_type != "application/json":
                out["media_type"] = part.media_type
            return out
        r = {"data": part.content}
        if part.media_type and part.media_type != "application/json":
            r["media_type"] = part.media_type
        return r
    if kind_discriminator:
        return {"kind": "text", "text": ""}
    return {"text": ""}


# ─── Message Translation ────────────────────────────────────────────────────

def message_from_v1(v1_msg: Dict[str, Any]) -> Message:
    """Convert v1.0 message to internal Message."""
    role = role_from_v1(v1_msg.get("role", "user"))
    parts_raw = v1_msg.get("parts", [])
    parts = [part_from_v1(p) for p in parts_raw] if parts_raw else [TextPart(content="")]
    return Message(role=role, parts=parts, metadata=v1_msg.get("metadata"))


def message_to_v1(msg: Message) -> Dict[str, Any]:
    """Convert internal Message to v1.0 wire format."""
    return {
        "role": role_to_v1(msg.role),
        "parts": [part_to_v1(p) for p in msg.parts],
        "metadata": msg.metadata,
    }


# ─── Task Translation ───────────────────────────────────────────────────────

def artifact_parts_to_v1(a: Artifact) -> List[Dict[str, Any]]:
    """Serialize an artifact's content as v1.0 parts WITHOUT lossy ``str()``.

    A dict becomes a DataPart (``{"data": {...}}``) so structured payloads
    survive round-trip; a string becomes a TextPart; any other JSON value is
    JSON-encoded (never a Python ``repr``); a URL-only artifact emits a url part.
    """
    c = a.content
    if c is not None:
        if isinstance(c, dict):
            return [part_to_v1(DataPart(content=c))]
        if isinstance(c, str):
            return [part_to_v1(TextPart(content=c))]
        try:
            return [part_to_v1(TextPart(content=json.dumps(c)))]
        except (TypeError, ValueError):
            return [part_to_v1(TextPart(content=str(c)))]
    if a.url:
        return [{"url": str(a.url)}]
    return []


def task_to_v1(task: Task) -> Dict[str, Any]:
    """Convert internal Task to v1.0 wire format."""
    return {
        "id": task.id,
        "status": {
            "state": state_to_v1(task.state),
            "timestamp": task.updated_at.isoformat() if task.updated_at else None,
        },
        "history": [message_to_v1(m) for m in task.messages],
        "artifacts": [
            {
                "artifactId": a.id,
                "artifact_id": a.id,  # back-compat alias for v0.3 consumers
                "name": a.type,
                "parts": artifact_parts_to_v1(a),
                "metadata": a.metadata,
            }
            for a in task.artifacts
        ],
        "metadata": task.metadata,
    }


# ─── SSE Event Translation ──────────────────────────────────────────────────

def sse_event_to_v1(event: Any) -> Optional[Dict[str, Any]]:
    """Convert internal SSE event to v1.0 StreamResponse format."""
    if isinstance(event, TaskStatusUpdateEvent):
        return {
            "statusUpdate": {
                "taskId": event.task_id,
                "status": {
                    "state": state_to_v1(event.state),
                    "timestamp": event.timestamp.isoformat(),
                    "message": event.message,
                },
            }
        }
    elif isinstance(event, TaskMessageEvent):
        return {
            "message": message_to_v1(event.message),
        }
    elif isinstance(event, TaskArtifactUpdateEvent):
        return {
            "artifactUpdate": {
                "taskId": event.task_id,
                "artifact": {
                    "artifactId": event.artifact.id,
                    "artifact_id": event.artifact.id,
                    "name": event.artifact.type,
                    "parts": artifact_parts_to_v1(event.artifact),
                },
                "lastChunk": True,
            }
        }
    return None


# ─── Method Name Translation ─────────────────────────────────────────────────

# v1.0 method → v0.3 method
V1_METHOD_TO_INTERNAL = {
    "message/send": "tasks/send",
    "message/stream": "tasks/sendSubscribe",
    "tasks/get": "tasks/get",
    "tasks/cancel": "tasks/cancel",
    # v0.3 names pass through
    "tasks/send": "tasks/send",
    "tasks/sendSubscribe": "tasks/sendSubscribe",
}


def method_from_v1(method: str) -> str:
    """Convert v1.0 method name to internal v0.3 method name."""
    return V1_METHOD_TO_INTERNAL.get(method, method)


# ─── A2A v1.0 §4.5 SecurityScheme Translation ────────────────────────────────
# Q-C W3 (2026-05-12): SDK-side mirror of the backend `services.a2a_v1.compat`
# helpers. Used by SDK consumers building or consuming AgentCards on the wire.


def security_schemes_from_v03_auth_schemes(
    auth_schemes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Translate v0.3 ``authSchemes[]`` → v1.0 ``securitySchemes{}`` + ``security[]``.

    Returns: ``{"securitySchemes": {<name>: {...}, ...}, "security": [{<name>: []}, ...]}``

    Mapping (mirrors agentvault_registry.services.a2a_v1.compat):
      v0.3 {"scheme": "oauth2", "tokenUrl": ...}
           → securitySchemes["oauth2_agent_jwt"] (OAuth2, clientCredentials flow)
      v0.3 {"scheme": "apiKey", "name": ...}
           → securitySchemes["api_key"] (APIKey, in=header)
      v0.3 {"scheme": "bearer"}
           → securitySchemes["bearer"] (HTTPAuth bearer/JWT)
      v0.3 {"scheme": "mtls"} or {"scheme": "mutualTLS"}
           → securitySchemes["mtls"] (MutualTls — A2A v1.0 §4.5.6 native)
      v0.3 {"scheme": "none"}
           → empty maps (no auth required)
    """
    schemes: Dict[str, Any] = {}
    security: List[Dict[str, List[str]]] = []

    for entry in auth_schemes or []:
        if not isinstance(entry, dict):
            continue
        scheme_kind = (entry.get("scheme") or "").strip().lower()
        if scheme_kind == "none" or not scheme_kind:
            continue

        if scheme_kind == "oauth2":
            name = "oauth2_agent_jwt"
            token_url = entry.get("tokenUrl") or entry.get("token_url") or ""
            schemes[name] = {
                "type": "oauth2",
                "flows": {
                    "clientCredentials": {"tokenUrl": token_url, "scopes": {}},
                },
                "description": "Agent JWT via OAuth2 client-credentials grant",
            }
            security.append({name: []})

        elif scheme_kind == "apikey":
            name = "api_key"
            header_name = entry.get("name") or "X-Api-Key"
            schemes[name] = {
                "type": "apiKey",
                "in": "header",
                "name": header_name,
                "description": "API key in HTTP header",
            }
            security.append({name: []})

        elif scheme_kind == "bearer":
            name = "bearer"
            schemes[name] = {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Authorization: Bearer <jwt>",
            }
            security.append({name: []})

        elif scheme_kind in ("mtls", "mutualtls"):
            name = "mtls"
            schemes[name] = {
                "type": "mutualTLS",
                "description": "SPIFFE x509 SVID via mutual TLS (IRONHAND)",
            }
            security.append({name: []})

        else:
            # Unknown scheme — preserve as apiKey-shaped fallback so downstream
            # validators don't reject the card.
            name = scheme_kind or "custom"
            schemes[name] = {
                "type": "apiKey",
                "in": "header",
                "name": entry.get("name") or "X-Auth",
                "description": f"Legacy v0.3 scheme: {scheme_kind}",
            }
            security.append({name: []})

    return {"securitySchemes": schemes, "security": security}


def security_schemes_to_v03_auth_schemes(
    security_schemes: Dict[str, Any],
    security: Optional[List[Dict[str, List[str]]]] = None,
) -> List[Dict[str, Any]]:
    """Translate v1.0 ``securitySchemes{}`` → v0.3 ``authSchemes[]`` (lossy reverse).

    For emit to strict-v0.3 federation peers (Q10 signoff). Drops OAuth2 flow
    detail beyond clientCredentials tokenUrl; preserves only what v0.3 vocabulary
    expressed natively.
    """
    if not security_schemes:
        return [{"scheme": "none", "scopes": None, "tokenUrl": None, "description": None, "service_identifier": None}]

    # If `security` requirement is provided, prefer to project only those schemes
    required_names: Optional[List[str]] = None
    if security:
        required_names = []
        for req in security:
            if isinstance(req, dict):
                required_names.extend(req.keys())

    out: List[Dict[str, Any]] = []
    for name, scheme in security_schemes.items():
        if required_names is not None and name not in required_names:
            continue
        if not isinstance(scheme, dict):
            continue
        scheme_type = (scheme.get("type") or "").strip().lower()

        if scheme_type == "oauth2":
            flows = scheme.get("flows") or {}
            cc = flows.get("clientCredentials") or {}
            out.append({
                "scheme": "oauth2",
                "scopes": list((cc.get("scopes") or {}).keys()) or None,
                "tokenUrl": cc.get("tokenUrl"),
                "description": scheme.get("description"),
                "service_identifier": None,
            })
        elif scheme_type == "apikey":
            out.append({
                "scheme": "apiKey",
                "scopes": None,
                "tokenUrl": None,
                "description": scheme.get("description"),
                "service_identifier": scheme.get("name"),
            })
        elif scheme_type == "http":
            http_scheme = (scheme.get("scheme") or "bearer").lower()
            out.append({
                "scheme": "bearer" if http_scheme == "bearer" else http_scheme,
                "scopes": None,
                "tokenUrl": None,
                "description": scheme.get("description"),
                "service_identifier": None,
            })
        elif scheme_type == "mutualtls":
            out.append({
                "scheme": "mtls",
                "scopes": None,
                "tokenUrl": None,
                "description": scheme.get("description"),
                "service_identifier": None,
            })
        elif scheme_type == "openidconnect":
            out.append({
                "scheme": "oauth2",
                "scopes": None,
                "tokenUrl": scheme.get("openIdConnectUrl"),
                "description": scheme.get("description"),
                "service_identifier": None,
            })

    if not out:
        out = [{"scheme": "none", "scopes": None, "tokenUrl": None, "description": None, "service_identifier": None}]
    return out


def agent_card_to_v03(card: Dict[str, Any]) -> Dict[str, Any]:
    """Render an internal/v1.0 AgentCard dict as a strict-v0.3 wire card.

    Strips v1.0-only fields (``supportedInterfaces``, ``securitySchemes``,
    ``security``, ``extensions``, ``capabilities.extendedAgentCard``) and rebuilds
    v0.3 fallback fields where missing. Used for outbound federation to
    v0.3-only peers (Q10 signoff).
    """
    if not isinstance(card, dict):
        return card
    result = dict(card)

    # 1. Synthesize authSchemes from securitySchemes if v0.3 missing
    if "authSchemes" not in result and "securitySchemes" in result:
        result["authSchemes"] = security_schemes_to_v03_auth_schemes(
            result.get("securitySchemes") or {},
            result.get("security") or [],
        )

    # 2. Synthesize url/preferredTransport from supportedInterfaces[0] if missing
    if "url" not in result and result.get("supportedInterfaces"):
        first = result["supportedInterfaces"][0] if isinstance(result["supportedInterfaces"], list) else None
        if isinstance(first, dict):
            result["url"] = first.get("url", "")
            result.setdefault("preferredTransport", first.get("protocolBinding") or "JSONRPC")

    # 3. Drop v1.0-only fields
    for v1_only in ("supportedInterfaces", "securitySchemes", "security", "extensions"):
        result.pop(v1_only, None)
    caps = result.get("capabilities")
    if isinstance(caps, dict):
        caps = dict(caps)
        caps.pop("extendedAgentCard", None)
        # Restore v0.3-style field name where applicable
        if "pushNotifications" in caps and "supportsPushNotifications" not in caps:
            caps["supportsPushNotifications"] = caps.pop("pushNotifications")
        result["capabilities"] = caps

    # 4. v0.3-marker
    if "schemaVersion" not in result and "protocolVersion" in result:
        result["schemaVersion"] = result["protocolVersion"]
    result["protocolVersion"] = "0.3.0"
    return result


def agent_card_from_v03(card: Dict[str, Any]) -> Dict[str, Any]:
    """Canonicalize a v0.3 AgentCard dict to v1.0 dual-shape.

    Adds v1.0 fields (``supportedInterfaces``, ``securitySchemes``, ``security``)
    derived from v0.3 fields while preserving the v0.3 fields for 6-month
    transition (Q5 signoff). Mirrors the backend canonicalize_card_data.

    IDEMPOTENT — safe to call on a card that is already v1.0.
    """
    if not isinstance(card, dict):
        return card
    result = dict(card)

    if "securitySchemes" not in result and "authSchemes" in result:
        derived = security_schemes_from_v03_auth_schemes(result.get("authSchemes") or [])
        result["securitySchemes"] = derived["securitySchemes"]
        result["security"] = derived["security"]

    if "supportedInterfaces" not in result and result.get("url"):
        interfaces = [{
            "url": result["url"],
            "protocolBinding": result.get("preferredTransport") or "JSONRPC",
            "protocolVersion": result.get("protocolVersion") or "1.0",
        }]
        extras = result.get("additionalInterfaces") or []
        if isinstance(extras, list):
            for extra in extras:
                if isinstance(extra, dict) and extra.get("url"):
                    interfaces.append({
                        "url": extra["url"],
                        "protocolBinding": extra.get("transport") or extra.get("protocolBinding") or "JSONRPC",
                        "protocolVersion": extra.get("protocolVersion") or "1.0",
                    })
        result["supportedInterfaces"] = interfaces

    capabilities = result.get("capabilities") or {}
    if not isinstance(capabilities, dict):
        capabilities = {}
    if "extendedAgentCard" not in capabilities and "supportsAuthenticatedExtendedCard" in result:
        capabilities["extendedAgentCard"] = bool(result.get("supportsAuthenticatedExtendedCard"))
    result["capabilities"] = capabilities

    if "schemaVersion" in result and "protocolVersion" not in result:
        result["protocolVersion"] = result["schemaVersion"]

    has_derived_v1 = "supportedInterfaces" in result and "securitySchemes" in result
    if has_derived_v1 and str(result.get("protocolVersion", "")).startswith("0."):
        original = result["protocolVersion"]
        result["protocolVersion"] = "1.0"
        if "schemaVersion" not in result:
            result["schemaVersion"] = original

    return result
