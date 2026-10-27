"""Unit tests for the unified email pipeline.

Covers:
  - palette injection per theme
  - premailer inlining of CSS classes
  - plain-text + HTML multipart construction
  - sender-credential routing per theme
  - lint check: every .html.j2 has a matching .txt.j2

We mock aiosmtplib.send so no real SMTP traffic happens.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

# ⚠ `aiosmtplib.send()` returns a 2-TUPLE — (errors, response) — where `errors`
# maps refused recipients to their SMTP reply and `response` is the server's
# final line. It RAISES only when EVERY recipient is refused. A double that
# returns None (or a bare AsyncMock, whose MagicMock iterates empty) is
# UNFAITHFUL to that contract, and on 2026-09-04 that unfaithfulness made a
# CORRECT product change — §MAILHDRS, which started reading the tuple so a
# partial refusal could stop being logged as "Email sent" — look like a
# regression in two tests. The double must speak the library's language.
SMTP_ACCEPTED = ({}, "250 2.0.0 Ok: queued as TESTQUEUEID")

import pytest

from agentvault_registry import email_utils
from agentvault_registry.email_utils import (
    NEURAL_PALETTE,
    SOVEREIGN_PALETTE,
    PALETTES,
    _inline_styles,
    _resolve_sender,
    send_themed_email,
)


# ---------------------------------------------------------------------------
# Pure render tests — no SMTP at all.
# ---------------------------------------------------------------------------

def test_palettes_have_all_required_keys():
    """Every palette must define the keys the chassis expects."""
    required = {
        "bg", "surface", "border", "text_primary", "text_body",
        "kicker", "headline", "accent",
        "cta_bg", "cta_fg", "cta_border", "info_border", "muted",
    }
    for theme, palette in PALETTES.items():
        missing = required - set(palette.keys())
        assert not missing, f"theme {theme!r} missing palette keys: {missing}"


def test_neural_palette_uses_cyan_accent():
    assert NEURAL_PALETTE["accent"] == "#00d2d2"
    assert NEURAL_PALETTE["kicker"] == "#00d2d2"


def test_sovereign_palette_uses_sovereign_red():
    assert SOVEREIGN_PALETTE["accent"] == "#DC2626"
    assert SOVEREIGN_PALETTE["kicker"] == "#DC2626"


def test_inline_styles_strips_style_block_and_inlines_css():
    """premailer must move <style> rules into style="" attributes."""
    html = """<html><head><style>
      body { color: #DC2626; }
      .em-card { background: #1A1A1A; }
    </style></head><body><div class='em-card'>hi</div></body></html>"""
    out = _inline_styles(html)
    # premailer keeps the parsed declarations on each matching element.
    assert "<style>" not in out, "premailer must strip <style> blocks"
    assert "background:#1A1A1A" in out.replace(" ", "")


def test_every_html_template_has_matching_txt_template():
    """Lint check: every .html.j2 must have a parallel .txt.j2.

    §CHATCOHERE-CI (2026-09-01) — this read `loader.searchpath[0]`, which only
    exists on a bare `FileSystemLoader`. The env became a `ChoiceLoader` over
    several of them (public templates + the private-template dir), so the test
    raised `AttributeError` and had been red ever since — unnoticed, because
    nothing ran it.

    It now asks the module's OWN `TEMPLATE_SEARCH_DIRS` rather than reaching into
    Jinja's internals, so the lint follows the search path wherever it goes AND
    covers every directory rather than only the first — which is a wider check
    than the original ever performed.
    """
    dirs = [Path(d) for d in email_utils.TEMPLATE_SEARCH_DIRS if Path(d).is_dir()]
    assert dirs, "no template search dir exists — the lint would pass vacuously"
    missing = {}
    for d in dirs:
        html_stems = {p.name[: -len(".html.j2")] for p in d.glob("*.html.j2")}
        txt_stems = {p.name[: -len(".txt.j2")] for p in d.glob("*.txt.j2")}
        if html_stems - txt_stems:
            missing[str(d)] = sorted(html_stems - txt_stems)
    assert not missing, f"html templates without a txt sibling: {missing}"


# ---------------------------------------------------------------------------
# Sender-credential routing.
# ---------------------------------------------------------------------------

def test_resolve_sender_neural_uses_mail_username(monkeypatch):
    monkeypatch.setattr(email_utils.settings, "MAIL_USERNAME", "noreply@example.com")
    monkeypatch.setattr(email_utils.settings, "MAIL_PASSWORD", "neutral-pw")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM", "noreply@example.com")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM_NAME", "TheProtocol")
    user, pw, frm, name = _resolve_sender("neural")
    assert user == "noreply@example.com"
    assert frm == "noreply@example.com"
    assert name == "TheProtocol"


def test_resolve_sender_sovereign_prefers_security_username(monkeypatch):
    monkeypatch.setattr(email_utils.settings, "MAIL_USERNAME", "noreply@example.com")
    monkeypatch.setattr(email_utils.settings, "MAIL_PASSWORD", "neutral-pw")
    monkeypatch.setattr(
        email_utils.settings, "SECURITY_ALERTS_MAIL_USERNAME", "SecurityAlerts@example.com"
    )
    monkeypatch.setattr(email_utils.settings, "SECURITY_ALERTS_MAIL_PASSWORD", "")
    monkeypatch.setattr(
        email_utils.settings, "MAIL_FROM_NAME_SECURITY", "TheProtocol Security"
    )
    user, pw, frm, name = _resolve_sender("sovereign")
    assert user == "SecurityAlerts@example.com"
    assert frm == "SecurityAlerts@example.com"
    assert name == "TheProtocol Security"


def test_resolve_sender_sovereign_falls_back_when_username_unset(monkeypatch):
    monkeypatch.setattr(email_utils.settings, "SECURITY_ALERTS_MAIL_USERNAME", None)
    monkeypatch.setattr(email_utils.settings, "MAIL_USERNAME", "noreply@example.com")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM", "noreply@example.com")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM_NAME", "TheProtocol")
    user, _, frm, name = _resolve_sender("sovereign")
    assert user == "noreply@example.com"
    assert name == "TheProtocol"


# ---------------------------------------------------------------------------
# Full send path with mocked SMTP.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_themed_email_renders_both_parts(monkeypatch):
    """send_themed_email should build an EmailMessage with plain + html parts,
    inlined HTML, and pass the right credentials to aiosmtplib.send."""
    monkeypatch.setattr(email_utils.settings, "MAIL_SERVER", "smtp.test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PORT", 1025)
    monkeypatch.setattr(email_utils.settings, "MAIL_USERNAME", "noreply@test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PASSWORD", "")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM", "noreply@test")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM_NAME", "TheProtocol")
    monkeypatch.setattr(email_utils.settings, "MAIL_STARTTLS", False)
    monkeypatch.setattr(email_utils.settings, "MAIL_SSL_TLS", False)

    captured = {}
    async def fake_send(msg, **kwargs):
        captured["msg"] = msg
        captured["kwargs"] = kwargs
        return SMTP_ACCEPTED

    with patch.object(email_utils, "_inline_styles", side_effect=lambda h: h) as inline_spy:
        with patch("aiosmtplib.send", new=AsyncMock(side_effect=fake_send)):
            ok = await send_themed_email(
                subject="hello",
                recipients=["to@test"],
                template="verification",
                context={"username": "alice", "verification_link": "https://x", "expiry_hours": 24},
                theme="neural",
            )

    assert ok is True
    assert inline_spy.called, "premailer inliner must run"
    msg = captured["msg"]
    assert msg["Subject"] == "hello"
    assert "TheProtocol" in msg["From"]
    assert "to@test" in msg["To"]

    # multipart/alternative with text + html
    parts = list(msg.iter_parts())
    assert len(parts) >= 2
    types = sorted(p.get_content_type() for p in parts)
    assert types[:2] == ["text/html", "text/plain"]

    # Plain text contains rendered context
    text = msg.get_body(("plain",)).get_content()
    assert "alice" in text
    # HTML contains the chassis kicker
    html = msg.get_body(("html",)).get_content()
    assert "EMAIL VERIFICATION" in html.upper()


@pytest.mark.asyncio
async def test_send_themed_email_sovereign_uses_security_sender(monkeypatch):
    monkeypatch.setattr(email_utils.settings, "MAIL_SERVER", "smtp.test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PORT", 1025)
    monkeypatch.setattr(email_utils.settings, "MAIL_USERNAME", "noreply@test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PASSWORD", "")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM", "noreply@test")
    monkeypatch.setattr(
        email_utils.settings, "SECURITY_ALERTS_MAIL_USERNAME", "SecurityAlerts@test"
    )
    monkeypatch.setattr(email_utils.settings, "SECURITY_ALERTS_MAIL_PASSWORD", "")
    monkeypatch.setattr(
        email_utils.settings, "MAIL_FROM_NAME_SECURITY", "TheProtocol Security"
    )
    monkeypatch.setattr(email_utils.settings, "MAIL_STARTTLS", False)
    monkeypatch.setattr(email_utils.settings, "MAIL_SSL_TLS", False)

    captured = {}
    async def fake_send(msg, **kwargs):
        captured["msg"] = msg
        return SMTP_ACCEPTED

    with patch.object(email_utils, "_inline_styles", side_effect=lambda h: h):
        with patch("aiosmtplib.send", new=AsyncMock(side_effect=fake_send)):
            await send_themed_email(
                subject="reset",
                recipients=["alice@test"],
                template="password_reset",
                context={"username": "alice", "reset_link": "https://x", "expiry_hours": 24},
                theme="sovereign",
            )

    msg = captured["msg"]
    assert "SecurityAlerts@test" in msg["From"]
    assert "TheProtocol Security" in msg["From"]


@pytest.mark.asyncio
async def test_send_themed_email_returns_false_when_mailserver_unset(monkeypatch):
    monkeypatch.setattr(email_utils.settings, "MAIL_SERVER", None)
    ok = await send_themed_email(
        subject="x", recipients=["a@b"], template="verification",
        context={}, theme="neural",
    )
    assert ok is False


@pytest.mark.asyncio
async def test_send_email_legacy_shim_strips_html_suffix(monkeypatch):
    """The legacy send_email shim must accept "verification.html" and route to
    the .html.j2 template."""
    monkeypatch.setattr(email_utils.settings, "MAIL_SERVER", "smtp.test")
    monkeypatch.setattr(email_utils.settings, "MAIL_USERNAME", "noreply@test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PASSWORD", "")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM", "noreply@test")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM_NAME", "TheProtocol")
    monkeypatch.setattr(email_utils.settings, "MAIL_STARTTLS", False)
    monkeypatch.setattr(email_utils.settings, "MAIL_SSL_TLS", False)

    with patch.object(email_utils, "_inline_styles", side_effect=lambda h: h):
        with patch("aiosmtplib.send", new=AsyncMock(return_value=SMTP_ACCEPTED)):
            ok = await email_utils.send_email(
                subject="legacy",
                recipients=["a@b"],
                template_name="verification.html",
                template_body={"username": "u", "verification_link": "https://x", "expiry_hours": 1},
            )
    assert ok is True


@pytest.mark.asyncio
async def test_send_themed_email_reports_a_partial_recipient_refusal(monkeypatch):
    """A PARTIAL refusal must return False and name the refused recipient.

    §MAILHDRS (2026-09-04) changed what this function believes: `aiosmtplib.send`
    RAISES only when EVERY recipient is refused, so a mail accepted for one
    address and refused for another used to return True and log "Email sent" —
    the log line was never evidence of delivery. Nothing covered that path, which
    is how it survived; this is the test that makes the new behaviour real.

    The control is the sibling test above: the SAME call with an empty `errors`
    dict returns True, so this assertion cannot pass for the wrong reason.
    """
    monkeypatch.setattr(email_utils.settings, "MAIL_SERVER", "smtp.test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PORT", 1025)
    monkeypatch.setattr(email_utils.settings, "MAIL_USERNAME", "noreply@test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PASSWORD", "")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM", "noreply@test")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM_NAME", "TheProtocol")
    monkeypatch.setattr(email_utils.settings, "MAIL_STARTTLS", False)
    monkeypatch.setattr(email_utils.settings, "MAIL_SSL_TLS", False)

    refused = ({"bounce@test": (550, "5.1.1 unknown recipient")},
               "250 2.0.0 Ok: queued as PARTIAL")

    with patch.object(email_utils, "_inline_styles", side_effect=lambda h: h):
        with patch("aiosmtplib.send", new=AsyncMock(return_value=refused)):
            ok = await send_themed_email(
                subject="hello",
                recipients=["good@test", "bounce@test"],
                template="verification",
                context={"username": "alice", "verification_link": "https://x",
                         "expiry_hours": 24},
                theme="neural",
            )
    assert ok is False, "a refused recipient must not be reported as sent"


@pytest.mark.asyncio
async def test_send_themed_email_sets_date_and_message_id(monkeypatch):
    """Every mail carries Date and Message-ID.

    `EmailMessage()` sets neither and `aiosmtplib.send` adds neither, so before
    §MAILHDRS every mail this platform sent went out without them: Date is
    REQUIRED by RFC 5322 §3.6 and Message-ID is what receivers thread, dedupe
    and score on. The Message-ID domain must match the From domain so it aligns
    with the DKIM/SPF identity instead of leaking the container hostname.
    """
    monkeypatch.setattr(email_utils.settings, "MAIL_SERVER", "smtp.test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PORT", 1025)
    monkeypatch.setattr(email_utils.settings, "MAIL_USERNAME", "noreply@test")
    monkeypatch.setattr(email_utils.settings, "MAIL_PASSWORD", "")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM", "noreply@theprotocol.cloud")
    monkeypatch.setattr(email_utils.settings, "MAIL_FROM_NAME", "TheProtocol")
    monkeypatch.setattr(email_utils.settings, "MAIL_STARTTLS", False)
    monkeypatch.setattr(email_utils.settings, "MAIL_SSL_TLS", False)

    captured = {}

    async def fake_send(msg, **kwargs):
        captured["msg"] = msg
        return SMTP_ACCEPTED

    with patch.object(email_utils, "_inline_styles", side_effect=lambda h: h):
        with patch("aiosmtplib.send", new=AsyncMock(side_effect=fake_send)):
            ok = await send_themed_email(
                subject="hello",
                recipients=["to@test"],
                template="verification",
                context={"username": "alice", "verification_link": "https://x",
                         "expiry_hours": 24},
                theme="neural",
            )
    assert ok is True
    msg = captured["msg"]
    assert msg["Date"], "RFC 5322 §3.6 requires Date"
    assert msg["Message-ID"], "receivers thread and dedupe on Message-ID"
    assert msg["Message-ID"].endswith("@theprotocol.cloud>"), (
        f"Message-ID must align with the From domain, got {msg['Message-ID']}"
    )
