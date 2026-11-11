"""The proxy's agent identity: its token from its own client credentials, kept fresh, and optionally its IRONHAND SVID.

The credentials are the Agent Forge starter's (`.env` names the agent and its registry, `.env.secret` holds CLIENT_ID and
CLIENT_SECRET); the spec names them by reference. The token comes from POST /api/v1/auth/agent/token (form-encoded:
username = the client id, password = the client secret) and is renewed before it expires, or at once after a 401. With
`identity.mtls.enabled`, the proxy also holds an X509-SVID (POST /api/v1/agent/enable-mtls, the SDK's IronhandClient) and
renews it before it expires by calling enable-mtls again, each time with a token that is still valid.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

log = logging.getLogger("theprotocol.proxy.identity")

TOKEN_PATH = "/api/v1/auth/agent/token"
#: renew the token this many seconds before its exp
RENEW_MARGIN_S = 120.0


class IdentityError(RuntimeError):
    """The registry did not issue the proxy a token; `status` is its HTTP status (None: it could not be reached)."""

    def __init__(self, detail: str, status: Optional[int] = None):
        self.detail, self.status = detail, status
        super().__init__(detail)


def token_claims(token: str) -> Dict[str, Any]:
    """A JWT's claims, read without checking the signature (the registry checks it; the proxy only reads exp and sub)."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return {}


def _detail(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:200]
    d = body.get("detail") if isinstance(body, dict) else body
    return d if isinstance(d, str) else json.dumps(d, default=str)[:200]


class Identity:
    """One agent's token (and SVID) for the proxy's calls."""

    def __init__(self, registry: str, agent_did: str, client_id: str, client_secret: str, *,
                 mtls_dir: Optional[str] = None, transport: Optional[httpx.AsyncBaseTransport] = None,
                 clock: Callable[[], float] = time.time, timeout: float = 20.0):
        self.registry = registry.rstrip("/")
        self.agent_did = agent_did
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport
        self._clock = clock
        self._timeout = timeout
        self._token: Optional[str] = None
        self._exp: float = 0.0
        self._lock = asyncio.Lock()
        self.mtls_dir = mtls_dir
        self._iron = None
        self.issued = 0          # tokens issued in this process (the metrics read it)
        self.last_error: Optional[str] = None

    # ── the token ─────────────────────────────────────────────────────────────────────────────────────────────────

    def secrets(self) -> Tuple[str, ...]:
        """The values the log redactor must never print."""
        return tuple(v for v in (self._client_secret, self._token) if v)

    def invalidate(self) -> None:
        """Forget the token (the registry answered 401): the next call asks for a new one."""
        self._token, self._exp = None, 0.0

    async def token(self) -> str:
        """A token valid for at least RENEW_MARGIN_S more seconds (or one just issued)."""
        if self._token and self._clock() < self._exp - RENEW_MARGIN_S:
            return self._token
        async with self._lock:
            if self._token and self._clock() < self._exp - RENEW_MARGIN_S:
                return self._token
            try:
                async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as http:
                    r = await http.post(f"{self.registry}{TOKEN_PATH}",
                                        data={"username": self._client_id, "password": self._client_secret})
            except httpx.HTTPError as e:
                self.last_error = f"the registry could not be reached: {type(e).__name__}"
                raise IdentityError(self.last_error) from None
            if r.status_code != 200:
                self.last_error = f"the registry refused the proxy's credentials (HTTP {r.status_code}): {_detail(r)}"
                raise IdentityError(self.last_error, r.status_code)
            token = (r.json() or {}).get("access_token") or ""
            claims = token_claims(token)
            sub = claims.get("sub") or claims.get("agent_did")
            if self.agent_did and sub and sub != self.agent_did:
                self.last_error = f"the credentials are {sub}'s, not {self.agent_did}'s"
                raise IdentityError(self.last_error, r.status_code)
            exp = claims.get("exp")
            # a token without a readable exp is used for five minutes, then asked for again
            self._exp = float(exp) if isinstance(exp, (int, float)) else self._clock() + 300 + RENEW_MARGIN_S
            self._token = token
            self.issued += 1
            self.last_error = None
            return token

    # ── IRONHAND (optional) ───────────────────────────────────────────────────────────────────────────────────────

    @property
    def iron(self):
        if self._iron is None and self.mtls_dir:
            from ..mtls import IronhandClient
            self._iron = IronhandClient(self.registry, cert_dir=self.mtls_dir, transport=self._transport)
        return self._iron

    def client_cert(self) -> Optional[Tuple[str, str]]:
        """(svid.pem, key.pem) once an inline SVID is on disk; None otherwise."""
        iron = self.iron
        last = getattr(iron, "last_enrollment", None)
        if iron is None or last is None or not last.has_files:
            return None
        return iron.svid_path, iron.key_path

    async def ensure_svid(self) -> Optional[Any]:
        """Enroll, or renew the SVID once it is inside its margin (a no-op otherwise, and without IRONHAND)."""
        if self.iron is None:
            return None
        return await self.iron.ensure_fresh(await self.token())

    def start_svid_renewal(self, *, check_interval: float = 60.0) -> Optional["asyncio.Task"]:
        """Keep the SVID fresh until cancelled, asking for the current token on every renewal."""
        if self.iron is None:
            return None
        return self.iron.start_auto_rotate(self.token, check_interval=check_interval)
