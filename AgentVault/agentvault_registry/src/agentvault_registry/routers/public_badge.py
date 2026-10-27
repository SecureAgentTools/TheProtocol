"""Public status endpoints — supply-invariant badge + security.txt.

Both are unauthenticated and safe to serve from every registry/operator. The
badge exposes only the OK/BREACH status of the prime directive (Δ=0) in the
shields.io "endpoint" schema — no balances, no amounts.
"""
from __future__ import annotations

import os
import time
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Response

from ..config import settings
from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Public — Status"])

# 60s in-proc cache so a README badge hammering the endpoint never stampedes the ES.
_BADGE_CACHE: Dict[str, Any] = {"body": None, "ts": 0.0}
_BADGE_CACHE_TTL = 60.0


def _internal_key() -> str:
    """Same resolution as supply_auditor.py / event_emitter.py."""
    return os.getenv("EVENT_STORE_API_KEY", os.getenv("EVENT_STORE_INTERNAL_KEY", ""))


def _shield(message: str, color: str) -> Dict[str, Any]:
    return {
        "schemaVersion": 1,
        "label": "supply invariant",
        "message": message,
        "color": color,
        "cacheSeconds": 60,
    }


async def _compute_badge() -> Dict[str, Any]:
    """Read our own EventStore supply-audit; never raise."""
    try:
        async with httpx.AsyncClient(timeout=8.0, verify=get_httpx_verify()) as client:
            resp = await client.get(
                f"{settings.EVENT_STORE_URL}/api/v1/projections/supply-audit",
                headers={"X-Internal-Key": _internal_key()},
            )
        if resp.status_code != 200:
            return _shield("unknown", "lightgrey")
        data = resp.json()
        delta = data.get("delta")
        status_str = str(data.get("status", "")).upper()
        # Atomic single-statement delta is truth; the HTTP read can show cosmetic
        # ±1-2 skew under cross-frame load, so trust status when present.
        if status_str == "OK" or (delta is not None and abs(float(delta)) < 1.0):
            return _shield("Δ=0", "brightgreen")
        return _shield(f"Δ={delta}", "red")
    except Exception as e:  # noqa: BLE001 — badge must never 5xx
        logger.debug("[Badge] supply-audit read failed: %s", e)
        return _shield("unknown", "lightgrey")


@router.get(
    "/api/v1/public/badge/supply",
    summary="Supply-invariant status badge (shields.io endpoint schema)",
    description=(
        "Unauthenticated. Returns a shields.io 'endpoint' JSON reflecting this "
        "registry's live supply-invariant status (Δ=0). Wire into a README with "
        "https://img.shields.io/endpoint?url=<this-url>. 60s cached; never 5xx."
    ),
)
async def supply_badge() -> Response:
    import json

    now = time.time()
    if _BADGE_CACHE["body"] is not None and (now - _BADGE_CACHE["ts"]) < _BADGE_CACHE_TTL:
        body = _BADGE_CACHE["body"]
    else:
        body = json.dumps(await _compute_badge())
        _BADGE_CACHE["body"] = body
        _BADGE_CACHE["ts"] = now
    return Response(
        content=body,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=60"},
    )


_SECURITY_TXT_CACHE: Optional[str] = None


def _security_contact() -> Optional[str]:
    """§LEGALKIT: the mailbox comes from the provider facts (SECURITY_CONTACT_EMAIL stays as an override).
    There is no literal default any more: a frame that names nobody serves no security.txt (404) rather
    than the software author's mailbox as a stranger's security contact."""
    from ..core import provider_facts as _pf
    explicit = (os.getenv("SECURITY_CONTACT_EMAIL", "") or "").strip()
    if explicit:
        return explicit
    facts = _pf.provider_facts()
    return facts.security_email or facts.legal_email or None


def _security_policy_url() -> Optional[str]:
    """Where the disclosure policy lives: the operator's own link, or this frame's /legal/security page."""
    from ..core import provider_facts as _pf
    from ..core.public_url import public_ui_origin
    explicit = (os.getenv("LEGAL_SECURITY_POLICY_URL", "") or "").strip()
    if explicit:
        return explicit
    if _pf.suite_mode() == _pf.MODE_THEPROTOCOL:
        origin = public_ui_origin()
        if origin:
            return f"{origin.rstrip('/')}/#/legal/security"
    return None


def _preferred_languages() -> Optional[str]:
    """§DOCSFIX CB-355: the languages a report may be written in. LEGAL_SECURITY_LANGUAGES says so where set; a
    `theprotocol` frame (run by the author of the software) reads reports in English and German; any other frame names
    none unless it says so, rather than advertising German for a stranger (RFC 9116: absent, a reporter assumes
    English)."""
    from ..core import provider_facts as _pf
    explicit = (os.getenv("LEGAL_SECURITY_LANGUAGES", "") or "").strip()
    if explicit:
        return explicit
    return "en, de" if _pf.suite_mode() == _pf.MODE_THEPROTOCOL else None


def _build_security_txt() -> Optional[str]:
    contact = _security_contact()
    if not contact:
        return None
    # Expires: RFC 9116 requires a future date; recompute ~1y out at first serve.
    expires = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 365 * 24 * 3600)
    )
    canonical = os.getenv("SECURITY_TXT_CANONICAL", "").strip()
    lines = [
        f"Contact: mailto:{contact}",
        f"Expires: {expires}",
    ]
    languages = _preferred_languages()
    if languages:
        lines.append(f"Preferred-Languages: {languages}")
    policy = _security_policy_url()
    if policy:
        lines.append(f"Policy: {policy}")
    if canonical:
        lines.append(f"Canonical: {canonical}")
    lines.append("")
    return "\n".join(lines)


@router.get(
    "/.well-known/security.txt",
    response_class=Response,
    summary="RFC 9116 security contact",
)
async def security_txt() -> Response:
    global _SECURITY_TXT_CACHE
    if _SECURITY_TXT_CACHE is None:
        _SECURITY_TXT_CACHE = _build_security_txt()
    if _SECURITY_TXT_CACHE is None:
        # No contact is configured on this frame: say nothing rather than someone else's address.
        return Response(status_code=404, content="", media_type="text/plain; charset=utf-8")
    return Response(
        content=_SECURITY_TXT_CACHE,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "public, max-age=86400"},
    )
