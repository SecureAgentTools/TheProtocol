"""D6-752 (2026-10-16): the backlog a new subscription is sent follows the channel's key, as the live stream does.

An agent:<did> subscription was sent the last 15 events of every agent (only events:<type> was filtered), and so was
any other channel name. What these tests pin, through FastAPI on the real /ws/events route (only the database session
is replaced, by an in-memory ledger that evaluates the route's WHERE clause, so an unfiltered query gets every row,
as a real database would answer it):
- agent:<did> is sent that agent's own last 15 events and nothing of another agent's,
- a channel the store publishes no events on (balance:updates) is sent none,
- events:all and events:<type> are sent what they were before (the controls: they pass on the old code too).
Run: python -m pytest tests/test_ws_backlog_follows_the_channel.py -q   (needs pytest and httpx)
"""
import datetime
import os
import sys
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

# The database module builds its engine at import; nothing here connects to it.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@127.0.0.1:1/ci")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.sql import operators  # noqa: E402
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList  # noqa: E402

import src.database.connection as connection  # noqa: E402
from src.routers import websocket as ws_router  # noqa: E402

ALICE = "did:theprotocol:d6-752-alice"
BOB = "did:theprotocol:d6-752-bob"
T0 = datetime.datetime(2026, 10, 16, 12, 0, tzinfo=datetime.timezone.utc)


def _event(n: int, aggregate_id: str, event_type: str):
    return SimpleNamespace(id=uuid.UUID(int=n), event_type=event_type, aggregate_id=aggregate_id,
                           aggregate_type="Agent", data={"n": n}, timestamp=T0 + datetime.timedelta(seconds=n),
                           version=n, source_service="d6-752-test")


# Alice's 18 events are older than all 20 of Bob's: the newest 15 of the whole ledger hold none of hers.
ROWS = [_event(n, ALICE, "ReputationChanged") for n in range(1, 19)] + \
       [_event(n, BOB, "TokensTransferred") for n in range(19, 39)]


def _matches(clause, row) -> bool:
    """Evaluate the route's WHERE clause on one in-memory row: column == value, and and/or of those. Any other shape
    fails the test loudly rather than being guessed at."""
    if clause is None:
        return True
    if isinstance(clause, BooleanClauseList):
        results = [_matches(c, row) for c in clause.clauses]
        return all(results) if clause.operator is operators.and_ else any(results)
    if isinstance(clause, BinaryExpression) and clause.operator is operators.eq and isinstance(clause.right, BindParameter):
        return getattr(row, clause.left.key) == clause.right.value
    raise AssertionError(f"the in-memory ledger cannot evaluate {clause!r}")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))


class MemoryLedger:
    """Stands in for AsyncSessionLocal: answers the backlog query newest first, honouring its WHERE and LIMIT."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = 0
        self.closed = threading.Event()  # the route closes its session after it has sent the backlog

    def __call__(self):
        return _Session(self)


class _Session:
    def __init__(self, ledger):
        self.ledger = ledger

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.ledger.closed.set()
        return False

    async def execute(self, stmt):
        self.ledger.queries += 1
        rows = sorted((r for r in self.ledger.rows if _matches(stmt.whereclause, r)),
                      key=lambda r: r.timestamp, reverse=True)
        limit = getattr(stmt, "_limit", None)
        return _Result(rows[:limit] if limit else rows)


@pytest.fixture
def subscribe(monkeypatch):
    monkeypatch.delenv("EVENTSTORE_WS_AUTH_REQUIRED", raising=False)
    monkeypatch.setattr(ws_router.connection_manager, "_redis_url", None)  # local fan-out only, no Redis

    def _subscribe(channel: str, wait: float = 5.0):
        """Subscribe to channel on the real route; return (the backlog's events in the order sent, the ledger)."""
        ledger = MemoryLedger(ROWS)
        monkeypatch.setattr(connection, "AsyncSessionLocal", ledger)
        app = FastAPI()
        app.include_router(ws_router.router)
        with TestClient(app) as client, client.websocket_connect("/ws/events") as ws:
            assert ws.receive_json()["type"] == "connected"
            ws.send_json({"action": "subscribe", "channel": channel})
            ledger.closed.wait(wait)  # the backlog is sent before the route closes its session
            ws.send_json({"action": "ping"})
            got = []
            while True:
                msg = ws.receive_json()
                if msg.get("type") == "pong":
                    break
                got.append(msg)
        assert {"type": "subscription_confirmed", "channel": channel} in got
        return [m["event"] for m in got if m.get("type") == "event"], ledger

    return _subscribe


def _ids(rows):
    return [str(r.id) for r in rows]


def test_an_agent_channel_is_sent_only_that_agents_last_events(subscribe):
    events, _ = subscribe(f"agent:{ALICE}")
    assert {e["aggregate_id"] for e in events} <= {ALICE}, "another agent's events in this agent's backlog"
    alice = [r for r in ROWS if r.aggregate_id == ALICE]
    assert [e["id"] for e in events] == _ids(alice[-15:]), "not this agent's last 15, oldest first"


def test_a_channel_with_no_events_is_sent_no_backlog(subscribe):
    events, ledger = subscribe("balance:updates", wait=1.0)
    assert events == []
    assert ledger.queries == 0


def test_events_all_is_still_sent_the_last_events_of_the_ledger(subscribe):
    events, _ = subscribe("events:all")
    assert [e["id"] for e in events] == _ids(ROWS[-15:])


def test_an_event_type_channel_is_still_sent_that_types_last_events(subscribe):
    events, _ = subscribe("events:ReputationChanged")
    assert [e["id"] for e in events] == _ids([r for r in ROWS if r.event_type == "ReputationChanged"][-15:])
