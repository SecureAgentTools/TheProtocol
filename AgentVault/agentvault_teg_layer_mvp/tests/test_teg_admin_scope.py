"""§TEGSCOPE (2026-10-07, his word "2. yes fix"): the TEG's admin role follows the caller's RELATION to this TEG.

sessionlogs2026/FINDINGS_2026-10-02_TEG_ADMIN_SCOPE.md: every internal service identity of every trusted domain was an
admin on every admin route, so a peer frame's registry could read and move this frame's treasury (measured 200 on
treasury/info and fee-collector/info on the sandbox pair). Now:
  own         (same trust domain, same owner: the frame's /service/ ids, an operator's /operator/<op>/ ids) -> everything
  peer        (another trusted domain)        -> TEG_PEER_ADMIN_ROUTES (default GET fx/reserve, POST fx/move)
  local-other (same domain, another owner)    -> TEG_LOCAL_OTHER_ADMIN_ROUTES (default none)
The certificates are real (minted here). RED control: with the module before this change every peer and local-other
refusal below is accepted ("mtls"), while the own and FX-route controls pass on both.
"""
from __future__ import annotations

import datetime
import logging
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from starlette.requests import Request

from teg_core_service.core import internal_auth as ia

MARKER = "X-TEG-Proxy-Auth"
SECRET = "test-only-marker-0123456789-abcdefghijkl"   # a made-up value of the right shape, never a real secret
A, B = "sandbox-a.theprotocol.cloud", "sandbox-b.theprotocol.cloud"
FRAME_TEG = f"spiffe://{A}/service/teg-layer"
OP_TEG = f"spiffe://{A}/operator/sbxalphaop/svid-writer"
FRAME_REG = f"spiffe://{A}/service/sbx-alpha-registry"
PEER_REG = f"spiffe://{B}/service/sbx-beta-registry"
OWN_OP_REG = f"spiffe://{A}/operator/sbxalphaop/registry"
OTHER_OP_REG = f"spiffe://{A}/operator/elsewhere/registry"
RESERVE, MOVE = "/api/v1/admin/fx/reserve", "/api/v1/admin/fx/move"
TREASURY, FEES = "/api/v1/admin/treasury/info", "/api/v1/admin/fee-collector/info"


def _cert(uri: str):
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "workload")])
    return (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(uri)]), critical=False)
            .sign(key, hashes.SHA256()))


def _request(caller: str, method: str, path: str) -> Request:
    pem = _cert(caller).public_bytes(serialization.Encoding.PEM).decode()
    headers = {"X-SSL-Client-Cert": urllib.parse.quote(pem), "X-SSL-Client-Verify": "SUCCESS", MARKER: SECRET}
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    return Request({"type": "http", "method": method, "path": path, "raw_path": path.encode(),
                    "query_string": b"", "headers": raw})


def _call(caller: str, method: str, path: str):
    return ia.resolve_internal_caller(_request(caller, method, path), route=path)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", f"{A},{B}")
    monkeypatch.setenv("TEG_PROXY_TRUST_SECRET", SECRET)
    monkeypatch.setenv("TEG_MTLS_REQUIRED", "true")
    for name in ("TEG_ADMIN_SCOPE_MODE", "TEG_PEER_ADMIN_ROUTES", "TEG_LOCAL_OTHER_ADMIN_ROUTES", "TEG_OWN_SPIFFE_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(ia._OWN_ID, "value", None)
    monkeypatch.setitem(ia._OWN_ID, "read_at", 0.0)


def _refused(caller, method, path):
    with pytest.raises(HTTPException) as e:
        _call(caller, method, path)
    assert e.value.status_code == 403 and "admin scope" in str(e.value.detail), e.value.detail
    return e.value.detail


def test_on_a_frame_teg_its_own_frame_keeps_every_admin_route(monkeypatch):
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", FRAME_TEG)
    for method, path in (("GET", TREASURY), ("GET", FEES), ("POST", "/api/v1/admin/treasury/transfer"), ("GET", RESERVE)):
        assert _call(FRAME_REG, method, path) == ("mtls", FRAME_REG)


def test_on_a_frame_teg_a_peer_frame_keeps_only_the_fx_pool(monkeypatch):
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", FRAME_TEG)
    assert _call(PEER_REG, "GET", RESERVE) == ("mtls", PEER_REG), "the designed use: the FX pool's reserve read"
    assert _call(PEER_REG, "POST", MOVE) == ("mtls", PEER_REG), "the designed use: the FX pool's move"
    assert _call(PEER_REG, "GET", RESERVE + "/") == ("mtls", PEER_REG), "a trailing slash is the same route"
    detail = _refused(PEER_REG, "GET", TREASURY)
    assert "peer identity" in detail and TREASURY in detail
    _refused(PEER_REG, "GET", FEES)
    _refused(PEER_REG, "POST", "/api/v1/admin/treasury/transfer")
    _refused(PEER_REG, "POST", RESERVE)          # the right path with the wrong method is another route


def test_on_a_frame_teg_its_own_operators_get_no_admin_route(monkeypatch):
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", FRAME_TEG)
    assert "local-other identity" in _refused(OWN_OP_REG, "GET", TREASURY)
    _refused(OWN_OP_REG, "GET", RESERVE)


def test_on_an_operator_teg_only_that_operator_is_its_own(monkeypatch):
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", OP_TEG)
    assert _call(OWN_OP_REG, "GET", TREASURY) == ("mtls", OWN_OP_REG)
    assert _call(OWN_OP_REG, "POST", "/api/v1/admin/treasury/transfer") == ("mtls", OWN_OP_REG)
    _refused(FRAME_REG, "GET", TREASURY)         # its parent frame: same domain, another owner
    _refused(OTHER_OP_REG, "GET", TREASURY)      # a sibling operator
    _refused(PEER_REG, "GET", TREASURY)          # a peer frame
    assert _call(PEER_REG, "GET", RESERVE) == ("mtls", PEER_REG)


def test_shadow_logs_what_enforce_would_refuse_and_allows_it(monkeypatch, caplog):
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", FRAME_TEG)
    monkeypatch.setenv("TEG_ADMIN_SCOPE_MODE", "shadow")
    with caplog.at_level(logging.WARNING, logger=ia.logger.name):
        assert _call(PEER_REG, "GET", TREASURY) == ("mtls", PEER_REG)
    assert any("WOULD-DENY relation=peer" in r.getMessage() and TREASURY in r.getMessage() for r in caplog.records)


def test_off_is_the_old_rule(monkeypatch):
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", FRAME_TEG)
    monkeypatch.setenv("TEG_ADMIN_SCOPE_MODE", "off")
    assert _call(PEER_REG, "GET", TREASURY) == ("mtls", PEER_REG)
    assert _call(OWN_OP_REG, "GET", FEES) == ("mtls", OWN_OP_REG)


def test_an_unknown_mode_is_enforce(monkeypatch):
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", FRAME_TEG)
    monkeypatch.setenv("TEG_ADMIN_SCOPE_MODE", "enforced-please")
    assert ia.admin_scope_mode() == "enforce"
    _refused(PEER_REG, "GET", TREASURY)


def test_the_route_lists_are_env_and_replace_their_default(monkeypatch):
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", FRAME_TEG)
    monkeypatch.setenv("TEG_PEER_ADMIN_ROUTES", f"GET {TREASURY}")
    assert _call(PEER_REG, "GET", TREASURY) == ("mtls", PEER_REG)
    _refused(PEER_REG, "GET", RESERVE)
    monkeypatch.setenv("TEG_LOCAL_OTHER_ADMIN_ROUTES", f"GET {FEES}, POST {MOVE}")
    assert _call(OWN_OP_REG, "GET", FEES) == ("mtls", OWN_OP_REG)
    assert _call(OWN_OP_REG, "POST", MOVE) == ("mtls", OWN_OP_REG)


def test_the_own_identity_is_read_from_the_teg_svid(monkeypatch, tmp_path):
    (tmp_path / "svid.0.pem").write_bytes(_cert(OP_TEG).public_bytes(serialization.Encoding.PEM))
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path))
    assert ia.own_spiffe_id() == OP_TEG
    assert ia.caller_relation(OWN_OP_REG, ia.own_spiffe_id()) == "own"
    assert ia.caller_relation(FRAME_REG, ia.own_spiffe_id()) == "local-other"
    assert ia.caller_relation(PEER_REG, ia.own_spiffe_id()) == "peer"
    _refused(FRAME_REG, "GET", TREASURY)


def test_an_unknown_own_identity_is_named_and_keeps_the_old_rule(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("SVID_CERT_DIR", str(tmp_path / "empty"))
    with caplog.at_level(logging.ERROR, logger=ia.logger.name):
        assert _call(PEER_REG, "GET", TREASURY) == ("mtls", PEER_REG)
    assert any("own identity is UNKNOWN" in r.getMessage() for r in caplog.records)
