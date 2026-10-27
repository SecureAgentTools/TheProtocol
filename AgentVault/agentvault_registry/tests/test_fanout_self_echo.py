"""§ONESHOT (2026-09-12) — a node recognises its OWN card in the parent's fan-out, whatever name it travels under.

Measured on every operator the §ONESHOT proof stood up: the relayed card carried
`identity.spiffe_id = spiffe://<td>/registry/cloud-op-<slug>` and `identity.registry_name = <slug>`, the
fan-out named it `<slug>`, and the receiver's live SVID was its cert-writer's `…/operator/<slug>/svid-writer`,
so the old spiffe-id-only check (with an env fallback that never ran) inserted a `discovered` row named
after the operator itself, which then dialed itself every cycle.
"""
from agentvault_registry.core.operator_names import is_own_fanout_entry, topology_self_names

TD = "juice.theprotocol.cloud"
CARD = {"identity": {"spiffe_id": "spiffe://juice.theprotocol.cloud/registry/cloud-op-juiceop", "registry_name": "juiceop"}}


def test_the_operator_recognises_itself_under_its_slug_with_the_cert_writers_svid():
    own, why = is_own_fanout_entry("juiceop", CARD, own_registry_name="cloud-op-juiceop",
                                   own_spiffe="spiffe://juice.theprotocol.cloud/operator/juiceop/svid-writer", trust_domain=TD)
    assert own and "own registry name" in why


def test_the_canonical_spiffe_form_is_recognised_even_when_the_live_svid_differs():
    own, why = is_own_fanout_entry("Juice Op", CARD, own_registry_name="cloud-op-juiceop",
                                   own_spiffe="spiffe://juice.theprotocol.cloud/operator/juiceop/svid-writer", trust_domain=TD)
    assert own and "spiffe_id" in why


def test_the_cards_registry_name_alone_is_enough():
    own, why = is_own_fanout_entry("Juice Op", {"identity": {"registry_name": "juiceop"}}, own_registry_name="cloud-op-juiceop",
                                   own_spiffe="", trust_domain=TD)
    assert own and "registry_name" in why


def test_a_real_peer_is_never_mistaken_for_self():
    peer = {"identity": {"spiffe_id": "spiffe://brrr.theprotocol.cloud/registry/brrr", "registry_name": "brrr"}}
    own, _ = is_own_fanout_entry("brrr", peer, own_registry_name="cloud-op-juiceop",
                                 own_spiffe="spiffe://juice.theprotocol.cloud/operator/juiceop/svid-writer", trust_domain=TD)
    assert not own
    # the PARENT frame (same trust domain, its own name) is a legitimate peer of an operator
    parent = {"identity": {"spiffe_id": "spiffe://juice.theprotocol.cloud/registry/juice", "registry_name": "juice"}}
    own, _ = is_own_fanout_entry("Juice", parent, own_registry_name="cloud-op-juiceop", own_spiffe="", trust_domain=TD)
    assert not own


def test_a_mainframe_still_recognises_itself_by_name_and_by_live_svid():
    own, _ = is_own_fanout_entry("eu", {"identity": {"spiffe_id": "spiffe://eu.theprotocol.cloud/registry/eu"}},
                                 own_registry_name="eu", own_spiffe="spiffe://eu.theprotocol.cloud/registry/eu", trust_domain="eu.theprotocol.cloud")
    assert own


def test_the_topology_writeback_knows_an_operator_by_its_slug_and_its_public_host():
    """The boot-time BFS lists an operator under its slug and its public host; neither was in the self set."""
    env = {"REGISTRY_NAME": "cloud-op-juiceop", "PUBLIC_URL": "https://juiceop.op.theprotocol.cloud", "SPIRE_TRUST_DOMAIN": "juice.theprotocol.cloud"}
    names = topology_self_names(env, "cloud-op-juiceop")
    assert {"juiceop", "juiceop.op.theprotocol.cloud", "cloud-op-juiceop"} <= names
    assert "juice" not in names and "juice.theprotocol.cloud" not in names   # the parent is a peer, not self


def test_a_frame_keeps_its_old_self_names():
    env = {"REGISTRY_NAME": "eu", "REGISTRY_DISPLAY_NAME": "EU", "BASE_URL": "https://eu.theprotocol.cloud",
           "FEDERATION_BASE_URL": "http://eu-nginx-federation:8443", "BILATERAL_PEER_NAME": "EU"}
    names = topology_self_names(env, "EU")
    assert {"eu", "eu.theprotocol.cloud", "eu-nginx-federation", "local registry"} <= names
