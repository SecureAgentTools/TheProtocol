"""Shared STRICT test doubles (batch 2, item 2 — 07's generalisation of §EMITKEY: a double that
accepts everything is the same defect as a gate whose control never goes red).

StrictEmitter stands in for EventEmitter with the REAL signatures: every `emit*` attribute binds
its call against `inspect.signature(EventEmitter.<name>)` — a wrong keyword raises HERE, inside
the test, instead of vanishing into the caller's except-and-log — and records what it received,
so a test can ASSERT RECEIPT of the event and its idempotency key.
"""
from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional

from agentvault_registry.event_emitter import EventEmitter


class StrictEmitter:
    def __init__(self) -> None:
        self.received: List[Dict[str, Any]] = []

    def __getattr__(self, name: str):
        real = getattr(EventEmitter, name, None)
        if real is None or not name.startswith("emit"):
            raise AttributeError(f"StrictEmitter: EventEmitter has no '{name}' — a fake that invents methods proves nothing")
        sig = inspect.signature(real)

        async def _recorder(*args, **kwargs):
            bound = sig.bind(self, *args, **kwargs)     # TypeError here = the caller's signature is wrong
            bound.apply_defaults()
            rec = {k: v for k, v in bound.arguments.items() if k != "self"}
            rec["_method"] = name
            self.received.append(rec)
            return True
        return _recorder

    # ── assertions ──────────────────────────────────────────────────────────────────
    def of_type(self, event_type: str) -> List[Dict[str, Any]]:
        return [r for r in self.received if r.get("event_type") == event_type]

    def assert_received(self, event_type: str, *, key: Optional[str] = None, via: str = "emit") -> Dict[str, Any]:
        hits = self.of_type(event_type)
        assert hits, f"no {event_type} reached the emitter; received={[r.get('event_type') for r in self.received]}"
        if via:
            assert hits[-1]["_method"] == via, f"{event_type} arrived through {hits[-1]['_method']}, not {via}"
        if key is not None:
            assert hits[-1].get("idempotency_key") == key, f"key={hits[-1].get('idempotency_key')!r} want {key!r}"
        return hits[-1]

    def assert_nothing_received(self) -> None:
        assert not self.received, [r.get("event_type") for r in self.received]


def resolve_names_publicly(monkeypatch, address: str = "93.184.216.34") -> None:
    """SEC-14 (2026-10-17): a webhook delivery resolves its host itself and connects only to an address that lookup
    checked, so a test whose receiver is a name nothing resolves (`receiver.invalid`) answers every name with one public
    address. Such a name used to pass the check (a host that resolves to nothing was let through) and was then handed to
    the HTTP client, which a client double never asked to resolve."""
    import socket

    def getaddrinfo(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


class RecordingWebhookClient:
    """V0662 (item 16): a webhook send goes through the outbound guard, which drives a real httpx client's connection
    layer, so a test's stand-in for WebhookService.client is a real httpx.AsyncClient whose transport records each
    request and answers `code`. Each request is handed to `record(entry)` as {"url", "content", "headers", "extensions"} (the headers
    an httpx.Headers, read by any case); a test file shapes what it keeps by overriding `record`. `pause` yields to
    the event loop inside the send (a fan-out test lets the other delivery run)."""

    def __new__(cls, code: int = 200, pause: bool = False):
        import asyncio

        import httpx

        holder = super().__new__(cls)
        holder.code, holder.received, holder.urls = code, [], []

        async def handle(request):
            holder.urls.append(str(request.url))
            holder.record({"url": str(request.url), "content": request.content, "headers": request.headers,
                           "extensions": dict(request.extensions)})
            if pause:
                await asyncio.sleep(0)
            return httpx.Response(holder.code, text="ok" if holder.code < 300 else "nope")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handle), timeout=5)
        client.received, client.urls = holder.received, holder.urls
        client.holder = holder
        return client

    def record(self, entry: Dict[str, Any]) -> None:
        self.received.append(entry)
