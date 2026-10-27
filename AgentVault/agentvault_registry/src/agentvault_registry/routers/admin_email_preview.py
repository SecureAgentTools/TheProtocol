"""Admin-only email-template preview endpoint.

Renders a themed email template with sample (or admin-supplied) context and
returns the inlined HTML directly. Useful for designing the email pipeline
without spamming inboxes or even pinging mailpit.

Endpoints:
    GET  /api/v1/admin/email/preview              — list available templates
    GET  /api/v1/admin/email/preview/{template}    — render with default sample
    POST /api/v1/admin/email/preview/{template}    — render with custom context
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Security
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from agentvault_registry import models, security
from agentvault_registry.email_utils import (
    NEURAL_PALETTE,
    SOVEREIGN_PALETTE,
    PALETTES,
    PRIVATE_TEMPLATE_DIR,
    TEMPLATE_SEARCH_DIRS,
    _inline_styles,
    _jinja_env,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/email", tags=["Admin — Email Studio"])


# Sample contexts let the preview endpoint render without the admin needing to
# remember every template's required fields.
_SAMPLE_CONTEXT: Dict[str, Dict[str, Any]] = {
    # §ORGINVITE (2026-08-28) — org_invitation had NO sample context at all, so
    # the preview rendered its ACCEPT INVITATION button with an empty
    # `accept_url` and it fell back to the site root. The preview is the tool an
    # operator uses to check this template, and it was blind to the one link in
    # it — the same link that was a 404 page for three months (§ORGJOIN). The
    # sample URL is the REAL shape built by
    # organization_service.send_invitation_email, so what the preview shows is
    # what an invitee gets.
    "org_invitation": {
        "organization_name": "Acme Logistics",
        "inviter_name": "Dana Reyes",
        "role": "member",
        "accept_url": "https://api.theprotocol.cloud/ui/#/organizations/invitations/sample-invitation-token/accept",
        "token": "sample-invitation-token",
    },
    "verification": {
        "username": "alice",
        "verification_link": "https://api.theprotocol.cloud/api/v1/auth/verify-email?token=sample",
        "expiry_hours": 24,
    },
    "password_reset": {
        "username": "alice",
        "reset_link": "https://api.theprotocol.cloud/ui#/reset-password?token=sample",
        # Match runtime: send_password_reset_email() uses 1 hour to align with
        # the backend's `timedelta(hours=1)` reset-token TTL (2026-05-10 fix).
        "expiry_hours": 1,
    },
    "funding_approved": {
        "request_id": 42,
        "approved_amount": "5000",
        "requester_did": "did:theprotocol:sample",
        "transaction_id": "tx-sample-id",
    },
    "funding_rejected": {
        "request_id": 42,
        "requested_amount": "100000",
        "requester_did": "did:theprotocol:sample",
        "rejection_reason": "Amount exceeds beta-phase ceiling. Submit a smaller request.",
    },
    "broadcast_notification": {
        "title": "Scheduled Maintenance Window",
        "body": "We will be performing scheduled maintenance on Saturday from 02:00 UTC to 04:00 UTC.\n\nYou may experience brief disruptions during this period.",
        "broadcast_type": "maintenance",
        "type_label": "MAINTENANCE NOTICE",
    },
    "supply_breach": {
        "delta": "0.000123456789",
        "net_supply": "10000000.0",
        "circulating": "9999999.999876",
        "detected_at": datetime.utcnow().isoformat(),
        "audit_type": "self_consistent_es",
        "auto_lockdown": False,
    },
    # §EXCISION — the partnership/sponsorship sample contexts used to live here.
    # They carried a counterparty's customer number, ticket ID and both admin
    # logins, and this dict is what the preview renders BY DEFAULT, so removing
    # only the .j2 templates would have closed the route while leaving the
    # strings in an image that ships to 14 machines we do not own. They now load
    # from the same private, non-shipping directory as the templates themselves.
    # PRODUCTION_DOCS/08_SECURITY/Private_Surface_Excision.md
    "beta_invite": {
        "code": "BETA-A1B2-C3D4",
        "invite_url": "https://theprotocol.cloud/register?invite=BETA-A1B2-C3D4",
    },
    "operator_application_received": {
        "name": "Acme Frame Operators",
        "email": "ops@acme.example",
        "organization": "Acme",
        "deployment": "self-hosted-vps",
        "experience": "3-5 years",
        "use_case": "Run a regional registry for European agents.",
        "developer_linked": "Yes (id=42)",
        "timestamp": "2026-04-26 22:00 UTC",
    },
    "operator_application_approved": {"activation_code": "ACT-12345-XYZW"},
    "operator_suspended": {
        "name": "Acme Frame Operators",
        "reason": "Compliance review pending — suspending until resolution.",
    },
    "operator_reinstated": {"name": "Acme Frame Operators"},
    "operator_revoked": {
        "name": "Acme Frame Operators",
        "reason": "Sustained TOS violation after multiple warnings.",
    },
    "operator_activated": {
        "name": "Acme Frame Operators",
        "developer_email": "alice@acme.example",
        "bundle_status": "Provisioned — download from the Operator Portal",
        "pull_token": "dpt_sample_pull_token_value_shown_once_only",
        "docker_username": "operator-acme-frame-operators",
    },
    "frame_federation_invited": {
        "initiator_name": "Sovereign Frame Acme",
        "trust_domain": "frame.acme.example",
        "bundle_endpoint_url": "https://frame.acme.example:8443/",
        "federation_endpoint_url": "https://frame.acme.example/federation",
        "contact_email": "ops@acme.example",
        "source_ip": "203.0.113.10",
        "description": "Bilateral federation request from Acme.",
        "invitation_id": "inv-sample-1234",
    },
    "frame_federation_approved": {
        "local_name": "TheProtocol Mainframe",
        "initiator_trust_domain": "frame.acme.example",
        "local_trust_domain": "agentvault.com",
        "local_bundle_endpoint": "https://api.theprotocol.cloud:8443/",
        "invitation_id": "inv-sample-1234",
        "completed": True,
        "notes": "Bundle verified. Welcome.",
    },
    "frame_federation_rejected": {
        "local_name": "TheProtocol Mainframe",
        "invitation_id": "inv-sample-1234",
        "trust_domain": "frame.acme.example",
        "reason": "Bundle endpoint reachability check failed during review.",
    },
    "frame_federation_revoked": {
        "local_name": "TheProtocol Mainframe",
        "trust_domain": "frame.acme.example",
        "reason": "Compliance escalation; revoking federation.",
    },
    "admin_notice": {
        "kicker_label": "ADMIN NOTICE",
        "headline_text": "Sample Admin Notification",
        "body_text": "This is a generic admin notice rendered with the unified email base.\nIt accepts free-form body text plus optional rows + notice.",
        "rows": [
            ("Field A", "value-a"),
            ("Field B", "value-b"),
            ("Counter", "42"),
        ],
        "notice_text": "Optional info-box content below the rows.",
    },
    # ── Reactor-emitted security/critical events ─────────────────────────
    "agent_slashed": {
        "defendant_did": "did:theprotocol:7f9a-2c1d-sample-agent",
        "dispute_id": "dispute-2026-04-30-0042",
        "slash_tx_id": "tx-slash-9c4f1a8b-sample",
        "origin_registry_url": "https://api.theprotocol.cloud",
        "amount": "250.000000",
    },
    "attestation_revoked": {
        "attestation_id": "attest-7f3a-9c1b-sample",
        "agent_did": "did:theprotocol:5e2a-1b8c-sample-agent",
        "revoked_at": "2026-04-30 22:14:07 UTC",
        "revoked_by": "developer:42",
        "revoked_reason": "Circuit upgraded; previous proof bytes no longer cover the new policy parameters. Re-submit with circuit version 2.",
    },
    "bridge_transfer_expired": {
        "bridge_tx_id": "bridge-2026-04-30-0317-sample",
        "source_agent_did": "did:theprotocol:9b2f-4e8c-sample-source",
        "source_frame_id": "agentvault.com",
        "target_frame_id": "frame-b.theprotocol.cloud",
        "expires_at": "2026-04-30 22:55:00 UTC",
        "expired_at": "2026-04-30 23:55:00 UTC",
        "amount": "1500.000000",
    },
    "treasury_balance_corrected": {
        "agent_did": "did:theprotocol:treasury-corrections-recipient",
        "delta": "-12.345678",
        "new_balance": "9876.543210",
        "reason": "Reconciliation of off-chain settlement variance noted in 2026-04-29 audit. Negative delta records the correction without decrementing the issued total.",
        "actor": "commander@theprotocol.cloud",
        "recorded_at": "2026-04-30 18:32:11 UTC",
    },
    "webhook_retry_exhausted": {
        "webhook_id": "wh-acme-prod-001-sample",
        "target_url": "https://hooks.acme.example/theprotocol/events",
        "consecutive_failures": 12,
        "last_error": "HTTP 502 Bad Gateway (received 12 times in a row over 36 minutes)",
        "disabled_at": "2026-04-30 21:08:44 UTC",
    },
    # ── Net-new templates added 2026-05-01 polish pass ───────────────────
    "dispute_filed": {
        "dispute_id": "dispute-2026-05-01-0001",
        "claimant_did": "did:theprotocol:filer-3a1b-sample",
        "defendant_did": "did:theprotocol:respondent-7f9a-sample",
        "claim_summary": "Service was paid for via A2A authorization but never delivered. Settle window passed without invoice match.",
        "evidence_count": 3,
        "filed_at": "2026-05-01 09:14:22 UTC",
        "respond_by": "2026-05-08 09:14:22 UTC",
    },
    "agent_reinstated": {
        "agent_did": "did:theprotocol:reinstated-1d4e-sample",
        "previous_status": "suspended",
        "reinstated_by": "commander@theprotocol.cloud",
        "reason": "Compliance review complete; no further action required.",
        "reinstated_at": "2026-05-01 11:02:45 UTC",
    },
    "mtls_enrolled": {
        "agent_did": "did:theprotocol:mtls-enrolled-9c1f-sample",
        "spiffe_id": "spiffe://agentvault.com/agent/9c1f-sample",
        "cert_serial": "0x4f8a2b1c9e7d3f50",
        "issued_at": "2026-05-01 11:32:15 UTC",
        "expires_at": "2026-05-01 12:02:15 UTC",
        "renewal_window": "30 minutes (auto-renewed by SDK)",
    },
}


def _sample_context(template: str) -> Dict[str, Any]:
    """Sample context for `template`, packaged or private.

    §EXCISION: contexts for the private correspondence templates are NOT baked
    into the image (they name a counterparty and carry admin logins). They ship
    beside their templates in the bind-mounted private directory. Read on every
    call so the Commander can edit the fill-in values without a recreate.
    """
    if template in _SAMPLE_CONTEXT:
        return _SAMPLE_CONTEXT[template]
    path = PRIVATE_TEMPLATE_DIR / f"{template}.context.json"
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # JSON has no tuples; the templates iterate `(label, value)`
                # pairs, so re-tuple any 2-element list rows.
                return {
                    k: [tuple(i) if isinstance(i, list) and len(i) == 2 else i for i in v]
                    if isinstance(v, list) else v
                    for k, v in data.items()
                }
    except Exception as e:  # never let a malformed private file 500 the console
        logger.warning("private sample context unreadable for %s: %s", template, e)
    return {}


def _list_templates() -> list[str]:
    """Return the set of templates that have BOTH .html.j2 and .txt.j2 files.

    Searches every directory the Jinja env searches, not just the packaged one:
    §EXCISION moved the private correspondence templates out of the image and
    behind an optional bind-mount, so a node without that mount legitimately
    lists fewer templates than one with it.
    """
    html_stems: set[str] = set()
    txt_stems: set[str] = set()
    for template_dir in TEMPLATE_SEARCH_DIRS:
        if not template_dir.is_dir():
            continue
        html_stems |= {p.name[: -len(".html.j2")] for p in template_dir.glob("*.html.j2")}
        txt_stems |= {p.name[: -len(".txt.j2")] for p in template_dir.glob("*.txt.j2")}
    return sorted(html_stems & txt_stems)


def _render_preview(
    template: str,
    theme: str,
    context: Optional[Dict[str, Any]] = None,
    *,
    inline: bool = True,
) -> str:
    """Render a template like send_themed_email does, but without sending."""
    if theme not in PALETTES:
        raise HTTPException(status_code=400, detail=f"Unknown theme '{theme}'. Use neural|sovereign.")

    sample = _sample_context(template)
    # §MAILIDENT: same context builder as send_themed_email, so the preview shows
    # exactly the identity block (registry_name / registry_ui_url / frame_currency)
    # the recipient would get — a preview that renders differently from the send
    # path is a preview that gets believed and is wrong.
    from agentvault_registry.email_utils import build_email_context
    full_ctx = build_email_context(
        {**sample, **(context or {})},
        theme=theme,  # type: ignore[arg-type]
        subject=f"[Preview] {template}",
    )
    try:
        tpl = _jinja_env.get_template(f"{template}.html.j2")
        html = tpl.render(**full_ctx)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Render error: {exc}")
    if inline:
        html = _inline_styles(html)
    return html


@router.get("/preview", response_class=JSONResponse)
async def list_email_templates(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """List the templates available for preview."""
    return {
        "templates": _list_templates(),
        "themes": ["neural", "sovereign"],
        "neural_palette": NEURAL_PALETTE,
        "sovereign_palette": SOVEREIGN_PALETTE,
    }


@router.get("/preview/{template}", response_class=HTMLResponse)
async def preview_email_template(
    template: str,
    theme: str = "neural",
    inline: bool = True,
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Render an email template with the built-in sample context.

    `theme` is "neural" (default) or "sovereign".
    `inline=false` returns the raw Jinja-rendered HTML (with un-inlined <style>)
        for debugging the chassis.
    """
    return HTMLResponse(_render_preview(template, theme, inline=inline))


@router.get("/preview/{template}/text", response_class=PlainTextResponse)
async def preview_email_template_text(
    template: str,
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Render the matching plain-text alternative for a template."""
    sample = _sample_context(template)
    # §MAILIDENT: same builder as the send path — this route had its own third
    # copy of the context assembly, so text previews rendered WITHOUT the
    # identity block while real sends carried it. The live E2E caught it.
    from agentvault_registry.email_utils import build_email_context
    full_ctx = build_email_context(sample, theme="neural", subject=f"[Preview] {template}")
    try:
        tpl = _jinja_env.get_template(f"{template}.txt.j2")
        return PlainTextResponse(tpl.render(**full_ctx))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Render error: {exc}")


@router.post("/preview/{template}/text", response_class=PlainTextResponse)
async def preview_email_template_text_with_context(
    template: str,
    context: Dict[str, Any] = Body(default_factory=dict),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Plain-text render with caller-supplied context (overrides sample).

    The send dialog's TEXT toggle uses this so the text part it shows is the
    text part that would actually go out — the GET variant renders sample-only
    and would quietly lie once the admin has edited fields.
    """
    sample = _sample_context(template)
    # §MAILIDENT: same builder as the send path (fourth copy retired).
    from agentvault_registry.email_utils import build_email_context
    full_ctx = build_email_context(
        {**sample, **(context or {})}, theme="neural", subject=f"[Preview] {template}"
    )
    try:
        tpl = _jinja_env.get_template(f"{template}.txt.j2")
        return PlainTextResponse(tpl.render(**full_ctx))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Render error: {exc}")


@router.post("/preview/{template}", response_class=HTMLResponse)
async def preview_email_template_with_context(
    template: str,
    theme: str = "neural",
    inline: bool = True,
    context: Dict[str, Any] = Body(default_factory=dict),
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Render an email template with caller-supplied context (overrides sample)."""
    return HTMLResponse(_render_preview(template, theme, context=context, inline=inline))


# ---------------------------------------------------------------------------
# §2026-07-29 — Email Studio grows a SEND capability (Commander request:
# "choose recipient and which email i want to send it from").
#
# Sender choice is deliberately limited to the identities the SMTP relay will
# actually accept: Proton binds the From: header to the authenticated address,
# so a free-text From would render fine in preview and then bounce at the
# relay. We surface exactly what is configured — nothing that cannot send.
# ---------------------------------------------------------------------------

import re as _re

from pydantic import BaseModel, Field

from agentvault_registry.config import settings as _settings
from agentvault_registry.email_utils import send_themed_email as _send_themed_email

_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/senders", response_class=JSONResponse)
async def list_email_senders(
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """The From-identities this deployment can genuinely send as (no secrets)."""
    from agentvault_registry.email_utils import available_senders
    return {"senders": available_senders(), "smtp_configured": bool(_settings.MAIL_SERVER)}


@router.get("/context/{template}", response_class=JSONResponse)
async def get_template_sample_context(
    template: str,
    _admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """The sample context for a template, as editable JSON.

    This is what the send panel prefills, so the admin edits real fields
    instead of reconstructing the context shape from the template source.
    Tuples serialise as arrays; the templates iterate them identically.
    """
    if template not in _list_templates():
        raise HTTPException(status_code=404, detail=f"Unknown template '{template}'.")
    # §EXCISION — a per-template subject override rides in the private context
    # file (key `_subject`) rather than a packaged map, so the image carries no
    # trace of who we correspond with. Falls back to a generic subject.
    ctx = _sample_context(template)
    suggested = ctx.get("_subject") or f"TheProtocol · {template.replace('_', ' ')}"
    return {"template": template, "context": {k: v for k, v in ctx.items() if k != "_subject"},
            "suggested_subject": suggested}


class EmailSendRequest(BaseModel):
    template: str
    subject: str = Field(..., min_length=3, max_length=200)
    recipients: list[str] = Field(..., min_length=1, max_length=10)
    cc: Optional[list[str]] = None
    bcc: Optional[list[str]] = None
    # theme picks the sender identity (see /senders) AND the visual chassis.
    theme: str = Field("neural", pattern="^(neural|sovereign)$")
    # Which identity it goes out as (see /senders). None = theme-derived default.
    sender: Optional[str] = Field(None, pattern="^(noreply|founder|operators|security)$")
    # Overrides ON TOP of the sample context, so the panel only has to carry
    # the fields the admin actually changed (e.g. the real frame password).
    context: Dict[str, Any] = Field(default_factory=dict)


@router.post("/send", response_class=JSONResponse)
async def send_email_from_studio(
    req: EmailSendRequest,
    admin: models.Developer = Security(security.require_admin_flag("admin_platform")),
):
    """Send a rendered template to real recipients. This is a REAL send.

    Merge order matches the preview exactly (sample -> overrides), so what the
    admin previewed is what the recipient receives — the two paths cannot drift
    because both feed the same renderer with the same merged context.
    """
    if not _settings.MAIL_SERVER:
        raise HTTPException(status_code=503, detail="MAIL_SERVER is not configured on this deployment.")
    if req.template not in _list_templates():
        raise HTTPException(status_code=404, detail=f"Unknown template '{req.template}'.")
    for addr in (req.recipients + (req.cc or []) + (req.bcc or [])):
        if not _EMAIL_RE.match(addr or ""):
            raise HTTPException(status_code=422, detail=f"'{addr}' is not a valid email address.")

    merged = {**_sample_context(req.template), **req.context}
    ok = await _send_themed_email(
        subject=req.subject,
        recipients=req.recipients,
        template=req.template,
        context=merged,
        theme=req.theme,  # type: ignore[arg-type]
        cc=req.cc,
        bcc=req.bcc,
        sender=req.sender,
    )
    # Real outbound mail from an admin surface gets a loud, greppable trail.
    logger.info(
        "[EMAIL-STUDIO] send template=%s theme=%s sender=%s to=%s cc=%s bcc=%s by admin=%s ok=%s",
        req.template, req.theme, req.sender or "theme-default", req.recipients, req.cc or [], req.bcc or [], admin.id, ok,
    )
    if not ok:
        raise HTTPException(status_code=502, detail="SMTP send failed — see registry logs.")
    return {"sent": True, "template": req.template, "theme": req.theme,
            "recipients": req.recipients, "count": len(req.recipients)}
