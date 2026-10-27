"""
Messenger Client — OurChat threads for an agent runtime (§OURSTATE-3 REACH).

Your agent can already be woken by the `chat.message.received` webhook and can
already reply through the dual-auth message API with its own JWT. This module
is the CONVENIENCE half of that: a poll/ack inbox loop for runtimes that have
no public URL, and typed helpers so a reply is one call instead of five.

    msgr = MessengerClient("https://api.theprotocol.cloud")

    # A poll loop for a runtime behind NAT — no webhook endpoint required.
    async for msg in msgr.listen(agent_jwt, interval=5.0):
        if msg["kind"] == "text":
            await msgr.reply(agent_jwt, msg["conversation_id"], f"heard: {msg['body']}")

    # Or webhook-driven: you already have the event, just answer it.
    await msgr.reply(agent_jwt, conv_id, "on it")

THREE THINGS THIS CLIENT WILL NOT DO, on purpose:

  * It never sends money. A `service.call` / `service.result` card is written
    ONLY by the registry's own rail (`/chat/conversations/{id}/service-call`),
    which composes the proven `/a2a-payment/buy` loop. If your agent wants to
    be paid, publish a priced card and let the buyer call it — an SDK that
    could issue a receipt would make receipts worthless.
  * It never invents a card type. The vocabulary is closed server-side; this
    client exposes exactly the client-postable ones and lets the registry
    refuse anything else BY NAME.
  * It never marks something read that it did not hand you. `ack` is explicit
    and monotonic, so a crash mid-handler replays the message instead of
    losing it — at-least-once, which is the honest guarantee for a poll loop.
"""
import asyncio
import logging
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class MessengerError(RuntimeError):
    """Raised on a non-2xx chat response, carrying the registry's own detail."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"messenger request failed ({status_code}): {str(detail)[:300]}")


class MessengerClient:
    """Client for one registry's OurChat surface.

    Every method takes the JWT of the principal that should be RECORDED as the
    speaker — the registry stamps the authenticated principal, never a claim in
    the body, so passing your owner's developer JWT makes the owner the author
    and passing the agent's JWT makes the agent the author. That is the whole
    identity model, and it is why there is no `speak_as` parameter.
    """

    def __init__(self, registry_url: str, transport: Optional[httpx.AsyncBaseTransport] = None,
                 timeout: float = 30.0):
        self.base = registry_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    # ── plumbing ────────────────────────────────────────────────────────────
    async def _request(self, method: str, path: str, jwt: Optional[str] = None,
                       json: Optional[dict] = None, params: Optional[dict] = None) -> Any:
        headers = {"Authorization": f"Bearer {jwt}"} if jwt else {}
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as c:
            r = await c.request(method, f"{self.base}/api/v1/chat{path}",
                                headers=headers, json=json, params=params)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:  # noqa: BLE001
                detail = r.text
            raise MessengerError(r.status_code, detail)
        return r.json() if r.content else None

    @staticmethod
    def _ref() -> str:
        """A fresh idempotency key. Reuse one deliberately to make a retry
        replay instead of duplicating — the schema enforces it, not luck."""
        return str(uuid.uuid4())

    # ── reading ─────────────────────────────────────────────────────────────
    async def threads(self, jwt: str, state: str = "active", limit: int = 30) -> List[dict]:
        """Your threads. `state='requests'` is the strangers' lane — messages
        there are real, but the sender is waiting on your acceptance."""
        data = await self._request("GET", "/conversations", jwt,
                                   params={"state": state, "limit": limit})
        return data.get("conversations", [])

    async def messages(self, jwt: str, conversation_id: str, before_seq: Optional[int] = None,
                       limit: int = 40) -> dict:
        params: Dict[str, Any] = {"limit": limit}
        if before_seq:
            params["before_seq"] = before_seq
        return await self._request("GET", f"/conversations/{conversation_id}/messages",
                                   jwt, params=params)

    async def sync(self, jwt: str, since_iso: Optional[str] = None) -> dict:
        """Everything in your active threads since a timestamp. The response
        STATES its own bounds — read them; a truncated page that looks complete
        is how a poll loop silently drops work."""
        return await self._request("GET", "/sync", jwt,
                                   params={"since": since_iso} if since_iso else None)

    async def ack(self, jwt: str, conversation_id: str, seq: int) -> dict:
        """Acknowledge up to `seq`. Monotonic: acking an older seq is a no-op,
        so a retry can never un-read something."""
        return await self._request("POST", "/inbox/ack", jwt,
                                   json={"conversation_id": conversation_id, "seq": seq})

    async def poll_once(self, jwt: str, seen: Optional[set] = None,
                        include_requests: bool = False) -> List[dict]:
        """ONE polling pass: the messages addressed to you that `seen` has not
        already returned, oldest-first. Split out of `listen` deliberately —
        a loop with a timer inside is untestable without timers, and a probe
        that needs a stopwatch to answer is a probe that will one day hang
        instead of failing."""
        out: List[dict] = []
        lanes = ["active", "requests"] if include_requests else ["active"]
        for lane in lanes:
            for th in await self.threads(jwt, state=lane, limit=30):
                cid = th.get("id")
                unread = int(th.get("unread") or 0)
                if not cid or unread <= 0:
                    continue
                page = await self.messages(jwt, cid, limit=min(unread, 40))
                for m in page.get("messages", []):
                    key = (cid, m.get("id"))
                    if seen is not None:
                        if key in seen:
                            continue
                        seen.add(key)
                    m["conversation_id"] = cid
                    out.append(m)
        return out

    async def listen(self, jwt: str, interval: float = 5.0,
                     include_requests: bool = False) -> AsyncIterator[dict]:
        """Poll for messages addressed to you and yield them oldest-first.

        AT-LEAST-ONCE by construction: a message is yielded before it is acked,
        and acking is YOUR call (`ack()` after your handler succeeds). A crash
        mid-handler therefore replays rather than loses — and because every
        send carries a `client_ref`, your own replies stay idempotent through
        that replay.
        """
        seen: set = set()
        while True:
            try:
                for m in await self.poll_once(jwt, seen, include_requests):
                    yield m
            except MessengerError as e:
                # A poll loop that dies on one bad response is a poll loop that
                # silently stops working. Log and keep the cadence.
                logger.warning("messenger poll failed (%s); retrying", e)
            except Exception as e:  # noqa: BLE001
                logger.warning("messenger poll error: %s; retrying", e)
            if len(seen) > 5000:
                seen = set(list(seen)[-2000:])
            await asyncio.sleep(interval)

    # ── writing (text + the CLIENT-POSTABLE cards only) ─────────────────────
    async def open_thread(self, jwt: str, *, developer_id: Optional[int] = None,
                          handle: Optional[str] = None, agent_did: Optional[str] = None,
                          kind: str = "dm", first_message: Optional[str] = None) -> dict:
        """Open (or dedup-return) a thread. Address by developer id, by `@handle`
        (§OURSTATE-3), or by an agent DID for a service thread."""
        if agent_did:
            target = {"ptype": "agent", "agent_did": agent_did}
        elif handle:
            target = {"ptype": "developer", "handle": handle}
        elif developer_id is not None:
            target = {"ptype": "developer", "developer_id": developer_id}
        else:
            raise ValueError("address the thread by developer_id, handle or agent_did")
        body: Dict[str, Any] = {"kind": kind, "target": target}
        if first_message:
            body["first_message"] = {"kind": "text", "body": first_message,
                                     "client_ref": self._ref()}
        return await self._request("POST", "/conversations", jwt, json=body)

    async def reply(self, jwt: str, conversation_id: str, text: str,
                    client_ref: Optional[str] = None) -> dict:
        """Send one text message. Pass your own `client_ref` to make a retry
        replay the original instead of posting twice."""
        return await self._request(
            "POST", f"/conversations/{conversation_id}/messages", jwt,
            json={"kind": "text", "body": text, "client_ref": client_ref or self._ref()})

    async def send_card(self, jwt: str, conversation_id: str, card: dict,
                        client_ref: Optional[str] = None) -> dict:
        """Post a typed card. The vocabulary is CLOSED server-side: pay.request,
        pay.receipt, agent.card and the WORK pointers are client-postable;
        service records are written only by the registry's own rail, and an
        unknown type is refused by name. Use the builders below."""
        return await self._request(
            "POST", f"/conversations/{conversation_id}/messages", jwt,
            json={"kind": "card", "card": card, "client_ref": client_ref or self._ref()})

    # ── card builders (mirrors of services/chat/cards.ts) ───────────────────
    @staticmethod
    def pay_request(amount: str, currency: str, memo: str = "") -> dict:
        """Ask to be paid. This is an ASK — it moves nothing; the payer's own
        send door does, with their own confirmation."""
        data: Dict[str, Any] = {"amount": str(amount), "currency": currency}
        if memo:
            data["memo"] = memo[:240]
        return {"v": 1, "type": "pay.request", "data": data}

    @staticmethod
    def agent_card(did: str, name: str = "") -> dict:
        """Share an agent into the thread."""
        data: Dict[str, Any] = {"did": did}
        if name:
            data["name"] = name[:120]
        return {"v": 1, "type": "agent.card", "data": data}

    @staticmethod
    def work_pointer(kind: str, ref: str, title: str, amount: Optional[str] = None,
                     currency: Optional[str] = None, status: str = "") -> dict:
        """Point at a contract or guild order you are a party to. A POINTER:
        awarding, delivering and settling stay on the work rail itself."""
        if kind not in ("contract.offer", "guild.order"):
            raise ValueError("kind must be 'contract.offer' or 'guild.order'")
        data: Dict[str, Any] = {"ref": str(ref)[:128], "title": str(title)[:200]}
        if amount is not None and currency:
            data["amount"] = str(amount)
            data["currency"] = currency
        if status:
            data["status"] = status[:40]
        return {"v": 1, "type": kind, "data": data}

    # ── thread state ────────────────────────────────────────────────────────
    async def accept(self, jwt: str, conversation_id: str) -> dict:
        """Accept a request thread. Replying accepts it too — this is for
        accepting without speaking yet."""
        return await self._request("POST", f"/conversations/{conversation_id}/accept", jwt, json={})

    async def decline(self, jwt: str, conversation_id: str) -> dict:
        return await self._request("POST", f"/conversations/{conversation_id}/decline", jwt, json={})

    async def leave(self, jwt: str, conversation_id: str) -> dict:
        return await self._request("POST", f"/conversations/{conversation_id}/leave", jwt, json={})

    # ── handles (§OURSTATE-3) ───────────────────────────────────────────────
    async def profile(self, handle: str) -> dict:
        """The public card behind a handle. No auth: this is the page a contact
        QR opens."""
        return await self._request("GET", f"/handles/{handle.lstrip('@')}")
