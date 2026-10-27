"""§FEDLICENCE (2026-09-28, agentvault2-a4's review item 5): the public registry-card envelope carries THIS registry's
licence verdict, never the card's claim about itself.

The viewer (SovereignRegistryCard) renders peers' cards from GET /api/v1/public/registry-card?peer=<name>. A peer signs
its own card, so `card.federation.licence.state` is what the peer says about itself: a frame whose licence was revoked
can still publish "licensed". The envelope now carries the verdict this registry's sync worker reached (the peer row's
licence_state / licence_reason / licence_checked_at), and None when it has not reached one, never the card's value in
its place. On self, the card's block IS this registry's own derivation. The route is driven with a fake session.
"""
from __future__ import annotations

import datetime
import types

from agentvault_registry.routers import registry_card as rc

UTC = datetime.timezone.utc
CHECKED = datetime.datetime(2026, 9, 28, 2, 30, tzinfo=UTC)


class _Result:
    def __init__(self, value):
        self._v = value

    def scalar_one_or_none(self):
        return self._v


class _Db:
    def __init__(self, row):
        self.row = row

    async def execute(self, _stmt):
        return _Result(self.row)


def _card(state):
    lic = {"state": state, "hash": "h" * 64, "reason": "as the peer says"} if state else None
    fed = {"protocol_version": "1"} | ({"licence": lic} if lic else {})
    return {"identity": {"public_url": "https://sbx-beta.example"}, "federation": fed}


def _row(*, card_state, verdict, reason=None, checked=None):
    return types.SimpleNamespace(
        name="sbx-beta", base_url="https://nginx-federation:8443", card_etag="e1",
        card_signature_verified=True, card_last_pulled_at=None, cached_registry_card=_card(card_state),
        licence_state=verdict, licence_reason=reason, licence_checked_at=checked)


async def test_a_peer_envelope_carries_our_verdict_not_the_card_claim():
    row = _row(card_state="licensed", verdict="revoked", reason="genesis.example's list says revoked", checked=CHECKED)
    out = await rc.get_public_registry_card(peer="sbx-beta", db=_Db(row))
    assert out["is_self"] is False
    assert out["card"]["federation"]["licence"]["state"] == "licensed"     # the card still says what it says
    assert out["licence_state"] == "revoked"                                # the envelope says what WE concluded
    assert out["licence_reason"] == "genesis.example's list says revoked"
    assert out["licence_checked_at"] == CHECKED.isoformat()


async def test_control_no_verdict_here_is_none_never_the_card_claim():
    out = await rc.get_public_registry_card(peer="sbx-beta", db=_Db(_row(card_state="licensed", verdict=None)))
    assert out["licence_state"] is None and out["licence_reason"] is None and out["licence_checked_at"] is None


async def test_a_peer_on_an_older_image_with_no_block_and_no_verdict():
    out = await rc.get_public_registry_card(peer="sbx-beta", db=_Db(_row(card_state=None, verdict=None)))
    assert out["licence_state"] is None and "licence" not in out["card"]["federation"]


async def test_self_reports_the_cards_own_derived_block(monkeypatch):
    card = _card("licensed")
    card["federation"]["licence"]["checked_at"] = CHECKED.isoformat()

    async def fake_build(_db, sign=True):
        return card

    monkeypatch.setattr(rc, "build_registry_card", fake_build)
    out = await rc.get_public_registry_card(peer=None, db=_Db(None))
    assert out["is_self"] is True
    assert (out["licence_state"], out["licence_reason"], out["licence_checked_at"]) == (
        "licensed", "as the peer says", CHECKED.isoformat())


async def test_control_self_without_a_network_has_no_verdict(monkeypatch):
    async def fake_build(_db, sign=True):
        return _card(None)

    monkeypatch.setattr(rc, "build_registry_card", fake_build)
    out = await rc.get_public_registry_card(peer="  ", db=_Db(None))
    assert out["is_self"] is True and out["licence_state"] is None
