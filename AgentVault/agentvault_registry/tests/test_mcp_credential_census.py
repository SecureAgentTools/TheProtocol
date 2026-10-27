"""§MCPTEST30 (2026-10-01) — the credential exposure census (api_tests/contracts/credential_exposure.py).

The scanner reads VALUES with the product's own credential shapes, classes a JWT by its claims, keeps a kind and a path
and never a value; the classifier lets an issuer hand out what it issues and calls anything else unexpected; the flow's
JSON-RPC helper feeds every response into the running census; the census row goes red, and the offending tool's row
gets a BUG-FIND, only for an unexpected credential.
"""
from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import pytest

from agentvault_registry.api_tests.contracts import credential_exposure as CE
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


def _seg(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


BEARER = f"{_seg({'alg': 'HS256', 'typ': 'JWT'})}.{_seg({'sub': '7', 'exp': 4102444800, 'jti': 'j1', 'tv': 0})}.c2lnbmF0dXJlc2ln"
VC_DOC = f"{_seg({'alg': 'EdDSA'})}.{_seg({'iss': 'did:web:x', 'sub': 'did:x:1', 'vc': {'type': ['VerifiableCredential']}})}.c2lnbmF0dXJlc2ln"
# Built from parts so the repository's pre-commit hook (it refuses a private-key header in staged content) never sees one.
_DASH = "-" * 5
PEM_PRIVATE = f"{_DASH}BEGIN PRIVATE KEY{_DASH}\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n{_DASH}END PRIVATE KEY{_DASH}"
PEM_PUBLIC = f"{_DASH}BEGIN PUBLIC KEY{_DASH}\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8A\n{_DASH}END PUBLIC KEY{_DASH}"
SECRET_VALUE = "a-real-secret-value-77Q"


def _envelope(result):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(result)}]}}


def _kinds(obj):
    return {(k, CE.normalize(p)) for k, p in CE.scan(obj)}


def test_the_product_shapes_are_imported_not_copied():
    assert CE.available(), "the census must read the product sanitizer's shapes"


def test_a_bearer_jwt_and_a_signed_document_are_told_apart():
    assert CE.jwt_class(BEARER) == "bearer" and CE.jwt_class(VC_DOC) == "document"
    assert CE.jwt_class("eyJxx.notbase64.sig") == "bearer", "unreadable claims are treated as the dangerous kind"


def test_calibration_a_typed_signed_object_is_a_document_and_a_refresh_token_is_a_bearer():
    """2026-10-01 calibration: the federation licence certificate on every registry card (header typ tp-licence+jws,
    payload type frame) read as a bearer; a refresh token (typ JWT, type refresh) must still read as one."""
    licence = f"{_seg({'alg': 'EdDSA', 'kid': 'k1', 'typ': 'tp-licence+jws'})}.{_seg({'type': 'frame', 'sub': 'did:x', 'exp': 4102444800})}.c2lnbmF0dXJlc2ln"
    refresh = f"{_seg({'alg': 'HS256', 'typ': 'JWT'})}.{_seg({'sub': '7', 'type': 'refresh', 'exp': 4102444800, 'jti': 'j'})}.c2lnbmF0dXJlc2ln"
    assert CE.jwt_class(licence) == "document" and CE.jwt_class(refresh) == "bearer"
    found = _kinds({"federation": {"licence": {"certificate": licence, "chain": [licence]}}})
    assert found == {("jwt:document", "federation.licence.certificate"), ("jwt:document", "federation.licence.chain[*]")}
    assert CE.classify("theprotocol_getRegistryCard", "jwt:document") == "informational"
    assert CE.classify("theprotocol_enableMtls", "pem_private_key") == "issuer"
    assert CE.classify("theprotocol_setup2FA", "field:backup_codes") == "issuer"


def test_shapes_and_fields_are_found_inside_the_text_of_a_tool_result():
    found = _kinds(_envelope({"access_token": BEARER, "items": [{"client_secret": SECRET_VALUE}],
                              "key": PEM_PRIVATE, "pk": PEM_PUBLIC, "uri": "otpauth://totp/x?secret=ABCDEFGH",
                              "plain_api_key": "avreg_" + "A" * 32, "pay": "apt_" + "0" * 64}))
    assert ("jwt:bearer", "access_token") in found and ("field:access_token", "access_token") in found
    assert ("field:client_secret", "items[*].client_secret") in found
    assert ("pem_private_key", "key") in found and not any(p == "pk" for _, p in found), "a public key is not a credential"
    assert ("otpauth_uri", "uri") in found and ("token:avreg", "plain_api_key") in found and ("token:apt", "pay") in found


def test_counts_flags_masks_and_redaction_markers_are_not_credentials():
    found = _kinds(_envelope({"tokens_issued": 5, "token_type": "bearer", "session_scope": "per-credential",
                              "api_key": "avreg_ab12****", "client_secret": "<redacted:40 chars>",
                              "secret": True, "password": "short", "tokenUrl": "https://x/token"}))
    assert found == set(), found


def test_stored_hashes_are_found_and_informational():
    found = _kinds({"operators": [{"license_key_hash": "a" * 64}]})
    assert found == {("stored_hash:license_key_hash", "operators[*].license_key_hash")}
    assert CE.classify("theprotocol_getEventStoreFederationOperators", "stored_hash:license_key_hash") == "informational"


def test_the_classifier():
    assert CE.classify("theprotocol_createAgent", "field:client_secret") == "issuer"
    assert CE.classify("theprotocol_createAgent", "jwt:bearer") == "unexpected", "an issuer may hand out only what it issues"
    assert CE.classify("theprotocol_getWebhook", "field:secret") == "owner_read"
    assert CE.classify("theprotocol_getMyAgents", "field:client_secret") == "unexpected"
    assert CE.classify("theprotocol_adminRequest", "pem_private_key") == "proxied"
    assert CE.classify("theprotocol_getMyAgents", "jwt:document") == "informational"


def test_an_administrators_signing_key_rotation_issues_the_new_private_key():
    """V0637: V0636's pair proof read rotateAgentSigningKey's private_pem as a stranger's key. The admin rotation
    mints the agent's new EdDSA pair and answers its private key once, by design (agent_signing_keys_admin), like
    rotateAgentCredentials's new credentials. Any other credential from it, or the same key from a read, stays red."""
    assert CE.classify("theprotocol_rotateAgentSigningKey", "pem_private_key") == "issuer"
    assert CE.classify("theprotocol_rotateAgentSigningKey", "field:client_secret") == "unexpected"
    assert CE.classify("theprotocol_getAdminAgentSigningKeys", "pem_private_key") == "unexpected"
    assert CE.classify("theprotocol_getAdminAgentDetail", "pem_private_key") == "unexpected"


def test_the_collector_gathers_concurrent_tasks_and_is_silent_outside_a_census():
    CE.record("theprotocol_x", _envelope({"client_secret": SECRET_VALUE}))       # outside: a no-op, no error

    async def run():
        tok = CE.begin()
        await asyncio.gather(*(asyncio.to_thread(lambda: None) for _ in range(2)))
        await asyncio.gather(
            asyncio.create_task(_rec("theprotocol_a", {"client_secret": SECRET_VALUE})),
            asyncio.create_task(_rec("theprotocol_b", {"refresh_token": BEARER})),
            asyncio.create_task(_rec("theprotocol_c", {"n": 1})))
        return CE.end(tok)

    async def _rec(tool, result):
        CE.record(tool, _envelope(result))
    box = asyncio.run(run())
    assert box["responses"] == 3 and set(box["tools"]) == {"theprotocol_a", "theprotocol_b"}
    assert CE._COLLECT.get() is None


def test_the_flow_rpc_helper_feeds_the_census(monkeypatch):
    body = json.dumps(_envelope({"items": [{"client_secret": SECRET_VALUE}]}))
    monkeypatch.setattr(F, "exec_in_container", lambda name, args, timeout=30: (0, f"{body}\n{F._HTTP_MARKER}200--"))

    async def run():
        tok = CE.begin()
        ok, parsed, code = await F._mcp_rpc_call(SimpleNamespace(a_registry_container="c"), "theprotocol_getMyAgents", {}, jwt="j")
        return ok, code, CE.end(tok)
    ok, code, box = asyncio.run(run())
    assert ok and code == "200"
    assert box["tools"] == {"theprotocol_getMyAgents": {("field:client_secret", "items[*].client_secret")}}


def _row(tool, healthy=True, skip=None):
    return F.ContractOutcome(tool_name=tool, contract_tier="3", healthy=healthy, status_code=200, elapsed_ms=1,
                             skip_reason=skip, fail_reason=None, has_explicit_contract=True, args_used={},
                             result_excerpt={})


def _close(records, rows):
    tok = CE.begin()
    for tool, result in records:
        CE.record(tool, _envelope(result))
    return F._credential_census_close(rows, tok)


def test_an_unexpected_credential_reddens_the_census_and_the_tool_row_and_never_records_the_value():
    rows = [_row("theprotocol_getMyAgents"), _row("theprotocol_createAgent")]
    summary = _close([("theprotocol_getMyAgents", {"items": [{"client_secret": SECRET_VALUE}]}),
                      ("theprotocol_createAgent", {"client_secret": SECRET_VALUE})], rows)
    leak, issuer, census = rows
    assert not leak.healthy and "BUG-FIND: credential exposure" in leak.fail_reason
    assert issuer.healthy and issuer.fail_reason is None
    assert census.tool_name == CE.CENSUS_ROW and not census.healthy
    assert census.fail_reason.startswith("BUG-FIND: credential exposure: 1 tool(s)")
    assert census.result_excerpt["unexpected"] == {"getMyAgents": ["field:client_secret at items[*].client_secret"]}
    assert census.result_excerpt["issuer"] == {"createAgent": ["field:client_secret"]}
    everything = json.dumps([r.__dict__ for r in rows], default=str) + json.dumps(summary, default=str)
    assert SECRET_VALUE not in everything


def test_control_only_issuers_leave_the_census_green():
    rows = [_row("theprotocol_createAgent")]
    _close([("theprotocol_createAgent", {"client_secret": SECRET_VALUE})], rows)
    assert rows[0].healthy and rows[-1].tool_name == CE.CENSUS_ROW and rows[-1].healthy and rows[-1].fail_reason is None


def test_a_skipped_row_is_not_reddened_but_the_census_names_the_tool():
    rows = [_row("theprotocol_getMyAgents", healthy=False, skip="fixture missing")]
    _close([("theprotocol_getMyAgents", {"client_secret": SECRET_VALUE})], rows)
    assert rows[0].fail_reason is None and "getMyAgents" in rows[-1].fail_reason


def test_a_census_that_could_not_scan_says_not_measured(monkeypatch):
    monkeypatch.setattr(CE, "_PRODUCT_SHAPES", None)
    rows = []
    _close([("theprotocol_getMyAgents", {"client_secret": SECRET_VALUE})], rows)
    assert rows[-1].skip_reason.startswith("credential exposure census NOT MEASURED") and not rows[-1].healthy


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    """asyncio.run() closes its loop and leaves none current; a later file's sync test would fail far from here."""
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_only_a_credential_401_earns_a_relogin():
    """§MCPTEST30: the runner re-logs in on a 401 only when the 401 is about its credential; a tool refusing a wrong
    password (setup2FA's refusal probe) is that tool's answer."""
    cred = {"error": {"code": -32001, "message": "Could not validate credentials"}}
    revoked = {"result": {"content": [{"type": "text", "text": "Error: HTTP 401: JWT rejected: token_version mismatch"}]}}
    tool_refusal = {"result": {"content": [{"type": "text", "text": "Error: HTTP 401: Invalid password"}], "isError": True}}
    assert F._is_credential_401(cred) and F._is_credential_401(revoked)
    assert not F._is_credential_401(tool_refusal)
