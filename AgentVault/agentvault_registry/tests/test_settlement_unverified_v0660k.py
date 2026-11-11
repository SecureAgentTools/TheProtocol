"""V0660 (k), session-lead's review (the sessions' room seq 2452): an event store that cannot be read means "could not
verify", never a final verdict (CLAUDE.md, "COULD NOT VERIFY IS NOT INVALID").

The reconciliation read an unreadable store as "no slash found" and went on to decide: a settlement past its 24 hours
was marked EXPIRED, and with delivery off one no peer holds was ended NOT_DELIVERED, though the store that could have
shown a slash (which the reconciliation pays) was never read. Now a settlement whose store read did not answer is left
exactly as it was for the round: no expiry, no NOT_DELIVERED, no retry, no write. The round counts such settlements and
logs them once. Red on e621852f6.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agentvault_registry.tasks import settlement_reconciliation as R


class _Db:
    def __init__(self, pending=()):
        self.commits, self.pending = 0, list(pending)

    async def commit(self):
        self.commits += 1

    async def execute(self, stmt, params=None):
        rows = self.pending
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _settlement(sid="24ca7222", age_hours=1, msg="retry_count=1, last_retry=2026-11-08T05:20:00+00:00"):
    return SimpleNamespace(id=sid, dispute_id=94, status="PENDING_SLASH", error_message=msg, defendant_registry_url="",
                           origin_registry_url="http://sbx-beta-nginx-federation:8443", defendant_did="did:d",
                           requested_at=datetime.now(timezone.utc) - timedelta(hours=age_hours))


def _store_down(monkeypatch, how="unreadable"):
    seen = {"retries": []}

    async def down(_s):
        if how == "unreadable":
            raise R.EventStoreUnreadable("the event store answered 503")
        raise RuntimeError("an answer the finder could not read")

    async def retry(_db, _s, count):
        seen["retries"].append(count)

    monkeypatch.setattr(R, "find_slash_on_eventstore", down)
    monkeypatch.setattr(R, "_retry_slash_request", retry)
    return seen


@pytest.mark.parametrize("how", ["unreadable", "unexpected"])
@pytest.mark.parametrize("age_hours,delivery", [(25, "on"), (1, "off"), (25, "off")])
def test_a_store_that_cannot_be_read_leaves_the_settlement_as_it_was(monkeypatch, how, age_hours, delivery):
    # past its 24 hours it would EXPIRE; with delivery off and no peer holding it, it would end NOT_DELIVERED
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", delivery)
    monkeypatch.setenv("BILATERAL_PEER_URL", "https://sandbox-b.theprotocol.cloud:8443")
    seen = _store_down(monkeypatch, how)
    db, s = _Db(), _settlement(age_hours=age_hours)
    before = (s.status, s.error_message, s.defendant_registry_url)
    out = asyncio.run(R._reconcile_single_settlement(db, s))
    assert (s.status, s.error_message, s.defendant_registry_url) == before, "nothing is decided on a store not read"
    assert db.commits == 0 and seen["retries"] == []
    assert out == R.UNVERIFIED, "the round is told the settlement was not verified"


def test_the_round_counts_the_unverified_and_logs_them_once(monkeypatch, caplog):
    _store_down(monkeypatch)
    rows = [_settlement(sid=f"s{i}", age_hours=25) for i in range(3)]
    db = _Db(rows)

    class _Session:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *a):
            return False
    monkeypatch.setattr(R, "AsyncSessionLocal", lambda: _Session())
    with caplog.at_level(logging.DEBUG, logger=R.logger.name):
        out = asyncio.run(R.reconcile_pending_settlements())
    assert out == {"pending": 3, "failed": 0, "unverified": 3}
    assert all(r.status == "PENDING_SLASH" for r in rows) and db.commits == 0
    warns = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1 and "3" in warns[0] and "could not be read" in warns[0], warns


def test_control_a_store_that_answers_still_decides(monkeypatch):
    monkeypatch.setenv("CROSS_REGISTRY_SETTLEMENT_DELIVERY", "on")
    monkeypatch.setenv("BILATERAL_PEER_URL", "https://sandbox-b.theprotocol.cloud:8443")

    async def nothing(_s):
        return None
    monkeypatch.setattr(R, "find_slash_on_eventstore", nothing)
    s = _settlement(age_hours=25)
    asyncio.run(R._reconcile_single_settlement(_Db(), s))
    assert s.status == "EXPIRED"
