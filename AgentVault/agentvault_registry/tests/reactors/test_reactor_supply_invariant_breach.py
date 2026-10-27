"""Tests for the SupplyInvariantBreach reactor (Phase 5).

Focus on dispatch + throttling logic. The actual webhook + email send paths
are exercised in sandbox integration; here we monkeypatch the helper.
"""
from __future__ import annotations

import time
import datetime as dt
from typing import List

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks import reactor_supply_invariant_breach as r_sb


@pytest.fixture(autouse=True)
def reset_state():
    reactor_base._registered_leader_keys.clear()
    r_sb._instance = None
    yield
    reactor_base._registered_leader_keys.clear()
    r_sb._instance = None


@pytest.fixture
def patched_dispatch(monkeypatch):
    """Capture calls to the dispatch helper."""
    calls: List[dict] = []

    async def fake(event_data: dict, *, source_label: str = "?") -> None:
        calls.append({"event_data": event_data, "source": source_label})

    monkeypatch.setattr(r_sb, "dispatch_supply_breach_alert", fake)
    return calls


def _fresh_iso() -> str:
    """NOW, in the shape the EventStore stamps.

    §CHATCOHERE-CI (2026-09-01) — `_payload` defaulted to a FROZEN
    `2026-04-26T12:00:00+00:00`. §pass63 (2026-05-22) then taught this reactor to
    silence stale replays (`is_notification_stale`), because an ES reconnect replays
    the last 15 events and every container restart was re-firing CRITICAL alerts for
    historical breaches. From that day the four alert tests fed it a months-old
    timestamp, the guard correctly refused, and they went red — unnoticed, because
    nothing ran them.

    A fixture with a hardcoded date rots by construction: it was passing only while
    that date happened to be recent. `datetime.now` keeps the test asking the
    question it means to ask — does a FRESH breach alert — and the stale path keeps
    its own explicit coverage in `test_stale_replay_is_silenced` below.
    """
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _payload(delta: str = "100.0", detected_at: str | None = None) -> dict:
    return {
        "net_supply": "1000000.0",
        "total_circulating": "999900.0",
        "tokens_issued": "1000000.0",
        "tokens_destroyed": "0.0",
        "tokens_fees": "500.0",
        "delta": delta,
        "tolerance": "0.0",
        "auto_lockdown": False,
        "detected_at": detected_at or _fresh_iso(),
        "audit_type": "self_consistent_es",
    }


# ============================================================ first-alert behavior

@pytest.mark.asyncio
async def test_first_breach_dispatches(patched_dispatch):
    reactor = r_sb.SupplyInvariantBreachReactor()
    await reactor.handle_event(_payload(delta="100.0"))
    assert len(patched_dispatch) == 1
    assert patched_dispatch[0]["source"] == "SupplyInvariantBreach"
    assert patched_dispatch[0]["event_data"]["delta"] == "100.0"


# ============================================================ throttle behavior

@pytest.mark.asyncio
async def test_repeat_breach_with_same_delta_throttled(patched_dispatch):
    reactor = r_sb.SupplyInvariantBreachReactor()
    await reactor.handle_event(_payload(delta="100.0", detected_at="t1"))
    await reactor.handle_event(_payload(delta="100.0", detected_at="t2"))
    assert len(patched_dispatch) == 1, "Second event with same delta within throttle window should be suppressed"


@pytest.mark.asyncio
async def test_delta_change_breaks_throttle(patched_dispatch):
    """Even within the throttle window, an escalation (delta change) should re-alert."""
    reactor = r_sb.SupplyInvariantBreachReactor()
    await reactor.handle_event(_payload(delta="100.0"))
    await reactor.handle_event(_payload(delta="500.0"))
    assert len(patched_dispatch) == 2
    assert patched_dispatch[1]["event_data"]["delta"] == "500.0"


@pytest.mark.asyncio
async def test_throttle_window_expires(patched_dispatch):
    """After the throttle window, the same delta re-alerts."""
    reactor = r_sb.SupplyInvariantBreachReactor()
    await reactor.handle_event(_payload(delta="100.0"))
    reactor._last_alert_at = time.monotonic() - 1000
    await reactor.handle_event(_payload(delta="100.0"))
    assert len(patched_dispatch) == 2


@pytest.mark.asyncio
async def test_short_throttle_via_env(patched_dispatch, monkeypatch):
    """If SUPPLY_ALERT_THROTTLE_SECONDS is configured small, alerts fire faster."""
    from agentvault_registry import config
    monkeypatch.setattr(config.settings, "SUPPLY_ALERT_THROTTLE_SECONDS", 0)
    reactor = r_sb.SupplyInvariantBreachReactor()
    await reactor.handle_event(_payload(delta="100.0", detected_at="t1"))
    await reactor.handle_event(_payload(delta="100.0", detected_at="t2"))
    assert len(patched_dispatch) == 2


# ============================================================ critical log

@pytest.mark.asyncio
async def test_critical_log_emitted(patched_dispatch, caplog):
    import logging
    reactor = r_sb.SupplyInvariantBreachReactor()
    with caplog.at_level(logging.CRITICAL, logger=r_sb.__name__):
        await reactor.handle_event(_payload(delta="42.0"))
    assert any("SUPPLY-BREACH" in rec.message and "delta=42.0" in rec.message
               for rec in caplog.records)


# ============================================================ module API

@pytest.mark.asyncio
async def test_module_start_creates_singleton(monkeypatch):
    async def noop(self):
        pass
    monkeypatch.setattr(reactor_base.EventStoreReactor, "_ws_loop", noop)
    await r_sb.start()
    assert isinstance(r_sb._instance, r_sb.SupplyInvariantBreachReactor)
    await r_sb.stop()
    assert r_sb._instance is None


# ============================================================ leader-key uniqueness

def test_supply_breach_reactor_has_unique_leader_key():
    from agentvault_registry.background_tasks.reactor_peer_deactivated import (
        PeerRegistryDeactivatedReactor,
    )
    from agentvault_registry.background_tasks.reactor_federation_license_suspended import (
        FederationLicenseSuspendedReactor,
    )
    from agentvault_registry.background_tasks.reactor_registry_quarantined import (
        RegistryQuarantinedReactor,
    )
    keys = {
        PeerRegistryDeactivatedReactor.leader_key,
        FederationLicenseSuspendedReactor.leader_key,
        RegistryQuarantinedReactor.leader_key,
        r_sb.SupplyInvariantBreachReactor.leader_key,
    }
    assert len(keys) == 4, f"leader_key collision: {keys}"


@pytest.mark.asyncio
async def test_stale_replay_is_silenced(patched_dispatch):
    """§pass63's guard, pinned. An ES reconnect replays the last 15 events and the
    polling backstop looks back further; without this, every container restart
    re-alerted on historical breaches. A months-old `detected_at` must dispatch
    NOTHING — which is also why `_payload` must default to *now*."""
    reactor = r_sb.SupplyInvariantBreachReactor()
    await reactor.handle_event(_payload(delta="100.0",
                                        detected_at="2026-04-26T12:00:00+00:00"))
    assert patched_dispatch == []
