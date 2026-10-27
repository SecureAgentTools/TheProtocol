"""§MEMBERSHIP (V0560, his word 2026-10-03 "do the one more place left"): a registry's card key is named as its card.

registry_card_builder._build_spiffe_id() took settings.REGISTRY_NAME, a cloud operator's container label, so sbxbetaop's
card key was spiffe://<td>/registry/cloud-op-sbxbetaop while its card, SVID and parent's row say sbxbetaop. It now takes
federation_name(); a frame (no REGISTRY_FEDERATION_NAME) is unchanged. Recognising our own card coming back on the
fan-out accepts the card spiffe in either form (an older copy cached by a parent carries the label).
"""
from __future__ import annotations

import pytest

TD = "sandbox-b.theprotocol.cloud"


@pytest.fixture
def names(monkeypatch):
    from agentvault_registry.config import settings
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", TD)

    def set_(registry_name, federation_name=None):
        monkeypatch.setattr(settings, "REGISTRY_NAME", registry_name)
        if federation_name is None:
            monkeypatch.delenv("REGISTRY_FEDERATION_NAME", raising=False)
        else:
            monkeypatch.setenv("REGISTRY_FEDERATION_NAME", federation_name)
    return set_


def test_an_operators_card_key_is_named_as_its_card(names):
    from agentvault_registry.services.registry_card_builder import _build_spiffe_id, card_asset_slug
    names("cloud-op-sbxbetaop", "sbxbetaop")
    assert _build_spiffe_id() == f"spiffe://{TD}/registry/sbxbetaop"
    assert card_asset_slug() == f"{TD}_registry_sbxbetaop", "the asset slug moves with it (self-healing by design)"


def test_a_frames_card_key_is_unchanged(names):
    from agentvault_registry.services.registry_card_builder import _build_spiffe_id
    names("Sandbox Beta")
    assert _build_spiffe_id() == f"spiffe://{TD}/registry/Sandbox Beta"


def test_a_ballot_names_and_signs_as_the_card(names):
    from agentvault_registry.services import federation_ballot as fb
    names("cloud-op-sbxbetaop", "sbxbetaop")
    me = fb.own_identity()
    assert me["name"] == "sbxbetaop" and me["card_spiffe"] == f"spiffe://{TD}/registry/sbxbetaop"


def test_our_own_card_is_recognised_in_either_form():
    from agentvault_registry.core.operator_names import is_own_fanout_entry
    svid = f"spiffe://{TD}/operator/sbxbetaop/svid-writer"
    for spiffe in (f"spiffe://{TD}/registry/cloud-op-sbxbetaop", f"spiffe://{TD}/registry/sbxbetaop"):
        ok, why = is_own_fanout_entry("relayed-name", {"identity": {"spiffe_id": spiffe, "registry_name": "x"}},
                                      own_registry_name="cloud-op-sbxbetaop", own_spiffe=svid, trust_domain=TD)
        assert ok and "spiffe_id" in why, (spiffe, why)
    ok, _ = is_own_fanout_entry("relayed-name", {"identity": {"spiffe_id": f"spiffe://{TD}/registry/sbxalphaop",
                                                              "registry_name": "sbxalphaop"}},
                                own_registry_name="cloud-op-sbxbetaop", own_spiffe=svid, trust_domain=TD)
    assert not ok, "a sibling operator's card is not ours"


def test_a_renamed_operator_recognises_its_card_by_its_federation_name():
    """op-singapore's container carries op-losangeles: the label's slug is not the federation name."""
    from agentvault_registry.core.operator_names import is_own_fanout_entry
    card = {"identity": {"spiffe_id": f"spiffe://{TD}/registry/op-losangeles", "registry_name": "op-losangeles"}}
    kw = dict(own_registry_name="cloud-op-op-singapore", own_spiffe=f"spiffe://{TD}/operator/op-singapore/svid-writer",
              trust_domain=TD)
    assert not is_own_fanout_entry("op-losangeles", card, **kw)[0], "the control: without the federation name"
    ok, why = is_own_fanout_entry("op-losangeles", card, own_federation_name="op-losangeles", **kw)
    assert ok, why
    card_only = {"identity": {"spiffe_id": f"spiffe://{TD}/registry/op-losangeles", "registry_name": "Los Angeles"}}
    ok, why = is_own_fanout_entry("relayed-name", card_only, own_federation_name="op-losangeles", **kw)
    assert ok and "spiffe_id" in why, why


def test_both_self_checks_on_the_fan_out_know_the_federation_name():
    """The registry-card fan-out passes the federation name to the one rule; the carried stock card skips its own copy
    in the new spiffe form too (source pins: neither runs without a live parent)."""
    import inspect
    from agentvault_registry.background_tasks.federation_sync import FederationSyncWorker as W
    fan = inspect.getsource(W._pull_registry_cards_via_fanout)
    assert "own_federation_name=_fed_name_se()" in fan, "the fan-out asks without the federation name"
    carry = inspect.getsource(W._ingest_carried_stock_card)
    assert 'os.getenv("REGISTRY_FEDERATION_NAME")' in carry and '_own_spiffes.add(f"spiffe://{_td}/registry/{_fn}"' in carry
