"""§BUNDLECLOCK (2026-09-09) — the frame drift rule must see an EXPIRED bundle.

His report: *"we have drift scans for federation compliance poller. check why it doesnt auto
refresh anymore and why clock disappeared. this already worked."*

It had. The 2026-04-21 rewrite replaced a bad clock (BFS `last_seen_in_topology_at`, an on-demand
signal that false-positived when nobody opened the admin UI) with NO clock, and kept the name
`frame_bundle_stale`. Its docstring stated the premise that made that safe — "If BOTH present ->
SPIRE's internal refresh keeps the bundle current" — and that premise is false in exactly the case
that matters: `https_spiffe` authenticates the peer's bundle endpoint AGAINST THE BUNDLE THE
CALLER ALREADY HOLDS, so an expired bundle can never fetch its replacement.

MEASURED, which is why this file exists: frame-b and frame-c held agentvault.com bundles with 0
live roots for days while every mTLS hop to Frame A failed, and this monitor reported
`frame_bundle_stale: 0` on all 60 cycles.

CONTROLS BOTH WAYS ([[feedback_every_gate_needs_both_controls]]): each case that must fire is
paired with the neighbouring case that must NOT, so a rule that simply always fires cannot pass.
"""
import sys, types
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.background_tasks.license_drift_monitor import (  # noqa: E402
    BUNDLE_EXPIRY_WARN_SECONDS,
    DRIFT_TYPE_FRAME_BUNDLE_EXPIRED,
    DRIFT_TYPE_FRAME_BUNDLE_EXPIRING,
    DRIFT_TYPE_FRAME_BUNDLE_STALE,
    detect_drift_for_frame,
)

HOUR = 3600.0


def _frame(status="ACTIVE", peer_type="frame"):
    return types.SimpleNamespace(
        id=1, name="frame-b", peer_type=peer_type, status=status,
        trust_domain="frame-b.theprotocol.cloud",
    )


def _flags(**kw):
    base = dict(spire_has_federation=True, spire_has_bundle=True)
    base.update(kw)
    return detect_drift_for_frame(_frame(), **base)


# ── the case that hid: present AND expired ────────────────────────────────────────────────────
def test_expired_bundle_fires():
    """The live 2026-09-09 shape: relationship present, bundle present, every root expired."""
    assert DRIFT_TYPE_FRAME_BUNDLE_EXPIRED in _flags(bundle_expires_in_seconds=-46 * HOUR)


def test_expired_bundle_is_not_reported_as_merely_absent():
    """`frame_bundle_stale` means ABSENT and must not be reused for expiry — the two need
    different operator actions (federate vs `bundle set`)."""
    assert DRIFT_TYPE_FRAME_BUNDLE_STALE not in _flags(bundle_expires_in_seconds=-46 * HOUR)


# ── the control that makes the above mean something ───────────────────────────────────────────
def test_healthy_bundle_is_silent():
    """A bundle with real headroom fires NOTHING. Without this, a rule that always fires passes."""
    assert _flags(bundle_expires_in_seconds=6 * 24 * HOUR) == []


def test_expiring_soon_fires_but_expired_does_not():
    """Inside the warn window is a WARNING, not a terminal state: SPIRE can still refresh."""
    f = _flags(bundle_expires_in_seconds=BUNDLE_EXPIRY_WARN_SECONDS - HOUR)
    assert DRIFT_TYPE_FRAME_BUNDLE_EXPIRING in f
    assert DRIFT_TYPE_FRAME_BUNDLE_EXPIRED not in f


def test_boundary_just_outside_the_warn_window_is_silent():
    assert _flags(bundle_expires_in_seconds=BUNDLE_EXPIRY_WARN_SECONDS + HOUR) == []


# ── NOT MEASURED is a third state, never "healthy" ────────────────────────────────────────────
def test_unreadable_clock_emits_nothing_rather_than_healthy_or_drift():
    """"I could not read the clock" and "the clock says fine" must not render identically —
    that equivalence is how this class stayed invisible. The caller logs it instead."""
    assert _flags(bundle_expires_in_seconds=None, bundle_freshness_error="docker exec failed") == []
    assert _flags(bundle_expires_in_seconds=None) == []


def test_an_error_wins_over_a_number():
    """If the reader reported an error, the number it also returned is not trustworthy."""
    assert _flags(bundle_expires_in_seconds=-99 * HOUR, bundle_freshness_error="parse failed") == []


# ── the absent case still behaves as before ───────────────────────────────────────────────────
def test_absent_bundle_still_fires_stale_and_reads_no_clock():
    f = detect_drift_for_frame(_frame(), spire_has_federation=True, spire_has_bundle=False,
                               bundle_expires_in_seconds=-5 * HOUR)
    assert f == [DRIFT_TYPE_FRAME_BUNDLE_STALE]


def test_inactive_frame_is_never_drift():
    """A decommissioned frame is not a defect ([[feedback_never_delete_consent_to_tidy]]'s
    neighbour: do not alarm on state someone retired on purpose)."""
    f = detect_drift_for_frame(_frame(status="INACTIVE"), spire_has_federation=False,
                               spire_has_bundle=False, bundle_expires_in_seconds=-5 * HOUR)
    assert f == []


@pytest.mark.parametrize("ptype", ["cloud_operator", "discovered", "direct_peer"])
def test_non_frame_peers_are_out_of_scope(ptype):
    f = detect_drift_for_frame(_frame(peer_type=ptype), spire_has_federation=False,
                               spire_has_bundle=False, bundle_expires_in_seconds=-5 * HOUR)
    assert f == []
