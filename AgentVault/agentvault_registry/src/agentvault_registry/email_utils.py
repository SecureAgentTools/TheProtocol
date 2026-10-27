"""
TheProtocol email pipeline.

Two themed senders:
  - "neural"     → noreply@theprotocol.cloud         (informational)
  - "sovereign"  → the frame's own security sender (MAIL_FROM_SOVEREIGN; ours is the security mailbox in the facts)  (security/critical)

Rendering pipeline:
  1. Jinja renders {template}.html.j2 (extends _base.html.j2) and {template}.txt.j2.
  2. premailer.transform() inlines all <style> rules into style="" attributes
     so Gmail/Outlook/Apple Mail keep the styling.
  3. multipart/alternative MIME wraps plain-text + HTML (plain first per RFC).
  4. aiosmtplib delivers using the theme's SMTP credentials.

Backward-compat: send_email() kept as a thin shim around send_themed_email()
so existing callers (auth_secure, funding_requests, admin_broadcast, ...) keep
working while migration proceeds.
"""

from __future__ import annotations

import logging
import os
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Iterable, List, Literal, Optional

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import EmailStr

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Theme palettes — single source of truth for all email theming.
# Match the brand reference at /ui#/logo (LogoExample.vue).
# ---------------------------------------------------------------------------

NEURAL_PALETTE = {
    "bg": "#060810",
    "surface": "#0a0d16",
    "border": "rgba(0,210,210,0.18)",
    "text_primary": "#e8eaed",
    "text_body": "#a8b5c2",
    "kicker": "#00d2d2",
    "headline": "#e8eaed",
    "accent": "#00d2d2",
    "cta_bg": "transparent",
    "cta_fg": "#00d2d2",
    "cta_border": "rgba(0,210,210,0.5)",
    "info_border": "rgba(0,210,210,0.3)",
    "muted": "#5a6a7a",
}

SOVEREIGN_PALETTE = {
    "bg": "#0A0A0A",
    "surface": "#1A1A1A",
    "border": "rgba(220,38,38,0.25)",
    "text_primary": "#FAFAFA",
    "text_body": "#C0C0C0",
    "kicker": "#DC2626",
    "headline": "#FAFAFA",
    "accent": "#DC2626",
    "cta_bg": "transparent",
    "cta_fg": "#DC2626",
    "cta_border": "rgba(220,38,38,0.55)",
    "info_border": "rgba(252,165,165,0.4)",
    "muted": "#7A7A7A",
}

PALETTES: dict[str, dict] = {
    "neural": NEURAL_PALETTE,
    "sovereign": SOVEREIGN_PALETTE,
}

Theme = Literal["neural", "sovereign"]

# ---------------------------------------------------------------------------
# Sender-credential routing per theme.
# ---------------------------------------------------------------------------

def _resolve_sender(theme: Theme) -> tuple[str, str, str, str]:
    """
    Return (smtp_username, smtp_password, from_email, from_display_name) for the theme.

    Sovereign theme prefers SECURITY_ALERTS_MAIL_USERNAME for the visible From: header
    so password-reset / suspension emails read "TheProtocol Security" in clients. The
    SMTP password may be empty (sandbox/mailpit) — auth is decided downstream based on
    whether password is set.
    """
    if theme == "sovereign" and settings.SECURITY_ALERTS_MAIL_USERNAME:
        return (
            settings.SECURITY_ALERTS_MAIL_USERNAME,
            settings.SECURITY_ALERTS_MAIL_PASSWORD or "",
            settings.SECURITY_ALERTS_MAIL_USERNAME,
            settings.MAIL_FROM_NAME_SECURITY,
        )
    # Neural / fallback path uses the standard MAIL_* credentials.
    return (
        settings.MAIL_USERNAME or "",
        settings.MAIL_PASSWORD or "",
        str(settings.MAIL_FROM) if settings.MAIL_FROM else (settings.MAIL_USERNAME or ""),
        settings.MAIL_FROM_NAME or "TheProtocol",
    )


# ---------------------------------------------------------------------------
# §2026-07-29 — selectable sender identities (Email Studio).
#
# An identity is registered ONLY when username AND password are both set: a
# half-configured sender would render fine in the picker and bounce at the
# relay (Proton binds From: to the authenticated address), which is exactly
# the silent-failure class the send dialog exists to remove.
# ---------------------------------------------------------------------------

def available_senders() -> list[dict]:
    """Every From-identity this deployment can genuinely authenticate as."""
    out = []
    if settings.MAIL_USERNAME:
        out.append({
            "id": "noreply", "theme": "neural",
            "from_email": str(settings.MAIL_FROM) if settings.MAIL_FROM else settings.MAIL_USERNAME,
            "from_name": settings.MAIL_FROM_NAME or "TheProtocol",
            "hint": "Transactional / partnership (cyan chassis)",
        })
    if getattr(settings, "FOUNDER_MAIL_USERNAME", None) and getattr(settings, "FOUNDER_MAIL_PASSWORD", None):
        out.append({
            "id": "founder", "theme": "neural",
            "from_email": settings.FOUNDER_MAIL_USERNAME,
            "from_name": settings.MAIL_FROM_NAME_FOUNDER,
            "hint": "Personal — the founder writing back",
        })
    if getattr(settings, "OPERATORS_MAIL_USERNAME", None) and getattr(settings, "OPERATORS_MAIL_PASSWORD", None):
        out.append({
            "id": "operators", "theme": "neural",
            "from_email": settings.OPERATORS_MAIL_USERNAME,
            "from_name": settings.MAIL_FROM_NAME_OPERATORS,
            "hint": "Operator relations",
        })
    if settings.SECURITY_ALERTS_MAIL_USERNAME and settings.SECURITY_ALERTS_MAIL_PASSWORD:
        out.append({
            "id": "security", "theme": "sovereign",
            "from_email": settings.SECURITY_ALERTS_MAIL_USERNAME,
            "from_name": settings.MAIL_FROM_NAME_SECURITY,
            "hint": "Security / critical (red chassis)",
        })
    return out


def _resolve_sender_by_id(sender_id: str) -> Optional[tuple[str, str, str, str]]:
    """(smtp_user, smtp_pass, from_email, from_name) for a registered id, else None."""
    if sender_id == "noreply" and settings.MAIL_USERNAME:
        return (settings.MAIL_USERNAME, settings.MAIL_PASSWORD or "",
                str(settings.MAIL_FROM) if settings.MAIL_FROM else settings.MAIL_USERNAME,
                settings.MAIL_FROM_NAME or "TheProtocol")
    if sender_id == "founder" and getattr(settings, "FOUNDER_MAIL_USERNAME", None) and getattr(settings, "FOUNDER_MAIL_PASSWORD", None):
        return (settings.FOUNDER_MAIL_USERNAME, settings.FOUNDER_MAIL_PASSWORD,
                settings.FOUNDER_MAIL_USERNAME, settings.MAIL_FROM_NAME_FOUNDER)
    if sender_id == "operators" and getattr(settings, "OPERATORS_MAIL_USERNAME", None) and getattr(settings, "OPERATORS_MAIL_PASSWORD", None):
        return (settings.OPERATORS_MAIL_USERNAME, settings.OPERATORS_MAIL_PASSWORD,
                settings.OPERATORS_MAIL_USERNAME, settings.MAIL_FROM_NAME_OPERATORS)
    if sender_id == "security" and settings.SECURITY_ALERTS_MAIL_USERNAME and settings.SECURITY_ALERTS_MAIL_PASSWORD:
        return (settings.SECURITY_ALERTS_MAIL_USERNAME, settings.SECURITY_ALERTS_MAIL_PASSWORD,
                settings.SECURITY_ALERTS_MAIL_USERNAME, settings.MAIL_FROM_NAME_SECURITY)
    return None


# ---------------------------------------------------------------------------
# Jinja environment — single instance, autoescape on for HTML.
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = Path(__file__).parent / "templates" / "email"

# §EXCISION — private correspondence templates (partnership/sponsorship) are NOT
# baked into the image, because the image ships to parties we do not control
# (the Hetzner frame, every cloud-op, and the OSS repo). They live outside the
# Docker build context and are bind-mounted ONLY on the registry that sends them.
# Absent dir => TemplateNotFound at send time, which is the loud failure we want;
# a silently-blank email would be worse.
# PRODUCTION_DOCS/08_SECURITY/Private_Surface_Excision.md
PRIVATE_TEMPLATE_DIR = Path(
    os.getenv("PRIVATE_EMAIL_TEMPLATE_DIR", "/app/private-templates")
)

TEMPLATE_SEARCH_DIRS: List[Path] = [_TEMPLATE_DIR, PRIVATE_TEMPLATE_DIR]

_jinja_env = Environment(
    loader=ChoiceLoader([FileSystemLoader(str(d)) for d in TEMPLATE_SEARCH_DIRS]),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
    # NOT StrictUndefined — emails frequently have optional fields.
)


# ---------------------------------------------------------------------------
# Premailer — lazy import so the module loads even if the dep is missing
# (graceful degradation: emails just ship with un-inlined <style> blocks).
# ---------------------------------------------------------------------------

def _inline_styles(html: str) -> str:
    try:
        from premailer import transform
        return transform(
            html,
            keep_style_tags=False,
            remove_classes=False,
            strip_important=False,
            disable_validation=True,
        )
    except Exception:
        logger.warning("Premailer unavailable or failed — sending HTML with un-inlined <style> block. Gmail/Outlook may strip styles.", exc_info=True)
        return html


# ---------------------------------------------------------------------------
# Deployment identity (§MAILIDENT, 2026-08-02).
#
# One sender for the whole fleet (§FRAMEMAIL-4) means the BODY of every mail has
# to say which node is talking. These keys are injected into every render as
# DEFAULTS — a caller can override them, and the mail relay does exactly that,
# substituting the CHILD's identity when the parent sends on a child's behalf.
# ---------------------------------------------------------------------------

def deployment_identity() -> dict:
    """Identity block for outbound mail: who is sending, where its console lives,
    and what its money is called.

    ``registry_ui_url`` is the one templates should build console links from.
    When this node's public address is unknown it falls back to the platform
    root — a worse link than the node's own, but never a loopback and never
    another node's console (the pre-§MAILIDENT hardcodes pointed every
    registry's mail at Frame A)."""
    from agentvault_registry.core.public_url import public_base_url_static, public_ui_url_static

    name = str(getattr(settings, "REGISTRY_NAME", "") or "").strip() or "TheProtocol"
    base = public_base_url_static()
    ui = public_ui_url_static()
    # §LEGALKIT (W4): a mail names the provider behind the registry that sends it, from the provider facts,
    # never from a literal. A frame that has published no provider prints no provider line.
    from agentvault_registry.core import provider_facts as _pf
    facts = _pf.provider_facts()
    provider_line = facts.full_line if _pf.has_provider_identity(facts) else ""
    legal_url = (ui.rstrip("/") + "/#/legal/imprint") if (ui and provider_line) else ""
    return {
        "registry_name": name,
        "registry_base_url": base or "",
        "registry_ui_url": ui or "https://theprotocol.cloud/ui",
        "frame_currency": (os.getenv("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT",
        "provider_legal_line": provider_line,
        "legal_url": legal_url,
        "privacy_email": facts.privacy_email or facts.legal_email or "",
        "legal_email": facts.legal_email or "",
        # Terms § 13.2 (v2.2): a receipt from a small business under § 19 UStG says that no VAT is charged
        "legal_small_business": bool(getattr(facts, "small_business", False)),
    }


def build_email_context(context: Optional[dict], *, theme: Theme, subject: str) -> dict:
    """The ONE place render context is assembled — used by send_themed_email and
    the Email Studio preview, so what the admin previews cannot drift from what
    the recipient gets. Identity keys are defaults (caller/relay may override);
    palette/theme/subject/project_name are system-owned and always win."""
    palette = PALETTES.get(theme, NEURAL_PALETTE)
    return {
        **deployment_identity(),
        **(context or {}),
        "palette": palette,
        "theme": theme,
        "subject": subject,
        "project_name": "TheProtocol",
        "current_year": datetime.utcnow().year,
    }


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------

async def send_themed_email(
    *,
    subject: str,
    recipients: List[EmailStr] | List[str],
    template: str,
    context: Optional[dict] = None,
    theme: Theme = "neural",
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    sender: Optional[str] = None,
) -> bool:
    """
    Render + send a themed email.

    Args:
        subject:    Email subject line.
        recipients: To: list. Plain str also accepted.
        template:   Template basename without extension (e.g. "password_reset").
                    Both `{template}.html.j2` and `{template}.txt.j2` must exist.
        context:    Template context. Augmented with palette/theme/project_name/current_year/subject.
        theme:      "neural" (informational) or "sovereign" (security/critical).
        cc, bcc:    Optional lists.

    Returns True on success; False on render/SMTP failure (logs warning).
    """
    if getattr(settings, "MAIL_DISABLED", False):
        # §ONESHOT (2026-09-12): the frame DECLARED it sends no mail — say so per send, at INFO, so a
        # missing verification mail on such a frame is explained by its own log and not hunted as a defect.
        logger.info("mail disabled by declaration (MAIL_DISABLED=true) — not sending '%s' to %s", subject, recipients)
        return False
    if not settings.MAIL_SERVER:
        # §FRAMEMAIL-4: on a relay-posture node this is EXPECTED for every template
        # outside the relayable set — say so, so the operator reading this log is not
        # hunting a broken SMTP config that was never supposed to exist.
        if relay_configured():
            logger.warning(
                "Template '%s' is not relayable and this node holds no SMTP token "
                "(relay posture) — not sending to %s. Only credential-bearing templates "
                "(verification, password reset) go through the parent relay.",
                template, recipients,
            )
        else:
            logger.warning("MAIL_SERVER not configured — skipping email '%s' to %s", subject, recipients)
        return False

    full_ctx = build_email_context(context, theme=theme, subject=subject)

    # 1. Render HTML + plain-text.
    try:
        html_template = _jinja_env.get_template(f"{template}.html.j2")
        html_body = html_template.render(**full_ctx)
    except Exception:
        logger.exception("Failed to render HTML template '%s.html.j2'", template)
        return False

    try:
        txt_template = _jinja_env.get_template(f"{template}.txt.j2")
        text_body = txt_template.render(**full_ctx)
    except Exception:
        # Plain-text fallback is auto-derived from subject + a hint to view in HTML
        # if the .txt.j2 was forgotten. Log loudly.
        logger.warning("Plain-text template '%s.txt.j2' missing — using minimal fallback.", template)
        text_body = f"{subject}\n\nThis email is best viewed in an HTML-capable client.\n— TheProtocol"

    # 2. Inline CSS via premailer (Gmail/Outlook compat).
    html_inlined = _inline_styles(html_body)

    # 3. Build multipart/alternative MIME.
    # Explicit sender id (Email Studio) wins over the theme-derived identity;
    # every legacy caller passes no sender and behaves exactly as before.
    resolved = _resolve_sender_by_id(sender) if sender else None
    if sender and resolved is None:
        logger.warning("Unknown/unconfigured sender id '%s' — refusing send.", sender)
        return False
    smtp_user, smtp_pass, from_email, from_name = resolved or _resolve_sender(theme)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    # §MAILHDRS (2026-09-04) — `EmailMessage()` sets NEITHER of these and
    # `aiosmtplib.send()` does not add them either, so every mail this platform
    # has ever sent went out with no Date and no Message-ID. Date is REQUIRED by
    # RFC 5322 §3.6; Message-ID is a SHOULD that receivers lean on hard for
    # threading, dedupe and scoring. Gmail weights both, and spam scoring is
    # additive: small mails survived the penalty while a 54 KB one with links
    # and tables crossed the threshold and was dropped without even reaching
    # Spam. Found by dumping the generated headers while chasing exactly that.
    # The Message-ID domain matches the From domain so it aligns with the
    # DKIM/SPF identity rather than leaking the container hostname.
    msg["Date"] = formatdate(localtime=True)
    try:
        msg["Message-ID"] = make_msgid(domain=from_email.split("@", 1)[1])
    except Exception:
        msg["Message-ID"] = make_msgid()
    to_list = [str(r) for r in recipients]
    msg["To"] = ", ".join(to_list)
    if cc:
        msg["Cc"] = ", ".join(cc)
    # Plain part FIRST per RFC 2046 — clients pick the last alternative they understand.
    msg.set_content(text_body)
    msg.add_alternative(html_inlined, subtype="html")

    rcpt_to = list(to_list)
    if cc:
        rcpt_to.extend(cc)
    if bcc:
        rcpt_to.extend(bcc)

    # 4. Send via aiosmtplib.
    try:
        import aiosmtplib

        use_starttls = bool(settings.MAIL_STARTTLS) and not settings.MAIL_SSL_TLS
        use_ssl_tls = bool(settings.MAIL_SSL_TLS)
        use_credentials = bool(smtp_user and smtp_pass)

        # For a real STARTTLS handshake we need a TLS context that verifies certs.
        # Mailpit (sandbox) uses port 1025 plain — use_starttls=False, use_ssl_tls=False.
        tls_ctx: Optional[ssl.SSLContext] = None
        if use_starttls or use_ssl_tls:
            tls_ctx = ssl.create_default_context()

        # §MAILHDRS — the return value used to be DISCARDED. `aiosmtplib.send`
        # returns (errors, response) and only RAISES when EVERY recipient is
        # refused; a partial refusal comes back in `errors` and the old code
        # logged "Email sent" straight over it. So that line was never evidence
        # of anything. The response also carries the submission queue id
        # ("2.0.0 Ok: queued as 4hbq..."), which is the ONLY handle support can
        # trace a missing message by — we spent an afternoon without it.
        smtp_errors, smtp_response = await aiosmtplib.send(
            msg,
            hostname=settings.MAIL_SERVER,
            port=settings.MAIL_PORT,
            username=smtp_user if use_credentials else None,
            password=smtp_pass if use_credentials else None,
            start_tls=use_starttls,
            use_tls=use_ssl_tls,
            tls_context=tls_ctx,
            recipients=rcpt_to,
            timeout=30,
        )
        if smtp_errors:
            logger.error(
                "SMTP REFUSED %d of %d recipient(s): %s | response=%s | "
                "theme=%s subject='%s' template=%s",
                len(smtp_errors), len(rcpt_to), smtp_errors, smtp_response,
                theme, subject, template,
            )
            return False
        logger.info(
            "Email sent: theme=%s subject='%s' to=%s template=%s smtp=%s",
            theme, subject, to_list, template, smtp_response,
        )
        return True
    except Exception:
        logger.exception(
            "SMTP send failed: theme=%s subject='%s' to=%s template=%s",
            theme, subject, to_list, template,
        )
        return False


# ---------------------------------------------------------------------------
# Backward-compat shim — old callers pass `template_name="verification.html"`.
# Strip the .html suffix and route through the themed pipeline (defaults neural).
# ---------------------------------------------------------------------------

async def send_email(
    subject: str,
    recipients: List[EmailStr],
    template_name: str,
    template_body: dict,
) -> bool:
    """Legacy signature — defaults to neural theme. Kept for backward compat."""
    template = template_name
    for suffix in (".html.j2", ".html", ".j2"):
        if template.endswith(suffix):
            template = template[: -len(suffix)]
            break
    return await send_themed_email(
        subject=subject,
        recipients=recipients,
        template=template,
        context=template_body,
        theme="neural",
    )


# ---------------------------------------------------------------------------
# §FRAMEMAIL-4 — parent relay, CHILD side.
#
# A node whose admin credential is held outside this org holds no SMTP token
# (PART 11b). It sends by asking its parent to send. Only the two credential-
# bearing templates are relayable, and the interception lives HERE rather than in
# send_themed_email() for a concrete reason: the relay contract carries the opaque
# TOKEN, never a URL, and by the time send_themed_email() is called the token has
# already been baked into a link. These two helpers are the last place that still
# holds the token itself.
#
# Anything else a relay-only node tries to send falls through to
# send_themed_email(), which finds no MAIL_SERVER and returns False with a
# warning — honest and loud, rather than a confusing SMTP failure.
# ---------------------------------------------------------------------------

def relay_configured() -> bool:
    """True when this node must relay rather than dial SMTP.

    Deliberately requires BOTH halves. A URL with no license authenticates as
    nobody and every send 401s — the same dishonest-half-config failure the SMTP
    side already refuses. Note this does not consult MAIL_SERVER: a node with a
    relay configured relays, full stop, so a leftover MAIL_* block cannot silently
    win and start sending from a token the node was never supposed to have.
    """
    return bool(
        (getattr(settings, "MAIL_RELAY_PARENT_URL", None) or "").strip()
        and (getattr(settings, "MAIL_RELAY_LICENSE", None) or "").strip()
    )


async def relay_send(
    *,
    template: str,
    recipient: str,
    username: str,
    token: str,
    expiry_hours: Optional[int] = None,
) -> bool:
    """Ask the parent to send one templated mail. Returns True only on 2xx.

    Fails CLOSED and LOUD: any transport error, non-2xx, or misconfiguration logs
    at ERROR and returns False. It never falls back to local SMTP — a node in relay
    posture has no token to fall back to, and pretending otherwise would turn a
    delivery failure into a silent one.
    """
    base = (settings.MAIL_RELAY_PARENT_URL or "").strip().rstrip("/")
    lic = (settings.MAIL_RELAY_LICENSE or "").strip()
    if not base or not lic:
        logger.error("[mail-relay/child] relay half-configured — refusing to send '%s'", template)
        return False

    url = f"{base}/api/v1/federation/mail-relay"
    body = {
        "template": template,
        "recipient": recipient,
        "username": username,
        "token": token,
    }
    if expiry_hours:
        body["expiry_hours"] = int(expiry_hours)

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=body, headers={"X-Federation-License": lic})
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[mail-relay/child] transport failure asking parent %s to send '%s': %s",
            base, template, exc,
        )
        return False

    if 200 <= resp.status_code < 300:
        logger.info("[mail-relay/child] parent accepted '%s' for delivery", template)
        return True

    # Surface the parent's own refusal reason — the operator debugging this is
    # reading the CHILD's log and cannot see the parent's.
    detail = ""
    try:
        detail = str(resp.json().get("detail", ""))[:300]
    except Exception:  # noqa: BLE001
        detail = (resp.text or "")[:300]
    logger.error(
        "[mail-relay/child] parent REFUSED '%s': HTTP %s %s",
        template, resp.status_code, detail,
    )
    return False


# ---------------------------------------------------------------------------
# Helpers — pre-canned themed sends used widely.
# ---------------------------------------------------------------------------

async def send_verification_email(to_email: EmailStr, username: str, token: str) -> bool:
    """Email-verification link, neural theme."""
    if relay_configured():
        return await relay_send(
            template="verification", recipient=str(to_email), username=username, token=token,
            expiry_hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS,
        )
    # §MAILIDENT: the raw settings.BASE_URL read was the §OPGUIDE-6 loopback trap —
    # on a cloud operator (no BASE_URL, baked localhost default) every verification
    # link pointed at the reader's own machine. The static resolver prefers
    # BASE_URL, then PUBLIC_URL; raw BASE_URL survives only as the final fallback
    # so a misconfigured node behaves no worse than before, loudly.
    from agentvault_registry.core.public_url import public_base_url_static, public_ui_origin
    _base = public_ui_origin() or public_base_url_static()  # the origin a browser can open (§FIRSTHOUR)
    if not _base:
        logger.error(
            "No public base URL resolvable (BASE_URL/PUBLIC_URL) — verification link "
            "will use raw BASE_URL and is almost certainly wrong on this node."
        )
        _base = str(settings.BASE_URL).rstrip("/")
    verification_link = f"{_base}/api/v1/auth/verify-email?token={token}"
    _registry = deployment_identity()["registry_name"]
    return await send_themed_email(
        subject="Verify your email for TheProtocol",   # §MAILCOPY 2026-09-03 (his word): the platform, not the card name
        recipients=[to_email],
        template="verification",
        context={
            "username": username,
            "verification_link": verification_link,
            "expiry_hours": settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS,
        },
        theme="neural",
    )


async def send_password_reset_email(to_email: EmailStr, username: str, token: str) -> bool:
    """Password-reset link, sovereign theme (security-critical)."""
    if relay_configured():
        return await relay_send(
            template="password_reset", recipient=str(to_email), username=username, token=token,
            expiry_hours=1,
        )
    from agentvault_registry.core.public_url import public_base_url_static
    _base = public_base_url_static()
    if not _base:
        logger.error(
            "No public base URL resolvable (BASE_URL/PUBLIC_URL) — reset link will "
            "use raw BASE_URL and is almost certainly wrong on this node."
        )
        _base = str(settings.BASE_URL).rstrip("/")
    reset_link = f"{deployment_identity()['registry_ui_url']}/#/reset-password?token={token}"  # the console, not <base>/ui (§FIRSTHOUR)
    # 2026-05-10: real backend TTL is 1h (auth_secure.py forgot-password endpoint
    # uses timedelta(hours=1)); UI says "1 hour" too. Email was the only liar.
    _registry = deployment_identity()["registry_name"]
    return await send_themed_email(
        subject="Password reset for your TheProtocol account",   # §MAILCOPY 2026-09-03
        recipients=[to_email],
        template="password_reset",
        context={
            "username": username,
            "reset_link": reset_link,
            "expiry_hours": 1,
        },
        theme="sovereign",
    )
