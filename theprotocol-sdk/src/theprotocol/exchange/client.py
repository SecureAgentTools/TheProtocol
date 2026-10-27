"""
AGORA Client: trade organization points on the AGORA market from agent code.

Market data is public; order/portfolio calls take the agent's JWT.

    ex = ExchangeClient("https://api.theprotocol.cloud")
    book = await ex.book("BL1F")
    res = await ex.place_order(agent_jwt, "BL1F", "buy", qty=5, price="4.20")
    await ex.cancel_order(agent_jwt, res["order_id"])

Money model (why you can trust it): points are registry-ledger entries; every
money leg settles through the venue escrow on TEG rails — buy escrow is taken
on placement, refunds/proceeds drain via the settlement worker. Fees come from
SELLER proceeds (a buy never pays more than its escrow). Supply Δ=0 by
construction; the venue self-checks via GET /api/v1/agora/admin/invariant.
"""
import logging
import warnings
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


AGORA_PREFIX = "/api/v1/agora"
LEGACY_PREFIX = "/api/v1/exchange"


def _route_missing(r: httpx.Response) -> bool:
    """A 404 whose registry did not know the ROUTE (detail exactly "Not Found"), as opposed to an answer like an
    unknown listing, whose detail names the listing."""
    if r.status_code != 404:
        return False
    try:
        body = r.json()
    except ValueError:
        return True
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail in (None, "Not Found")


class ExchangeClient:
    """Client for an AGORA market (one registry hosting an order book).

    0.7.3: the documented base path /api/v1/agora (every registry since V0419). Before its first call a client asks
    the registry once whether it serves that path; a registry that does not know the route at all (an older one)
    is spoken to under /api/v1/exchange for the life of the client, and `launch_buy` uses that registry's older
    `ipo/buy` path. `base` holds the resolved path."""

    def __init__(self, registry_url: str, timeout: float = 15.0):
        self._root = registry_url.rstrip("/")
        self.base = self._root + AGORA_PREFIX
        self._resolved = False
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout

    async def _resolve(self) -> None:
        """Ask once: GET <registry>/api/v1/agora/listings (public). A route-missing 404 means an older registry."""
        try:
            r = await self._c().get(self._root + AGORA_PREFIX + "/listings")
            if _route_missing(r):
                self.base = self._root + LEGACY_PREFIX
        except httpx.HTTPError:
            pass  # keep the documented path: the real call raises with its own error
        self._resolved = True

    async def _url(self, path: str) -> str:
        if not self._resolved:
            await self._resolve()
        return f"{self.base}{path}"

    def _c(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @staticmethod
    def _auth(agent_jwt: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {agent_jwt}"}

    # ── market data (public) ──────────────────────────────────────────
    async def listings(self) -> List[Dict[str, Any]]:
        r = await self._c().get(await self._url(f"/listings"))
        r.raise_for_status()
        return r.json().get("listings", [])

    async def listing(self, ref: str) -> Dict[str, Any]:
        r = await self._c().get(await self._url(f"/listings/{ref}"))
        r.raise_for_status()
        return r.json()

    async def book(self, ref: str, depth: int = 12) -> Dict[str, Any]:
        r = await self._c().get(await self._url(f"/listings/{ref}/book"), params={"depth": depth})
        r.raise_for_status()
        return r.json()

    async def trades(self, ref: str, limit: int = 50) -> List[Dict[str, Any]]:
        r = await self._c().get(await self._url(f"/listings/{ref}/trades"), params={"limit": limit})
        r.raise_for_status()
        return r.json().get("trades", [])

    async def candles(self, ref: str, tf: str = "1h", limit: int = 120) -> List[Dict[str, Any]]:
        r = await self._c().get(await self._url(f"/listings/{ref}/candles"), params={"tf": tf, "limit": limit})
        r.raise_for_status()
        return r.json().get("candles", [])

    async def federation_tickers(self) -> List[Dict[str, Any]]:
        """Every live venue this registry can see (server-side aggregate)."""
        r = await self._c().get(await self._url(f"/federation-tickers"))
        r.raise_for_status()
        return r.json().get("venues", [])

    # ── trading (agent JWT) ───────────────────────────────────────────
    async def place_order(
        self, agent_jwt: str, listing: str, side: str, qty: int,
        price: Optional[str] = None, order_type: Optional[str] = None,
        client_order_id: Optional[str] = None, ttl_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Limit when `price` given (unless order_type overrides), else market.
        Returns {order_id, status, remaining, escrow_amount, fills[...]}."""
        body: Dict[str, Any] = {
            "listing": listing, "side": side, "qty": qty,
            "order_type": order_type or ("limit" if price is not None else "market"),
        }
        if price is not None:
            body["price"] = price
        if client_order_id:
            body["client_order_id"] = client_order_id
        if ttl_seconds:
            body["ttl_seconds"] = ttl_seconds
        r = await self._c().post(await self._url(f"/orders"), json=body, headers=self._auth(agent_jwt))
        r.raise_for_status()
        return r.json()

    async def cancel_order(self, agent_jwt: str, order_id: str) -> Dict[str, Any]:
        r = await self._c().delete(await self._url(f"/orders/{order_id}"), headers=self._auth(agent_jwt))
        r.raise_for_status()
        return r.json()

    async def my_orders(self, agent_jwt: str, listing: Optional[str] = None) -> List[Dict[str, Any]]:
        r = await self._c().get(await self._url(f"/orders/mine"),
                                params={"listing": listing} if listing else {},
                                headers=self._auth(agent_jwt))
        r.raise_for_status()
        return r.json().get("orders", [])

    async def portfolio(self, agent_jwt: str) -> Dict[str, Any]:
        r = await self._c().get(await self._url(f"/portfolio"), headers=self._auth(agent_jwt))
        r.raise_for_status()
        return r.json()

    async def launch_buy(self, agent_jwt: str, ref: str, qty: int) -> Dict[str, Any]:
        """Buy points at launch: from a listing's launch allocation, at the fixed launch price.

        `/api/v1/agora/listings/{ref}/launch/buy`; an older registry (spoken to under /api/v1/exchange) is sent its
        own `/listings/{ref}/ipo/buy`."""
        url = await self._url(f"/listings/{ref}/")
        url += "launch/buy" if self.base.endswith(AGORA_PREFIX) else "ipo/buy"
        r = await self._c().post(url, json={"qty": qty}, headers=self._auth(agent_jwt))
        r.raise_for_status()
        return r.json()

    async def ipo_buy(self, agent_jwt: str, ref: str, qty: int) -> Dict[str, Any]:
        """Deprecated: the earlier name of `launch_buy`. It keeps working and warns once per call site."""
        warnings.warn("ExchangeClient.ipo_buy is deprecated; use ExchangeClient.launch_buy",
                      DeprecationWarning, stacklevel=2)
        return await self.launch_buy(agent_jwt, ref, qty)
