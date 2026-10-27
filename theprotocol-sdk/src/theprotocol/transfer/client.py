"""
Smart Transfer Client — ONE call for any destination.

Wraps the registry's `POST /api/v1/teg/send` (f060): the registry auto-detects
the route from its federated agent-card cache and fires the canonical rail —

    local  — same registry, same currency           (sync, status "completed")
    2pc    — cross-registry, same currency          (sync, status "completed")
    async  — cross-registry, same currency, opt-in  (status "locked" → settles)
    fx     — cross-FRAME, between two frames' units (reserve-mediated swap)

The caller never picks an endpoint or a body shape, and `preview()` returns the
route decision without moving anything.

    client = TransferClient("https://api.theprotocol.cloud")
    plan = await client.preview(agent_jwt, "did:theprotocol:…", "2.5")
    print(plan["method"], plan["currency_sent"], "->", plan["currency_received"])
    result = await client.send(agent_jwt, "did:theprotocol:…", "2.5",
                               message="invoice 42", idempotency_key="inv-42")
    print(result["status"], result["transfer_id"])
"""
import logging
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)


class SmartSendError(RuntimeError):
    """Raised when /teg/send refuses or the inner rail fails. Carries the HTTP
    status and the structured detail the registry returned."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"smart send failed ({status_code}): {str(detail)[:300]}")


class TransferClient:
    """Client for the registry's unified smart-send endpoint."""

    def __init__(self, registry_url: str, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.base = registry_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._transport = transport  # test seam (httpx.MockTransport)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                transport=self._transport,
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                timeout=httpx.Timeout(120.0, connect=5.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def send(
        self,
        agent_jwt: str,
        receiver_did: str,
        amount: str,
        *,
        message: str = "",
        backend: Optional[str] = None,
        dry_run: bool = False,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Move `amount` (sender-frame currency, decimal string) to `receiver_did`.

        backend: optional same-currency remote hint — "2pc" (default, sync) or
                 "async" (locked → settled). Ignored for local and FX routes.
        dry_run: preview the route decision; nothing moves.
        idempotency_key: forwarded to the inner rail's 24h replay cache — safe retries.

        Returns the SmartSendResponse dict (method, status, transfer_id,
        currency_sent/received, receiver_registry, detail…). Raises SmartSendError
        on any non-2xx (the registry's status code + structured detail preserved).
        """
        payload: Dict[str, Any] = {
            "receiver_did": receiver_did,
            "amount": amount,
            "dry_run": bool(dry_run),
        }
        if message:
            payload["message"] = message
        if backend:
            payload["backend"] = backend
        headers = {"Authorization": f"Bearer {agent_jwt}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        client = self._get_client()
        resp = await client.post(f"{self.base}/api/v1/teg/send", json=payload, headers=headers)
        if resp.status_code in (200, 201, 202):
            data = resp.json()
            if not dry_run:
                logger.info(
                    f"[TransferClient] {data.get('method')} {amount} "
                    f"{data.get('currency_sent')}->{data.get('currency_received')} "
                    f"→ {receiver_did} tx={data.get('transfer_id')} status={data.get('status')}"
                )
            return data
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text[:300]
        raise SmartSendError(resp.status_code, detail)

    async def preview(self, agent_jwt: str, receiver_did: str, amount: str) -> Dict[str, Any]:
        """Route decision only — sugar for send(dry_run=True)."""
        return await self.send(agent_jwt, receiver_did, amount, dry_run=True)
