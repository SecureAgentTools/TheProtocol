"""
A2A Payment Client — helper for acquiring and settling payment tokens.

Used by orchestrators and agents that call other agents.

    client = PaymentClient("https://api.theprotocol.cloud")
    token = await client.get_token(agent_jwt, "did:theprotocol:weather", "0.5")
    # ... call agent A2A with X-Payment-Token header ...
    await client.settle(agent_jwt, token, task_id="weather-123")
"""
import logging
from typing import Optional, Dict

import httpx

logger = logging.getLogger(__name__)


class PaymentClient:
    """Client for the registry A2A payment authorization system."""

    def __init__(self, registry_url: str):
        self.base = registry_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create a persistent httpx client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
                timeout=httpx.Timeout(45.0, connect=5.0),
            )
        return self._client

    async def close(self):
        """Close the persistent client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def a2a_headers(self, token: str) -> Dict[str, str]:
        """
        Build headers to include in an A2A request.
        Returns both X-Payment-Token and X-Payment-Issuer for cross-registry support.
        """
        return {
            "X-Payment-Token": token,
            "X-Payment-Issuer": self.base,
        }

    async def get_token(
        self,
        agent_jwt: str,
        target_did: str,
        amount: str,
        contract_id: Optional[int] = None,
        ttl_seconds: int = 900,
    ) -> str:
        """
        Request a payment token from the registry.

        Returns the plain token string to include as X-Payment-Token header.
        Use a2a_headers(token) to get both X-Payment-Token and X-Payment-Issuer.
        Raises on failure (insufficient balance, target not found, etc.).
        """
        client = self._get_client()
        resp = await client.post(
            f"{self.base}/api/v1/a2a-payment/authorize",
            json={
                "target_agent_did": target_did,
                "amount": amount,
                "contract_id": contract_id,
                "ttl_seconds": ttl_seconds,
            },
            headers={"Authorization": f"Bearer {agent_jwt}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"[PaymentClient] Payment authorization acquired: {amount} units → {target_did}")
            return data["token"]
        error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"detail": resp.text}
        detail = error.get("detail", str(error))
        raise RuntimeError(f"Payment authorization failed ({resp.status_code}): {detail}")

    async def settle(
        self,
        agent_jwt: str,
        token: str,
        task_id: Optional[str] = None,
        success: bool = True,
    ) -> Dict:
        """
        Settle a payment token after task completion.
        Triggers the actual TEG transfer from caller to target.
        """
        client = self._get_client()
        resp = await client.post(
            f"{self.base}/api/v1/a2a-payment/settle",
            json={
                "token": token,
                "task_id": task_id,
                "success": success,
            },
            headers={"Authorization": f"Bearer {agent_jwt}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            logger.info(f"[PaymentClient] Settled: {data.get('settlement_tx_id', '?')}")
            return data
        error = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"detail": resp.text}
        raise RuntimeError(f"Settlement failed ({resp.status_code}): {error.get('detail', str(error))}")

    async def release(self, agent_jwt: str, token: str) -> Dict:
        """Release an unused payment token (cancel)."""
        client = self._get_client()
        resp = await client.post(
            f"{self.base}/api/v1/a2a-payment/release",
            json={"token": token},
            headers={"Authorization": f"Bearer {agent_jwt}"},
        )
        if resp.status_code == 200:
            return resp.json()
        raise RuntimeError(f"Release failed ({resp.status_code})")
