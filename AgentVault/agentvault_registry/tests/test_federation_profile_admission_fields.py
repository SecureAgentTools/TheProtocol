"""§DIRFEED — the public federation profile states ADMISSION, not just compliance.

`federation_status` is the compliance poller's verdict and reads "unknown" wherever that poller has never run
(every node that is not a central registry — both fresh frames answered "unknown" for every peer). An external
index needs the peer ROW's own facts instead: is this peer still federated with us, did we federate/license it
or merely hear of it, and what address can a client actually dial.
"""
import types

from agentvault_registry.routers.registry_health import _card_public_url, _peer_to_profile


def _peer(**kw):
    p = types.SimpleNamespace(
        id=7, name="amsterdam", base_url="https://amsterdam.op.theprotocol.cloud:8443",
        status="ACTIVE", peer_type="cloud_operator", discovery_auth_info={},
        cached_registry_card={"identity": {"public_url": "https://amsterdam.op.theprotocol.cloud"}},
    )
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_the_profile_carries_the_peer_rows_own_admission_facts():
    pr = _peer_to_profile(_peer(), None)
    assert pr.federation_status == "unknown", "no compliance row: the poller's verdict is honestly unknown"
    assert pr.peer_status == "ACTIVE" and pr.peer_type == "cloud_operator"


def test_the_dialable_address_comes_from_the_signed_card_not_the_federation_url():
    pr = _peer_to_profile(_peer(), None)
    assert pr.registry_url.endswith(":8443"), "base_url is the mTLS federation address"
    assert pr.public_url == "https://amsterdam.op.theprotocol.cloud", "a client dials the card's declared address"


def test_no_card_means_no_address_claimed():
    assert _card_public_url(_peer(cached_registry_card=None)) is None
    assert _card_public_url(_peer(cached_registry_card={})) is None
    assert _card_public_url(_peer(cached_registry_card={"identity": {"public_url": "   "}})) is None
    assert _peer_to_profile(_peer(cached_registry_card=None), None).public_url is None


def test_a_deactivated_peer_still_appears_and_says_so():
    """Deactivation, never deletion, is how a peer is stopped here — so the row must keep saying what it is."""
    pr = _peer_to_profile(_peer(status="INACTIVE"), None)
    assert pr.peer_status == "INACTIVE" and pr.registry_name == "amsterdam"
