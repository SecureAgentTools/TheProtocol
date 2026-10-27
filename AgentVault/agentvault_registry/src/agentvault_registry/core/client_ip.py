"""The one answer to "who is calling?" — forge-proof, in one place.

Two facts about this deployment make the textbook idioms wrong here:

1. nginx sets ``X-Forwarded-For $proxy_add_x_forwarded_for``, which APPENDS the
   real peer to whatever the caller already sent. The LAST element is the one
   our own edge wrote; everything before it is caller-supplied. Reading the
   FIRST element — the usual idiom, and exactly what uvicorn's ProxyHeaders
   middleware does under ``forwarded_allow_ips="*"`` — lets a caller choose its
   own address. Measured 2026-08-27: ``curl -H "X-Forwarded-For: 203.0.113.77"``
   against the public API made the registry log ``203.0.113.77:0`` as the
   client. So ``request.client.host`` — and therefore
   ``slowapi.util.get_remote_address``, which just returns it — is
   ATTACKER-CONTROLLED and must never key a rate limit or an audit row.

2. ``X-Real-IP $remote_addr`` REPLACES rather than appends, so it is
   trustworthy whenever it is present.

``is_internal_request`` is deliberately CONJUNCTIVE: no proxy headers AND an
RFC1918/loopback peer. Either half alone is forgeable — a caller reaching a
published container port directly sends no headers (but carries a public source
address), and one sending ``X-Forwarded-For: 10.0.0.1`` gets a private-looking
``client.host`` (but carries headers). Requiring both closes the gap without
depending on the firewall. This is the same reasoning as
``middleware/admission_control.py::_classify_lane``, with the address test added.
"""

import ipaddress
from typing import Optional


def effective_client_ip(request) -> Optional[str]:
    """The peer address our own edge observed — the only one a caller cannot forge."""
    if request is None:
        return None
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    return request.client.host if request.client else None


def is_internal_request(request) -> bool:
    """True only for traffic that never traversed our edge AND came from a
    private/loopback peer: on-box scripts (the sim runs host-networked and
    reaches published ports as the docker bridge gateway), container-to-container
    federation hops, and self-calls. See the module docstring for why both
    halves are required."""
    if request is None:
        return False
    headers = request.headers
    if "x-forwarded-for" in headers or "x-real-ip" in headers:
        return False
    host = request.client.host if request.client else None
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback


class SocketPeerClientMiddleware:
    """§MTLSHOPS V0379 (2026-09-15): a unix-socket request takes the address its door named.

    On a socket the ASGI scope carries no client: uvicorn reads getpeername(), which is not a (host, port) pair for
    AF_UNIX. The doors are the only peers a socket has, and each names the caller in X-Real-IP (nginx-registry its own
    $remote_addr, nginx-edge the host vhost's value or its own peer), so a request with no client takes that address. A
    TCP request always has a peer and is never touched. A request with no X-Real-IP (a process inside the container), or
    with a value that is not an address, keeps no client.

    The name decides nothing about trust: ``is_internal_request`` refuses any request that carries X-Real-IP, so nothing
    becomes internal by arriving on the socket (tests/test_socket_peer_lane.py). Pure ASGI, mounted last in main.py so it
    runs before every middleware that reads ``request.client``.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") in ("http", "websocket") and scope.get("client") is None:
            named = None
            for key, value in scope.get("headers") or ():
                if key == b"x-real-ip":
                    named = value
            if named is not None:
                try:
                    scope["client"] = (str(ipaddress.ip_address(named.decode("latin-1").strip())), 0)
                except ValueError:
                    pass  # not an address: the request keeps no client, exactly as it arrived
        await self.app(scope, receive, send)
