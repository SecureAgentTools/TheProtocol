"""
A2AClient — Call remote A2A agents via JSON-RPC 2.0 + SSE streaming.
Sends A2A v1.0 wire format. Accepts both v1.0 and v0.3 responses.
"""

import dataclasses
import json
import logging
import time
import uuid
from typing import Optional, Dict, Any, Union, AsyncGenerator, Tuple, List
from urllib.parse import urlparse, urlunparse

import httpx
import pydantic

from ..models import (
    AgentCard, Message, Task, TaskState,
    TaskSendParams, TaskSendResult, TaskGetParams, GetTaskResult,
    TaskCancelParams, TaskCancelResult, A2AEvent,
    TaskStatusUpdateEvent, TaskMessageEvent, TaskArtifactUpdateEvent,
)
from ..models.v1_compat import message_to_v1, state_from_v1, part_from_v1, role_from_v1
from ..exceptions import (
    A2AError, A2AConnectionError, A2AAuthenticationError,
    A2ARemoteAgentError, A2ATimeoutError, A2AMessageError,
    KeyManagementError,
)
from .credentials import KeyManager

logger = logging.getLogger(__name__)

SSE_EVENT_MAP = {
    # v0.3 event types
    "task_status": TaskStatusUpdateEvent,
    "task_message": TaskMessageEvent,
    "task_artifact": TaskArtifactUpdateEvent,
    # v1.0 event types
    "status_update": TaskStatusUpdateEvent,
    "message": TaskMessageEvent,
    "artifact_update": TaskArtifactUpdateEvent,
}


@dataclasses.dataclass
class _Scheme:
    """One auth scheme read from an A2A v1.0 card, shaped as _auth_headers reads a v0.3 authSchemes entry."""
    scheme: str
    service_identifier: Optional[str] = None
    token_url: Optional[str] = None
    scopes: Optional[List[str]] = None
    header: str = "X-Api-Key"


def _card_auth_schemes(card: AgentCard) -> List[Any]:
    """The schemes _auth_headers can use, from either card shape (D6-785). A v0.3 card names them in authSchemes. An
    A2A v1.0 card names them in securitySchemes and lists the ones it requires in `security`; it has no authSchemes,
    which _auth_headers iterated (TypeError). `security: []` declares that no credential is needed."""
    if card.auth_schemes:
        return list(card.auth_schemes)
    required: List[str] = []
    for req in card.security or []:
        if isinstance(req, dict):
            required.extend(n for n in req if n not in required)
    if not required:
        return [_Scheme("none")]
    out: List[Any] = []
    for name in required:
        s = (card.security_schemes or {}).get(name)
        if not isinstance(s, dict):
            continue
        kind = str(s.get("type") or "").strip().lower()
        if kind == "apikey" and str(s.get("in") or "header").lower() == "header":
            out.append(_Scheme("apiKey", header=str(s.get("name") or "X-Api-Key")))
        elif kind == "oauth2":
            cc = (s.get("flows") or {}).get("clientCredentials") or {}
            if cc.get("tokenUrl"):
                out.append(_Scheme("oauth2", token_url=str(cc["tokenUrl"]),
                                   scopes=list((cc.get("scopes") or {}).keys()) or None))
    return out


def _card_endpoint(card: AgentCard) -> str:
    """The card's A2A endpoint: its v0.3 `url`, else its first v1.0 supportedInterfaces entry (a v1.0 card may name
    only those; the client read `url` alone and called None)."""
    if card.url:
        return str(card.url)
    return str(card.supported_interfaces[0].url)


class A2AClient:
    """
    Client for calling remote A2A agents.

    Example::

        async with A2AClient() as client:
            task_id = await client.initiate_task(agent_card, message, key_manager)
            task = await client.get_task_status(agent_card, task_id, key_manager)
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None, timeout: float = 30.0):
        self.timeout = timeout
        if http_client:
            self._client = http_client
            self._owns_client = False
        else:
            self._client = httpx.AsyncClient(timeout=timeout, http2=True, follow_redirects=True)
            self._owns_client = True
        self._token_cache: Dict[str, Tuple[str, Optional[float]]] = {}

    async def close(self):
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "A2AClient":
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def initiate_task(
        self, agent_card: AgentCard, message: Message, key_manager: KeyManager
    ) -> str:
        """Start a new task on a remote agent. Returns the task ID.
        Sends v1.0 wire format (message/send with unified parts)."""
        headers = await self._auth_headers(agent_card, key_manager)
        v1_params = {"message": message_to_v1(message)}
        result = await self._rpc(_card_endpoint(agent_card), "message/send", v1_params, headers)
        # Accept both v1.0 (result.id or result["id"]) and v0.3 (TaskSendResult)
        if isinstance(result, dict) and "id" in result:
            return result["id"]
        return TaskSendResult.model_validate(result).id

    async def send_message(
        self, agent_card: AgentCard, task_id: str, message: Message, key_manager: KeyManager
    ) -> bool:
        """Send a follow-up message to an existing task.
        Sends v1.0 wire format."""
        headers = await self._auth_headers(agent_card, key_manager)
        v1_params = {"id": task_id, "message": message_to_v1(message)}
        result = await self._rpc(_card_endpoint(agent_card), "message/send", v1_params, headers)
        return True

    async def get_task_status(
        self, agent_card: AgentCard, task_id: str, key_manager: KeyManager
    ) -> Task:
        """Get current state of a task."""
        headers = await self._auth_headers(agent_card, key_manager)
        params = TaskGetParams(id=task_id)
        result = await self._rpc(_card_endpoint(agent_card), "tasks/get", params.model_dump(mode='json', by_alias=True), headers)
        return GetTaskResult.model_validate(result)

    async def cancel_task(
        self, agent_card: AgentCard, task_id: str, key_manager: KeyManager
    ) -> bool:
        """Request cancellation of a task."""
        headers = await self._auth_headers(agent_card, key_manager)
        params = TaskCancelParams(id=task_id)
        result = await self._rpc(_card_endpoint(agent_card), "tasks/cancel", params.model_dump(mode='json', by_alias=True), headers)
        return TaskCancelResult.model_validate(result).success

    async def subscribe(
        self, agent_card: AgentCard, task_id: str, key_manager: KeyManager
    ) -> AsyncGenerator[A2AEvent, None]:
        """Subscribe to SSE events for a task."""
        headers = await self._auth_headers(agent_card, key_manager)
        headers["Accept"] = "text/event-stream"
        url = self._ensure_trailing_slash(_card_endpoint(agent_card))
        # v1.0: message/stream (falls back to tasks/sendSubscribe on v0.3 servers)
        payload = {"jsonrpc": "2.0", "method": "message/stream", "params": {"id": task_id}, "id": f"sub-{uuid.uuid4()}"}

        async with self._client.stream('POST', url, headers=headers, json=payload, timeout=None) as resp:
            resp.raise_for_status()
            async for event in self._parse_sse(resp):
                yield event

    # ── Internal ──

    async def _rpc(self, url: Any, method: str, params: Dict, headers: Dict) -> Dict:
        url_str = self._ensure_trailing_slash(str(url))
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": f"req-{uuid.uuid4()}"}
        try:
            resp = await self._client.post(url_str, headers=headers, json=payload, follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise A2AMessageError(f"Expected JSON object, got {type(data)}")
            if "error" in data:
                err = data["error"]
                raise A2ARemoteAgentError(err.get("message", "Unknown error"), err.get("code"), err.get("data"))
            if "result" not in data:
                raise A2AMessageError("Missing 'result' in response")
            return data["result"]
        except httpx.TimeoutException as e:
            raise A2ATimeoutError(f"Timeout: {e}") from e
        except httpx.ConnectError as e:
            raise A2AConnectionError(f"Connection failed: {e}") from e
        except httpx.HTTPStatusError as e:
            raise A2ARemoteAgentError(f"HTTP {e.response.status_code}", e.response.status_code) from e
        except httpx.RequestError as e:
            raise A2AConnectionError(f"Request failed: {e}") from e

    async def _auth_headers(self, card: AgentCard, km: KeyManager) -> Dict[str, str]:
        for scheme in _card_auth_schemes(card):
            if scheme.scheme == 'apiKey':
                sid = scheme.service_identifier or card.human_readable_id
                key = km.get_key(sid)
                if key:
                    return {getattr(scheme, "header", None) or "X-Api-Key": key}
            elif scheme.scheme == 'oauth2':
                sid = scheme.service_identifier or card.human_readable_id
                cached = self._token_cache.get(sid)
                if cached and (cached[1] is None or cached[1] > time.time()):
                    return {"Authorization": f"Bearer {cached[0]}"}
                cid = km.get_oauth_client_id(sid)
                csec = km.get_oauth_client_secret(sid)
                if cid and csec and scheme.token_url:
                    if self._is_registry_agent_token_url(str(scheme.token_url)):
                        # A registry's agent token route takes the pair as an OAuth2 password form (client_id as
                        # username, client_secret as password); it answers a client-credentials form with 422.
                        token_data = {"grant_type": "password", "username": cid, "password": csec}
                    else:
                        token_data = {"grant_type": "client_credentials", "client_id": cid, "client_secret": csec}
                    if scheme.scopes:
                        token_data["scope"] = " ".join(scheme.scopes)
                    resp = await self._client.post(str(scheme.token_url), data=token_data, headers={"Content-Type": "application/x-www-form-urlencoded"})
                    resp.raise_for_status()
                    td = resp.json()
                    token = td.get("access_token", "")
                    exp = td.get("expires_in")
                    expiry = (time.time() + exp - 60) if isinstance(exp, (int, float)) and exp > 0 else None
                    self._token_cache[sid] = (token, expiry)
                    return {"Authorization": f"Bearer {token}"}
            elif scheme.scheme == 'none':
                return {}
        raise A2AAuthenticationError(f"No compatible auth scheme for {card.human_readable_id}")

    async def _parse_sse(self, resp: httpx.Response) -> AsyncGenerator[A2AEvent, None]:
        event_type = None
        data_lines: List[str] = []
        async for line in resp.aiter_lines():
            if not line:
                if data_lines:
                    etype = event_type or "message"
                    raw = "\n".join(data_lines)
                    data_lines = []
                    event_type = None
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    model = SSE_EVENT_MAP.get(etype)
                    if model and isinstance(parsed, dict):
                        try:
                            yield model.model_validate(parsed)
                        except pydantic.ValidationError:
                            continue
                continue
            if line.startswith(':'):
                continue
            colon = line.find(':')
            if colon == -1:
                continue
            field = line[:colon].strip()
            value = line[colon + 1:].lstrip(' ')
            if field == "event":
                event_type = value
            elif field == "data":
                data_lines.append(value)

    @staticmethod
    def _is_registry_agent_token_url(url: str) -> bool:
        """True for a registry's agent token route (``/api/v1/auth/agent/token``)."""
        return urlparse(url).path.rstrip('/').endswith('/auth/agent/token')

    @staticmethod
    def _ensure_trailing_slash(url: str) -> str:
        parsed = urlparse(url)
        if parsed.path and not parsed.path.endswith('/') and '.' not in parsed.path.split('/')[-1]:
            return urlunparse(parsed._replace(path=parsed.path + '/'))
        return url
