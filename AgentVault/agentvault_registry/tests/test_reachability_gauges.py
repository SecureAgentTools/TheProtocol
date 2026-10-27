"""§REACHGAUGE (2026-09-28) — the corridor gauges say what the report says, and keep saying it.

Measured on sbx-beta: a kit frame (`lickit`) was approved at 15:03Z, torn down, and its row went
INACTIVE at 17:59Z. FederationPeerStale kept firing on it at +Inf and FederationCorridorDegraded at
2/3 for hours afterwards, because:

  (1) only a USER read published the gauges (a federated discovery search, the compliance view), so
      they froze at the last one (17:22Z); on EU, ASIA and their four operators no such series
      existed at all, so the three alerts could not fire in production;
  (2) nothing retracted the series of a row that stopped being ACTIVE, and a multiprocess gauge
      cannot drop a label set, so retraction has to be a write (NaN, which no comparison matches);
  (3) the export judged what the report does not: a PENDING peer (inside its never-synced grace)
      went out as never-answered (+Inf) and counted against the ratio, and a NOT_DIALLED row
      (reached through its frame by design) exported an age that only grows. The read-only
      pre-flight (scratchpad/mcpsweep/reach_gauge_preflight.py) showed that refreshing alone would
      have fired FederationPeerStale on amsterdam and lisbon, four such rows each.

Each test below is red on the code before §REACHGAUGE except the three named controls (measured on
deps/v0488 ed240a03: 12 failed, 3 passed).
"""
from __future__ import annotations

import datetime
import logging
import math
import sys
import types
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.background_tasks import federation_sync as fs  # noqa: E402
from agentvault_registry.services import federation_reachability as fr  # noqa: E402

def _peer(name, *, ptype="frame", td=None, status="ACTIVE", pid=1, synced_ago_s=None,
          registered_ago_h=240.0):
    # The clock is read HERE, at call time: a module-level NOW rotted by the minutes the full suite
    # takes to reach this file (a "10 s ago" sync read 206 s old and failed the first full run).
    now = datetime.datetime.now(datetime.timezone.utc)
    return types.SimpleNamespace(
        id=pid, name=name, peer_type=ptype, trust_domain=td or f"{name}.example", status=status,
        base_url=f"https://{name}.example:8443", spiffe_id=None,
        last_synced_at=(now - datetime.timedelta(seconds=synced_ago_s)) if synced_ago_s is not None else None,
        last_sync_attempt_at=None, last_sync_error=None, consecutive_sync_failures=0,
        registered_at=now - datetime.timedelta(hours=registered_ago_h),
    )


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return _Result(self.rows)


def _row(name, state, *, status="ACTIVE", ptype="frame", age=None, diagnosis=None):
    """One classified row, the shape build_report hands publish_metrics."""
    return {"peer": name, "peer_type": ptype, "status": status, "state": state,
            "last_sync_age_seconds": age, "diagnosis": diagnosis}


def _report(rows, ratio=1.0, never=0):
    return {"peers": rows, "findings": [], "reachable_ratio": ratio,
            "counts": {fr.STATE_NEVER_SYNCED: never}}


def _age(name, ptype="frame"):
    return fr.PEER_LAST_SYNC_AGE.labels(peer=name, peer_type=ptype)._value.get()


def _state(name, state, diagnosis="none"):
    return fr.PEER_STATE.labels(peer=name, state=state, diagnosis=diagnosis)._value.get()


# ── (2) a series does not outlive its row ─────────────────────────────────────────────────────────
def test_a_row_that_leaves_active_is_retracted():
    """The sbx-beta shape: ACTIVE and never answered, then INACTIVE. Before: +Inf for ever."""
    fr.publish_metrics(_report([_row("rg-lickit", fr.STATE_NEVER_SYNCED, diagnosis="never attempted")]))
    assert _age("rg-lickit") == float("inf")
    assert _state("rg-lickit", fr.STATE_NEVER_SYNCED, "never attempted") == 1
    fr.publish_metrics(_report([_row("rg-lickit", fr.STATE_NEVER_SYNCED, status="INACTIVE")]))
    assert math.isnan(_age("rg-lickit")), "an INACTIVE row still exports an age the stale rule reads"
    assert _state("rg-lickit", fr.STATE_NEVER_SYNCED, "never attempted") == 0


def test_a_deleted_row_is_retracted():
    fr.publish_metrics(_report([_row("rg-gone", fr.STATE_STALE, age=90000, diagnosis="timeout"),
                                _row("rg-stays", fr.STATE_OK, age=5)]))
    fr.publish_metrics(_report([_row("rg-stays", fr.STATE_OK, age=7)]))
    assert math.isnan(_age("rg-gone"))
    assert _state("rg-gone", fr.STATE_STALE, "timeout") == 0
    assert _age("rg-stays") == 7


def test_a_findings_only_report_retracts_nothing():
    """Control: what a findings-only report leaves out is not gone (the healthy rows are simply
    not listed), so it must not retract them."""
    fr.publish_metrics(_report([_row("rg-quiet", fr.STATE_OK, age=4)]))
    fr.publish_metrics({"peers": None, "findings": [], "reachable_ratio": 1.0, "counts": {}})
    assert _age("rg-quiet") == 4


def test_a_state_change_retires_the_old_state_series():
    fr.publish_metrics(_report([_row("rg-flip", fr.STATE_OK, age=3)]))
    fr.publish_metrics(_report([_row("rg-flip", fr.STATE_STALE, age=30000, diagnosis="timeout")]))
    assert _state("rg-flip", fr.STATE_OK) == 0, "the peer reads as OK and STALE at once"
    assert _state("rg-flip", fr.STATE_STALE, "timeout") == 1


def test_a_type_change_retires_the_old_age_series():
    fr.publish_metrics(_report([_row("rg-retyped", fr.STATE_OK, ptype="discovered", age=2)]))
    fr.publish_metrics(_report([_row("rg-retyped", fr.STATE_OK, ptype="cloud_operator", age=3)]))
    assert math.isnan(_age("rg-retyped", "discovered"))
    assert _age("rg-retyped", "cloud_operator") == 3


# ── (3) only a judged corridor has an age ─────────────────────────────────────────────────────────
def test_a_pending_peer_is_not_a_stale_corridor():
    fr.publish_metrics(_report([_row("rg-pending", fr.STATE_PENDING)]))
    assert math.isnan(_age("rg-pending")), "a peer inside its grace goes out as never-answered"
    assert _state("rg-pending", fr.STATE_PENDING) == 1, "its state is still reported"


def test_a_not_dialled_row_exports_no_age():
    """The production operators' shape: 17 days since a row nobody dials by design last answered."""
    fr.publish_metrics(_report([_row("rg-nd", fr.STATE_NOT_DIALLED, ptype="discovered", age=1521182,
                                     diagnosis="not dialled by design")]))
    assert math.isnan(_age("rg-nd", "discovered"))


def test_a_judged_corridor_keeps_its_age():
    """Control: the rule must still see what it exists for, and +Inf keeps meaning never."""
    fr.publish_metrics(_report([_row("rg-ok", fr.STATE_OK, age=15),
                                _row("rg-dead", fr.STATE_STALE, age=30000, diagnosis="timeout"),
                                _row("rg-never", fr.STATE_NEVER_SYNCED, diagnosis="never attempted")]))
    assert _age("rg-ok") == 15
    assert _age("rg-dead") == 30000
    assert _age("rg-never") == float("inf")


# ── the ratio ─────────────────────────────────────────────────────────────────────────────────────
async def test_the_ratio_leaves_a_pending_peer_out():
    """sbx-beta read "2 of 3 answering" beside "Every active peer answered within the window"."""
    rows = [_peer("rg-a", pid=1, synced_ago_s=20), _peer("rg-b", pid=2, ptype="cloud_operator", synced_ago_s=20),
            _peer("rg-kit", pid=3, registered_ago_h=2.0)]
    rep = await fr.build_report(_DB(rows), include_ok=True)
    assert rep["counts"].get(fr.STATE_PENDING) == 1
    assert rep["peers_pending"] == 1
    assert rep["peers_active"] == 2
    assert rep["reachable_ratio"] == 1.0
    assert rep["findings"] == []


async def test_a_pending_peer_that_outlives_its_grace_counts_again():
    """Control: the exclusion ends with the grace, as NEVER_SYNCED."""
    rows = [_peer("rg-c", pid=1, synced_ago_s=20), _peer("rg-late", pid=2, registered_ago_h=30.0)]
    rep = await fr.build_report(_DB(rows), include_ok=True)
    assert rep["counts"].get(fr.STATE_NEVER_SYNCED) == 1
    assert rep["peers_active"] == 2 and rep["reachable_ratio"] == 0.5


def test_no_corridor_to_judge_is_not_the_last_ratio():
    fr.publish_metrics(_report([], ratio=0.5))
    assert fr.PEERS_REACHABLE_RATIO._value.get() == 0.5
    fr.publish_metrics(_report([], ratio=None))
    assert math.isnan(fr.PEERS_REACHABLE_RATIO._value.get()), "the ratio kept the last read's value"


async def test_a_findings_only_read_still_publishes_every_row():
    """The compliance overview asks include_ok=False; the gauges must still move for the rows it
    does not return."""
    fr.PEER_LAST_SYNC_AGE.labels(peer="rg-healthy", peer_type="frame").set(99999)
    rep = await fr.build_report(_DB([_peer("rg-healthy", pid=1, synced_ago_s=10)]), include_ok=False)
    assert rep["peers"] is None, "the response shape is unchanged"
    assert _age("rg-healthy") < 60


# ── (1) the sync cycle publishes ──────────────────────────────────────────────────────────────────
async def test_the_sync_cycle_publishes_before_it_can_return_early(monkeypatch):
    """A registry with no SPIFFE identity returns first thing, and is exactly the one whose
    corridors must go on being reported."""
    calls = []

    async def _pub():
        calls.append(1)

    monkeypatch.setattr(fs, "_publish_reachability", _pub)
    monkeypatch.setattr(fs.svid_client, "get_spiffe_id", lambda: None)
    await fs.federation_sync_worker._perform_sync_cycle()
    assert calls == [1]


async def test_the_publish_reads_every_row_in_its_own_session(monkeypatch):
    seen = {}

    class _Session:
        async def __aenter__(self):
            return "own-session"

        async def __aexit__(self, *exc):
            return False

    async def _build(db, *, include_ok=False):
        seen.update(db=db, include_ok=include_ok)

    monkeypatch.setattr(fs, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(fr, "build_report", _build)
    await fs._publish_reachability()
    assert seen == {"db": "own-session", "include_ok": True}


async def test_a_failing_publish_is_loud_and_never_breaks_the_cycle(monkeypatch, caplog):
    async def _boom(db, *, include_ok=False):
        raise RuntimeError("db gone")

    class _Session:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(fs, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(fr, "build_report", _boom)
    monkeypatch.setattr(fs, "_REACH_WARNED_AT", [None])
    with caplog.at_level(logging.WARNING):
        await fs._publish_reachability()
    assert any("reachability publish failed" in r.getMessage() for r in caplog.records)
