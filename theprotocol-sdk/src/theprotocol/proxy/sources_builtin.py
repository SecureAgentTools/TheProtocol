"""The core's own source: an HTTP webhook receiver, for anything that can POST JSON.

    sources:
      gate:
        type: webhook
        config:
          listen: 0.0.0.0:8711          # host:port this receiver listens on (the only port a proxy ever opens)
          path: /in/gate
          id_field: event_id            # the sender's own stable id for the item: a key, or a $.path into the body
          secret: env:GATE_HMAC         # HMAC-SHA256 key (a reference): each POST carries X-Signature-256: sha256=<hex>

A POST carries one JSON object, or a JSON array of them (each is one record). The receiver answers 202 only once every
record of the POST is in the proxy's outbox (so a 202 means the proxy has it, durably); a POST it could not keep in
time answers 503 with Retry-After, and the sender sends it again (a record already kept is not kept twice: its id is the
same). A body that is not signed with the secret answers 401, one that is not JSON or has a record without its id 400,
one larger than max_bytes 413. Without a secret the receiver listens only on a loopback address. In a dry run every
record is mapped and shown, never kept, so the receiver answers 503 ("dry run: send it again") and the sender keeps it.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from .mapping import _MISSING, lookup
from .plugins import PluginError, Record, Source


def _loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def signature(secret: str, body: bytes) -> str:
    """The X-Signature-256 value a sender puts on `body`."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class WebhookSource(Source):
    name = "webhook"
    description = "An HTTP receiver: each POSTed JSON object is a record, answered 202 once it is in the outbox"
    config_schema = {
        "type": "object",
        "required": ["listen", "path"],
        "additionalProperties": False,
        "properties": {
            "listen": {"type": "string", "pattern": r"^[^:]*:\d+$"},
            "path": {"type": "string", "pattern": "^/"},
            "id_field": {"type": "string", "minLength": 1},
            "secret": {"type": "string", "x-secret": True},
            "signature_header": {"type": "string", "minLength": 1},
            "max_bytes": {"type": "integer", "minimum": 1024},
            "commit_timeout_s": {"type": "number", "exclusiveMinimum": 0},
        },
    }

    def __init__(self, config, ctx):
        super().__init__(config, ctx)
        self._queue: "asyncio.Queue[Tuple[Record, asyncio.Future]]" = asyncio.Queue()
        self._waiting: Dict[int, asyncio.Future] = {}
        self._runner = None
        self._secret: Optional[str] = None
        self.port: Optional[int] = None       # the port bound (listen may name 0: any free port)

    @property
    def _host_port(self) -> Tuple[str, int]:
        host, _, port = self.config["listen"].rpartition(":")
        return host or "127.0.0.1", int(port)

    async def start(self) -> None:
        from aiohttp import web
        host, port = self._host_port
        ref = self.config.get("secret")
        if ref:
            self._secret = self.ctx.secret(ref)
            if not self._secret:
                raise PluginError("the webhook's secret resolves to nothing")
        elif not _loopback(host):
            raise PluginError(f"the webhook on {host}:{port} has no secret: a receiver on an address others can reach "
                              f"takes only signed POSTs (set secret, a reference), or listen on 127.0.0.1")
        app = web.Application(client_max_size=int(self.config.get("max_bytes") or 1048576))
        app.router.add_post(self.config["path"], self._post)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        sockets = getattr(getattr(site, "_server", None), "sockets", None) or []
        self.port = sockets[0].getsockname()[1] if sockets else port

    async def stop(self) -> None:
        for fut in self._waiting.values():
            if not fut.done():
                fut.cancel()
        self._waiting.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def signed(self, headers: Any, body: bytes) -> bool:
        """The body carries this receiver's signature (X-Signature-256: sha256=<hex HMAC-SHA256 of the body>)."""
        got = headers.get(self.config.get("signature_header") or "X-Signature-256", "")
        return bool(got) and hmac.compare_digest(got.strip(), signature(self._secret or "", body))

    def records_from(self, doc: Any, headers: Any, body: bytes) -> Tuple[List[Record], Optional[str]]:
        """The records a POSTed document carries (an object, or an array of them), or the problem with it."""
        items = doc if isinstance(doc, list) else [doc]
        records: List[Record] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                return [], f"item {i} is not a JSON object"
            rid = self._record_id(item)
            if rid is None:
                return [], f"item {i} has no {self.config.get('id_field') or 'id'}"
            records.append(Record(record_id=rid, payload=item, meta={"via": "webhook", "path": self.config["path"]}))
        return records, None

    def _record_id(self, item: Dict[str, Any]) -> Optional[str]:
        field = self.config.get("id_field") or "id"
        v = lookup(item, field) if field.startswith("$") else item.get(field, _MISSING)
        if v is _MISSING or v is None or (isinstance(v, str) and not v.strip()):
            return None
        return str(v)

    async def _post(self, request):
        from aiohttp import web
        try:
            body = await request.read()
        except web.HTTPRequestEntityTooLarge:
            return web.json_response({"detail": "the body is larger than this receiver takes"}, status=413)
        if self._secret is not None and not self.signed(request.headers, body):
            return web.json_response({"detail": "the body is not signed with this receiver's secret"}, status=401)
        try:
            doc = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return web.json_response({"detail": "the body is not JSON"}, status=400)
        records, problem = self.records_from(doc, request.headers, body)
        if problem:
            return web.json_response({"detail": problem}, status=400)
        loop = asyncio.get_running_loop()
        futures = []
        for rec in records:
            fut = loop.create_future()
            self._waiting[id(rec)] = fut
            futures.append(fut)
            await self._queue.put((rec, fut))
        if self.ctx.dry_run:
            for rec in records:
                self._waiting.pop(id(rec), None)
            return web.json_response({"detail": "dry run: mapped and shown, not kept; send it again"}, status=503,
                                     headers={"Retry-After": "60"})
        try:
            await asyncio.wait_for(asyncio.gather(*futures), timeout=float(self.config.get("commit_timeout_s") or 30))
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return web.json_response({"detail": "not kept in time; send it again"}, status=503,
                                     headers={"Retry-After": "5"})
        finally:
            for rec in records:
                self._waiting.pop(id(rec), None)
        return web.json_response({"accepted": len(records), "ids": [r.record_id for r in records]}, status=202)

    async def records(self) -> AsyncIterator[Record]:
        while True:
            rec, _fut = await self._queue.get()
            yield rec

    async def committed(self, record: Record) -> None:
        fut = self._waiting.get(id(record))
        if fut is not None and not fut.done():
            fut.set_result(True)


class TheProtocolEventsSource(WebhookSource):
    """TheProtocol's own events, as the registry's webhooks deliver them, for the outbound mappings (to sinks).

        sources:
          events:
            type: theprotocol_events
            config: {listen: "0.0.0.0:8712", path: /in/theprotocol, secret: env:TP_WEBHOOK_SECRET}

    The proxy's owner registers this receiver's URL as a webhook in the console (Developer, Webhooks) and gives its
    secret to the spec by reference. Every delivery is checked against it: X-TheProtocol-Signature is the hex
    HMAC-SHA256 of the exact body, and a body that does not verify answers 401. A delivery is one record: its id is the
    delivery's id (the registry sends a retry of a delivery under the same id), its payload the event's data, and its
    meta the event (type, agent, time) and what makes it verifiable later: the signed body and its signature, which
    the evidence export keeps and tp-proxy verify --webhook-secret checks."""
    name = "theprotocol_events"
    description = "The registry's webhooks: each signed delivery is one record of TheProtocol's events"
    config_schema = {
        "type": "object",
        "required": ["listen", "path", "secret"],
        "additionalProperties": False,
        "properties": {
            "listen": {"type": "string", "pattern": r"^[^:]*:\d+$"},
            "path": {"type": "string", "pattern": "^/"},
            "secret": {"type": "string", "x-secret": True},
            "events": {"type": "array", "items": {"type": "string"}},
            "max_bytes": {"type": "integer", "minimum": 1024},
            "commit_timeout_s": {"type": "number", "exclusiveMinimum": 0},
        },
    }

    def signed(self, headers: Any, body: bytes) -> bool:
        got = (headers.get("X-TheProtocol-Signature", "") or "").strip()
        want = hmac.new((self._secret or "").encode("utf-8"), body, hashlib.sha256).hexdigest()
        return bool(got) and hmac.compare_digest(got, want)

    def records_from(self, doc: Any, headers: Any, body: bytes) -> Tuple[List[Record], Optional[str]]:
        if not isinstance(doc, dict) or not doc.get("id") or not doc.get("event"):
            return [], "not a TheProtocol webhook delivery (id, event, data)"
        wanted = self.config.get("events")
        if wanted and doc["event"] not in wanted:
            return [], None          # signed and well formed, not an event this proxy takes: answered, kept nowhere
        data = doc.get("data") if isinstance(doc.get("data"), dict) else {"value": doc.get("data")}
        meta = {"via": "theprotocol_webhook", "event_type": doc["event"], "aggregate_id": doc.get("agent_did") or "",
                "occurred_at": doc.get("timestamp"),
                "ledger": {"delivery_id": doc["id"], "signed_body": body.decode("utf-8"),
                           "signature": headers.get("X-TheProtocol-Signature", ""),
                           "event_id": (data or {}).get("event_id"), "sequence": (data or {}).get("sequence")}}
        return [Record(record_id=str(doc["id"]), payload=data, meta=meta)], None
