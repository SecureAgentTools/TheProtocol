"""§LEGALKIT (W4): outbound mail names the provider behind the sending frame, from the facts, or not at all."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry import email_utils as eu  # noqa: E402

VARS = ["LEGAL_PROVIDER_LEGAL_NAME", "LEGAL_PROVIDER_TRADING_AS", "LEGAL_PROVIDER_STREET", "LEGAL_PROVIDER_POSTAL_CODE",
        "LEGAL_PROVIDER_CITY", "LEGAL_PROVIDER_COUNTRY", "LEGAL_CONTACT_EMAIL", "LEGAL_SUPPORT_EMAIL"]


def test_no_facts_no_line(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)
    ident = eu.deployment_identity()
    assert ident["provider_legal_line"] == "" and ident["legal_url"] == ""
    ctx = eu.build_email_context({}, theme="neural", subject="x")
    html = eu._jinja_env.get_template("_partials/footer.html").render(**ctx)
    assert "Provider:" not in html


def test_facts_render_the_line_in_html_and_text(monkeypatch):
    monkeypatch.setenv("LEGAL_PROVIDER_LEGAL_NAME", "Test Person")
    monkeypatch.setenv("LEGAL_PROVIDER_STREET", "Example Street 1")
    monkeypatch.setenv("LEGAL_PROVIDER_POSTAL_CODE", "12345")
    monkeypatch.setenv("LEGAL_PROVIDER_CITY", "Testtown")
    monkeypatch.setenv("LEGAL_PROVIDER_COUNTRY", "Germany")
    monkeypatch.setenv("LEGAL_CONTACT_EMAIL", "legal@example.invalid")
    ident = eu.deployment_identity()
    assert ident["provider_legal_line"].startswith("Test Person, Example Street 1, 12345 Testtown, Germany")
    ctx = eu.build_email_context({}, theme="neural", subject="x")
    html = eu._jinja_env.get_template("_partials/footer.html").render(**ctx)
    assert "Provider: Test Person, Example Street 1" in html
    txt = eu._jinja_env.get_template("_base.txt.j2").render(**ctx)
    assert "Provider: Test Person, Example Street 1" in txt
