"""One guard for outbound fetches a user, a card, a bundle or a peer can address (V0659 (p)).

The registry fetches addresses it is handed: an agent card's endpoint, a webhook, a bundle's source, a link a peer
sends. Every such fetch goes through this module, so the rule lives in one place.

THE RULE
  * A destination is fetched only when every address its host name resolves to is a public unicast address.
    Public means two answers agree: ipaddress calls it is_global (an IPv4-mapped IPv6 address judged as the IPv4
    address it carries), and the rule webhook URLs already follow (input_validators._is_internal_address: private,
    loopback, link-local, multicast, reserved, unspecified, an IPv4 address carried in 6to4) does not call it
    internal. A name with one public and one non-public address is refused. A special-use name (localhost and the
    TLDs the agent-card pull never asks, agent_card_pullsync.reserved_tld_of) is refused without a lookup. A name
    that resolves to nothing is not a refusal: there is nothing to connect to, and the fetch fails as httpx fails
    it, with a ConnectError.
  * The connection then goes to one of the addresses that were checked. The request is sent to that address and
    still names its host: the Host header and, for https, the TLS server name, so the certificate is verified for
    the name. Nothing looks the name up a second time, so the answer cannot change between the check and the
    connection. Every request asks for its connection to be closed after the answer, so a connection made for one
    name is never reused for another name that shares its address. When connecting fails (nothing was sent), the
    next checked address is tried.
  * Redirects are never followed by the HTTP client on its own. GuardedClient.fetch(..., max_redirects=n) follows up
    to n of them, and every hop goes through the same check as the first address: a hop that fails it, or one hop
    more than allowed, refuses the request.
  * A refusal raises OutboundRefused (an httpx.RequestError, so a call site's existing handlers still see a failed
    request), counts registry_outbound_refused_total{site, reason} and logs one WARNING line with the site, the
    class of refusal and the hop, never the address.
  * The sandbox allowance is explicit and off by default: OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE lets the private
    network ranges through (10/8, 172.16/12, 192.168/16, fc00::/7, where a sandbox's containers live), and only
    where the registry's sandbox flag is set (the one the agent-card pull reads, agent_card_pullsync._is_sandbox_mode).
    Loopback, link-local, unspecified, multicast, the special-use names and every other non-public range stay
    refused there too.

Addresses an operator sets (the environment, admin peer rows) are not what this guards; they keep their own clients.

FOR A CALL SITE
    async with guarded_client("agent_card_pull", timeout=10.0) as client:     # in place of httpx.AsyncClient(...)
        resp = await client.fetch("GET", url, headers=headers, max_redirects=3)
    resp = await guarded_request("POST", url, site="webhook_delivery", content=body, headers=headers)
    except OutboundRefused as e:                                              # e.site, e.reason, e.hop
inspect_destination(url) answers what the guard would decide: it resolves the name and fetches, counts and logs
nothing (for a count of stored addresses the guard would refuse). A site that does its own sending, so that the
guard can only be ASKED (pywebpush), records its refusal in the guard's series itself:
    verdict = await inspect_destination(target)
    if verdict.refusal:
        record_refusal("webpush", verdict.refusal)    # counted and logged exactly as a raised refusal is
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union

import httpx

from .. import input_validators as _input_validators
from .tls_client import client_cert_verify

logger = logging.getLogger(__name__)

__all__ = [
    "Destination", "GuardedClient", "GuardedTransport", "OutboundRefused", "REASONS", "SANDBOX_PRIVATE_ENV",
    "address_refusal", "guarded_client", "guarded_request", "inspect_destination", "record_refusal",
    "sandbox_private_allowed",
]

SANDBOX_PRIVATE_ENV = "OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE"

# The classes of refusal: the counter's `reason` label and the log line's (a fixed set, so the label stays small).
REASONS = (
    "scheme",          # not http or https
    "malformed",       # the address names no host, or is not an address at all
    "reserved_name",   # a special-use name: localhost, .localhost, .local, .invalid, .test, .example
    "loopback",
    "unspecified",
    "link_local",
    "multicast",
    "private",         # 10/8, 172.16/12, 192.168/16, fc00::/7
    "non_global",      # any other address that is not public: shared, documentation, benchmarking, reserved, ...
    "redirect_limit",  # one redirect more than the caller allows
)

# A request extension the guard sets on a redirect it follows, so a refusal can say which hop it was.
HOP_EXTENSION = "outbound_guard_hop"
# How many of the checked addresses one request tries, in the resolver's order, when connecting fails.
MAX_ADDRESSES_TRIED = 4
# The bound on a name lookup when the request carries no connect timeout of its own.
RESOLVE_TIMEOUT_SEC = 10.0

_SITE_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_NETWORK_PRIVATE = tuple(ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                                                            "fc00::/7"))
_DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)
_TRUE = ("1", "true", "yes")
_NO_AUTOMATIC_REDIRECTS = ("a guarded client never follows a redirect by itself: "
                           "fetch(..., max_redirects=n) follows up to n, checking every hop like the first address")

_Address = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

try:  # pragma: no cover - import guard, as elsewhere in this codebase
    from prometheus_client import Counter as _Counter

    OUTBOUND_REFUSED_TOTAL = _Counter(
        "registry_outbound_refused_total",
        "Outbound fetches the outbound guard refused before connecting, by calling site and class of refusal",
        ["site", "reason"],
    )
except Exception:  # pragma: no cover - metrics never decide a fetch
    OUTBOUND_REFUSED_TOTAL = None


def _count_refusal(site: str, reason: str) -> None:
    if OUTBOUND_REFUSED_TOTAL is not None:
        try:
            OUTBOUND_REFUSED_TOTAL.labels(site=site, reason=reason).inc()
        except Exception:  # never let bookkeeping change the decision
            pass


class OutboundRefused(httpx.RequestError):
    """The guard refused an outbound fetch before connecting. `site` is the calling site's name, `reason` one of
    REASONS, `hop` "first" or "redirect". The text names no address."""

    def __init__(self, site: str, reason: str, hop: str = "first", *, request: Optional[httpx.Request] = None) -> None:
        self.site = site
        self.reason = reason
        self.hop = hop
        super().__init__(f"outbound fetch refused: site={site} reason={reason} hop={hop}", request=request)


def _refuse(site: str, reason: str, hop: str, request: Optional[httpx.Request] = None) -> OutboundRefused:
    """Count and log one refusal; return the exception for the caller to raise. The counting and the log line are
    record_refusal's, so a refusal the guard raises and one a call site decides land in one series, in one wording."""
    record_refusal(site, reason, hop)
    return OutboundRefused(site, reason, hop, request=request)


def _site_name(site: Any) -> str:
    if not isinstance(site, str) or not _SITE_RE.fullmatch(site):
        raise ValueError("an outbound guard site is a short snake_case name such as agent_card_pull "
                         "(it becomes the refusal counter's site label)")
    return site


def record_refusal(site: str, reason: str, hop: str = "first") -> None:
    """Count and log one refusal a call site decided for itself, in the guard's own series and its own words.

    For a call site that asks inspect_destination and then refuses without sending at all (a web-push endpoint it
    will not register, a notification it skips): the refusal lands in registry_outbound_refused_total{site, reason}
    beside every refusal the guard raises, and in the same single WARNING line, which names no address. `reason` must
    be one of REASONS and `site` a site name, so the counter's label sets stay bounded; anything else is a ValueError
    rather than a new label, because a metric label nobody chose is unbounded cardinality in production.
    """
    site = _site_name(site)
    if reason not in REASONS:
        raise ValueError(f"an outbound refusal reason is one of {', '.join(REASONS)} (not {reason!r}), so the "
                         "refusal counter's reason label stays a fixed set")
    _count_refusal(site, reason)
    logger.warning("outbound fetch refused: site=%s reason=%s hop=%s", site, reason, hop)


# --- the address rule ------------------------------------------------------------------------------------------

def _as_address(value: Any) -> Optional[_Address]:
    if isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return value
    try:
        return ipaddress.ip_address(str(value).strip().strip("[]").split("%", 1)[0])
    except ValueError:
        return None


def address_refusal(address: Any) -> Optional[str]:
    """None when `address` is a public unicast address; otherwise its class of refusal (one of REASONS).

    Public: ipaddress's is_global, with an IPv4-mapped IPv6 address judged as the IPv4 address it carries, and not
    internal by input_validators' rule. The class names the address a mapped or 6to4 address carries. The sandbox
    allowance is not applied here: this is the rule itself."""
    ip = _as_address(address)
    if ip is None:
        return "malformed"
    mapped = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) else None
    if (mapped or ip).is_global and not _input_validators._is_internal_address(ip):
        return None
    carried = mapped or (ip.sixtofour if isinstance(ip, ipaddress.IPv6Address) else None)
    subject = carried or ip
    if subject.is_unspecified:
        return "unspecified"
    if subject.is_loopback:
        return "loopback"
    if subject.is_link_local:
        return "link_local"
    if subject.is_multicast:
        return "multicast"
    if any(subject in net for net in _NETWORK_PRIVATE if net.version == subject.version):
        return "private"
    return "non_global"


def _registry_in_sandbox() -> bool:
    """The registry's sandbox flag: the one the agent-card pull reads (SANDBOX_MODE, or CC_TARGET_ENVIRONMENT=sandbox).
    Imported when asked, so the pull-sync can import this module."""
    from ..background_tasks.agent_card_pullsync import _is_sandbox_mode
    return bool(_is_sandbox_mode())


def sandbox_private_allowed() -> bool:
    """True only when OUTBOUND_GUARD_SANDBOX_ALLOW_PRIVATE is set AND the registry's sandbox flag is set."""
    return (os.getenv(SANDBOX_PRIVATE_ENV) or "").strip().lower() in _TRUE and _registry_in_sandbox()


def _refusal_here(ip: _Address) -> Optional[str]:
    """The rule, with the sandbox allowance applied: in a sandbox that allows it, a private address goes ahead."""
    reason = address_refusal(ip)
    if reason == "private" and sandbox_private_allowed():
        return None
    return reason


def _reserved_name(name: str) -> bool:
    """A special-use name, by the agent-card pull's own list (one list for the pull, create_agent and this guard)."""
    from ..background_tasks.agent_card_pullsync import reserved_tld_of
    return reserved_tld_of(f"http://{name}/") is not None


# --- the decision ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Destination:
    """What the guard decides about one address, before anything connects.

    `refusal` is the class of refusal, or None when the fetch may go ahead. `addresses` are the checked addresses a
    connection may use, in the resolver's order: empty when refused, and empty with `resolved` False when the name
    resolves to nothing (not a refusal). `literal`: the host is written as an address, connected to as written."""
    host: str
    port: int
    refusal: Optional[str]
    addresses: Tuple[str, ...] = ()
    resolved: bool = False
    literal: bool = False


async def _resolve(name: str, port: int, timeout: Optional[float]) -> List[_Address]:
    """Every address `name` resolves to, in the resolver's order; [] when it resolves to nothing. A lookup that does not
    answer within `timeout` raises TimeoutError."""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(name, port, type=socket.SOCK_STREAM), timeout)
    except TimeoutError:
        raise
    except (OSError, UnicodeError):
        return []
    found: List[_Address] = []
    for info in infos:
        try:
            ip = _as_address(info[4][0])
        except Exception:
            ip = None
        if ip is not None and ip not in found:
            found.append(ip)
    return found


def _connect_form(ip: _Address) -> str:
    """The address a connection uses: an IPv4-mapped address as the IPv4 address it carries."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return str(ip.ipv4_mapped)
    return str(ip)


async def _decide(url: httpx.URL, timeout: Optional[float]) -> Destination:
    scheme = (url.scheme or "").lower()
    try:
        host = url.raw_host.decode("ascii").lower()
    except Exception:
        host = ""
    port = url.port or (443 if scheme == "https" else 80)
    if scheme not in ("http", "https"):
        return Destination(host, port, "scheme")
    if not host:
        return Destination(host, port, "malformed")
    literal = _as_address(host)
    if literal is not None:
        reason = _refusal_here(literal)
        return Destination(host, port, reason, () if reason else (str(literal),), True, True)
    name = host[:-1] if host.endswith(".") else host
    if not name:
        return Destination(host, port, "malformed")
    if _reserved_name(name):
        return Destination(host, port, "reserved_name")
    found = await _resolve(name, port, timeout)
    if not found:
        return Destination(host, port, None)
    for ip in found:
        reason = _refusal_here(ip)
        if reason is not None:
            return Destination(host, port, reason, (), True, False)
    addresses: List[str] = []
    for ip in found:
        a = _connect_form(ip)
        if a not in addresses:
            addresses.append(a)
    return Destination(host, port, None, tuple(addresses), True, False)


async def inspect_destination(url: Union[str, httpx.URL], *,
                              timeout: Optional[float] = RESOLVE_TIMEOUT_SEC) -> Destination:
    """What the guard would decide about `url`. The name is resolved; nothing is fetched, counted or logged. A lookup
    that does not answer within `timeout` raises TimeoutError (neither a refusal nor an empty answer)."""
    try:
        u = url if isinstance(url, httpx.URL) else httpx.URL(str(url))
    except Exception:
        return Destination("", 0, "malformed")
    return await _decide(u, timeout)


# --- the transport and the client --------------------------------------------------------------------------------

def _resolve_timeout(request: httpx.Request) -> float:
    connect = (request.extensions.get("timeout") or {}).get("connect")
    try:
        return float(connect) if connect is not None else RESOLVE_TIMEOUT_SEC
    except (TypeError, ValueError):
        return RESOLVE_TIMEOUT_SEC


def _forward(request: httpx.Request, url: httpx.URL, headers: httpx.Headers, extensions: dict) -> httpx.Request:
    """A copy of `request` for the connection layer. The caller's request is left as it was, so the response, its
    redirects and any error still name the destination, not the address."""
    return httpx.Request(request.method, url, headers=headers, stream=request.stream, extensions=extensions)


class GuardedTransport(httpx.AsyncBaseTransport):
    """An httpx transport that decides every request's destination before it connects, and connects only to an
    address that decision checked. `inner` is the connection layer (an httpx.AsyncHTTPTransport built from verify,
    cert, trust_env and limits unless one is given; tests give an httpx.MockTransport)."""

    def __init__(self, site: str, *, inner: Optional[httpx.AsyncBaseTransport] = None, verify: Any = True,
                 cert: Any = None, trust_env: bool = True, limits: httpx.Limits = _DEFAULT_LIMITS,
                 max_addresses: int = MAX_ADDRESSES_TRIED) -> None:
        self.site = _site_name(site)
        self._inner = inner if inner is not None else httpx.AsyncHTTPTransport(
            verify=client_cert_verify(verify, cert), cert=cert, trust_env=trust_env, limits=limits)
        self._max_addresses = max(1, int(max_addresses))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hop = "redirect" if request.extensions.get(HOP_EXTENSION) == "redirect" else "first"
        try:
            dest = await _decide(request.url, _resolve_timeout(request))
        except TimeoutError:
            raise httpx.ConnectTimeout("the destination's name did not resolve in time", request=request)
        if dest.refusal is not None:
            raise _refuse(self.site, dest.refusal, hop, request)
        if not dest.addresses:
            raise httpx.ConnectError("the destination's name resolves to no address", request=request)
        headers = request.headers.copy()
        headers["Connection"] = "close"
        if dest.literal:
            return await self._inner.handle_async_request(_forward(request, request.url, headers, request.extensions))
        headers["Host"] = request.url.netloc.decode("ascii")
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = request.url.raw_host.decode("ascii")
        failure: Optional[Exception] = None
        for address in dest.addresses[: self._max_addresses]:
            try:
                return await self._inner.handle_async_request(
                    _forward(request, request.url.copy_with(host=address), headers, extensions))
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:  # nothing reached this address: try the next
                failure = e
        raise failure  # type: ignore[misc]

    async def aclose(self) -> None:
        await self._inner.aclose()


class GuardedClient(httpx.AsyncClient):
    """An httpx.AsyncClient whose every request goes through GuardedTransport(site). It takes the client's keyword
    arguments (timeout, headers, auth, base_url, ...) and verify, cert, trust_env and limits for its connections. It
    never follows a redirect by itself: fetch(..., max_redirects=n) follows up to n, each hop checked."""

    def __init__(self, site: str, *, inner: Optional[httpx.AsyncBaseTransport] = None, verify: Any = True,
                 cert: Any = None, trust_env: bool = True, limits: httpx.Limits = _DEFAULT_LIMITS,
                 **kwargs: Any) -> None:
        for name in ("transport", "mounts", "proxy", "proxies", "app"):
            if name in kwargs:
                raise TypeError(f"a guarded client takes no {name}=: every request goes through its guarded transport")
        if "http2" in kwargs:
            raise TypeError("a guarded client speaks HTTP/1.1: one connection per request, never shared between names")
        if kwargs.pop("follow_redirects", False) or "max_redirects" in kwargs:
            raise ValueError(_NO_AUTOMATIC_REDIRECTS)
        transport = GuardedTransport(site, inner=inner, verify=verify, cert=cert, trust_env=trust_env, limits=limits)
        self.site = transport.site
        super().__init__(transport=transport, follow_redirects=False, **kwargs)

    async def send(self, request: httpx.Request, *, stream: bool = False, auth: Any = httpx.USE_CLIENT_DEFAULT,
                   follow_redirects: Any = httpx.USE_CLIENT_DEFAULT) -> httpx.Response:
        if follow_redirects is True:
            raise ValueError(_NO_AUTOMATIC_REDIRECTS)
        return await super().send(request, stream=stream, auth=auth, follow_redirects=False)

    async def fetch(self, method: str, url: Any, *, max_redirects: int = 0, auth: Any = httpx.USE_CLIENT_DEFAULT,
                    **kwargs: Any) -> httpx.Response:
        """Send one request and follow up to `max_redirects` redirects, each hop checked like the first address. With
        0 (the default) a redirect comes back as it is, unfollowed. One hop more than allowed refuses the request
        (reason "redirect_limit"). The keyword arguments are build_request's (headers, content, json, params, ...);
        the response is read, as client.request reads it."""
        limit = max(0, int(max_redirects))
        response = await self.send(self.build_request(method, url, **kwargs), auth=auth)
        history: List[httpx.Response] = []
        while limit and response.next_request is not None:
            nxt = response.next_request
            await response.aclose()
            if len(history) >= limit:
                raise _refuse(self.site, "redirect_limit", "redirect", nxt)
            history.append(response)
            nxt.extensions = {**nxt.extensions, HOP_EXTENSION: "redirect"}
            response = await self.send(nxt, auth=auth)
        if history:
            response.history = history
        return response


def guarded_client(site: str, **kwargs: Any) -> GuardedClient:
    """The client a call site builds in place of httpx.AsyncClient(...): the same keyword arguments, every request
    decided and pinned by the guard, refusals counted under `site`."""
    return GuardedClient(site, **kwargs)


async def guarded_request(method: str, url: Any, *, site: str, max_redirects: int = 0, timeout: Any = 10.0,
                          verify: Any = True, cert: Any = None, inner: Optional[httpx.AsyncBaseTransport] = None,
                          **kwargs: Any) -> httpx.Response:
    """One guarded request on a client of its own, for a call site that makes one call. The keyword arguments are
    build_request's; redirects as GuardedClient.fetch follows them."""
    async with GuardedClient(site, timeout=timeout, verify=verify, cert=cert, inner=inner) as client:
        return await client.fetch(method, url, max_redirects=max_redirects, **kwargs)
