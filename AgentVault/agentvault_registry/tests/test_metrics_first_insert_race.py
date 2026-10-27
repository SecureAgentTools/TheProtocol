"""§MCPTEST30 (V0551): two first requests of a NEW agent may both find no agent_metrics row; the loser counts on the winner's.

process_metric selected the agent's AgentMetrics row and, finding none, inserted one. Two requests of a new agent arriving
together both found none and both inserted; the second met ix_agent_metrics_agent_id, its transaction rolled back (its
metric and its request log lost) and an ERROR with a traceback was logged: sbx-alpha 2026-10-02 16:55Z, twice, while a
membership gate's new agents voted (the roll's observe counted six tracebacks). The insert now runs in a savepoint and the
loser re-reads the winner's row. Driven here through the real function with a session double; the control is the path
with no race.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from agentvault_registry.middleware import metrics_collector as mc


class _Nested:
    def __init__(self, sess):
        self.sess = sess

    async def __aenter__(self):
        self.sess.savepoints += 1
        return self

    async def __aexit__(self, et, ev, tb):
        if et is not None:
            self.sess.savepoints_rolled_back += 1
        return False


class _Result:
    def __init__(self, v):
        self.v = v

    def scalar_one_or_none(self):
        return self.v

    def scalar_one(self):
        assert self.v is not None, "the re-read found no row"
        return self.v


class _Session:
    def __init__(self, race: bool):
        self.race, self.selects, self.added, self.commits = race, 0, [], 0
        self.savepoints = self.savepoints_rolled_back = 0
        self.winner = SimpleNamespace(total_requests=4, successful_requests=4, failed_requests=0,
                                      total_response_time_ms=40, last_request_at=None, last_updated=None)

    async def execute(self, stmt):
        if type(stmt).__name__ == "Select":
            self.selects += 1
            return _Result(self.winner if (self.race and self.selects > 1) else None)
        return _Result(None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        if self.race:
            raise IntegrityError("INSERT INTO agent_metrics", {}, Exception(
                'duplicate key value violates unique constraint "ix_agent_metrics_agent_id"'))

    def begin_nested(self):
        return _Nested(self)

    async def commit(self):
        self.commits += 1


def _run(race: bool) -> _Session:
    sess = _Session(race)

    @asynccontextmanager
    async def ctx():
        yield sess

    orig = mc.get_db_context
    mc.get_db_context = ctx
    try:
        asyncio.run(mc.process_metric({"agent_id": 7, "agent_did": "did:theprotocol:race", "endpoint": "/x",
                                       "method": "GET", "status_code": 200, "response_time_ms": 10,
                                       "timestamp": datetime.now(timezone.utc)}))
    finally:
        mc.get_db_context = orig
    return sess


def test_the_loser_of_the_first_insert_counts_on_the_winners_row():
    sess = _run(race=True)
    assert sess.savepoints == 1 and sess.savepoints_rolled_back == 1, "the insert ran in a savepoint that rolled back"
    assert sess.selects == 2, "the loser re-read the row"
    assert sess.winner.total_requests == 5 and sess.winner.successful_requests == 5
    assert any(type(o).__name__ == "AgentRequest" for o in sess.added), "its request log is kept"
    assert sess.commits == 1


def test_control_with_no_race_the_new_row_is_used():
    sess = _run(race=False)
    assert sess.savepoints == 1 and sess.savepoints_rolled_back == 0 and sess.selects == 1
    rows = [o for o in sess.added if type(o).__name__ == "AgentMetrics"]
    assert len(rows) == 1 and rows[0].total_requests == 1
    assert sess.winner.total_requests == 4, "the other agent's row is untouched"
    assert sess.commits == 1
