"""This registry's public base URL, as an outside caller would type it.

Extracted from ``routers/downloads.py`` (§OPGUIDE) so the rule lives in ONE place.
It was already needed by two surfaces and got the wrong answer in a third:

  * ``/api/v1/downloads/CLAUDE.md`` substitutes it into the served operator manual.
  * ``/api/v1/admin/invite-codes`` builds the shareable ``…/ui#/register?invite=…``
    link. Before §OPGUIDE-6 that used ``settings.BASE_URL`` raw, so on a cloud
    operator — whose baked default is ``http://localhost:8000`` — every invite link
    an admin copied out of the UI pointed at their own loopback and was useless to
    the recipient.

Two copies of a rule is how the two copies drift, so new callers import this one.
"""

from __future__ import annotations

from fastapi import Request


def public_base_url(request: Request) -> str:
    """Return e.g. ``https://hetzner.theprotocol.cloud`` (no trailing slash).

    ``settings.BASE_URL`` is authoritative WHEN SET TO SOMETHING REAL, but it cannot
    be trusted blindly:

      * a cloud operator is deliberately provisioned without it (setting BASE_URL
        without ALLOWED_ORIGINS flips ``validate_production_config()`` on and
        crash-loops the container, §V0160), and
      * the image bakes ``http://localhost:8000`` as the default, which is WORSE
        than empty because it is truthy — a naive ``settings.BASE_URL`` read yields
        a link that looks valid and points at the reader's own machine.

    Hence the explicit loopback rejection before falling back to the request.
    nginx fronts every deployment, so X-Forwarded-* is preferred over
    ``request.base_url``, which would report http:// and the container port.
    """
    try:
        from agentvault_registry.config import settings
        configured = str(getattr(settings, "BASE_URL", "") or "").strip()
        if configured and "localhost" not in configured and "127.0.0.1" not in configured:
            return configured.rstrip("/")
    except Exception:  # pragma: no cover - config import should never fail here
        pass

    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip() or request.url.scheme
    if host:
        return f"{proto}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


def public_base_url_static() -> "str | None":
    """Request-free variant for background senders (email, workers).

    Resolution order, loopback-rejected at every step:
      1. ``settings.BASE_URL``   — mainframes set it (e.g. https://api.theprotocol.cloud)
      2. ``PUBLIC_URL`` env      — cloud operators carry it in .env.operator; they
                                   deliberately do NOT set BASE_URL (§V0160), and the
                                   baked BASE_URL default is a truthy localhost.
    Returns None when this node's public address is genuinely unknown: callers must
    degrade honestly (drop the link, fall back to the platform root) rather than emit
    a loopback or another node's address.
    """
    import os as _os

    candidates = []
    try:
        from agentvault_registry.config import settings as _settings
        candidates.append(str(getattr(_settings, "BASE_URL", "") or ""))
    except Exception:  # pragma: no cover - config import should never fail here
        pass
    candidates.append(_os.getenv("PUBLIC_URL", "") or "")

    for raw in candidates:
        url = raw.strip()
        if url and "localhost" not in url and "127.0.0.1" not in url:
            return url.rstrip("/")
    return None


def public_ui_url_static() -> "str | None":
    """The console a PERSON is sent to — mail links and the verify-email 303.

    §FIRSTHOUR (2026-09-03): registry-a's public base is api.theprotocol.cloud, but the
    people it registers arrive from the APEX (theprotocol.cloud serves the app at /). A
    verify link that lands them on api.theprotocol.cloud/ui logs them in on a host they
    never typed, and the apex forgets them. ``PUBLIC_UI_URL`` names the console when it
    differs from ``<base>/ui``; loopback is rejected like every other public address.
    """
    import os as _os

    ui = (_os.getenv("PUBLIC_UI_URL", "") or "").strip()
    if ui and "localhost" not in ui and "127.0.0.1" not in ui:
        return ui.rstrip("/")
    base = public_base_url_static()
    return (base + "/ui") if base else None


def public_ui_origin() -> "str | None":
    """The ORIGIN a PERSON's browser can open (scheme+host[:port]): ``PUBLIC_UI_URL`` without a
    trailing ``/ui``, else this node's public base. Every link a human follows (the verify link in
    the mail, the console link, the reset link) is built from it. Machine-facing links keep
    ``public_base_url_static()`` — on our cloud operators that carries the external mTLS port
    (``:27543``-style), which a browser cannot open (measured 2026-09-03: ``000`` vs ``200`` on 443)."""
    ui = public_ui_url_static()
    if not ui:
        return None
    return ui[:-3] if ui.endswith("/ui") else ui


def credential_home_url() -> "str | None":
    """§FEFRAME W1: WHERE an agent credential this registry issues is used: the browser-openable origin of this
    registry (its console; ``/api/v1`` answers there too). Returned beside every client_secret this registry shows
    (create, reset, admin rotate, spawn, bundle restore), so a saved or downloaded credential names its home instead
    of being assumed local to whichever console reads it later. None when this node's public address is unknown."""
    o = public_ui_origin()
    if not o:
        return None
    from urllib.parse import urlsplit
    p = urlsplit(o)
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.netloc else None


def spa_url(route: str) -> str:
    """A link into the SPA for ``route`` (e.g. ``email-verification?status=success``): ABSOLUTE only
    when ``PUBLIC_UI_URL`` names the console (registry-a → the apex, which serves the app at ``/``);
    otherwise the RELATIVE ``/#/<route>``, so the person stays on the host they typed (a registry
    root 301s to /ui). Never derived from ``PUBLIC_URL``: on a cloud operator that is the mTLS port."""
    import os as _os

    ui = (_os.getenv("PUBLIC_UI_URL", "") or "").strip()
    if ui and "localhost" not in ui and "127.0.0.1" not in ui:
        return f"{ui.rstrip('/')}/#/{route}"
    return f"/#/{route}"
