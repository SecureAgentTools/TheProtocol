"""§FEDSYNCTRUTH — the registry-card fan-out may create a peer row only under a name the peer signs its own
card with (pure rule, no network). This is the structural end of the op-singapore ghost class."""
from agentvault_registry.core.operator_names import fanout_peer_name_allowed


def _card(registry_name=None):
    ident = {"spiffe_id": "spiffe://frame-b.theprotocol.cloud/registry/cloud-op-op-singapore"}
    if registry_name:
        ident["registry_name"] = registry_name
    return {"identity": ident}


def test_the_measured_ghost_is_refused_on_both_grounds():
    ok, why = fanout_peer_name_allowed("op-singapore", _card("op-losangeles"))
    assert not ok and why == "infra_label"                     # a container label is never a peer name


def test_a_name_that_disagrees_with_the_card_is_refused():
    ok, why = fanout_peer_name_allowed("op-berlin", _card("op-paris"))
    assert not ok and why == "card_name_mismatch"


def test_identities_pass_with_a_matching_or_absent_card_name():
    assert fanout_peer_name_allowed("op-losangeles", _card("op-losangeles")) == (True, "ok")
    assert fanout_peer_name_allowed("OP-LOSANGELES", _card("op-losangeles")) == (True, "ok")
    assert fanout_peer_name_allowed("op-berlin", _card()) == (True, "ok")           # a card without a name cannot refute
    assert fanout_peer_name_allowed("qatest16", None) == (True, "ok")
    assert fanout_peer_name_allowed("Frame-C", {"identity": {"registry_name": "Frame-C"}}) == (True, "ok")


def test_an_empty_name_is_refused():
    assert fanout_peer_name_allowed("", _card("x")) == (False, "empty_name")
    assert fanout_peer_name_allowed(None, None) == (False, "empty_name")
