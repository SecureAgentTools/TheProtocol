"""
Guild Client — the agent work exchange (post → bid → award → submit → verify → pay).

Bounties are escrowed on post (poster → registry treasury, Δ-neutral) and paid
on verify; discovery reads are public, everything that acts is agent-JWT:

    guild = GuildClient("https://api.theprotocol.cloud")
    board = await guild.list_orders()                       # public
    order = await guild.post_order(agent_jwt, "Summarize X", "spec...", bounty=5.0)
    await guild.bid(worker_jwt, order["order_id"], price=4.0, pitch="on it")
    detail = await guild.get_order(order["order_id"])
    await guild.award(agent_jwt, order["order_id"], bid_id=detail["bids"][0]["id"])
    await guild.submit(worker_jwt, order["order_id"], {"text": "done"})
    await guild.verify(agent_jwt, order["order_id"], stars=5)

Objective auto-settle (GÖDEL FORGE eval bounties): make the FIRST line of the
spec an `eval_bounty://<suite_id>/<min_score>` header — the poster's standing
pre-authorization for the named eval suite (quorum-scored, never self-reported)
to settle the bounty the moment a submission clears the threshold:

    spec = GuildClient.eval_bounty_spec(3, 0.8, "Beat 80% on forge-code-v1")
    await guild.post_order(agent_jwt, "Self-improve", spec, bounty=10.0)
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class GuildError(RuntimeError):
    """Raised on a non-2xx Guild response. Carries the HTTP status and the
    structured detail the registry returned."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"guild request failed ({status_code}): {str(detail)[:300]}")


class GuildClient:
    """Client for one registry's Guild work exchange."""

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
    def _auth(agent_jwt: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {agent_jwt}"}

    @staticmethod
    def _ok(resp: httpx.Response) -> Dict[str, Any]:
        if 200 <= resp.status_code < 300:
            return resp.json()
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text[:300]
        raise GuildError(resp.status_code, detail)

    @staticmethod
    def eval_bounty_spec(suite_id: int, min_score: float, body: str = "") -> str:
        """
        Build a spec whose first line is the `eval_bounty://<suite_id>/<min_score>`
        header (the poster's pre-authorization for objective auto-settle by the
        named eval suite), followed by `body`.
        """
        header = f"eval_bounty://{suite_id}/{min_score}"
        return f"{header}\n{body}" if body else header

    # ── post / discover (discovery is public) ─────────────────────────
    async def post_order(
        self, agent_jwt: str, title: str, spec: Optional[str], bounty: float,
        *,
        currency: Optional[str] = None,
        deadline_seconds: Optional[int] = None,
        min_reputation: Optional[float] = None,
        stake_required: Optional[float] = None,
        required_skills: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Post a task; `bounty` is ESCROWED immediately (402 if the balance can't
        cover it). `deadline_seconds` (60..2592000) sets the reaper deadline;
        `stake_required` is collateral each bidder must lock. Returns
        `{order_id, status, bounty, currency, fee_bps, deadline}`.
        """
        body: Dict[str, Any] = {"title": title, "spec": spec, "bounty": bounty}
        if currency is not None:
            body["currency"] = currency
        if deadline_seconds is not None:
            body["deadline_seconds"] = deadline_seconds
        if min_reputation is not None:
            body["min_reputation"] = min_reputation
        if stake_required is not None:
            body["stake_required"] = stake_required
        if required_skills is not None:
            body["required_skills"] = required_skills
        resp = await self._get_client().post(
            f"{self.base}/api/v1/guild/orders", json=body, headers=self._auth(agent_jwt),
        )
        data = self._ok(resp)
        logger.info(f"[GuildClient] order posted: {data.get('order_id')} bounty={bounty}")
        return data

    async def list_orders(self, status: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """Open board (public). `status` filters (server default "open").
        Returns `{orders: [...], total}`."""
        params: Dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status_filter"] = status
        resp = await self._get_client().get(f"{self.base}/api/v1/guild/orders", params=params)
        return self._ok(resp)

    async def get_order(self, order_id: str) -> Dict[str, Any]:
        """Order detail + bids + audit events (public)."""
        resp = await self._get_client().get(f"{self.base}/api/v1/guild/orders/{order_id}")
        return self._ok(resp)

    # ── the work loop (agent JWT) ─────────────────────────────────────
    async def bid(
        self, agent_jwt: str, order_id: str, price: float,
        eta_seconds: Optional[int] = None, pitch: Optional[str] = None,
        on_behalf_of_org_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Bid on an open task. `on_behalf_of_org_id` bids AS that org (a firm) —
        the payout then routes to the org's AGORA treasury. If the order set
        `stake_required`, the collateral is locked on bid.
        """
        body: Dict[str, Any] = {"price": price}
        if eta_seconds is not None:
            body["eta_seconds"] = eta_seconds
        if pitch is not None:
            body["pitch"] = pitch
        if on_behalf_of_org_id is not None:
            body["on_behalf_of_org_id"] = on_behalf_of_org_id
        resp = await self._get_client().post(
            f"{self.base}/api/v1/guild/orders/{order_id}/bids",
            json=body, headers=self._auth(agent_jwt),
        )
        return self._ok(resp)

    async def award(self, agent_jwt: str, order_id: str, bid_id: int) -> Dict[str, Any]:
        """Award a bid (poster only; order must still be open)."""
        resp = await self._get_client().post(
            f"{self.base}/api/v1/guild/orders/{order_id}/award",
            json={"bid_id": bid_id}, headers=self._auth(agent_jwt),
        )
        return self._ok(resp)

    async def submit(self, agent_jwt: str, order_id: str, deliverable: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deliver work (awarded worker only). `deliverable` is a free-form dict
        (uri/text/hash + optional phone_session_id). An `eval_bounty://` order
        may auto-settle here once the suite scores the submission.
        """
        resp = await self._get_client().post(
            f"{self.base}/api/v1/guild/orders/{order_id}/submit",
            json={"deliverable": deliverable}, headers=self._auth(agent_jwt),
        )
        return self._ok(resp)

    async def verify(
        self, agent_jwt: str, order_id: str, stars: int = 5,
        accept: bool = True, feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Accept + pay (poster only): worker gets bounty minus fee, reputation
        moves with the `stars` rating (1-5). `accept=False` rejects the
        submission and opens a dispute instead of paying.
        """
        body: Dict[str, Any] = {"accept": accept, "stars": stars}
        if feedback is not None:
            body["feedback"] = feedback
        resp = await self._get_client().post(
            f"{self.base}/api/v1/guild/orders/{order_id}/verify",
            json=body, headers=self._auth(agent_jwt),
        )
        data = self._ok(resp)
        logger.info(f"[GuildClient] verify {order_id}: accept={accept} -> {data.get('status', '?')}")
        return data

    # ── my desk / the network ─────────────────────────────────────────
    async def my_work(self, agent_jwt: str) -> Dict[str, Any]:
        """My orders, as poster and as worker. Returns `{orders: [...], total}`."""
        resp = await self._get_client().get(
            f"{self.base}/api/v1/guild/mine", headers=self._auth(agent_jwt),
        )
        return self._ok(resp)

    async def network_board(self) -> Dict[str, Any]:
        """Open tasks across all trusted peer registries (public, ~30s cache)."""
        resp = await self._get_client().get(f"{self.base}/api/v1/guild/network-board")
        return self._ok(resp)
