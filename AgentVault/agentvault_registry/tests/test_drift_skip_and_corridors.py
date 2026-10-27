"""§DRIFTSKIP (2026-09-09) — a peer the syncer deliberately never dials is not drift.

His report pointed at the CONSUL compliance page. Measured on EU before this change:

    7 hochiminh discovered ACTIVE  synced 732m ago   -> "peer_url_misconfigured"
    8 shenzhen  discovered ACTIVE  synced 732m ago   -> "peer_url_misconfigured"
    ... and 4 of 4 FederationStateDriftDetected events in 48h were those two.

Both are `discovered` rows inside ASIA's trust domain, and `asia` is an ACTIVE `frame` row. §BATCH8
item 4 made `federation_sync` skip exactly that shape on purpose ("refused 401 every cycle by a
proxy that never federated with us"), so their `last_synced_at` can never advance. The drift rule
excluded only `peer_type == "frame"`, so it reported a deliberate skip as a misconfiguration for
ever — and named a CAUSE (the URL) it had never measured. From inside eu-registry both peers
resolve, :8443 is OPEN, and ASIA's SPIRE entries for both federate with eu.theprotocol.cloud.

The rule under test is `is_peer_frames_operator`, which now has three callers instead of one:
federation_sync (the syncer), license_drift_monitor (the alarm) and federation_reachability (the
page). One predicate, or they disagree about the same row — which is how this hid.
"""
import ast
import sys
import types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.background_tasks.federation_sync import (  # noqa: E402
    is_peer_frames_operator,
)
from agentvault_registry.services import federation_reachability as fr  # noqa: E402


def _peer(name, ptype, td, status="ACTIVE", **kw):
    base = dict(
        id=kw.pop("id", 1), name=name, peer_type=ptype, trust_domain=td, status=status,
        base_url=kw.pop("base_url", f"https://{name}.example:8443"),
        last_synced_at=kw.pop("last_synced_at", None),
        last_sync_attempt_at=kw.pop("last_sync_attempt_at", None),
        last_sync_error=kw.pop("last_sync_error", None),
        consecutive_sync_failures=kw.pop("consecutive_sync_failures", 0),
        registered_at=kw.pop("registered_at", None),
        spiffe_id=None,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


# the exact live EU population
ASIA_FRAME = _peer("asia", "frame", "asia.theprotocol.cloud", id=3)
SHENZHEN = _peer("shenzhen", "discovered", "asia.theprotocol.cloud", id=8)
HOCHIMINH = _peer("hochiminh", "discovered", "asia.theprotocol.cloud", id=7)
AMSTERDAM = _peer("amsterdam", "cloud_operator", "eu.theprotocol.cloud", id=1)
EU_PEERS = [AMSTERDAM, _peer("lisbon", "cloud_operator", "eu.theprotocol.cloud", id=2),
            ASIA_FRAME, HOCHIMINH, SHENZHEN]


# ── the predicate, on the shape that hid ──────────────────────────────────────────────────────
def test_a_frames_own_operator_is_not_dialled():
    assert is_peer_frames_operator(SHENZHEN, EU_PEERS)
    assert is_peer_frames_operator(HOCHIMINH, EU_PEERS)


def test_our_own_cloud_operator_is_still_dialled():
    """The control that makes the above mean something: a rule that skipped everything would
    silence real drift, which is worse than the noise it replaces."""
    assert not is_peer_frames_operator(AMSTERDAM, EU_PEERS)


def test_a_discovered_peer_with_no_matching_frame_is_still_dialled():
    """Only a frame we ACTIVELY federate with re-serves its operators' cards. A discovered row in
    a domain we do not carry as a frame is nobody's relay — it is ours to dial."""
    orphan = _peer("stray", "discovered", "somewhere.else", id=99)
    assert not is_peer_frames_operator(orphan, EU_PEERS + [orphan])


# ── the alarm must actually ask ───────────────────────────────────────────────────────────────
def test_the_drift_monitor_calls_the_predicate():
    """Structural, because the defect was never in what the monitor computed but in what it
    failed to ask. A behavioural test would need a database to say the same thing."""
    src = (_SRC / "agentvault_registry" / "background_tasks" / "license_drift_monitor.py").read_text()
    tree = ast.parse(src)
    calls = [
        n.func.id for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "is_peer_frames_operator" in calls, (
        "the drift monitor does not ask the syncer's question, so it will report a deliberate "
        "skip as a misconfiguration"
    )


def test_the_drift_query_can_still_see_frames():
    """The predicate needs the frame rows to know which trust domains are relays. A query that
    pre-filters them out makes the question unanswerable — which is how the skip went unmirrored
    in the first place."""
    src = (_SRC / "agentvault_registry" / "background_tasks" / "license_drift_monitor.py").read_text()
    seg = src.split("url_drift_threshold = ", 1)[1].split("for peer in active_peers", 1)[0]
    assert 'PeerRegistry.peer_type != "frame"' not in seg, (
        "frames are filtered out of the query the predicate reads from"
    )


# ── the corridor report ───────────────────────────────────────────────────────────────────────
def test_not_dialled_peer_is_not_a_broken_corridor():
    c = fr.classify(SHENZHEN, not_dialled=True)
    assert c["state"] == fr.STATE_NOT_DIALLED
    assert c["severity"] == "info"


def test_not_dialled_peer_still_says_what_it_is():
    """The Diagnosis and What-to-do columns exist to tell an operator what to do. Blank in exactly
    the case they are for is the defect this closes."""
    c = fr.classify(SHENZHEN, not_dialled=True)
    assert c["diagnosis"] and c["diagnosis"] != "—"
    assert c["remedy"]


def test_a_never_attempted_peer_names_that_state():
    never = _peer("ghost", "cloud_operator", "eu.theprotocol.cloud", id=42,
                  registered_at=None, last_sync_attempt_at=None)
    c = fr.classify(never)
    assert c["state"] == fr.STATE_NEVER_SYNCED
    assert c["diagnosis"] == "never attempted", c["diagnosis"]


def test_an_attempted_peer_with_no_error_is_not_called_never_attempted():
    """Two states that must not collapse: nothing dialled it, versus it was dialled and left no
    error. They have different next steps."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    tried = _peer("tried", "cloud_operator", "eu.theprotocol.cloud", id=43,
                  last_sync_attempt_at=now, registered_at=now - datetime.timedelta(days=9))
    c = fr.classify(tried)
    assert c["diagnosis"] == "attempted, no error recorded", c["diagnosis"]


def test_a_healthy_peer_says_nothing():
    """The control: the honest states must stay silent, or every row grows a diagnosis and the
    column stops meaning anything."""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    ok = _peer("amsterdam", "cloud_operator", "eu.theprotocol.cloud", id=1,
               last_synced_at=now, registered_at=now - datetime.timedelta(days=9))
    c = fr.classify(ok, now)
    assert c["state"] == fr.STATE_OK
    assert c["diagnosis"] is None and c["remedy"] is None


@pytest.mark.parametrize("name", ["STATE_OK", "STATE_PENDING", "STATE_NOT_DIALLED"])
def test_these_states_are_never_findings(name):
    """⚠ Parametrised by NAME, not by value. Reading `fr.STATE_NOT_DIALLED` in the decorator makes
    a module without it explode at COLLECTION, so the pre-fix control would fail for the wrong
    reason and prove nothing about the behaviour ([[feedback_every_gate_needs_both_controls]])."""
    state = getattr(fr, name, None)
    assert state is not None, f"{name} is not defined — a deliberate skip has no state of its own"
    assert fr.SEVERITY[state] in ("ok", "info")
