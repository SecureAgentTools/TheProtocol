"""§EXTTEST (V0649): fixes from the external dev-machine test of 2026-10-30 (sessionlogs2026/exttest-REPORT-2026-10-30.md):
the create-agent schema dropped agent_name silently, disable-mtls promised "4 hours" for a 30-minute certificate, and the
registration mail did not open the resend window, so the first login mailed the same link again."""
import pathlib

from agentvault_registry.routers import agent_mtls, auth_secure, onboarding


def test_the_placeholder_card_takes_the_creators_name():
    card = onboarding._build_stub_card_data("https://exttest-agent-1.invalid", None, name="exttest-agent-1")
    assert card["name"] == "exttest-agent-1"


def test_without_a_name_the_placeholder_card_keeps_the_hosts_slug():
    card = onboarding._build_stub_card_data("https://exttest-agent-1.invalid", None)
    assert card["name"] and card["name"] != "exttest-agent-1"


def test_create_agent_accepts_agent_name():
    req = onboarding.CreateAgentRequest(agent_host="https://exttest-agent-1.invalid", agent_did_method="theprotocol",
                                         agent_name="exttest-agent-1")
    assert req.agent_name == "exttest-agent-1"


def test_disable_mtls_no_longer_promises_four_hours():
    src = pathlib.Path(agent_mtls.__file__).read_text(encoding="utf-8")
    assert "Existing SVID will expire within 4 hours" not in src   # the old sentence, verbatim
    assert "_inline_svid_ttl() // 60" in src


def test_the_registration_mail_opens_the_resend_window():
    src = pathlib.Path(auth_secure.__file__).read_text(encoding="utf-8")
    at = src.index('logger.info(f"Verification email sent for {created_developer.email}")')
    assert "await _verification_resend_allowed(created_developer.id)" in src[at:at + 600]


def _fresh_agent():
    import types
    return types.SimpleNamespace(did="did:theprotocol:frame.example:0f0e0d0c", status="active", mtls_enabled=False,
                                 spiffe_id=None, mtls_revoked_at=None, mtls_enrolled_at=None)


def test_a_frame_without_its_runner_answers_503_naming_the_fix(monkeypatch):
    """§EXTTEST run 2 (2026-10-31): enable-mtls on a kit frame stood up without --with-runner answered a bare 500
    ("SPIRE registration failed: no frame runner operator socket at ..."). It is a known state of the frame: 503, and the
    sentence names the fix. RED control: V0648's agent_mtls lets SpireOpsUnavailable fall into the generic 500."""
    import asyncio
    import pytest
    from fastapi import HTTPException
    from agentvault_registry.services.spire_ops_client import SpireOpsUnavailable

    def no_runner(*a, **k):
        raise SpireOpsUnavailable("no frame runner operator socket at /run/theprotocol/frame-runner.sock")

    monkeypatch.setattr(agent_mtls, "_detect_deployment", lambda request, did: ("onbox", "internal_network_source"))
    monkeypatch.setattr(agent_mtls, "_parent_fingerprint_for_self", lambda: "f" * 40)
    monkeypatch.setattr(agent_mtls, "register_agent_spire_entry", no_runner)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(agent_mtls.enable_mtls(request=None, current_agent=_fresh_agent(), db=None))
    assert exc.value.status_code == 503
    assert "--with-runner" in exc.value.detail and "no frame runner operator socket" in exc.value.detail


def test_an_external_enrollment_without_the_runner_says_why(monkeypatch):
    """The same state on the external path: nothing is written (200 not_enrolled, as before) and the answer now names
    the runner instead of only "Retry"."""
    import asyncio
    from agentvault_registry.services.spire_ops_client import SpireOpsUnavailable

    def no_runner(*a, **k):
        raise SpireOpsUnavailable("no frame runner operator socket at /run/theprotocol/frame-runner.sock")

    monkeypatch.setattr(agent_mtls, "_detect_deployment", lambda request, did: ("external", "public_network_source"))
    monkeypatch.setattr(agent_mtls, "_inline_svid_enabled", lambda: True)
    monkeypatch.setattr(agent_mtls, "mint_agent_svid", no_runner)
    out = asyncio.run(agent_mtls.enable_mtls(request=None, current_agent=_fresh_agent(), db=None))
    assert out["status"] == "not_enrolled" and out["delivery"] == "mint_failed"
    assert "--with-runner" in out["instructions"]


def test_initialize_answers_the_version_the_client_asked_for_when_supported():
    """§EXTTEST run 2 (2026-10-31): EU answered protocolVersion 2025-11-25 to a client that asked for 2025-06-18. The MCP
    lifecycle rule: a supported requested version is echoed, anything else gets the latest. RED control: V0648's
    _handle_initialize returns its constant."""
    import asyncio
    from agentvault_registry.mcp import server
    from agentvault_registry.mcp.protocol_version import LATEST_PROTOCOL_VERSION, negotiate_protocol_version
    assert asyncio.run(server._handle_initialize({"protocolVersion": "2025-06-18"}))["protocolVersion"] == "2025-06-18"
    assert asyncio.run(server._handle_initialize({"protocolVersion": "2099-01-01"}))["protocolVersion"] == LATEST_PROTOCOL_VERSION
    assert negotiate_protocol_version(None) == LATEST_PROTOCOL_VERSION
    assert negotiate_protocol_version({"protocolVersion": 2025}) == LATEST_PROTOCOL_VERSION


def test_the_admin_server_negotiates_with_the_same_rule():
    from agentvault_registry.mcp import server_admin
    src = pathlib.Path(server_admin.__file__).read_text(encoding="utf-8")
    at = src.index('if method == "initialize":')
    assert '"protocolVersion": negotiate_protocol_version(params)' in src[at:at + 300]
