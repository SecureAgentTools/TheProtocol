"""§FRAMELIC findings row 187 — our own cloud operators share our trust domain, and the
impersonation guard was refusing every one of their registry cards.

`check_card_namespace` refuses a card claiming THIS registry's issuer (`did_namespace_self`).
That is the impersonation defence and it must stay. But a cloud operator legitimately lives
under its PARENT FRAME's trust domain, so every operator card EU pulled was refused — measured
live: `[RegistryCardSync] peer=amsterdam validation failed; skip`, every two minutes since the
standup. Downstream that is what his eye actually saw: no logo (the logo IS the card's visual)
and no signature on all four operators.

The exemption is decided by OUR PEER ROW, never by the card. A card that could assert its way
past this guard is the entire attack it exists to stop, so the parameter defaults to False and
the caller must opt in from `peer_type` / `is_own_reachable_op`.
"""
import os

import pytest

from agentvault_registry.services import registry_card_validator as V


def _card(ns: str, td: str | None = None):
    return {"identity": {"did_namespace": ns, "trust_domain": td if td is not None else ns}}


@pytest.fixture(autouse=True)
def _own_domain(monkeypatch):
    monkeypatch.setenv("DID_ISSUER_NAMESPACE", "eu.theprotocol.cloud")
    monkeypatch.delenv("SPIRE_TRUST_DOMAIN", raising=False)


def test_an_own_operator_card_is_accepted_when_the_caller_vouches_for_it():
    """The operator's card declares our domain — correct, and previously fatal."""
    assert V.check_card_namespace(_card("eu.theprotocol.cloud"), allow_own_namespace=True) is None


def test_the_same_card_is_still_refused_by_default():
    """THE CONTROL, and the reason this is safe: nothing about the CARD changed. Only a caller
    that knows, from its own peer row, that this is our operator may opt in."""
    assert V.check_card_namespace(_card("eu.theprotocol.cloud")) == "did_namespace_self"
    assert V.check_card_namespace(_card("eu.theprotocol.cloud"),
                                  allow_own_namespace=False) == "did_namespace_self"


def test_a_foreign_peer_claiming_our_namespace_is_refused_even_with_the_exemption():
    """The exemption must not become a skeleton key. A card whose OWN trust domain disagrees with
    the namespace it claims is malformed no matter who vouches for it."""
    bad = _card("eu.theprotocol.cloud", td="asia.theprotocol.cloud")
    assert V.check_card_namespace(bad, allow_own_namespace=True) == "did_namespace_mismatch"


def test_a_peer_row_trust_domain_mismatch_still_refuses_under_the_exemption():
    assert V.check_card_namespace(_card("eu.theprotocol.cloud"),
                                  peer_trust_domain="asia.theprotocol.cloud",
                                  allow_own_namespace=True) == "did_namespace_mismatch"


def test_a_normal_foreign_card_is_unaffected():
    assert V.check_card_namespace(_card("asia.theprotocol.cloud")) is None


def test_validate_and_normalize_threads_the_flag(monkeypatch):
    """A synthetic card cannot pass `validate_payload` (it is not a real signed card), so stub
    that leg and assert only the thing this test is about: the flag reaching the namespace
    check. Testing it through a real card would be testing the signer, not the wiring."""
    monkeypatch.setattr(V, "validate_payload", lambda *a, **k: None)
    card = _card("eu.theprotocol.cloud")
    assert V.validate_and_normalize(card, 10, peer_svid="", allow_own_namespace=True) is not None
    assert V.validate_and_normalize(card, 10, peer_svid="") is None


def test_the_caller_decides_from_the_peer_row_not_the_card():
    """Structural: if the flag is ever derived from card content, the guard is gone."""
    import pathlib
    here = pathlib.Path(__file__).resolve()
    cands = [here.parents[1] / "src/agentvault_registry/background_tasks/federation_sync.py",
             pathlib.Path("/app/src/agentvault_registry/background_tasks/federation_sync.py")]
    src = next((c for c in cands if c.exists()), None)
    assert src is not None, f"federation_sync.py not found in {cands}"
    body = src.read_text()
    i = body.index("allow_own_namespace=_own_op")
    decl = body[max(0, i - 900):i]
    assert "peer.peer_type" in decl and "is_own_reachable_op(peer)" in decl, \
        "the exemption must be decided by our peer row"
    assert "card.get" not in decl.split("_own_op =")[-1], "never derive the exemption from the card"
