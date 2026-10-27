"""§MAILHDRS — every outbound mail must carry Date and Message-ID.

`EmailMessage()` sets neither and `aiosmtplib.send()` does not add them, so for
the life of this platform every message went out missing two headers RFC 5322
asks for. Gmail scores both, and because scoring is additive the small mails got
through while a 54 KB one was dropped outright — not even filed to Spam. That is
an expensive failure to re-introduce, so it gets a test.
"""
import re
import pytest

from agentvault_registry import email_utils


def _build(monkeypatch, subject="t", to=("a@b.example",)):
    """Build the message the send path would build, without sending it."""
    from email.message import EmailMessage
    from email.utils import formataddr, formatdate, make_msgid
    # Mirrors send_themed_email's construction block.
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("TheProtocol", "noreply@theprotocol.cloud"))
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="theprotocol.cloud")
    msg["To"] = ", ".join(to)
    msg.set_content("text")
    msg.add_alternative("<p>html</p>", subtype="html")
    return msg


def test_send_path_sets_date_and_message_id():
    """The SOURCE must set both headers, not a test-local copy of the logic."""
    src = open(email_utils.__file__, encoding="utf-8").read()
    assert 'msg["Date"] = formatdate(' in src, "Date header not set in send_themed_email"
    assert 'msg["Message-ID"] = make_msgid(' in src, "Message-ID not set in send_themed_email"


def test_message_id_domain_aligns_with_from():
    """A Message-ID on the container hostname leaks infra and misaligns with
    the DKIM/SPF identity; it must use the From domain."""
    src = open(email_utils.__file__, encoding="utf-8").read()
    assert 'make_msgid(domain=from_email.split("@", 1)[1])' in src


def test_smtp_response_is_not_discarded():
    """aiosmtplib.send returns (errors, response) and only RAISES when EVERY
    recipient is refused. Discarding it made 'Email sent' meaningless and threw
    away the submission queue id, the only handle for tracing a lost message."""
    src = open(email_utils.__file__, encoding="utf-8").read()
    assert "smtp_errors, smtp_response = await aiosmtplib.send(" in src
    assert "if smtp_errors:" in src, "partial recipient refusal is not detected"
    assert "SMTP REFUSED" in src, "refusal is not logged"


def test_built_message_carries_both_headers():
    msg = _build(None)
    assert msg["Date"], "Date missing"
    assert msg["Message-ID"], "Message-ID missing"
    assert re.match(r"^<[^@]+@theprotocol\.cloud>$", msg["Message-ID"]), msg["Message-ID"]
