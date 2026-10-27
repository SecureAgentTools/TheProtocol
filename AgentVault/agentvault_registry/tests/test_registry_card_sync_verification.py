"""§DOCSFIX CB-399 and CB-401: how the card sync verifies a peer's registry card.

CB-399: the receiver normalised the card first (registry_card_validator sets a sovereign_variant it cannot draw to
null, for display) and then resolved the signed paths on the normalised copy. visual.sovereign_variant is a signed leaf,
so every card naming a style this receiver does not know was recorded as unverified, although its signature was good.
The signature is now checked on the card as received; the normalised copy is what is stored and shown.

CB-401: no receiver recomputed compliance.digest (spec 7.4 step 7). The signature covers the digest leaf only, so a
compliance block altered after signing (its digest left alone) was stored as verified. The digest is now recomputed
from the block, and a mismatch records the card as unverified.

The worker's _sync_registry_card runs whole, with the peer's two documents served by a fake HTTP client, a real
Ed25519 signature, and the store's upsert captured.
"""
import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agentvault_registry.background_tasks import federation_sync as fs
from agentvault_registry.crud import crud_peer_registry
from agentvault_registry.routers import teg_integration
from agentvault_registry.services import regulatory_auth
from agentvault_registry.services.registry_card_signer import SIGNED_CANONICAL_PATHS, extract_paths

BASE = "https://peer.example:8443"
KID = "spiffe://peer.example/registry/peer#1"
KEY = Ed25519PrivateKey.generate()
JWK = {"kty": "OKP", "crv": "Ed25519", "kid": KID, "alg": "EdDSA", "use": "sig",
       "x": base64.urlsafe_b64encode(KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).rstrip(b"=").decode()}


def _card(variant=None, compliance=None):
    now = datetime.now(timezone.utc)
    card = {"registry_card_version": "0.6",
            "identity": {"spiffe_id": "spiffe://peer.example/registry/peer", "registry_name": "peer",
                         "trust_domain": "peer.example"},
            "description": "A peer registry.",
            "visual": {"sovereign_variant": variant},
            "signature": {"alg": "EdDSA", "kid": KID, "signed_canonical": list(SIGNED_CANONICAL_PATHS),
                          "signed_at": now.isoformat(), "expires_at": (now + timedelta(hours=1)).isoformat()}}
    if compliance is not None:
        card["compliance"] = dict(compliance, digest=regulatory_auth.compliance_digest(compliance))
    sig = card["signature"]
    payload = extract_paths(card, sig["signed_canonical"])
    payload["_signed_at"], payload["_expires_at"] = sig["signed_at"], sig["expires_at"]
    msg = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    sig["value"] = base64.urlsafe_b64encode(KEY.sign(msg)).rstrip(b"=").decode()
    return card


class _Resp:
    def __init__(self, body, headers=None):
        self.status_code = 200
        self._body = body
        self.content = json.dumps(body).encode()
        self.headers = headers or {}

    def json(self):
        return self._body


@pytest.fixture
def sync(monkeypatch):
    served, stored = {}, []

    class _Client:
        def __init__(self, **_cfg):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, url):
            if url.endswith("/.well-known/registry-jwks.json"):
                return _Resp({"keys": [JWK]})
            return _Resp(served["card"], {"etag": '"sha256:' + "b" * 64 + '"'})

    class _Session:
        async def __aenter__(self):
            return SimpleNamespace()

        async def __aexit__(self, *_a):
            return False

    async def _upsert(db, peer_id, card, **kw):
        stored.append((card, kw))

    monkeypatch.setattr(fs.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fs, "AsyncSessionLocal", _Session)
    monkeypatch.setattr(crud_peer_registry, "upsert_registry_card_from_peer", _upsert)
    monkeypatch.setattr(teg_integration, "_to_registry_dialable_url", lambda u: u)
    for k in ("FEDERATION_INGEST_FAIL_CLOSED", "STOCK_CARD_SYNC_ENABLED", "DID_ISSUER_NAMESPACE", "OPERATOR_DID"):
        monkeypatch.delenv(k, raising=False)
    worker = object.__new__(fs.FederationSyncWorker)
    peer = SimpleNamespace(id=7, name="peer", base_url=BASE, card_etag=None, trust_domain="peer.example",
                           peer_type="frame", cached_registry_card=None, card_signature_verified=False,
                           card_signature_kid=None)

    async def run(card):
        served["card"] = card
        stored.clear()
        await worker._sync_registry_card(peer, {}, {})
        assert len(stored) == 1, "the card was not stored"
        return stored[0]
    return run


async def test_a_good_signature_verifies_on_a_card_naming_a_style_this_receiver_cannot_draw(sync):
    card, kw = await sync(_card(variant="no-such-style-here"))
    assert kw["signature_verified"] is True
    assert card["visual"]["sovereign_variant"] is None      # stored as normalised, for display


async def test_a_plain_signed_card_verifies(sync):
    _card_, kw = await sync(_card())
    assert kw["signature_verified"] is True


async def test_a_card_changed_after_signing_does_not_verify(sync):
    tampered = _card()
    tampered["description"] = "Edited after signing."
    _card_, kw = await sync(tampered)
    assert kw["signature_verified"] is False


async def test_a_compliance_block_that_matches_its_digest_verifies(sync):
    _card_, kw = await sync(_card(compliance={"jurisdiction_profile": {"name": "p", "version": 1}}))
    assert kw["signature_verified"] is True


async def test_a_compliance_block_altered_after_signing_does_not_verify(sync):
    card = _card(compliance={"jurisdiction_profile": {"name": "p", "version": 1, "features_denied": ["fiat"]}})
    card["compliance"]["jurisdiction_profile"]["features_denied"] = []   # the signed digest leaf is left alone
    _card_, kw = await sync(card)
    assert kw["signature_verified"] is False
