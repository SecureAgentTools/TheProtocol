"""§MCPTEST30 (V0641, D6-831/832, agentvault2-66 2026-10-25): the buy door's quote and the public showcase ask
authorize's own payee question before they offer a paid call.

Measured on sbx-alpha (agentvault2-5b's console runs, 2026-10-25): the door priced the unbonded WeatherAgent and
enabled Buy, and the press met authorize's 403 "holds no reputation bond". Pinned here:
- each gate's decision and sentence come from one `decide`, which counts and logs nothing; `gate` applies it with the
  same outcome at every mode (off, shadow, enforce) and standing (bonded, unbonded, unknown; enforced or not);
- payee_refusal asks the bond, then enforcement (authorize's order), returns the first sentence and counts nothing,
  and authorize refuses an unbonded payee with exactly that sentence;
- the quote of a paid card with a refused payee offers no Buy and says authorize's sentence (no rate is fetched), a
  free card is not asked, and an allowed payee is priced as before.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import a2a_payment as ap
from agentvault_registry.services import enforcement_propagation as ep
from agentvault_registry.services import reputation_bond as rb

_DID = "did:theprotocol:sandbox-a.theprotocol.cloud:d506dd2e-ea2c-4908-9833-3e368f30abb5"


def _run(c):
    return asyncio.run(c)


@pytest.fixture
def counted(monkeypatch):
    seen = []
    monkeypatch.setattr(rb, "_count", lambda site, mode, decision: seen.append(("rb", site, mode, decision)))
    monkeypatch.setattr(ep, "_count", lambda site, mode, decision: seen.append(("ep", site, mode, decision)))
    return seen


def _gate_outcome(coro):
    try:
        return _run(coro), None
    except HTTPException as e:
        return None, e


_BONDED = {"bonded": True, "unbonded": False, "unknown": None}


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize("standing", sorted(_BONDED))
def test_the_bond_gate_applies_decide(monkeypatch, counted, mode, standing):
    async def _bonded(db, did):
        return _BONDED[standing]

    async def _pol(db):
        return {"reputation_bond": {"amount_avt": 250}}

    monkeypatch.setattr(rb, "is_bonded_did", _bonded)
    monkeypatch.setattr(rb, "policy_json", _pol)
    out, why = _run(rb.decide(None, _DID, site="a2a_payee", mode=mode))
    assert counted == [], "decide counts nothing"
    g, raised = _gate_outcome(rb.gate(None, _DID, site="a2a_payee", mode=mode))
    if why:
        assert raised is not None and raised.status_code == 403 and raised.detail == why
    else:
        assert raised is None and g == out
    assert counted == ([] if mode == "off" else [("rb", "a2a_payee", mode, out["decision"])])
    assert bool(why) == (mode == "enforce" and standing != "bonded")


_ENFORCED = {"active": False, "suspended": True, "unknown": None}


@pytest.mark.parametrize("mode", ["off", "shadow", "enforce"])
@pytest.mark.parametrize("standing", sorted(_ENFORCED))
def test_the_enforcement_gate_applies_decide(monkeypatch, counted, mode, standing):
    async def _enf(db, did):
        return _ENFORCED[standing]

    async def _block(db, did):
        return {"status": "suspended", "registry": "Sandbox Alpha", "since": "2026-10-25"}

    monkeypatch.setattr(ep, "is_enforced_did", _enf)
    monkeypatch.setattr(ep, "enforcement_block", _block)
    out, why = _run(ep.decide(None, _DID, site="a2a_payee", mode=mode))
    assert counted == [], "decide counts nothing"
    g, raised = _gate_outcome(ep.gate(None, _DID, site="a2a_payee", mode=mode))
    if why:
        assert raised is not None and raised.status_code == 403 and raised.detail == why
    else:
        assert raised is None and g == out
    assert counted == ([] if mode == "off" else [("ep", "a2a_payee", mode, out["decision"])])
    assert bool(why) == (mode == "enforce" and standing == "suspended")


def test_payee_refusal_asks_the_bond_then_enforcement(monkeypatch):
    order = []

    def _decider(name, why):
        async def _d(db, did, *, site, mode=None, policy=None):
            order.append((name, site, did))
            return {"decision": "refuse" if why else "allow"}, why
        return _d

    monkeypatch.setattr(ap._rb, "decide", _decider("bond", "no bond here"))
    monkeypatch.setattr(ap._ep, "decide", _decider("enforcement", "suspended here"))
    assert _run(ap.payee_refusal(None, _DID)) == "no bond here"
    assert order == [("bond", "a2a_payee", _DID)], "the bond first; its refusal is the answer"
    order.clear()
    monkeypatch.setattr(ap._rb, "decide", _decider("bond", None))
    assert _run(ap.payee_refusal(None, _DID)) == "suspended here"
    assert [o[0] for o in order] == ["bond", "enforcement"]
    order.clear()
    monkeypatch.setattr(ap._ep, "decide", _decider("enforcement", None))
    assert _run(ap.payee_refusal(None, _DID)) is None


def test_authorize_refuses_with_the_sentence_the_preview_says(monkeypatch, counted):
    """The real decisions under enforce: authorize's 403 is the preview's sentence, word for word."""
    async def _no(db, did):
        return False

    async def _active(db, did):
        return False

    async def _pol(db):
        return {"reputation_bond": {"amount_avt": 250}}

    monkeypatch.setenv("REPUTATION_BOND_MODE", "enforce")
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "enforce")
    rb._np.reset_cache()
    monkeypatch.setattr(rb, "is_bonded_did", _no)
    monkeypatch.setattr(rb, "policy_json", _pol)
    monkeypatch.setattr(ep, "is_enforced_did", _active)
    try:
        preview = _run(ap.payee_refusal(None, _DID))
        assert preview and "holds no reputation bond" in preview
        assert counted == [], "the preview adds nothing to the gate's counters"
        req = ap.AuthorizeRequest(target_agent_did=_DID, amount="0.5")
        with pytest.raises(HTTPException) as ei:
            _run(ap.authorize_payment(req, None, None, None, None))
        assert ei.value.status_code == 403 and ei.value.detail == preview
    finally:
        rb._np.reset_cache()


def _card(paid=True):
    return {
        "name": "WeatherAgent", "endpoint_url": "https://sandbox-a.theprotocol.cloud/agents/weather-agent/a2a",
        "is_paid": paid,
        "pricing": ({"base_rate": "0.5", "currency": ap._FRAME_CCY, "source": "pricing-block", "model": "per_request"}
                    if paid else None),
    }


@pytest.fixture
def card_is(monkeypatch):
    def _set(card):
        async def _for(db, did):
            return card
        monkeypatch.setattr("agentvault_registry.routers.agent_cards.effective_pricing_for_did", _for)
    return _set


def test_a_refused_payee_is_quoted_with_authorizes_sentence_and_no_buy(monkeypatch, card_is):
    card_is(_card())
    asked = []

    async def _why(db, did):
        asked.append(did)
        return f"{did} holds no reputation bond. Providing services here (a2a_payee) requires a bond of 250."

    async def _no_fx(*a, **k):
        raise AssertionError("no rate is fetched for a payee authorize refuses")

    monkeypatch.setattr(ap, "payee_refusal", _why)
    monkeypatch.setattr("agentvault_registry.services.service_purchase.fetch_fx_pairs", _no_fx)
    q = _run(ap._quote_for(None, None, _DID))
    assert asked == [_DID]
    assert q.payment_required is True and q.price == "0.5"
    assert q.can_buy is False and q.reason.startswith(f"{_DID} holds no reputation bond")
    assert q.recommended_amount is None, "nothing to authorize is quoted"


def test_an_allowed_payee_is_priced_as_before(monkeypatch, card_is):
    card_is(_card())

    async def _none(db, did):
        return None

    monkeypatch.setattr(ap, "payee_refusal", _none, raising=False)   # a control: the old tree prices it the same
    q = _run(ap._quote_for(None, None, _DID))
    assert q.can_buy is True and q.reason == "" and q.recommended_amount


def test_a_free_card_is_not_asked(monkeypatch, card_is):
    card_is(_card(paid=False))

    async def _boom(db, did):
        raise AssertionError("a free call pays nobody: authorize is never asked")

    monkeypatch.setattr(ap, "payee_refusal", _boom, raising=False)   # a control: the old tree answers the same
    q = _run(ap._quote_for(None, None, _DID))
    assert q.payment_required is False and q.can_buy is True
