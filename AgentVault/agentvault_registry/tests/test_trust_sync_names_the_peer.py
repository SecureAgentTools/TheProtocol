"""§TRUSTROW (2026-09-16, his word "1. approved ... dont change the overall mechanism"): the trust sync names the peer.

The sync keys a peer by the LICENCE id this frame issued, while the event store's vote weight resolves a voter by its
SPIFFE id (services/federation_governance.py, via routers/federation_governance.py:117, which takes
`auth_context.get("spiffe_id") or operator_id or "origin"`). A SPIFFE URI never equals a UUID, so the row the vote reads
is the spiffe-keyed one the WS3 admin rail wrote, and the measured discount the sync writes lands on a different row.
Measured 2026-09-16 on the live stores: EU held TWO rows for ASIA (73f0193f licence-keyed carrying 0.974, a9d3f8d0
spiffe-keyed carrying 1), and ASIA held one spiffe-keyed row for eu at 1 while its own licence for eu is fcfdc424, which
is why its sync answered 400 every cycle (the store's insert branch requires a hash the sync never sends).

The mechanism does not change: the sync still carries the licence id. It now also NAMES the peer, so the store can put
the value on the row that is read.

  1. a peer with a trust domain contributes spiffe://<trust domain> in its payload;
  2. a peer without one contributes a payload with no spiffe_id key at all, never an empty or invented value;
  3. everything the previous rule decided is unchanged: the licence id, the name matching, and every skip.

RED before the change: no payload carries spiffe_id.
Run: python -m pytest tests/test_trust_sync_names_the_peer.py -q

SEC-20 (2026-10-17): the value is derived from the peer's record, never read from its column, so these rows carry a
record (total_interactions, disputes_lost_with) and the expected value is its Beta(1,1) posterior mean; a peer without a
record sends the prior 0.5 instead of being skipped.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agentvault_registry.background_tasks.federation_sync import trust_sync_payloads


def peer(name, record=(9, 0), trust_domain=None):
    total, lost = record
    return SimpleNamespace(name=name, total_interactions=total, disputes_lost_with=lost,
                           last_interaction_at=datetime.now(timezone.utc) - timedelta(hours=2) if total else None,
                           registered_at=None, bayesian_discount=1.0, trust_domain=trust_domain)


LICENCES = [
    ("11111111-1111-1111-1111-111111111111", "asia", "active"),
    ("22222222-2222-2222-2222-222222222222", "amsterdam", "active"),
    ("33333333-3333-3333-3333-333333333333", "gone", "revoked"),
]


def test_red_a_peer_with_a_trust_domain_is_named_by_its_spiffe_id():
    payloads, skipped = trust_sync_payloads([peer("asia", (31, 0), "asia.theprotocol.cloud")], LICENCES)
    assert skipped == []
    assert len(payloads) == 1
    assert payloads[0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert payloads[0]["operator_name"] == "asia"
    assert payloads[0]["bayesian_discount"] == pytest.approx(32 / 33)
    assert payloads[0]["spiffe_id"] == "spiffe://asia.theprotocol.cloud"


def test_red_a_peer_without_a_trust_domain_carries_no_spiffe_key():
    for td in (None, "", "   "):
        payloads, _ = trust_sync_payloads([peer("amsterdam", (0, 0), td)], LICENCES)
        assert len(payloads) == 1, td
        assert "spiffe_id" not in payloads[0], (td, payloads[0])


def test_the_licence_rule_is_unchanged():
    """The mechanism he asked to keep: the licence id decides, a revoked licence is skipped, and a licence already claimed
    by an earlier peer is not claimed twice. (SEC-20: a peer with no record is no longer skipped; it sends the prior.)"""
    payloads, skipped = trust_sync_payloads(
        [peer("asia", (31, 0), "asia.theprotocol.cloud"), peer("gone", (2, 0), "gone.example"),
         peer("amsterdam", (0, 0), "eu.theprotocol.cloud"), peer("unknown-peer", (4, 1), "x.example")],
        LICENCES,
    )
    assert [p["id"] for p in payloads] == ["11111111-1111-1111-1111-111111111111",
                                           "22222222-2222-2222-2222-222222222222"]
    assert payloads[1]["bayesian_discount"] == pytest.approx(0.5)
    assert sorted(skipped) == ["gone", "unknown-peer"]


def test_two_peers_cannot_claim_one_licence():
    payloads, skipped = trust_sync_payloads(
        [peer("asia", (9, 0), "asia.theprotocol.cloud"), peer("asia", (8, 0), "other.example")], LICENCES)
    assert len(payloads) == 1 and skipped == ["asia"]
