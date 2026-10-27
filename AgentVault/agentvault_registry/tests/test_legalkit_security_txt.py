"""§LEGALKIT: security.txt names the frame's own security contact or nothing; never the author's mailbox."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry.routers import public_badge as pb  # noqa: E402

VARS = ["SECURITY_CONTACT_EMAIL", "LEGAL_SECURITY_EMAIL", "LEGAL_CONTACT_EMAIL", "LEGAL_SUITE_MODE",
        "LEGAL_SECURITY_POLICY_URL", "PUBLIC_UI_URL", "BASE_URL"]


def _clear(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)


def test_no_contact_means_no_file(monkeypatch):
    _clear(monkeypatch)
    assert pb._build_security_txt() is None


def test_facts_contact_and_policy(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LEGAL_SECURITY_EMAIL", "sec@example.invalid")
    body = pb._build_security_txt()
    assert "Contact: mailto:sec@example.invalid" in body and "Expires:" in body
    assert "Policy:" not in body  # operator mode with no policy link says nothing about a policy
    monkeypatch.setenv("LEGAL_SECURITY_POLICY_URL", "https://operator.example.invalid/security")
    assert "Policy: https://operator.example.invalid/security" in pb._build_security_txt()


def test_explicit_override_wins_and_no_author_literal_survives(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("LEGAL_SECURITY_EMAIL", "sec@example.invalid")
    monkeypatch.setenv("SECURITY_CONTACT_EMAIL", "override@example.invalid")
    assert "Contact: mailto:override@example.invalid" in pb._build_security_txt()
    import inspect
    src = inspect.getsource(pb)
    assert "jeziorny" not in src.lower()
