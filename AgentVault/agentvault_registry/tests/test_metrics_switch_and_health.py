"""§SECFIX D6-254 (2026-10-16, his word): /metrics stays, as a switch per registry an operator can turn off
(METRICS_ENABLED, default on, so nothing changes for anyone who relies on it); the treasury's balance leaves the metrics;
/health no longer names the event store's internal address.

Measured on the base (14520b9f) through the real app (main.create_app, the factory the registry runs): /metrics answered
with METRICS_ENABLED=false, /health carried event_store.event_store_url, and after one treasury watcher cycle /metrics
carried registry_treasury_balance with the balance read from the TEG.
"""
from __future__ import annotations

import httpx
import pytest

from agentvault_registry import main


async def _get(app, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


@pytest.mark.parametrize("value", ["false", "0", "off", "NO"])
async def test_an_operator_can_turn_metrics_off(monkeypatch, value):
    monkeypatch.setenv("METRICS_ENABLED", value)
    r = await _get(main.create_app(), "/metrics")
    assert r.status_code == 404 and "# HELP" not in r.text


@pytest.mark.parametrize("value", [None, "true", "1", ""])
async def test_control_metrics_stay_on_by_default(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("METRICS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("METRICS_ENABLED", value)
    r = await _get(main.create_app(), "/metrics")
    assert r.status_code == 200 and "# HELP" in r.text


async def test_health_answers_without_the_event_stores_address(monkeypatch):
    monkeypatch.setattr(main.settings, "EVENT_STORE_URL", "https://frame-nginx-event-store:8443", raising=False)
    r = await _get(main.create_app(), "/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "event_store_url" not in body["event_store"] and "nginx-event-store" not in r.text
    assert body["event_store"]["enabled"] is True        # what a health check reads is still there


async def test_the_treasury_balance_is_not_in_the_metrics(monkeypatch):
    from decimal import Decimal

    from agentvault_registry.background_tasks import treasury_low_watch as tlw

    monkeypatch.delenv("METRICS_ENABLED", raising=False)
    monkeypatch.setenv("TREASURY_LOW_NOTIFY_THRESHOLD", "100")
    worker = tlw.TreasuryLowWatchWorker()

    async def _balance():
        return Decimal("987654.321")

    async def _state(*_a, **_k):
        return "ok"

    async def _nothing(*_a, **_k):
        return None

    monkeypatch.setattr(worker, "_read_platform_balance", _balance)
    monkeypatch.setattr(worker, "_get_state", _state)
    monkeypatch.setattr(worker, "_set_state", _nothing)
    monkeypatch.setattr(worker, "_notify_platform", _nothing)
    async def _no_orgs():
        return []

    monkeypatch.setattr(worker, "_org_candidates", _no_orgs)
    await worker._cycle_once()
    text = (await _get(main.create_app(), "/metrics")).text
    assert "registry_treasury_low_active" in text                 # control: the watcher's cycle reached the metrics
    assert "registry_treasury_balance" not in text and "987654" not in text
