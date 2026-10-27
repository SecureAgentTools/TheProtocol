"""
IRONKEY Authz Client — delegation grants + attenuable capability tokens (L3/L4).

An agent with the `authz.delegate` meta-permission issues scoped `att_`
capability tokens for its sub-agents; any holder may derive strictly-weaker
children (attenuate); revoking a token kills its whole subtree. The plain
token rides requests as the `X-Capability-Token` header:

    authz = AuthzClient("https://api.theprotocol.cloud")
    cap = await authz.issue_capability(
        parent_jwt, ["exchange.trade", "teg.transfer"],
        holder_agent_did=clerk_did, budget_total=400.0, ttl_seconds=86400,
    )
    token = cap["token"]                       # shown ONCE — store it now
    headers = {**clerk_auth, **AuthzClient.capability_headers(token)}
    child = await authz.attenuate(clerk_jwt, cap["id"], ["exchange.trade"],
                                  budget_total=50.0)
    mine = await authz.my_capabilities(clerk_jwt)
    await authz.revoke_capability(parent_jwt, cap["id"])   # cascades subtree

Effective authority is always caveats ∩ ISSUER-CURRENT permissions — clamping
the issuer instantly empties every token it issued. Flags (`AGENT_RBAC_MODE`,
`AGENT_DELEGATION_MODE`) default off: the API works everywhere, enforcement
bites only where the registry has them on.
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class AuthzError(RuntimeError):
    """Raised on a non-2xx IRONKEY response. Carries the HTTP status and the
    structured detail the registry returned."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"authz request failed ({status_code}): {str(detail)[:300]}")


class AuthzClient:
    """Client for the registry's IRONKEY delegation + capability-token API."""

    def __init__(self, registry_url: str, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.base = registry_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._transport = transport  # test seam (httpx.MockTransport)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
                timeout=httpx.Timeout(60.0, connect=5.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _auth(jwt: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {jwt}"}

    @staticmethod
    def _ok(resp: httpx.Response) -> Dict[str, Any]:
        if 200 <= resp.status_code < 300:
            return resp.json()
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text[:300]
        raise AuthzError(resp.status_code, detail)

    @staticmethod
    def capability_headers(token: str) -> Dict[str, str]:
        """Headers that attach a capability token to any registry request."""
        return {"X-Capability-Token": token}

    @staticmethod
    def _caveats(permissions: List[str], caveats: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        merged: Dict[str, Any] = dict(caveats or {})
        merged["permissions"] = permissions
        return merged

    # ── L3 — delegation grants (developer JWT) ────────────────────────
    async def list_delegations(self, developer_jwt: str, agent_did: str) -> Dict[str, Any]:
        """
        Delegation grants held by an agent (developer JWT — owner/admin view).
        Returns `{agent_did, grants: [{id, principal, permissions,
        may_redelegate, max_depth, expires_at, revoked}]}`.
        """
        resp = await self._get_client().get(
            f"{self.base}/api/v1/agents/{agent_did}/delegations",
            headers=self._auth(developer_jwt),
        )
        return self._ok(resp)

    # ── L4 — attenuable capability tokens (agent JWT) ─────────────────
    async def issue_capability(
        self, agent_jwt: str, permissions: List[str],
        *,
        holder_agent_did: Optional[str] = None,
        budget_total: Optional[float] = None,
        currency: Optional[str] = None,
        max_uses: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
        caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Issue a root `att_` capability token (requires the `authz.delegate`
        meta-permission; `permissions` must be ⊆ your CURRENT authority).

        `caveats` merges extra caveat fields (max_per_tx, allowed_currencies,
        counterparty_allow, operations, no_redelegate, phone_* …).
        `ttl_seconds` 60..86400 (server default 900). The response's `token`
        is shown ONCE — store it; only the hash persists server-side.
        """
        body: Dict[str, Any] = {"caveats": self._caveats(permissions, caveats)}
        if holder_agent_did is not None:
            body["holder_agent_did"] = holder_agent_did
        if budget_total is not None:
            body["budget_total"] = budget_total
        if currency is not None:
            body["currency"] = currency
        if max_uses is not None:
            body["max_uses"] = max_uses
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        resp = await self._get_client().post(
            f"{self.base}/api/v1/agents/capabilities",
            json=body, headers=self._auth(agent_jwt),
        )
        data = self._ok(resp)
        logger.info(f"[AuthzClient] capability issued: id={data.get('id')} -> {holder_agent_did or 'bearer'}")
        return data

    async def attenuate(
        self, agent_jwt: str, token_id: int, permissions: List[str],
        *,
        budget_total: Optional[float] = None,
        max_uses: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
        caveats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Derive a strictly-weaker CHILD token from a token you hold (or issued).
        Attenuation rides the TOKEN, not your role — no meta-permission needed;
        the child can never exceed the parent (denied if the parent set
        `no_redelegate`, or past the max chain depth of 3).
        """
        body: Dict[str, Any] = {"caveats": self._caveats(permissions, caveats)}
        if budget_total is not None:
            body["budget_total"] = budget_total
        if max_uses is not None:
            body["max_uses"] = max_uses
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        resp = await self._get_client().post(
            f"{self.base}/api/v1/agents/capabilities/{token_id}/attenuate",
            json=body, headers=self._auth(agent_jwt),
        )
        return self._ok(resp)

    async def my_capabilities(self, agent_jwt: str) -> Dict[str, Any]:
        """
        Capability tokens I issued or hold. Returns `{agent_did, mode, tokens:
        [{id, role, issuer_did, holder_did, parent_token_id, depth, status,
        permissions, budget_remaining, currency, expires_at}]}`.
        """
        resp = await self._get_client().get(
            f"{self.base}/api/v1/agents/capabilities/mine",
            headers=self._auth(agent_jwt),
        )
        return self._ok(resp)

    async def revoke_capability(self, agent_jwt: str, token_id: int) -> Dict[str, Any]:
        """
        Revoke a token AND its whole subtree (issuer or holder only). Returns
        `{ok, root_token_id, revoked_count}`.
        """
        resp = await self._get_client().delete(
            f"{self.base}/api/v1/agents/capabilities/{token_id}",
            headers=self._auth(agent_jwt),
        )
        data = self._ok(resp)
        logger.info(f"[AuthzClient] revoked token {token_id} subtree: {data.get('revoked_count')} tokens")
        return data
