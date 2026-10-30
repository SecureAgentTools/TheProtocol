"""§SECFIX D6-823 (agentvault2-13, 2026-10-30; the Maintainer's approval that day): the public /metrics carries no
system balance.

/metrics stays public (D6-254, his word: kept for development, a switch per registry), but EU's and ASIA's consoles
proxied it with agora_escrow_balance (the exchange's escrow holdings) and fx_reserve_keeper_reserve (the FX reserve),
balances of the treasury's class, which D6-254 had already taken out for the treasury itself. A request that reached
the registry through a proxy (it carries X-Forwarded-For, X-Real-IP or Forwarded, which every console vhost and the
kit's console template set) gets /metrics without those two families; the frame's own Prometheus scrapes the registry
directly (eu-registry:8000, the kit's job alike), carries none of those headers and keeps them. No alert rule or
dashboard reads either family (monitoring/ and templates/, read 2026-10-30). The supply audit's figures stay public by
design, as /api/v1/projections/supply-audit is.
"""
from __future__ import annotations

from typing import Iterable, List, Tuple

WITHHELD = ("agora_escrow_balance", "fx_reserve_keeper_reserve")
_PROXY_HEADERS = (b"x-forwarded-for", b"x-real-ip", b"forwarded")


def proxied(headers: Iterable[Tuple[bytes, bytes]]) -> bool:
    """Whether the request came through a proxy: any forwarding header at all (a proxy adds them; a caller cannot
    remove what the console's nginx appends)."""
    return any(k.lower() in _PROXY_HEADERS for k, _ in headers)


def _family(line: bytes) -> bytes:
    """The metric family a line of the text exposition belongs to (b"" for a blank or a free comment)."""
    if line.startswith(b"# HELP ") or line.startswith(b"# TYPE "):
        parts = line.split(b" ", 3)
        return parts[2] if len(parts) > 2 else b""
    if not line or line.startswith(b"#"):
        return b""
    for i, c in enumerate(line):
        if c in b"{ ":
            return line[:i]
    return line


def withhold(body: bytes, names: Tuple[str, ...] = WITHHELD) -> bytes:
    """The exposition without the named families: their HELP, TYPE and every sample line, nothing else."""
    drop = {n.encode() for n in names}
    keep: List[bytes] = [ln for ln in body.split(b"\n") if _family(ln) not in drop]
    return b"\n".join(keep)


class PublicMetricsMiddleware:
    """Pure ASGI: on GET /metrics through a proxy, the response body is read whole, filtered and re-sent with its own
    Content-Length. Every other request passes untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") != "/metrics" or not proxied(scope.get("headers") or []):
            await self.app(scope, receive, send)
            return
        start = None
        chunks: List[bytes] = []

        async def _send(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            if message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = withhold(b"".join(chunks))
                headers = [(k, v) for k, v in (start or {}).get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**(start or {"type": "http.response.start", "status": 200}), "headers": headers})
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            await send(message)

        await self.app(scope, receive, _send)
