"""§MTLSHOPS (c) (2026-09-15) — SF-5B's trust sync addresses the event store's rows by the LICENCE id.

The store keys `federation_operators` by the licence id this frame issued. The sync sent the peer ROW id (1, 2, 3), which
no store row carries, so every call fell into the store's insert branch and was refused 400 for a missing licence hash:
every synced peer on EU, ASIA and both sandbox frames, every two minutes, 0 successes in four hours (measured
2026-09-15). The pure rule is pinned here with rows shaped like the ones measured on EU (amsterdam and lisbon hold operator
licences, the peer frame `asia` matches the frame licence `ASIA`, Hansa Freight's licence is revoked, `shenzhen` holds none).
A payload never carries a status: the store authenticates an operator on status == "active", so a peer row's "ACTIVE"
would lock the operator out.
RED control: the tree before this change has no trust_sync_payloads.

SEC-20 (2026-10-17): the value sent is DERIVED from each peer's record (settlements and lost disputes, the last outcome's
time), never read from the row's bayesian_discount column. These rows used to carry a hand-written discount and the
tests asserted it came back out, which pinned the defect (whatever wrote the column decided what the store weighed the
peer's votes by). They now carry a record and a column that disagrees with it, and the record wins.
"""
from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agentvault_registry.background_tasks import federation_sync as fs

NOW = datetime.now(timezone.utc)


def Peer(id, name, record=(0, 0), column=1.0, **kw):
    """A peer row: (total_interactions, disputes_lost_with), its last outcome a day ago, and a bayesian_discount column
    holding a value nothing derived (1.0 by default, the old column default)."""
    total, lost = record
    return SimpleNamespace(id=id, name=name, total_interactions=total, disputes_lost_with=lost,
                           last_interaction_at=NOW - timedelta(days=1) if total else None,
                           registered_at=NOW - timedelta(days=90), bayesian_discount=column, **kw)


def beta(total, lost):
    """The Beta(1,1) posterior mean of a record, written out (no idle decay a day after the last outcome)."""
    return (1 + total - lost) / (2 + total)

LICENCES = [
    ("73f0193f-64fb-454f-abac-004693f274e1", "ASIA", "active"),
    ("bc13aed3-b61c-4551-b3df-4e93b1f1958c", "Hansa Freight", "revoked"),
    ("fa43d7b6-a25b-48fc-a7a5-5afc52357a67", "amsterdam", "active"),
    ("d2197a61-7d0f-423a-8aa5-b01649057dd6", "lisbon", "active"),
]


def test_licensed_peers_are_addressed_by_their_licence_id():
    peers = [Peer(id=1, name="amsterdam", record=(10, 0), column=1.0),
             Peer(id=2, name="lisbon", record=(5, 0), column=0.2)]
    payloads, skipped = fs.trust_sync_payloads(peers, LICENCES)
    assert [(p["id"], p["operator_name"]) for p in payloads] == [
        ("fa43d7b6-a25b-48fc-a7a5-5afc52357a67", "amsterdam"),
        ("d2197a61-7d0f-423a-8aa5-b01649057dd6", "lisbon"),
    ]
    assert payloads[0]["bayesian_discount"] == pytest.approx(beta(10, 0))   # 11/12, not the column's 1.0
    assert payloads[1]["bayesian_discount"] == pytest.approx(beta(5, 0))    # 6/7, not the column's 0.2
    assert skipped == []


def test_a_payload_never_carries_a_status_a_hash_or_the_peer_row_id():
    payloads, _ = fs.trust_sync_payloads([Peer(id=1, name="amsterdam", status="ACTIVE")], LICENCES)
    assert set(payloads[0]) == {"id", "operator_name", "bayesian_discount"}
    assert payloads[0]["id"] != "1"


def test_a_unique_case_insensitive_match_takes_the_licences_own_name():
    payloads, _ = fs.trust_sync_payloads([Peer(id=3, name="asia", record=(24, 1))], LICENCES)
    assert [(p["id"], p["operator_name"]) for p in payloads] == [("73f0193f-64fb-454f-abac-004693f274e1", "ASIA")]
    assert payloads[0]["bayesian_discount"] == pytest.approx(beta(24, 1))


def test_an_exact_name_wins_and_an_ambiguous_one_is_skipped():
    two = [("id-lower", "asia", "active"), ("id-upper", "ASIA", "active")]
    payloads, skipped = fs.trust_sync_payloads([Peer(id=3, name="asia")], two)
    assert [p["id"] for p in payloads] == ["id-lower"] and skipped == []
    payloads, skipped = fs.trust_sync_payloads([Peer(id=4, name="Asia")], two)
    assert payloads == [] and skipped == ["Asia"]


def test_unlicensed_revoked_and_duplicate_peers_are_skipped_and_an_unmeasured_one_sends_the_prior():
    peers = [
        Peer(id=7, name="shenzhen"),                       # no licence issued here
        Peer(id=9, name="Hansa Freight"),                  # revoked licence
        Peer(id=1, name="amsterdam", column=None),         # no record: the prior, whatever the column holds
        Peer(id=3, name="asia", record=(24, 1)),
        Peer(id=6, name="ASIA", record=(3, 0)),            # the same licence, already claimed
    ]
    payloads, skipped = fs.trust_sync_payloads(peers, LICENCES)
    assert [p["operator_name"] for p in payloads] == ["amsterdam", "ASIA"]
    assert payloads[0]["bayesian_discount"] == pytest.approx(0.5)
    assert payloads[1]["bayesian_discount"] == pytest.approx(beta(24, 1))
    assert skipped == ["shenzhen", "Hansa Freight", "ASIA"]


def test_the_sync_posts_the_payloads_and_no_longer_builds_one_from_a_peer_row():
    src = inspect.getsource(fs.FederationSyncWorker._sync_trust_to_eventstore) if hasattr(fs, "FederationSyncWorker") else None
    if src is None:
        cls = next(v for v in vars(fs).values()
                   if isinstance(v, type) and hasattr(v, "_sync_trust_to_eventstore"))
        src = inspect.getsource(cls._sync_trust_to_eventstore)
    tree = ast.parse(src.strip() if not src.startswith(" ") else "class _W:\n" + src)
    calls = {getattr(n.func, "id", None) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "trust_sync_payloads" in calls
    peer_ids = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "id"
                and isinstance(n.value, ast.Name) and n.value.id == "peer"]
    assert peer_ids == []
