"""§FEDLICENCE (2026-09-28, his word "cross-teg cut off also approved on revoke") — the TEG refuses a federated frame whose
network licence its own registry refuses.

Before this, a TEG accepted any certificate of a domain in TRUSTED_SPIFFE_DOMAINS: after a licence revoke the registry
lanes refused the frame while its cross-TEG legs still passed (DESIGN_2026-09-28_FEDERATION_LICENCE.md § 10 point 3).
The TEG copies its registry's verdicts (core/licence_gate) and the ONE certificate reader refuses a foreign domain the
registry refuses while enforcing.

The certificates are real (minted here) and go through the real reader with this frame's terminator marker.
RED control: on the tree before the change, test_a_refused_peer_is_not_an_identity_under_enforce fails (the reader
returns the peer's identity) and the licence-reason tests fail (no such reason exists).
"""
from __future__ import annotations

import datetime
import urllib.parse

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from starlette.requests import Request

from teg_core_service.core import internal_auth as ia
from teg_core_service.core import licence_gate as lg

SECRET = "test-only-marker-0123456789-abcdefghijkl"   # a made-up value of the right shape, never a real secret
OWN = "sandbox-a.theprotocol.cloud"
PEER = "sandbox-b.theprotocol.cloud"
PEER_REGISTRY = f"spiffe://{PEER}/service/sbx-beta-registry"
OWN_REGISTRY = f"spiffe://{OWN}/service/sbx-alpha-registry"


def _escaped_leaf(uri: str) -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "workload")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(uri)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return urllib.parse.quote(cert.public_bytes(serialization.Encoding.PEM).decode())


def _request(uri: str, path: str = "/api/v1/cross-teg/prepare") -> Request:
    headers = {"X-SSL-Client-Cert": _escaped_leaf(uri), "X-SSL-Client-Verify": "SUCCESS", ia.PROXY_MARKER_HEADER: SECRET}
    raw = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
    return Request({"type": "http", "method": "POST", "path": path, "raw_path": path.encode(),
                    "query_string": b"", "headers": raw})


def _payload(mode="enforce", refused=(PEER,), verdicts=None, local=OWN) -> dict:
    return {"mode": mode, "local_trust_domain": local,
            "verdicts": verdicts if verdicts is not None else {PEER: "suspended"}, "refused": list(refused)}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", f"{OWN},{PEER}")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", OWN)
    monkeypatch.setenv("TEG_PROXY_TRUST_SECRET", SECRET)
    monkeypatch.delenv("TEG_MTLS_REQUIRED", raising=False)
    monkeypatch.delenv("TEG_FEDERATION_LICENCE_MODE", raising=False)
    saved = dict(lg._STATE)
    lg._STATE.update(mode="off", local="", refused=frozenset(), verdicts={}, loaded_at=0.0, last_error="")
    lg._WARNED.clear()
    yield
    lg._STATE.clear()
    lg._STATE.update(saved)
    lg._WARNED.clear()


def test_a_refused_peer_is_not_an_identity_under_enforce():
    assert lg.apply_payload(_payload(), now=100.0)
    req = _request(PEER_REGISTRY)
    assert ia.extract_spiffe_from_request(req) is None
    assert ia.licence_refusal_of(req) == f"{PEER} (suspended)"


def test_a_licensed_peer_passes_and_the_own_domain_is_never_checked():
    lg.apply_payload(_payload(refused=(), verdicts={PEER: "licensed"}), now=100.0)
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) == PEER_REGISTRY
    # even a (wrong) registry answer naming our own domain never refuses our own frame
    lg.apply_payload(_payload(refused=(OWN, PEER)), now=101.0)
    assert ia.extract_spiffe_from_request(_request(OWN_REGISTRY)) == OWN_REGISTRY


def test_observe_names_the_crossing_and_refuses_nothing(caplog):
    lg.apply_payload(_payload(mode="observe"), now=100.0)
    with caplog.at_level("WARNING"):
        req = _request(PEER_REGISTRY)
        assert ia.extract_spiffe_from_request(req) == PEER_REGISTRY
    assert ia.licence_refusal_of(req) is None
    assert "WOULD_REFUSE" in caplog.text and PEER in caplog.text


def test_before_the_first_copy_nobody_is_refused():
    assert lg.effective_mode() == "off"
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) == PEER_REGISTRY


def test_unverified_and_unevaluated_peers_pass():
    lg.apply_payload(_payload(refused=(), verdicts={PEER: "unverified"}), now=100.0)
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) == PEER_REGISTRY
    lg.apply_payload(_payload(refused=(), verdicts={}), now=101.0)
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) == PEER_REGISTRY


def test_the_teg_override_wins_over_the_registry_mode(monkeypatch):
    lg.apply_payload(_payload(mode="enforce"), now=100.0)
    monkeypatch.setenv("TEG_FEDERATION_LICENCE_MODE", "off")
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) == PEER_REGISTRY
    lg.apply_payload(_payload(mode="observe"), now=101.0)
    monkeypatch.setenv("TEG_FEDERATION_LICENCE_MODE", "enforce")
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) is None
    monkeypatch.setenv("TEG_FEDERATION_LICENCE_MODE", "follow")
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) == PEER_REGISTRY


def test_a_bad_answer_keeps_the_last_copy():
    lg.apply_payload(_payload(), now=100.0)
    for bad in (None, "garbage", {"mode": "enforce"}, {"verdicts": {}, "refused": "not-a-list"}):
        assert lg.apply_payload(bad, now=200.0) is False
    assert lg._STATE["refused"] == frozenset({PEER}) and lg._STATE["loaded_at"] == 100.0
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) is None


@pytest.mark.asyncio
async def test_a_failed_read_keeps_the_last_copy():
    lg.apply_payload(_payload(), now=100.0)

    async def boom():
        raise OSError("registry unreachable")

    assert await lg.refresh_once(fetch=boom) is False
    assert "registry unreachable" in lg._STATE["last_error"]
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) is None

    async def good():
        return _payload(refused=(), verdicts={PEER: "licensed"})

    assert await lg.refresh_once(fetch=good, now=lambda: 300.0) is True
    assert ia.extract_spiffe_from_request(_request(PEER_REGISTRY)) == PEER_REGISTRY


def test_the_internal_caller_refusal_names_the_licence(monkeypatch):
    monkeypatch.setenv("TEG_MTLS_REQUIRED", "true")
    lg.apply_payload(_payload(verdicts={PEER: "revoked"}), now=100.0)
    with pytest.raises(HTTPException) as e:
        ia.resolve_internal_caller(_request(PEER_REGISTRY, path="/api/v1/admin/fx/reserve"))
    assert e.value.status_code == 403 and e.value.detail == f"federation licence refused: {PEER} (revoked)"
    # the control: an unrelated refusal still reads as before
    lg.apply_payload(_payload(refused=(), verdicts={PEER: "licensed"}), now=101.0)
    with pytest.raises(HTTPException) as e2:
        ia.resolve_internal_caller(_request("spiffe://elsewhere.example/service/registry"))
    assert e2.value.detail == "mTLS identity required"


def test_the_cross_teg_refusal_names_the_licence(monkeypatch):
    from teg_core_service.api import cross_teg_router as r
    monkeypatch.setenv("TEG_MTLS_REQUIRED", "true")
    lg.apply_payload(_payload(), now=100.0)
    with pytest.raises(HTTPException) as e:
        r._validate_cross_teg_auth(_request(PEER_REGISTRY))
    assert e.value.status_code == 403
    assert e.value.detail == f"federation licence refused (cross-TEG): {PEER} (suspended)"
    lg.apply_payload(_payload(refused=(), verdicts={PEER: "licensed"}), now=101.0)
    assert r._validate_cross_teg_auth(_request(PEER_REGISTRY)) == PEER_REGISTRY


def test_the_check_never_raises():
    lg.apply_payload(_payload(), now=100.0)
    for odd in (None, "", "not-a-spiffe-id", "spiffe://", 42):
        assert lg.refusal(odd) is None


def test_the_status_block_names_domains_only():
    lg.apply_payload(_payload(), now=100.0)
    s = lg.status()
    assert s["mode"] == "enforce" and s["refused"] == [PEER] and s["peers"] == 1
    assert set(s) == {"mode", "registry_mode", "override", "refused", "peers", "loaded_seconds_ago", "last_error"}
