"""D6-263 (2026-10-16): a card-signing key verifies nothing once its grace window has ended.

A rotation (`POST /admin/agents/{did}/signing-keys/rotate` or the agent's own rotation) stamps the old key's
`expires_at` = now + KEY_ROTATION_GRACE_DAYS. `_lookup_public_jwk` returned an expired key WITH the reason
`expired_kid`, and `verify_card_signature` still accepted a valid signature by it (counted as `grace_expired`),
so a rotation never shut out an old or leaked key. The grace window itself stays: a key whose `expires_at` is
still ahead verifies, a current key (`expires_at` NULL) verifies.

No route reaches the verifier: its one caller is the agent-card pull-sync worker, so the test calls it the way
the worker does, with a session double that answers the key lookup. The SDK's Ed25519 check is replaced by a
double that accepts a signature only for the signer's key (the control proves it refuses any other key), so what
is measured is the key-lifecycle decision this fix changes.

RED on 14520b9f: test_an_expired_key_verifies_nothing (the base answers (True, None)).
"""
import base64
import datetime as dt
import json
import sys
import types

import pytest

from agentvault_registry.services.a2a_v1 import jws_verifier

DID = "did:theprotocol:sec-card-key-expiry"
KID = f"{DID}#1"
SIGNER_JWK = {"kty": "OKP", "crv": "Ed25519", "x": "signer-key"}
OTHER_JWK = {"kty": "OKP", "crv": "Ed25519", "x": "some-other-key"}


def _card():
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "EdDSA", "kid": KID}).encode()).decode().rstrip("=")
    return {"name": "x", "signatures": [{"protected": hdr, "signature": "sig"}]}


class _Row:
    def __init__(self, jwk, expires_at):
        self.public_jwk = jwk
        self.expires_at = expires_at


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    """Answers the agent_signing_keys lookup with one row (the verifier's only read when the row exists)."""

    def __init__(self, row):
        self.row = row
        self.reads = 0

    async def execute(self, stmt):
        self.reads += 1
        return _Result(self.row)


@pytest.fixture(autouse=True)
def _verifier_on(monkeypatch):
    monkeypatch.setenv("JWS_VERIFY_ENABLED", "true")
    sdk = types.ModuleType("theprotocol.auth.jws_card")

    def verify_agent_card(card_data, public_jwk, *, expected_kid=None):
        return (True, None) if public_jwk == SIGNER_JWK else (False, "signature verification failed")

    sdk.verify_agent_card = verify_agent_card
    pkg = types.ModuleType("theprotocol")
    auth = types.ModuleType("theprotocol.auth")
    pkg.auth = auth
    auth.jws_card = sdk
    monkeypatch.setitem(sys.modules, "theprotocol", pkg)
    monkeypatch.setitem(sys.modules, "theprotocol.auth", auth)
    monkeypatch.setitem(sys.modules, "theprotocol.auth.jws_card", sdk)


def _now():
    return dt.datetime.now(dt.timezone.utc)


async def test_an_expired_key_verifies_nothing():
    db = _Db(_Row(SIGNER_JWK, _now() - dt.timedelta(hours=1)))
    valid, reason = await jws_verifier.verify_card_signature(_card(), db, source="test")
    assert (valid, reason) == (False, "expired_kid"), (valid, reason)


async def test_a_key_expired_long_ago_verifies_nothing():
    db = _Db(_Row(SIGNER_JWK, _now() - dt.timedelta(days=400)))
    assert await jws_verifier.verify_card_signature(_card(), db, source="test") == (False, "expired_kid")


async def test_a_key_inside_its_grace_window_still_verifies():
    db = _Db(_Row(SIGNER_JWK, _now() + dt.timedelta(days=6)))
    assert await jws_verifier.verify_card_signature(_card(), db, source="test") == (True, None)


async def test_the_current_key_verifies():
    db = _Db(_Row(SIGNER_JWK, None))
    assert await jws_verifier.verify_card_signature(_card(), db, source="test") == (True, None)


async def test_control_the_signature_double_refuses_any_other_key():
    db = _Db(_Row(OTHER_JWK, None))
    valid, reason = await jws_verifier.verify_card_signature(_card(), db, source="test")
    assert valid is False and reason == "signature verification failed", (valid, reason)
    assert db.reads == 1
