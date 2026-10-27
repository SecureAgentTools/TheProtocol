"""§OPLANE (V0614, agentvault2-5b, 2026-10-14; his word "please fix the header policy thing if its needed"): how a cloud
operator reaches its PARENT frame for the calls that carry its federation licence.

The operator's self-service (self-logs, self-restart) and its IRONHAND proxy (an agent's SPIRE entry, its inline SVID and
the entry's deletion, done by the frame that owns the SPIRE server) dialled CENTRAL_REGISTRY_URL: the parent's public
CONSOLE host on 443. EU's and ASIA's console vhosts, like every frame the template builds, clear X-Federation-License
there (with X-Federation-Secret and X-Federation-SPIFFE-ID: a public console is no place to present a federation
credential), so on production each of those calls answered 401 "X-Federation-License header required". The sandbox's
hand-made vhosts let the header through and hid it. Measured 2026-10-14 with a fake licence on GET self-logs: 403
"Invalid or revoked federation license" on sandbox-a (the header arrived), 401 "header required" on EU and ASIA.

The fix keeps the edge as it is and moves the calls to the lane federation already uses: the parent's mTLS federation
address (the operator's ACTIVE `frame` peer row on the configured parent host, https://<frame>:8443 on every frame we
run), presenting the operator's SVID, to aliases under /api/v1/federation/ (the only prefix a frame's nginx-federation
forwards). The parent serves those aliases only through its own terminator (mtls_auth.require_vouched_peer_cert), so a
licence alone on a public host never reaches them. Where the lane is unknown (no such peer row, no SVID) or the parent
predates the aliases, the caller keeps its old path.

A lane that is not known yet is asked for again after RETRY_SECONDS, a lane that was found after REFRESH_SECONDS
(agentvault2-56, 2026-10-22). The provisioner writes a new operator's parent `frame` row about 20 s AFTER the operator
boots (cloud_provisioner, the bilateral peer row), so every worker's first answer is "no lane"; it was kept the full
REFRESH_SECONDS, and for five minutes after the boot every licence call took the console path and met its 401 (the
nightly pair's cloud_op_self_logs_per_cloudop ran about four minutes after its operators booted, red every night since
it measured the operator's real path; a pair whose suites started later passed).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 300.0
RETRY_SECONDS = 15.0
_PARENT_URL_VARS = ("CENTRAL_REGISTRY_URL", "MAINFRAME_PROXY_URL", "MAINFRAME_PUBLIC_URL")
_SIDECAR_404 = "Only federation endpoints are served via mTLS proxy"
_state: Dict[str, Any] = {"host": None, "origin": None, "at": 0.0, "why": "not resolved yet"}


def configured_parent_host() -> Optional[str]:
    """The parent's host as this operator's env names it (the console host it dialled), lower case; None when unset."""
    for var in _PARENT_URL_VARS:
        value = (os.getenv(var) or "").strip()
        host = urlparse(value).hostname if value else None
        if host:
            return host.lower()
    return None


def pick_origin(host: Optional[str], rows) -> tuple:
    """(origin, why) from (base_url, peer_type, status) rows: the ONE active `frame` row on `host` whose base_url names a
    port other than 443, i.e. the federation lane, never the console. Pure, so the choice is tested without a database."""
    if not host:
        return None, "no parent host configured (CENTRAL_REGISTRY_URL / MAINFRAME_PROXY_URL / MAINFRAME_PUBLIC_URL)"
    found = []
    for base_url, peer_type, status in rows:
        u = urlparse(str(base_url or ""))
        if (str(peer_type or "").lower() != "frame" or str(status or "").upper() != "ACTIVE" or u.scheme != "https"
                or (u.hostname or "").lower() != host or u.port in (None, 443)):
            continue
        origin = f"https://{u.hostname}:{u.port}"
        if origin not in found:
            found.append(origin)
    if len(found) != 1:
        return None, f"{len(found)} active frame peer rows name a federation lane on {host}"
    return found[0], None


def _kept_for(origin: Optional[str]) -> float:
    """How long an answer stands: a found lane REFRESH_SECONDS, "no lane yet" only RETRY_SECONDS (a fresh operator's
    parent row arrives after its boot)."""
    return REFRESH_SECONDS if origin else RETRY_SECONDS


async def resolve_origin(db) -> Optional[str]:
    """The parent's federation origin from the peer table, cached REFRESH_SECONDS (a None only RETRY_SECONDS); None
    keeps the caller's old path."""
    host = configured_parent_host()
    now = time.monotonic()
    if _state["host"] == host and now - _state["at"] < _kept_for(_state["origin"]):
        return _state["origin"]
    from sqlalchemy import select
    from agentvault_registry import models
    rows = (await db.execute(select(models.PeerRegistry.base_url, models.PeerRegistry.peer_type,
                                    models.PeerRegistry.status))).all()
    origin, why = pick_origin(host, rows)
    if origin != _state["origin"] or why != _state["why"]:
        logger.info("[OPLANE] parent federation lane: %s", origin or f"none ({why}); the console path stays")
    _state.update(host=host, origin=origin, at=now, why=why)
    return origin


def cached_origin() -> Optional[str]:
    """The last resolved origin, for the synchronous IRONHAND proxy calls (the refresher keeps it current)."""
    return _state["origin"] if _state["host"] == configured_parent_host() else None


def client_verify(url: str) -> Any:
    """What an httpx client passes as `verify=` to dial `url` with this registry's SVID (the SSLContext that verifies the
    parent against the SPIRE bundle and presents the SVID: core/tls_client.py); None when this node holds no SVID."""
    try:
        from agentvault_registry.identity import svid_client
        cfg = svid_client.get_client_cert_config(target_url=url)
    except Exception as e:  # noqa: BLE001 - no lane is a fallback, never a failure
        logger.warning("[OPLANE] no client certificate config for the parent lane: %s", type(e).__name__)
        return None
    return (cfg or {}).get("verify") if (cfg or {}).get("cert") else None


def route_missing(status_code: int, text: str) -> bool:
    """A 404 that says the parent does not serve the alias (an older image answers its unknown-route body, detail exactly
    "Not Found"; a sidecar that forwards no such path answers its own sentence), never a route's own 404 (no operator
    application for this licence, which is an answer and is passed on)."""
    if status_code != 404:
        return False
    t = text or ""
    if _SIDECAR_404 in t:
        return True
    try:
        body = json.loads(t)
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    nested = body.get("error") if isinstance(body.get("error"), dict) else {}
    return body.get("detail", nested.get("detail")) == "Not Found"


async def refresher(stop: Optional[asyncio.Event] = None) -> None:
    """On a cloud operator: keep cached_origin() current from the peer table, every REFRESH_SECONDS (every
    RETRY_SECONDS while no lane is known, so the IRONHAND proxy finds a fresh operator's lane as soon as its row exists)."""
    from agentvault_registry.database import get_db_context
    while stop is None or not stop.is_set():
        try:
            async with get_db_context() as db:
                _state["at"] = 0.0
                await resolve_origin(db)
        except Exception as e:  # noqa: BLE001 - the lane is optional; the next turn tries again
            logger.warning("[OPLANE] parent lane refresh failed: %s", type(e).__name__)
        await asyncio.sleep(_kept_for(_state["origin"]))
