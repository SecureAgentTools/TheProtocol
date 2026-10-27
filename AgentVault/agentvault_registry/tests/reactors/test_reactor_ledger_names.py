"""W4 phase 1 (agentvault2-aa, 2026-10-25): a reactor hears its event under the old name and the new one.

A reactor is written for one event name (CanaryTokensTransferredReactor for TokensTransferred, the push reactor, the
balance sync). Phase 2 lets an emitter write the new name (UnitsTransferred); a reactor that listened for the old name
alone would stop hearing transfers on the day an emitter switched. So the base class listens, filters and polls by every
live name of its event (core/ledger_names.live_names: the old name and its new one, never a legacy spelling), and an
unrenamed event behaves exactly as before: one channel, one name, the two requests it always made.
"""
from __future__ import annotations

import asyncio
import json
import types
from datetime import datetime, timezone
from typing import List

import pytest

from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks.reactor_base import EventStoreReactor
from agentvault_registry.core import ledger_names


@pytest.fixture(autouse=True)
def _fresh_keys():
    reactor_base._registered_leader_keys.clear()
    yield
    reactor_base._registered_leader_keys.clear()


def _reactor(event_type):
    captured: List[dict] = []

    class _R(EventStoreReactor):
        async def handle_event(self, event_data: dict) -> None:
            captured.append(event_data)

    _R.event_type, _R.leader_key, _R.name, _R.dispatch_mode = event_type, f"w4_{event_type}", "W4", "serial"
    return _R(), captured


def test_the_map_names_each_event_once():
    assert ledger_names.names_of("TokensTransferred") == ("TokensTransferred", "UnitsTransferred", "TokenTransferred")
    assert ledger_names.names_of("UnitsTransferred") == ledger_names.names_of("TokensTransferred")
    assert ledger_names.live_names("TokensStaked") == ("TokensStaked", "UnitsLocked")
    assert ledger_names.live_names("RewardDistributed") == ("RewardsDistributed", "LockPayoutsDistributed")
    assert ledger_names.names_of("AgentCreated") == ("AgentCreated",) == ledger_names.live_names("AgentCreated")
    assert ledger_names.old_name("UnitsIssued") == "TokensIssued" and ledger_names.new_name("TokensIssued") == "UnitsIssued"
    assert ledger_names.same("UnitsLocked", "TokensStaked") and not ledger_names.same("UnitsLocked", "UnitsUnlocked")
    assert ledger_names.expand({"TokensIssued", "AgentCreated"}) == {"TokensIssued", "UnitsIssued", "AgentCreated"}
    assert ledger_names.new_name("ExchangeDividendPaid") == "ExchangeDistributionPaid"


def test_every_new_name_is_new_and_names_one_event():
    olds = set(ledger_names.RENAMED) | set(ledger_names.AGORA_RENAMED)
    news = list(ledger_names.RENAMED.values()) + list(ledger_names.AGORA_RENAMED.values())
    assert len(news) == len(set(news)) and not olds & set(news)
    for n in news:
        assert not any(w in n for w in ("Token", "Stak", "Reward", "Dividend", "Share")), n


@pytest.mark.asyncio
async def test_a_reactor_for_the_old_name_hears_the_new_one():
    r, captured = _reactor("TokensTransferred")
    assert r._event_names == ("TokensTransferred", "UnitsTransferred")
    for t, n in (("TokensTransferred", 1), ("UnitsTransferred", 2), ("UnitsLocked", 3), ("TokenTransferred", 4)):
        await r._on_event(json.dumps({"type": "event", "event": {"id": f"e{n}", "event_type": t, "data": {"n": n}}}))
    assert captured == [{"n": 1}, {"n": 2}], "the two live names, never another event, never a legacy spelling"


@pytest.mark.asyncio
async def test_an_unrenamed_reactor_is_unchanged():
    r, captured = _reactor("PeerRegistryDeactivated")
    assert r._event_names == ("PeerRegistryDeactivated",)
    await r._on_event(json.dumps({"type": "event", "event": {"id": "x", "event_type": "PeerRegistryDeactivated",
                                                             "data": {"k": 1}}}))
    assert captured == [{"k": 1}]


class _Resp:
    def __init__(self, url, events):
        self.status_code, self._events, self.request = 200, events, types.SimpleNamespace(url=url)

    def json(self):
        return self._events


def _fake_client(store, asked):
    class _Client:
        def __init__(self, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, url, params=None, headers=None):
            asked.append((url.rsplit("/", 1)[-1], params["event_type"]))
            local = url.endswith("/export")
            return _Resp(url, [e for e in store if e["event_type"] == params["event_type"] and e["local"] == local])
    return _Client


async def _poll(r, store, monkeypatch):
    asked: list = []
    monkeypatch.setenv("EVENT_STORE_URL", "http://event-store:8200")
    monkeypatch.setenv("INTERNAL_API_KEY", "test-internal-key")
    monkeypatch.setattr(reactor_base.httpx, "AsyncClient", _fake_client(store, asked))

    async def _no_save(_ts):
        return None
    monkeypatch.setattr(r, "_save_cursor_to_redis", _no_save)
    r._last_polled_ts = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)
    ok = await r._do_polling_backstop_cycle()
    return ok, asked


@pytest.mark.asyncio
async def test_the_poll_asks_each_live_name_local_and_foreign(monkeypatch):
    r, captured = _reactor("TokensTransferred")
    store = [
        {"id": "a", "event_type": "TokensTransferred", "data": {"n": 1}, "timestamp": "2026-10-25T20:00:00Z", "local": True},
        {"id": "b", "event_type": "UnitsTransferred", "data": {"n": 2}, "timestamp": "2026-10-25T20:01:00Z", "local": True},
        {"id": "c", "event_type": "UnitsTransferred", "data": {"n": 3}, "timestamp": "2026-10-25T20:02:00Z", "local": False},
    ]
    ok, asked = await _poll(r, store, monkeypatch)
    assert ok is True
    assert sorted(asked) == sorted([("export", "TokensTransferred"), ("foreign", "TokensTransferred"),
                                    ("export", "UnitsTransferred"), ("foreign", "UnitsTransferred")])
    assert sorted(e["n"] for e in captured) == [1, 2, 3]
    assert r._last_polled_ts == datetime(2026, 10, 25, 20, 2, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_an_unrenamed_poll_makes_the_two_requests_it_always_made(monkeypatch):
    r, captured = _reactor("PeerRegistryDeactivated")
    ok, asked = await _poll(r, [{"id": "p", "event_type": "PeerRegistryDeactivated", "data": {"k": 1},
                                 "timestamp": "2026-10-25T20:00:00Z", "local": True}], monkeypatch)
    assert ok is True and sorted(asked) == [("export", "PeerRegistryDeactivated"), ("foreign", "PeerRegistryDeactivated")]
    assert [e["k"] for e in captured] == [1], "(the poll adds the envelope's timestamp to the data, as it always did)"
