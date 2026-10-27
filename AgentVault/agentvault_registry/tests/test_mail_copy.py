"""§MAILCOPY (2026-09-03, his word) — the two account mails name the PLATFORM in the subject and the
greeting; the registry keeps its place in the footer ("Sent by <registry>, a TheProtocol registry.").
The send functions are exercised end to end with the transport recorded, so the subject, the template
and the link shape are asserted as the recipient receives them. Pure: no SMTP, no relay, no network."""
import pytest

from agentvault_registry import email_utils as eu
from agentvault_registry.core import public_url as pu


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def _record(subject, recipients, template, context, **kw):
        calls.append({"subject": subject, "recipients": recipients, "template": template, "context": context, **kw})
        return True

    monkeypatch.setattr(eu, "send_themed_email", _record)
    if hasattr(eu, "relay_configured"):
        monkeypatch.setattr(eu, "relay_configured", lambda: False)
    monkeypatch.delenv("PUBLIC_UI_URL", raising=False)
    monkeypatch.setattr(pu, "public_base_url_static", lambda: "https://frame-c.theprotocol.cloud")
    monkeypatch.setattr(eu.settings, "MAIL_SERVER", "smtp.example.invalid", raising=False)
    monkeypatch.setattr(eu.settings, "MAIL_USERNAME", "noreply", raising=False)
    monkeypatch.setattr(eu.settings, "MAIL_FROM", "noreply@example.invalid", raising=False)
    return calls


@pytest.mark.asyncio
async def test_verification_mail_names_the_platform(sent):
    await eu.send_verification_email(to_email="ada@example.org", username="Ada Probe", token="tok-123")
    assert len(sent) == 1
    m = sent[0]
    assert m["subject"] == "Verify your email for TheProtocol"
    assert m["template"] == "verification"
    assert m["context"]["verification_link"] == "https://frame-c.theprotocol.cloud/api/v1/auth/verify-email?token=tok-123"
    html = eu._jinja_env.get_template("verification.html.j2").render(**eu.build_email_context(m["context"], theme="neural", subject=m["subject"]))
    assert "welcome to <strong>TheProtocol</strong>" in html
    assert "did not create an account on TheProtocol" in html
    assert "a TheProtocol registry" in html  # the footer still names the sending registry


@pytest.mark.asyncio
async def test_password_reset_mail_names_the_platform_and_the_console(sent):
    await eu.send_password_reset_email(to_email="ada@example.org", username="Ada Probe", token="tok-reset")
    assert len(sent) == 1
    m = sent[0]
    assert m["subject"] == "Password reset for your TheProtocol account"
    assert m["template"] == "password_reset"
    assert m["context"]["reset_link"] == "https://frame-c.theprotocol.cloud/ui/#/reset-password?token=tok-reset"
    assert m["context"]["expiry_hours"] == 1
    txt = eu._jinja_env.get_template("password_reset.txt.j2").render(**eu.build_email_context(m["context"], theme="sovereign", subject=m["subject"]))
    assert "your account on TheProtocol (" in txt


@pytest.mark.asyncio
async def test_reset_link_follows_the_console_knob(sent, monkeypatch):
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    await eu.send_password_reset_email(to_email="ada@example.org", username="Ada Probe", token="tok-apex")
    assert sent[0]["context"]["reset_link"] == "https://theprotocol.cloud/#/reset-password?token=tok-apex"


@pytest.mark.asyncio
async def test_verify_link_follows_the_console_origin_when_named(sent, monkeypatch):
    """registry-a: the link a person taps lives on the apex, the host they typed — one host from mail to home."""
    monkeypatch.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    await eu.send_verification_email(to_email="ada@example.org", username="Ada Probe", token="tok-apex")
    assert sent[0]["context"]["verification_link"] == "https://theprotocol.cloud/api/v1/auth/verify-email?token=tok-apex"


@pytest.mark.asyncio
async def test_verify_link_never_carries_an_operator_machine_port(sent, monkeypatch):
    monkeypatch.setattr(pu, "public_base_url_static", lambda: "https://op-berlin.op.theprotocol.cloud:27543")
    monkeypatch.setenv("PUBLIC_UI_URL", "https://op-berlin.op.theprotocol.cloud")
    await eu.send_verification_email(to_email="ada@example.org", username="Ada Probe", token="tok-op")
    assert sent[0]["context"]["verification_link"] == "https://op-berlin.op.theprotocol.cloud/api/v1/auth/verify-email?token=tok-op"

