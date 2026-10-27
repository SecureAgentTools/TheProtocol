"""The card-signature verifier fails closed when it cannot verify (2026-10-16, wave 2).

services/a2a_v1/jws_verifier.verify_card_signature imported `theprotocol.auth.jws_card` (the SDK's verifier) and, when
the import failed, answered (True, None): "valid". The V0618 registry image does not carry that module, so with
JWS_VERIFY_ENABLED=true every signed card passed, a forged signature included, and with JWS_REQUIRE_SIGNATURE=true even
an unsigned card passed (the import was asked before the unsigned rule). Now a signed card reads as not verified
(False, "verifier_unavailable") while the verifier is missing, the missing verifier is logged once (the metric counts
each card), and the unsigned-card policy, which needs no verifier, is applied as written. JWS_VERIFY_ENABLED is off by
default and is not set on EU, ASIA or in the frame template, so nothing changes there until it is switched on.

No route reaches the verifier: its one caller is the agent-card pull-sync worker, so the test calls it the way the
worker does (as tests/test_sec_card_key_expiry.py does); the SDK module is made unimportable (it is absent from the
image as well), and the key lookup is a double that is never reached.
RED on 7140a4a6: test_a_signed_card_is_not_verified_without_the_verifier, test_the_missing_verifier_is_logged_once,
test_an_unsigned_card_is_refused_when_signatures_are_required.
"""
import base64
import json
import logging
import sys

import pytest

from agentvault_registry.services.a2a_v1 import jws_verifier

KID = "did:theprotocol:sec2-card#1"


def _signed_card():
    hdr = base64.urlsafe_b64encode(json.dumps({"alg": "EdDSA", "kid": KID}).encode()).decode().rstrip("=")
    return {"name": "x", "signatures": [{"protected": hdr, "signature": "forged"}]}


class _Db:
    async def execute(self, stmt):
        raise AssertionError("no key lookup is needed to know the verifier is missing")


@pytest.fixture(autouse=True)
def no_verifier(monkeypatch):
    monkeypatch.setitem(sys.modules, "theprotocol.auth.jws_card", None)   # import raises ImportError
    monkeypatch.setenv("JWS_VERIFY_ENABLED", "true")
    monkeypatch.delenv("JWS_REQUIRE_SIGNATURE", raising=False)
    monkeypatch.setattr(jws_verifier, "_VERIFIER_MISSING_LOGGED", False, raising=False)


@pytest.mark.asyncio
async def test_a_signed_card_is_not_verified_without_the_verifier():
    valid, reason = await jws_verifier.verify_card_signature(_signed_card(), _Db(), source="pullsync")
    assert (valid, reason) == (False, "verifier_unavailable")


@pytest.mark.asyncio
async def test_the_missing_verifier_is_logged_once(caplog):
    with caplog.at_level(logging.WARNING, logger=jws_verifier.logger.name):
        for _ in range(3):
            await jws_verifier.verify_card_signature(_signed_card(), _Db(), source="pullsync")
    said = [r for r in caplog.records if r.levelno >= logging.WARNING and "jws_card" in r.getMessage()]
    assert len(said) == 1, [r.getMessage() for r in said]


@pytest.mark.asyncio
async def test_an_unsigned_card_is_refused_when_signatures_are_required(monkeypatch):
    monkeypatch.setenv("JWS_REQUIRE_SIGNATURE", "true")
    assert await jws_verifier.verify_card_signature({"name": "x"}, _Db()) == (False, "missing_sig")


@pytest.mark.asyncio
async def test_control_an_unsigned_card_passes_where_signatures_are_optional():
    assert await jws_verifier.verify_card_signature({"name": "x"}, _Db()) == (True, None)


@pytest.mark.asyncio
async def test_control_the_switch_off_verifies_nothing(monkeypatch):
    monkeypatch.setenv("JWS_VERIFY_ENABLED", "false")
    assert await jws_verifier.verify_card_signature(_signed_card(), _Db()) == (True, None)


def test_the_switch_is_off_by_default(monkeypatch):
    monkeypatch.delenv("JWS_VERIFY_ENABLED", raising=False)
    assert jws_verifier.jws_verify_enabled() is False
