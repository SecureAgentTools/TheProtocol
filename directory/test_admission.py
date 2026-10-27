"""§DIRFEED — who gets INTO the index (his question: "how do we manage who can emit into graphql?").

Nobody emits. The Directory pulls, and it pulls exactly the set the federation already defines: the anchors its
operator named, plus every registry an anchor FEDERATED with or LICENSED — and, deliberately, not the names an
anchor merely heard of through someone else's fan-out. Run:
  docker run --rm -v $PWD:/t -w /t --entrypoint python theprotocol-directory:trial -m pytest test_admission.py -q
"""
from directory.ingest import admits


def test_a_federated_frame_and_a_licensed_operator_are_admitted():
    assert admits({"peer_type": "frame", "peer_status": "ACTIVE"})[0] is True
    assert admits({"peer_type": "cloud_operator", "peer_status": "ACTIVE"})[0] is True


def test_hearsay_is_not_an_admission():
    ok, why = admits({"peer_type": "discovered", "peer_status": "ACTIVE"})
    assert ok is False and "discovered" in why, "a name learned through a fan-out is a lead, not a licence"


def test_a_peer_that_was_stopped_stops_being_pulled():
    """A peer is stopped by DEACTIVATION, never deletion — the row stays in the table and must stop the pull."""
    for state in ("INACTIVE", "PENDING_APPROVAL", "REJECTED"):
        ok, why = admits({"peer_type": "frame", "peer_status": state})
        assert ok is False and state in why, state


def test_an_older_registry_that_states_neither_is_trusted_as_before():
    """The control: the fields are §DIRFEED-new. A registry too old to publish them must not vanish from the
    index — that would be an upgrade breaking a federation it never joined."""
    ok, why = admits({"registry_name": "x", "registry_url": "https://x/"})
    assert ok is True and "unstated" in why
