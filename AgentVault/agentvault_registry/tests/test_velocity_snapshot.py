"""§VITALS — the velocity snapshot reads the EventStore API that actually exists.

Four independent silent defects lived here at once, and every one of them
produced the same innocent line, "No transfer events in window":

  1. `/api/v1/events` without the trailing slash -> the ES vhost's absolute
     redirect drops scheme+port -> ConnectError on a dead :80.
  2. the payload was read as `event_data` / `sender_did`; the ES ships
     `data` / `from`.
  3. `from=`/`to=` are NOT parameters of that endpoint — FastAPI drops unknown
     query params, so the window was never applied.
  4. `limit=10000` is that endpoint's maximum and the type-filtered path is DESC.

`velocity_metrics` therefore stayed empty, and `agent_authz.check_spend_admission`
sums that table for the IRONKEY rolling-24h `max_per_day` cap — so the cap could
never bind. These tests pin the contract in both directions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agentvault_registry.background_tasks import velocity_snapshot as vs


WSTART = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)
WEND = WSTART + timedelta(hours=1)


def _ev(minute: int, sender: str, amount, ev_id=None, key="data", sender_key="from"):
    ts = (WSTART + timedelta(minutes=minute)).isoformat()
    return {"id": ev_id or f"e{minute}-{sender}", "event_type": "TokensTransferred",
            "timestamp": ts, key: {sender_key: sender, "to": "x", "amount": amount}}


def _ev_s(second: int, sender: str, amount, ev_id=None):
    """Second-spaced, so a FULL page still fits inside the one-hour window —
    minute-spaced events would run past window_end and end the walk correctly,
    which is the paging path this fixture is not trying to test."""
    ts = (WSTART + timedelta(seconds=second)).isoformat()
    return {"id": ev_id or f"s{second}-{sender}", "event_type": "TokensTransferred",
            "timestamp": ts, "data": {"from": sender, "to": "x", "amount": amount}}


class _Resp:
    def __init__(self, status, payload=None, location=None):
        self.status_code = status
        self._p = payload if payload is not None else []
        self.headers = {"location": location} if location else {}

    def json(self):
        return self._p


class _Client:
    """Fake httpx.AsyncClient: serves a scripted list of responses in order, to the queries for one event name (W4: the
    worker asks for the transfers under each live name; a store answers the other name with nothing, as a real one does
    until an emitter writes it)."""

    def __init__(self, pages, recorder=None, serve_type="TokensTransferred"):
        self._pages = list(pages)
        self._serve_type = serve_type
        self.calls: list = recorder if recorder is not None else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append((url, dict(params or {})))
        if (params or {}).get("event_type", self._serve_type) != self._serve_type:
            return _Resp(200, [])
        return self._pages.pop(0) if self._pages else _Resp(200, [])


def _patch(monkeypatch, pages, recorder=None, serve_type="TokensTransferred"):
    monkeypatch.setattr(vs.httpx, "AsyncClient",
                        lambda *a, **k: _Client(pages, recorder, serve_type))
    monkeypatch.setattr(vs, "get_httpx_verify", lambda: True, raising=False)


# --------------------------------------------------------------- failure vs empty
async def test_a_failed_query_returns_None_not_an_empty_window(monkeypatch):
    _patch(monkeypatch, [_Resp(503)])
    got = await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    assert got is None, "a transport failure must be distinguishable from an empty hour"


async def test_a_redirect_is_a_failure_and_is_not_followed(monkeypatch):
    _patch(monkeypatch, [_Resp(307, location="http://nginx-event-store/api/v1/events/")])
    got = await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    assert got is None, "following the scheme-dropping redirect is what made this silent"


async def test_a_genuinely_empty_window_returns_an_empty_dict(monkeypatch):
    _patch(monkeypatch, [_Resp(200, [])])
    assert await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND) == {}


# --------------------------------------------------------------- the wire contract
async def test_it_calls_the_export_rail_with_a_since_cursor(monkeypatch):
    calls: list = []
    _patch(monkeypatch, [_Resp(200, [])], recorder=calls)
    await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    url, params = calls[0]
    assert url.endswith("/api/v1/events/export"), "the /events/ rail has no window filter"
    assert params["since"] == WSTART.isoformat()
    assert params["event_type"] == "TokensTransferred"
    assert params["limit"] <= 1000, "the export rail caps limit at 1000"
    assert "from" not in params and "to" not in params, "params the endpoint ignores"


async def test_it_reads_the_shape_the_eventstore_actually_ships(monkeypatch):
    _patch(monkeypatch, [_Resp(200, [_ev(5, "did:a", 10), _ev(6, "did:a", 2.5),
                                     _ev(7, "did:b", 4)])])
    got = await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    assert got == {"did:a": {"count": 2, "volume": Decimal("12.5")},
                   "did:b": {"count": 1, "volume": Decimal("4")}}


async def test_volume_is_decimal_and_sub_unit_survives(monkeypatch):
    """mig 0170. tx_volume was a BigInteger, so Postgres ROUNDED on the way in —
    half away from zero, losing 0.1 and inflating 0.6 to 1. The column it is summed
    against (agent_spend_policies.max_per_day) is NUMERIC(36,18), so the aggregate
    must be exact and it must not be a binary float."""
    _patch(monkeypatch, [_Resp(200, [_ev(m, "did:dust", "0.01") for m in range(10)])])
    got = await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    vol = got["did:dust"]["volume"]
    assert isinstance(vol, Decimal), "a money aggregate is not a float"
    assert vol == Decimal("0.1"), f"exact decimal sum, got {vol!r}"
    assert int(vol) == 0, "…and as an integer it would have been LOST — that was the defect"


async def test_the_legacy_shape_still_parses(monkeypatch):
    """Kept as a fallback so an ES rename degrades instead of silently zeroing."""
    _patch(monkeypatch, [_Resp(200, [_ev(5, "did:c", 7, key="event_data",
                                         sender_key="sender_did")])])
    got = await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    assert got == {"did:c": {"count": 1, "volume": 7.0}}


async def test_events_at_or_after_the_window_end_are_excluded(monkeypatch):
    _patch(monkeypatch, [_Resp(200, [_ev(59, "did:in", 1), _ev(60, "did:out", 99),
                                     _ev(75, "did:out", 99)])])
    got = await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    assert got == {"did:in": {"count": 1, "volume": 1.0}}


async def test_it_pages_until_the_window_is_covered(monkeypatch):
    page1 = [_ev_s(sec, "did:a", 1) for sec in range(0, vs._EXPORT_PAGE_SIZE)]
    page2 = [_ev(59, "did:b", 5)]
    calls: list = []
    _patch(monkeypatch, [_Resp(200, page1), _Resp(200, page2)], recorder=calls)
    got = await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    asked = [c[1]["event_type"] for c in calls]
    assert asked.count("TokensTransferred") == 2, "a full page must not end the window"
    assert asked.count("UnitsTransferred") == 1, "W4: the new name is asked too (an empty answer ends its walk)"
    assert got["did:b"]["count"] == 1


async def test_the_upsert_conflicts_on_columns_not_a_constraint_name(monkeypatch):
    """THE FIFTH DEFECT, visible only once the other four were fixed. The DB carries
    `ix_velocity_agent_window` as a UNIQUE INDEX, not a constraint, so
    `on_conflict_do_update(constraint=...)` — which compiles to ON CONFLICT ON
    CONSTRAINT and resolves against pg_constraint alone — died on every upsert with
    `constraint "ix_velocity_agent_window" does not exist`."""
    import inspect
    src = inspect.getsource(vs.VelocitySnapshotWorker._run_snapshot)
    assert "index_elements=['agent_did', 'window_start']" in src
    assert "constraint='ix_velocity_agent_window'" not in src


async def test_a_failed_cycle_is_never_reported_as_ok(monkeypatch):
    """The author's OWN wiring reproduced the defect this whole contract exists to
    kill: `_run_snapshot` caught everything, so an upsert failure stamped `ok`.
    Any internal failure must reach the cycle stamp."""
    import inspect
    assert issubclass(vs.VelocityQueryFailed, vs.VelocitySnapshotFailed)
    src = inspect.getsource(vs.VelocitySnapshotWorker._run_snapshot)
    assert "raise VelocitySnapshotFailed" in src, "the catch-all must re-raise, not swallow"


async def test_a_stalled_cursor_does_not_spin(monkeypatch):
    """Every event on the same timestamp: the cursor cannot advance. It must stop,
    not loop 200 times against a live EventStore."""
    same = [_ev_s(300, f"did:{i}", 1, ev_id=f"same-{i}") for i in range(vs._EXPORT_PAGE_SIZE)]
    calls: list = []
    _patch(monkeypatch, [_Resp(200, same)] * 5, recorder=calls)
    await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    asked = [c[1]["event_type"] for c in calls]
    assert asked.count("TokensTransferred") <= 2 and asked.count("UnitsTransferred") <= 2


async def test_a_transfer_under_its_new_name_counts_the_same(monkeypatch):
    """W4 phase 1 (agentvault2-aa, 2026-10-25): once an emitter writes UnitsTransferred (phase 2), the hour's volume reads
    the same; the spend cap sums this table, so a transfer the worker could not see would let a sender past its cap."""
    def _new(minute, sender, amount):
        e = _ev(minute, sender, amount)
        e["event_type"], e["id"] = "UnitsTransferred", f"n{minute}-{sender}"
        return e
    calls: list = []
    _patch(monkeypatch, [_Resp(200, [_new(5, "did:a", 10), _new(6, "did:a", "2.5")])], recorder=calls,
           serve_type="UnitsTransferred")
    got = await vs.VelocitySnapshotWorker()._query_event_store_transfers(WSTART, WEND)
    assert got == {"did:a": {"count": 2, "volume": Decimal("12.5")}}
    assert [c[1]["event_type"] for c in calls] == ["TokensTransferred", "UnitsTransferred"]


# ------------------------------------------------- the fee's velocity index (2026-10-16)
# It was the agent's volume over the hour's LARGEST volume, so the busiest sender of any hour read 1.0 and paid the
# maximum fee, a lone sender on a quiet frame included (his word: "its not intended to do this even on a quiet
# network"). velocity_indices() compares a sender with the typical sender of the hour instead.

def _vols(*amounts):
    return {f"did:theprotocol:a{i}": Decimal(str(a)) for i, a in enumerate(amounts)}


def test_a_lone_sender_on_a_quiet_frame_reads_zero():
    assert vs.velocity_indices(_vols(5000)) == {"did:theprotocol:a0": 0.0}


def test_an_hour_with_fewer_senders_than_the_minimum_reads_zero_for_everyone():
    idx = vs.velocity_indices(_vols(*([10] * 8 + [100000])))  # 9 senders, one of them huge
    assert set(idx.values()) == {0.0}


def test_the_busiest_sender_of_an_ordinary_hour_stays_under_the_surcharge():
    idx = vs.velocity_indices(_vols(*([200] * 9 + [260])))
    assert max(idx.values()) < 0.7  # the fee service charges the base rate up to 0.7


def test_a_crowd_of_tiny_transfers_does_not_make_an_ordinary_one_an_outlier():
    idx = vs.velocity_indices(_vols(*([0.01] * 10 + [50])))
    assert idx["did:theprotocol:a10"] == 0.0  # the baseline never drops below 100 units


def test_an_outlier_far_above_the_median_pays_and_the_index_saturates():
    idx = vs.velocity_indices(_vols(*([100] * 10 + [3000, 10000, 50000])))
    assert idx["did:theprotocol:a10"] > 0.7  # 30 times the baseline: a surcharge
    assert idx["did:theprotocol:a11"] == pytest.approx(1.0)  # 100 times: the maximum rate
    assert idx["did:theprotocol:a12"] == 1.0  # capped


async def test_the_cycle_writes_zero_for_a_lone_sender(monkeypatch):
    """Through _run_snapshot: the index the hourly cycle stores for the only sender of the hour."""
    written = []

    class _Stmt:
        def __init__(self, values):
            self.values_ = values

        def on_conflict_do_update(self, **kw):
            return self

    class _Insert:
        def values(self, **kw):
            written.append(kw)
            return _Stmt(kw)

    class _Db:
        async def execute(self, *a, **k):
            return None

        async def commit(self):
            return None

    class _Ctx:
        async def __aenter__(self):
            return _Db()

        async def __aexit__(self, *a):
            return False

    async def _stats(self, start, end):
        return {"did:theprotocol:solo": {"count": 3, "volume": Decimal("750")}}

    monkeypatch.setattr(vs.VelocitySnapshotWorker, "_query_event_store_transfers", _stats)
    monkeypatch.setattr(vs, "pg_insert", lambda model: _Insert())
    monkeypatch.setattr(vs, "get_db_context", lambda: _Ctx())
    await vs.VelocitySnapshotWorker()._run_snapshot()
    assert written and written[0]["agent_did"] == "did:theprotocol:solo"
    assert written[0]["velocity_index"] == 0.0  # the rule this replaces wrote 1.0 here
