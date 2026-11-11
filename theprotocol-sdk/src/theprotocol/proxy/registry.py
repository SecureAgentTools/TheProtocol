"""The proxy's one way to TheProtocol: every action's call goes through here, as the proxy's agent.

What this layer guarantees, whatever a plugin does:

* every call carries the agent's token, renewed before it expires and asked for again once after a 401;
* every write (anything but GET, HEAD and OPTIONS) carries the record's Idempotency-Key, and a write without one is
  refused here, before it leaves the proxy;
* a dry run sends no write at all;
* a registry that cannot be reached, or does not answer in time, raises `Retry`; credentials the registry refuses raise
  `Refused` with its answer (a token route that is down, `Retry`). Every answer the registry gives (a 429 and a 5xx
  included) is returned to the plugin, which reads it, Retry-After included.
"""
from __future__ import annotations

import asyncio
import ssl
from typing import Any, Dict, Mapping, Optional

import httpx

from .identity import Identity, IdentityError
from .plugins import PluginError, Refused, Retry

READS = frozenset({"GET", "HEAD", "OPTIONS"})


def retry_after(r: Any) -> Optional[float]:
    """The seconds a Retry-After header names (a number of seconds; a date is left to the backoff)."""
    v = next((val for k, val in dict(getattr(r, "headers", {}) or {}).items() if str(k).lower() == "retry-after"), None)
    try:
        return max(0.0, float(v)) if v is not None else None
    except ValueError:
        return None


class RegistryClient:
    """Calls to one registry as one agent."""

    def __init__(self, identity: Identity, *, transport: Optional[httpx.AsyncBaseTransport] = None,
                 timeout: float = 30.0):
        self.identity = identity
        self._transport = transport
        self._timeout = timeout
        self._http: Optional[httpx.AsyncClient] = None
        self._cert = None
        self.calls = 0           # the metrics read these
        self.writes = 0

    def _client(self) -> httpx.AsyncClient:
        cert = self.identity.client_cert()
        if self._http is None or cert != self._cert:
            old, self._cert = self._http, cert
            kw: Dict[str, Any] = {"timeout": self._timeout, "transport": self._transport}
            if cert:
                # the SVID is presented on every call; the registry's own certificate is checked as always
                ctx = ssl.create_default_context()
                ctx.load_cert_chain(certfile=cert[0], keyfile=cert[1])
                kw["verify"] = ctx
            self._http = httpx.AsyncClient(**kw)
            if old is not None:
                # the old pool (the SVID before its renewal) closes once its calls finish; nothing waits on it here
                asyncio.ensure_future(old.aclose())
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _headers(self, extra: Optional[Mapping[str, str]], key: Optional[str]) -> Dict[str, str]:
        try:
            token = await self.identity.token()
        except IdentityError as e:
            if e.status is None or e.status >= 500 or e.status == 429:
                raise Retry(e.detail, status=e.status) from None
            raise Refused(e.detail, status=e.status) from None
        h = {k: v for k, v in (extra or {}).items() if k.lower() not in ("authorization", "idempotency-key")}
        h["Authorization"] = f"Bearer {token}"
        if key:
            h["Idempotency-Key"] = key
        return h

    async def call(self, method: str, path: str, *, json: Any = None, params: Optional[Mapping[str, Any]] = None,
                   idempotency_key: Optional[str] = None, headers: Optional[Mapping[str, str]] = None,
                   dry_run: bool = False) -> httpx.Response:
        m = method.upper()
        if not path.startswith("/"):
            raise PluginError(f"a call names a path on the registry (/api/v1/...), not {path!r}")
        if m not in READS:
            if dry_run:
                raise PluginError(f"a dry run sends nothing: the plugin called {m} {path}")
            if not idempotency_key:
                raise PluginError(f"{m} {path} without the record's key: every write carries its Idempotency-Key")
        url = f"{self.identity.registry}{path}"
        for attempt in (1, 2):
            h = await self._headers(headers, idempotency_key if m not in READS else None)
            try:
                self.calls += 1
                if m not in READS:
                    self.writes += 1
                r = await self._client().request(m, url, json=json, params=params, headers=h)
            except httpx.TimeoutException as e:
                raise Retry(f"{m} {path}: no answer in time ({type(e).__name__})") from None
            except httpx.HTTPError as e:
                raise Retry(f"{m} {path}: the registry could not be reached ({type(e).__name__})") from None
            if r.status_code == 401 and attempt == 1:
                self.identity.invalidate()     # a token the registry no longer takes: ask for a new one, once
                continue
            return r
        return r  # pragma: no cover - the loop returns
