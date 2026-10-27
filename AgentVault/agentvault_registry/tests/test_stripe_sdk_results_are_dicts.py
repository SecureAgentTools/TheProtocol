"""§DEPS stripe15 (2026-09-29): every Stripe SDK result the fiat code reads is a PLAIN dict, on stripe-python 12 and 15.

stripe-python 15.0 (2026-03-25) made StripeObject stop inheriting from dict: no .get()/.items(), and dict(obj) raises
TypeError (its __iter__ exists and raises, so a `hasattr(obj, "__iter__")` guard does not help). The fiat code reads SDK
results dict-style behind four entry points: the webhook event (Webhook.construct_event -> the normaliser, 21 .get()
reads incl. nested data.object and refunds), the CREATED Checkout Session (the proxy checkout reads
session.get("payment_intent"), the provider dict(session)), the RETRIEVED Checkout Session (the admin drill-down's 11
.get() reads, the provider's dict(result), the reconciler) and the SDK refund (the admin refund's refund.get("id")).
services/stripe_checkout.py and the two Refund.create sites now call .to_dict() once.

These tests build REAL SDK objects: a webhook payload signed with a test HMAC secret through the SDK's own
Webhook.construct_event, and Session/Refund objects through construct_from. No Stripe key, no network, no API call:
the SDK calls that would reach Stripe are replaced by functions returning those objects. The CONTROLS show the same reads
on the raw SDK object raise on 15 (on 12 they worked, which is why nothing failed before).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest
import stripe

from agentvault_registry.services import stripe_checkout
from agentvault_registry.services.fiat_providers.stripe_provider import StripeProvider

STRIPE_MAJOR = int(stripe.VERSION.split(".")[0])
TEST_SECRET = "heldlibs-test-webhook-secret"   # an HMAC key for a locally signed payload; not a Stripe credential
NO_KEY = "heldlibs-no-stripe-key"              # never used for a request: every SDK call that would reach Stripe is replaced


def _signed(event: dict) -> tuple[bytes, str]:
    body = json.dumps(event)
    ts = int(time.time())
    sig = hmac.new(TEST_SECRET.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return body.encode(), f"t={ts},v1={sig}"


def _event(event_type: str, obj: dict) -> dict:
    return {"id": f"evt_{event_type.replace('.', '_')}", "object": "event", "type": event_type,
            "created": 1790000000, "livemode": False, "pending_webhooks": 1, "data": {"object": obj}}


SESSION = {"id": "cs_test_heldlibs", "object": "checkout.session", "payment_intent": "pi_heldlibs",
           "metadata": {"fiat_purchase_id": "fp_heldlibs", "tier_label": "t2"}, "customer_email": None,
           "customer_details": {"email": "buyer@example.test", "name": None}, "url": "https://checkout.stripe.test/c/pay/cs_test_heldlibs",
           "status": "complete", "payment_status": "paid", "amount_total": 2000, "currency": "eur",
           "expires_at": 1790086400, "created": 1790000000, "mode": "payment"}
CHARGE = {"id": "ch_heldlibs", "object": "charge", "payment_intent": "pi_heldlibs", "amount_refunded": 1234,
          "metadata": {"fiat_purchase_id": "fp_heldlibs"},
          "refunds": {"object": "list", "url": "/v1/charges/ch_heldlibs/refunds", "has_more": False,
                      "data": [{"id": "re_heldlibs", "object": "refund", "reason": "requested_by_customer", "amount": 1234}]}}
DISPUTE = {"id": "dp_heldlibs", "object": "dispute", "payment_intent": "pi_heldlibs", "reason": "fraudulent",
           "metadata": {"fiat_purchase_id": "fp_heldlibs"}}
REFUND = {"id": "re_heldlibs", "object": "refund", "status": "succeeded", "amount": 1234, "currency": "eur",
          "payment_intent": "pi_heldlibs", "reason": "requested_by_customer", "metadata": {"fiat_purchase_id": "fp_heldlibs"}}

CASES = [
    ("checkout.session.completed", SESSION,
     dict(kind="checkout_completed", provider_session_id="cs_test_heldlibs", provider_payment_id="pi_heldlibs",
          customer_email="buyer@example.test")),
    ("checkout.session.expired", SESSION,
     dict(kind="checkout_expired", provider_session_id="cs_test_heldlibs", provider_payment_id="pi_heldlibs")),
    ("charge.refunded", CHARGE,
     dict(kind="charge_refunded", provider_payment_id="pi_heldlibs", refund_reason="requested_by_customer",
          refund_amount_eur=Decimal("12.34"))),
    ("charge.dispute.created", DISPUTE,
     dict(kind="charge_disputed", provider_payment_id="pi_heldlibs")),
]


@pytest.fixture(autouse=True)
def _stripe_globals(monkeypatch):
    # the fiat code assigns stripe.api_key; keep the module's globals as they were after each test
    monkeypatch.setattr(stripe, "api_key", None)
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)


@pytest.mark.parametrize("event_type, obj, want", CASES, ids=[c[0] for c in CASES])
def test_the_webhook_event_is_a_plain_dict_and_normalises(event_type, obj, want):
    body, header = _signed(_event(event_type, obj))
    event = stripe_checkout.verify_webhook_signature(payload=body, signature_header=header, webhook_secret=TEST_SECRET)
    assert type(event) is dict
    assert event.get("id") == f"evt_{event_type.replace('.', '_')}" and event.get("type") == event_type  # the route's reads
    pe = StripeProvider()._normalize_event(event)
    for k, v in want.items():
        assert getattr(pe, k) == v, (k, getattr(pe, k), v)
    assert pe.metadata.get("fiat_purchase_id") == "fp_heldlibs"


@pytest.mark.asyncio
@pytest.mark.parametrize("event_type, obj, want", CASES[:1] + CASES[2:3], ids=["checkout.session.completed", "charge.refunded"])
async def test_the_provider_webhook_door_verifies_and_normalises(monkeypatch, event_type, obj, want):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", TEST_SECRET)
    body, header = _signed(_event(event_type, obj))
    pe = await StripeProvider().verify_webhook(body, {"Stripe-Signature": header})
    assert pe.kind == want["kind"] and pe.provider_payment_id == "pi_heldlibs"
    with pytest.raises(ValueError):  # a wrong signature is still refused
        await StripeProvider().verify_webhook(body, {"Stripe-Signature": header.replace("v1=", "v1=0")})


def test_control_the_raw_sdk_event_breaks_the_normaliser_on_15():
    body, header = _signed(_event("charge.refunded", CHARGE))
    raw = stripe.Webhook.construct_event(payload=body, sig_header=header, secret=TEST_SECRET)  # what 12.5.1 code handed on
    if STRIPE_MAJOR >= 15:
        assert not isinstance(raw, dict)
        with pytest.raises(AttributeError):
            StripeProvider()._normalize_event(raw)
    else:
        assert isinstance(raw, dict)  # the reason the dict-style reads never failed on 12
        assert StripeProvider()._normalize_event(raw).refund_reason == "requested_by_customer"


def _fake_create(captured):
    def create(**kwargs):
        captured.update(kwargs)
        return stripe.checkout.Session.construct_from(dict(SESSION, status="open", payment_status="unpaid"), NO_KEY)
    return create


@pytest.mark.asyncio
async def test_the_created_session_is_a_plain_dict_for_both_callers(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(_fake_create(captured)))
    s = stripe_checkout.create_checkout_session(
        api_key=NO_KEY, eur_amount=Decimal("20"), avt_amount=Decimal("50000"),
        success_url="https://console.example.test/ok?session_id={CHECKOUT_SESSION_ID}", cancel_url="https://console.example.test/no",
        customer_email="buyer@example.test", metadata={"fiat_purchase_id": "fp_heldlibs", "tier_display_name": "T2"})
    assert type(s) is dict
    # the proxy checkout's reads (routers/fiat_onramp.py create_proxy_checkout)
    assert s["id"] == "cs_test_heldlibs" and s.get("payment_intent") == "pi_heldlibs" and s["url"].startswith("https://")
    # what we send under the SDK's pinned API version: no ui_mode (dahlia renamed its values) and no
    # payment_method_types (the dashboard decides), a hosted page answered with a url
    assert captured["mode"] == "payment" and "ui_mode" not in captured and "payment_method_types" not in captured
    assert set(captured) == {"mode", "line_items", "success_url", "cancel_url", "locale", "metadata",
                             "payment_intent_data", "billing_address_collection", "customer_email"}
    # the provider's reads
    monkeypatch.setenv("STRIPE_API_KEY", NO_KEY)
    ps = await StripeProvider().create_checkout(
        eur_amount=Decimal("20"), avt_amount=Decimal("50000"), success_url="https://console.example.test/ok",
        cancel_url="https://console.example.test/no", customer_email=None, metadata={"fiat_purchase_id": "fp_heldlibs"},
        tier_label="t2", tier_display_name="T2")
    assert (ps.provider_session_id, ps.redirect_url, ps.provider_payment_id, ps.expires_at) == (
        "cs_test_heldlibs", SESSION["url"], "pi_heldlibs", 1790086400)
    assert type(ps.raw) is dict and ps.raw["id"] == "cs_test_heldlibs"


def test_control_the_raw_created_session_breaks_its_readers_on_15():
    raw = stripe.checkout.Session.construct_from(SESSION, NO_KEY)
    assert raw.id == "cs_test_heldlibs" and raw["url"] == SESSION["url"]  # attribute and bracket access survive 15
    if STRIPE_MAJOR >= 15:
        with pytest.raises(AttributeError):
            raw.get("payment_intent")           # routers/fiat_onramp.py create_proxy_checkout, before the fix
        assert hasattr(raw, "__iter__")
        with pytest.raises(TypeError):
            dict(raw)                           # stripe_provider.create_checkout's raw=, before the fix
    else:
        assert raw.get("payment_intent") == "pi_heldlibs" and dict(raw)["id"] == "cs_test_heldlibs"


DRILLDOWN_KEYS = ("id", "status", "payment_status", "amount_total", "currency", "customer_email", "customer_details",
                  "payment_intent", "url", "expires_at", "created")   # routers/fiat_onramp.py admin purchase detail


@pytest.mark.asyncio
async def test_the_retrieved_session_is_a_plain_dict_for_every_reader(monkeypatch):
    seen = []
    monkeypatch.setattr(stripe.checkout.Session, "retrieve",
                        staticmethod(lambda sid, **kw: seen.append(sid) or stripe.checkout.Session.construct_from(SESSION, NO_KEY)))
    s = stripe_checkout.retrieve_session(api_key=NO_KEY, session_id="cs_test_heldlibs")
    assert type(s) is dict and seen == ["cs_test_heldlibs"]
    detail = {k: s.get(k) for k in DRILLDOWN_KEYS}
    assert detail["payment_status"] == "paid" and detail["customer_details"] == {"email": "buyer@example.test", "name": None}
    monkeypatch.setenv("STRIPE_API_KEY", NO_KEY)
    payment = await StripeProvider().retrieve_session("cs_test_heldlibs")
    assert type(payment) is dict and payment["id"] == "cs_test_heldlibs"
    # the reconciler hands the retrieved session to the normaliser: it must not raise (a Session is no event: unknown)
    assert StripeProvider()._normalize_event(payment).kind == "unknown"


def test_control_the_raw_retrieved_session_breaks_the_drilldown_on_15():
    raw = stripe.checkout.Session.construct_from(SESSION, NO_KEY)
    if STRIPE_MAJOR >= 15:
        with pytest.raises(AttributeError):
            {k: raw.get(k) for k in DRILLDOWN_KEYS}
    else:
        assert {k: raw.get(k) for k in DRILLDOWN_KEYS}["id"] == "cs_test_heldlibs"


def _fake_refund(captured):
    def create(**kwargs):
        captured.update(kwargs)
        return stripe.Refund.construct_from(REFUND, NO_KEY)
    return create


@pytest.mark.asyncio
async def test_the_provider_refund_reads_a_plain_dict(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(stripe.Refund, "create", staticmethod(_fake_refund(captured)))
    monkeypatch.setenv("STRIPE_API_KEY", NO_KEY)
    rid = await StripeProvider().refund("pi_heldlibs", amount_eur=Decimal("12.34"), reason="requested_by_customer",
                                        metadata={"fiat_purchase_id": "fp_heldlibs", "skip": None})
    assert rid == "re_heldlibs"
    assert captured == {"payment_intent": "pi_heldlibs", "reason": "requested_by_customer", "amount": 1234,
                        "metadata": {"fiat_purchase_id": "fp_heldlibs"}}


@pytest.mark.asyncio
async def test_the_admin_refund_reads_a_plain_dict(monkeypatch):
    from agentvault_registry.routers import fiat_onramp

    captured: dict = {}
    emitted: list = []
    monkeypatch.setattr(stripe.Refund, "create", staticmethod(_fake_refund(captured)))
    monkeypatch.setenv("STRIPE_API_KEY", NO_KEY)

    async def _emit(**kw):
        emitted.append(kw)

    monkeypatch.setattr(fiat_onramp, "_emit", _emit)
    p = SimpleNamespace(id="fp_heldlibs", status=fiat_onramp.FiatPurchaseStatus.COMPLETED.value,
                        stripe_payment_intent_id="pi_heldlibs", amount_eur=Decimal("20"), amount_avt=Decimal("50000"),
                        agent_did="did:theprotocol:heldlibs", refunded_at=None, failure_reason=None)

    class _DB:
        async def get(self, model, pid):
            return p if pid == p.id else None

        def add(self, obj):
            pass

        async def commit(self):
            pass

    res = await fiat_onramp.admin_refund_purchase(purchase_id="fp_heldlibs", db=_DB(), admin=SimpleNamespace(id=7))
    assert res.status == "refunded" and "re_heldlibs" in res.detail
    assert p.status == fiat_onramp.FiatPurchaseStatus.REFUNDED.value and "stripe_refund=re_heldlibs" in p.failure_reason
    assert captured["payment_intent"] == "pi_heldlibs" and captured["reason"] == "requested_by_customer"
    assert emitted and emitted[0]["data"]["stripe_refund_id"] == "re_heldlibs"


def test_control_the_raw_refund_breaks_the_admin_refund_on_15():
    raw = stripe.Refund.construct_from(REFUND, NO_KEY)
    assert raw.id == "re_heldlibs"  # the provider's old getattr(refund, "id", "") survived 15; the admin's .get did not
    if STRIPE_MAJOR >= 15:
        with pytest.raises(AttributeError):
            raw.get("id")
    else:
        assert raw.get("id") == "re_heldlibs"


def test_the_sdk_names_the_docstrings_use_exist():
    # the fiat code names stripe.StripeError and stripe.SignatureVerificationError (stripe.error.* went away in 13)
    assert issubclass(stripe.SignatureVerificationError, stripe.StripeError)
