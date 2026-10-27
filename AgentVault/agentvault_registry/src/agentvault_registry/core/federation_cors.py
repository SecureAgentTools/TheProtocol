"""§FEFRAME W2 — CORS follows federation membership, never credentials.

Before W2 the answer to "which browser origins may read this registry's API" was a hand-kept list per frame (EU's four
own hosts, ASIA's one, the sandbox's one) and NOTHING on the operators, whose config default ["*"] was served WITH
Access-Control-Allow-Credentials (Starlette echoes any origin in that case). So a console could not read its own peer
frame (ASIA's console refused by EU, and the reverse), while every operator answered any origin on the internet.

Now the set is DERIVED, per worker, every CORS_REFRESH_SEC (60) seconds, from the frame manifest
(core/federation_view.py): this registry's own console, public and base origins, every origin ALLOWED_ORIGINS names
explicitly (the env stays an addition, never a replacement), and the console and public origins of every ACTIVE peer.
allow_credentials is False everywhere: the API authenticates with bearer tokens, never cookies, so no origin gains a
credential by being allowed; it gains the right to READ a response its page asked for with a token it already held.

Wildcards stay available only as an explicit choice: CORS_ALLOW_ALL_ORIGINS=true, or an ALLOWED_ORIGINS variable that
literally contains "*" (both without credentials). The config default is no longer ["*"].

A refresh that fails keeps the previous set (a database blip never shrinks the allowlist to nothing).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Iterable, List, Optional, Set

from starlette.middleware.cors import CORSMiddleware

from agentvault_registry.core import federation_view as fv

logger = logging.getLogger(__name__)

REFRESH_SEC = float(os.getenv("CORS_REFRESH_SEC", "60") or 60)
# §REPATLANE-7 (after V0606): a console on a peer frame reads a send's answer across origins (the console sends an
# agent's request to that agent's home registry), and a browser hides every response header CORS does not expose. The
# mark on an answer given again under the same Idempotency-Key (services/idempotency/cache.py REPLAYED_HEADER) is
# exposed, or that console never says the first press had already gone through.
EXPOSED_HEADERS = ("Idempotent-Replayed",)
_allowed: frozenset = frozenset()
_refreshed_at: float = 0.0


def _explicit_env_origins() -> List[str]:
    """ALLOWED_ORIGINS as the operator typed it (a JSON list or a comma list), each reduced to its origin. Read from the
    ENVIRONMENT, not settings: the settings default must not read as a choice."""
    raw = (os.getenv("ALLOWED_ORIGINS", "") or "").strip()
    if not raw:
        return []
    try:
        vals = json.loads(raw)
        vals = vals if isinstance(vals, list) else [vals]
    except ValueError:
        vals = [v for v in raw.split(",")]
    out: List[str] = []
    for v in vals:
        s = str(v or "").strip()
        if s == "*":
            out.append("*")
            continue
        o = fv.web_origin(s) or fv.web_origin(s, scheme="http")
        if o and o not in out:
            out.append(o)
    return out


def wildcard_requested() -> bool:
    if (os.getenv("CORS_ALLOW_ALL_ORIGINS", "") or "").strip().lower() == "true":
        return True
    return "*" in _explicit_env_origins()


def own_origins() -> List[str]:
    """This registry's own browser origins: its console, its public URL, its BASE_URL (loopback rejected)."""
    from agentvault_registry.core import public_url as _pu
    out: List[str] = []
    for u in (_pu.public_ui_origin(), _pu.public_base_url_static()):
        o = fv.web_origin(u)
        if o and o not in out:
            out.append(o)
    return out


def compute(manifest_origins: Iterable[str] = ()) -> frozenset:
    s: Set[str] = set(own_origins())
    s.update(o for o in _explicit_env_origins() if o != "*")
    s.update(o for o in manifest_origins if o)
    return frozenset(s)


def allowed_origins() -> frozenset:
    return _allowed


def _set(origins: frozenset) -> None:
    global _allowed, _refreshed_at
    import time
    if origins != _allowed:
        added, removed = sorted(origins - _allowed), sorted(_allowed - origins)
        if _allowed:
            logger.info("[FederationCORS] allowlist now %d origins (+%s -%s)", len(origins), added, removed)
    _allowed = origins
    _refreshed_at = time.time()


async def refresh_once() -> frozenset:
    """Recompute from the manifest; on any failure keep the previous set and say so."""
    from agentvault_registry.background_tasks.leader import get_redis
    from agentvault_registry.database import get_db_context
    try:
        redis = await get_redis()
        async with get_db_context() as db:
            m = await fv.build_manifest(db, redis)
        _set(compute(fv.manifest_origins(m)))
    except Exception as e:  # noqa: BLE001
        logger.warning("[FederationCORS] refresh failed, keeping %d origins: %s", len(_allowed), e)
        if not _allowed:
            _set(compute())
    return _allowed


async def run_refresher() -> None:
    """Per worker (every worker needs its own set), not leader-elected."""
    _set(compute())
    await asyncio.sleep(5)
    while True:
        await refresh_once()
        await asyncio.sleep(REFRESH_SEC)


class FederationCORSMiddleware(CORSMiddleware):
    """Starlette's CORS with the origin decision read from the derived set at request time (both the preflight and
    the simple-response paths call `is_allowed_origin`)."""

    def __init__(self, app, allow_all: bool = False, max_age: int = 600):
        super().__init__(app, allow_origins=["*"] if allow_all else [], allow_methods=["*"], allow_headers=["*"],
                         allow_credentials=False, expose_headers=list(EXPOSED_HEADERS), max_age=max_age)

    def is_allowed_origin(self, origin: str) -> bool:
        if self.allow_all_origins:
            return True
        return origin in _allowed


def install(app) -> Optional[str]:
    """Add the middleware; returns a one-line description for the boot log."""
    allow_all = wildcard_requested()
    app.add_middleware(FederationCORSMiddleware, allow_all=allow_all)
    _set(compute())
    return ("CORS: allowing ALL origins without credentials (explicit wildcard)" if allow_all else
            f"CORS: derived from federation membership ({len(_allowed)} own/explicit origins at boot; the ACTIVE "
            f"peers' consoles join within {int(REFRESH_SEC)} s; no credentials)")
