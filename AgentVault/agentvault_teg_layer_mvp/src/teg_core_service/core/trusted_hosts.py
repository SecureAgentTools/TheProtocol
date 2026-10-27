"""§SECFIX-9 (2026-09-25) — the TEG checks the Host header by its own posture flag.

main.py added Starlette's TrustedHostMiddleware only when `settings.environment == "production"`. ENVIRONMENT was
unset on all 24 running TEG containers (measured 2026-09-25: EU, ASIA, the sandbox pair, every operator and every
nginx-teg sidecar), so the check never ran anywhere, and its list named Frame A's containers (teg-layer-b,
teg-layer-test, ...) rather than the names today's TEGs are dialed by. A gate keyed on an environment NAME is open
wherever the name is unset (§MONEY-M3a); this one has its own flag.

    TEG_TRUSTED_HOSTS_MODE     off | observe | enforce   (default observe: count and log, refuse nothing)
    TEG_TRUSTED_HOSTS          extra names, comma-separated; `*.example.org` matches that domain's subdomains
    TEG_TRUSTED_HOST_SUFFIXES  public domains whose names are accepted, comma-separated (default theprotocol.cloud)

Accepted with no configuration, because each is how a legitimate caller reaches a TEG today: a loopback name or
address, a single-label name (a Docker service or container name such as `teg-layer` or `eu-teg`, which only the
frame's own networks resolve), an IP literal on a private or loopback network (a caller dialing a container address),
this container's own hostname, and any name under the configured suffixes (a federation peer's request arrives through
nginx-federation carrying the public name it dialed). A request over the unix socket carries whatever Host its client
wrote, which is one of the above.

Refused under enforce (400, as Starlette's middleware answers): a dotted name outside the suffixes and the extra list
(a DNS-rebinding page and a poisoned absolute URL both need one), a public IP literal, and an empty or malformed Host.
Observe is the default so a frame learns its real Host population before it enforces: every miss is counted
(`teg_untrusted_host_requests_total{mode}`) and logged once per distinct host per ten minutes.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
import time
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

MODES = ("off", "observe", "enforce")
DEFAULT_SUFFIXES = ("theprotocol.cloud",)
_LOG_EVERY_S = 600.0
_LOG_TABLE_MAX = 256

try:
    from prometheus_client import Counter as _C

    TEG_UNTRUSTED_HOST_TOTAL = _C(
        "teg_untrusted_host_requests_total",
        "Requests whose Host header is outside the TEG's trusted hosts (observe: served; enforce: refused 400)",
        ["mode"],
    )
except Exception:  # pragma: no cover
    TEG_UNTRUSTED_HOST_TOTAL = None


def _split(raw: Optional[str]) -> List[str]:
    return [p.strip().lower().rstrip(".") for p in (raw or "").split(",") if p.strip()]


def resolve_mode(raw: Optional[str]) -> str:
    """The configured mode. An unknown value is served as observe (the TEG keeps answering) and said loudly: a typo in
    `enforce` must not pass for a posture it does not have."""
    m = (raw or "observe").strip().lower()
    if m not in MODES:
        logger.error("[TRUSTED-HOSTS] TEG_TRUSTED_HOSTS_MODE=%r is not one of %s; serving as observe", m[:40], MODES)
        return "observe"
    return m


def host_of(header: Optional[str]) -> Optional[str]:
    """The name part of a Host header, lowercased, without a port; None when the header is empty or malformed."""
    if not header:
        return None
    h = header.strip().lower()
    if not h or any(ch.isspace() for ch in h) or "/" in h or "@" in h:
        return None
    if h.startswith("["):  # [v6]:port
        end = h.find("]")
        if end < 0:
            return None
        rest = h[end + 1:]
        if rest and not (rest.startswith(":") and rest[1:].isdigit()):
            return None
        return h[1:end]
    if h.count(":") == 1:
        name, port = h.split(":", 1)
        if not port.isdigit():
            return None
        h = name
    elif h.count(":") > 1:  # a bare v6 literal
        return h
    return h.rstrip(".") or None


def _ip(name: str) -> Optional[ipaddress._BaseAddress]:
    try:
        return ipaddress.ip_address(name)
    except ValueError:
        return None


class HostPolicy:
    def __init__(self, extra: Iterable[str] = (), suffixes: Iterable[str] = DEFAULT_SUFFIXES,
                 own_hostnames: Iterable[str] = ()):
        self.exact = set()
        self.wild = set()
        for e in extra:
            if e.startswith("*."):
                self.wild.add(e[2:])
            elif e:
                self.exact.add(e)
        self.suffixes = tuple(s for s in (x.lstrip("*.") for x in suffixes) if s)
        self.exact |= {h.lower() for h in own_hostnames if h}
        self.exact |= {"localhost"}

    def allowed(self, name: Optional[str]) -> bool:
        if not name:
            return False
        ip = _ip(name)
        if ip is not None:
            return bool(ip.is_loopback or ip.is_private or ip.is_link_local)
        if name in self.exact:
            return True
        if not all(label and len(label) <= 63 and all(c.isascii() and (c.isalnum() or c in "-_") for c in label)
                   for label in name.split(".")):
            return False
        if "." not in name:
            return True  # a Docker service or container name: only the frame's own networks resolve it
        for s in self.suffixes + tuple(self.wild):
            if name == s or name.endswith("." + s):
                return True
        return False


def policy_from_env(env=os.environ) -> Tuple[str, HostPolicy]:
    mode = resolve_mode(env.get("TEG_TRUSTED_HOSTS_MODE"))
    suffixes = _split(env.get("TEG_TRUSTED_HOST_SUFFIXES")) or list(DEFAULT_SUFFIXES)
    own = []
    try:
        own.append(socket.gethostname())
    except Exception:  # pragma: no cover
        pass
    return mode, HostPolicy(extra=_split(env.get("TEG_TRUSTED_HOSTS")), suffixes=suffixes, own_hostnames=own)


def _printable(s: str, n: int = 100) -> str:
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in (s or ""))[:n]


class TrustedHostsGate:
    """Pure ASGI middleware. Off passes everything through; observe counts, logs and serves; enforce answers 400."""

    def __init__(self, app, mode: Optional[str] = None, policy: Optional[HostPolicy] = None):
        self.app = app
        env_mode, env_policy = policy_from_env()
        self.mode = resolve_mode(mode) if mode is not None else env_mode
        self.policy = policy or env_policy
        self._last_logged: Dict[str, float] = {}
        logger.info("[TRUSTED-HOSTS] mode=%s suffixes=%s extra=%d", self.mode, ",".join(self.policy.suffixes),
                    len(self.policy.exact) + len(self.policy.wild))

    def _note(self, raw: Optional[str], scope) -> None:
        if TEG_UNTRUSTED_HOST_TOTAL is not None:
            try:
                TEG_UNTRUSTED_HOST_TOTAL.labels(mode=self.mode).inc()
            except Exception:  # pragma: no cover
                pass
        key = _printable(raw or "<none>", 120)
        now = time.monotonic()
        last = self._last_logged.get(key)
        if last is not None and now - last < _LOG_EVERY_S:
            return
        if len(self._last_logged) >= _LOG_TABLE_MAX:
            self._last_logged.clear()
        self._last_logged[key] = now
        client = scope.get("client") or ("unix", 0)
        logger.warning("[TRUSTED-HOSTS] %s: Host %r outside the trusted hosts (path %s, peer %s)",
                       "REFUSED" if self.mode == "enforce" else "observed", key, _printable(scope.get("path") or "", 100),
                       _printable(str(client[0]), 60))

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in ("http", "websocket") or self.mode == "off":
            await self.app(scope, receive, send)
            return
        raw = None
        for k, v in scope.get("headers") or []:
            if k == b"host":
                raw = v.decode("latin-1")
                break
        if self.policy.allowed(host_of(raw)):
            await self.app(scope, receive, send)
            return
        self._note(raw, scope)
        if self.mode != "enforce":
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = b"Invalid host header"
        await send({"type": "http.response.start", "status": 400,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
