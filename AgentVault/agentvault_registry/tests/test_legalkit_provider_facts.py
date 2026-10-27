"""§LEGALKIT: provider facts are data, never literals; a `theprotocol` frame without them refuses to boot."""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry.core import provider_facts as pf  # noqa: E402

FACT_VARS = [
    "LEGAL_SUITE_MODE", "LEGAL_PROVIDER_LEGAL_NAME", "LEGAL_PROVIDER_LEGAL_FORM", "LEGAL_PROVIDER_TRADING_AS",
    "LEGAL_PROVIDER_STREET", "LEGAL_PROVIDER_POSTAL_CODE", "LEGAL_PROVIDER_CITY", "LEGAL_PROVIDER_COUNTRY",
    "LEGAL_PROVIDER_COUNTRY_CODE", "LEGAL_CONTACT_EMAIL", "LEGAL_PRIVACY_EMAIL", "LEGAL_SECURITY_EMAIL",
    "LEGAL_SUPPORT_EMAIL", "LEGAL_SUPERVISORY_AUTHORITY", "LEGAL_GOVERNING_LAW", "LEGAL_VENUE",
    "LEGAL_BUSINESS_DAYS", "LEGAL_VAT_ID", "LEGAL_SMALL_BUSINESS", "LEGAL_EDITORIAL_PERSON",
    "LEGAL_TERMS_URL", "LEGAL_PRIVACY_URL", "LEGAL_SECURITY_POLICY_URL", "LEGAL_PROVIDER_PHONE",
]


@pytest.fixture
def clean_env(monkeypatch):
    for v in FACT_VARS:
        monkeypatch.delenv(v, raising=False)
    yield monkeypatch


def _set_ours(monkeypatch):
    monkeypatch.setenv("LEGAL_SUITE_MODE", "theprotocol")
    monkeypatch.setenv("LEGAL_PROVIDER_LEGAL_NAME", "Test Person")
    monkeypatch.setenv("LEGAL_PROVIDER_TRADING_AS", "Test Trading Name")
    monkeypatch.setenv("LEGAL_PROVIDER_STREET", "Example Street 1")
    monkeypatch.setenv("LEGAL_PROVIDER_POSTAL_CODE", "12345")
    monkeypatch.setenv("LEGAL_PROVIDER_CITY", "Testtown")
    monkeypatch.setenv("LEGAL_PROVIDER_COUNTRY", "Germany")
    monkeypatch.setenv("LEGAL_CONTACT_EMAIL", "legal@example.invalid")
    monkeypatch.setenv("LEGAL_PRIVACY_EMAIL", "privacy@example.invalid")
    monkeypatch.setenv("LEGAL_SECURITY_EMAIL", "security@example.invalid")


def test_no_literal_defaults_anywhere(clean_env):
    """The control the export gate relies on: with nothing set, every fact is None and nothing is invented."""
    f = pf.provider_facts()
    assert all(getattr(f, k) is None for k in f.__dataclass_fields__ if k not in ("small_business",))
    assert f.small_business is False
    assert f.full_line is None and f.address_block is None and f.address_line is None
    assert pf.suite_mode() == pf.MODE_OPERATOR
    assert pf.has_provider_identity(f) is False


def test_theprotocol_mode_without_facts_refuses_boot(clean_env):
    clean_env.setenv("LEGAL_SUITE_MODE", "theprotocol")
    with pytest.raises(RuntimeError) as exc:
        pf.validate_at_boot()
    assert "legal_name" in str(exc.value) and "street" in str(exc.value)


def test_theprotocol_mode_with_facts_boots_and_renders(clean_env):
    _set_ours(clean_env)
    pf.validate_at_boot()
    f = pf.provider_facts()
    assert f.missing() == []
    assert f.full_line == 'Test Person, trading as "Test Trading Name", Example Street 1, 12345 Testtown, Germany'
    assert f.address_block == "Test Person\nExample Street 1\n12345 Testtown\nGermany"
    assert f.editorial_person == "Test Person"  # defaults to the legal name
    cfg = pf.legal_config(tos_version="2.1", documents_version="2.1", effective="2026-10-20", published="2026-09-20")
    assert cfg["mode"] == "theprotocol" and cfg["provider"]["full_line"] == f.full_line
    assert cfg["operator_links"] is None


def test_operator_mode_never_borrows_and_publishes_links(clean_env):
    clean_env.setenv("LEGAL_TERMS_URL", "https://operator.example.invalid/terms")
    cfg = pf.legal_config(tos_version="2.1", documents_version="2.1", effective="x", published="y")
    assert cfg["mode"] == "operator" and cfg["provider"] is None and cfg["provider_identified"] is False
    assert cfg["operator_links"]["terms_url"].endswith("/terms")
    # an operator who names themselves is identified without switching mode
    clean_env.setenv("LEGAL_PROVIDER_LEGAL_NAME", "Some Operator")
    clean_env.setenv("LEGAL_SUPPORT_EMAIL", "ops@operator.example.invalid")
    cfg = pf.legal_config(tos_version="2.1", documents_version="2.1", effective="x", published="y")
    assert cfg["mode"] == "operator" and cfg["provider_identified"] is True
    assert cfg["provider"]["legal_name"] == "Some Operator"
    pf.validate_at_boot()  # operator mode never refuses


def test_control_mode_spelling_is_strict(clean_env):
    clean_env.setenv("LEGAL_SUITE_MODE", "TheProtocol ")
    assert pf.suite_mode() == pf.MODE_THEPROTOCOL
    clean_env.setenv("LEGAL_SUITE_MODE", "ours")
    assert pf.suite_mode() == pf.MODE_OPERATOR


def test_source_code_url_is_served_only_when_it_is_a_url(monkeypatch):
    """AGPL-3.0 § 13 by configuration (2026-09-30): the legal config names where this deployment's source is, or nothing."""
    monkeypatch.delenv("SOURCE_CODE_URL", raising=False)
    assert pf.legal_config(tos_version="2.3", documents_version="2.4", effective="x", published="y")["source_code_url"] is None
    monkeypatch.setenv("SOURCE_CODE_URL", "https://github.com/example/fork/tree/v1")
    assert pf.source_code_url() == "https://github.com/example/fork/tree/v1"
    for bad in ("github.com/example/fork", "javascript:alert(1)", "https://a b", "https://x/" + "a" * 400, "  "):
        monkeypatch.setenv("SOURCE_CODE_URL", bad)
        assert pf.source_code_url() is None, bad


def test_phone_is_optional_and_never_a_placeholder(clean_env):
    """§COOKIES (2026-10-02): the imprint's second direct channel beside the email (§ 5 (1) no. 2 DDG). A frame without a
    phone still boots and serves no phone at all; a phone that is set is served as written; whitespace counts as unset."""
    _set_ours(clean_env)
    pf.validate_at_boot()  # optional: never a reason to refuse a boot
    assert pf.provider_facts().phone is None
    cfg = pf.legal_config(tos_version="2.3", documents_version="2.4", effective="x", published="y")
    assert cfg["provider"]["phone"] is None
    clean_env.setenv("LEGAL_PROVIDER_PHONE", "+49 30 1234567")
    assert pf.provider_facts().as_public_dict()["phone"] == "+49 30 1234567"
    clean_env.setenv("LEGAL_PROVIDER_PHONE", "   ")
    assert pf.provider_facts().phone is None
