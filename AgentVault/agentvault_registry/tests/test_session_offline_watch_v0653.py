"""V0653: org.session_offline, a session went quiet (session-lead, the sessions' room seq 716; his approval of the missing
notices, sessionlogs2026/NOTIFICATION_GAPS_2026-10-31.md).

When an organization's agent's status line lapses and is not renewed, its owner hears it once, in the app. The sweep
(background_tasks/session_offline_watch.py) over real SQLite rows; only Redis (a set with NX) and the notifier are
replaced. BASE: on a5ef48ddd (V0652) the module does not exist, nothing tells anyone, and the catalog declares the type
without an emitter.
"""
from __future__ import annotations

import datetime as dt

import pytest

from agentvault_registry import models
from agentvault_registry.background_tasks import session_offline_watch as W
from tests._sqlite_db import sqlite_db


T0 = dt.datetime(2026, 11, 1, 21, 0, 0, tzinfo=dt.timezone.utc)
DID = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-00000000rel0"
DID2 = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-00000000test"
ORG = "org-sessions"


class Redis:
    def __init__(self):
        self.keys = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


def _db(lines, *, org=ORG, status="active", room=True):
    db = sqlite_db(models.Developer, models.Agent, models.AgentCard, models.AgentStatusLine, models.Conversation)
    s = db.sync
    s.add(models.Developer(id=6, name="maintainer", email="m@example.org", hashed_password="x"))
    for i, did in enumerate((DID, DID2), start=1):
        s.add(models.Agent(id=i, did=did, client_id=f"c{i}", hashed_client_secret="x", creator_developer_id=6,
                           status=status, organization_id=org))
    s.add(models.AgentCard(agent_did=DID, name="session-release", developer_id=6, card_data={}, is_active=True))
    if room:
        s.add(models.Conversation(id="room-1", kind="org", org_id=ORG, created_by_ptype="developer", created_by_id="6",
                                  last_seq=10))
    for did, text, expires in lines:
        s.add(models.AgentStatusLine(agent_did=did, status_text=text, set_at=expires - dt.timedelta(hours=1),
                                     expires_at=expires))
    s.commit()
    return db


class Told:
    def __init__(self):
        self.calls = []

    async def __call__(self, type_key, devs, **kw):
        self.calls.append((type_key, list(devs), kw))
        return len(devs)


@pytest.mark.asyncio
async def test_a_line_that_lapsed_tells_its_owner_once():
    db = _db([(DID, "building (al)", T0 - dt.timedelta(minutes=2))])
    told, redis = Told(), Redis()
    assert await W.sweep_once(db, redis, now=T0, notify=told) == 1
    (type_key, devs, kw), = told.calls
    assert type_key == "org.session_offline" and devs == [6]
    assert kw["title"] == "session-release went quiet"
    assert "20:58Z" in kw["message"] and "“building (al)”" in kw["message"]
    assert kw["click"] == "/ui#/pocket/ourchat/room-1"
    assert await W.sweep_once(db, redis, now=T0 + dt.timedelta(minutes=1), notify=told) == 0   # once per lapse
    assert len(told.calls) == 1


@pytest.mark.asyncio
async def test_a_live_line_an_old_lapse_and_a_line_without_an_organization_tell_nobody():
    told = Told()
    live = _db([(DID, "proof running", T0 + dt.timedelta(minutes=5))])
    assert await W.sweep_once(live, Redis(), now=T0, notify=told) == 0
    old = _db([(DID, "went home", T0 - dt.timedelta(seconds=W.WINDOW_S + 60))])   # lapsed while nothing watched
    assert await W.sweep_once(old, Redis(), now=T0, notify=told) == 0
    loose = _db([(DID, "on my own", T0 - dt.timedelta(minutes=2))], org=None)
    assert await W.sweep_once(loose, Redis(), now=T0, notify=told) == 0
    gone = _db([(DID, "suspended", T0 - dt.timedelta(minutes=2))], status="suspended")
    assert await W.sweep_once(gone, Redis(), now=T0, notify=told) == 0
    assert told.calls == []


@pytest.mark.asyncio
async def test_without_redis_nobody_is_told_rather_than_told_twice():
    db = _db([(DID, "building (al)", T0 - dt.timedelta(minutes=2))])
    told = Told()
    assert await W.sweep_once(db, None, now=T0, notify=told) == 0 and told.calls == []


@pytest.mark.asyncio
async def test_a_renewed_line_that_lapses_again_is_a_new_lapse():
    db = _db([(DID, "building (al)", T0 - dt.timedelta(minutes=2))])
    told, redis = Told(), Redis()
    assert await W.sweep_once(db, redis, now=T0, notify=told) == 1
    row = db.sync.get(models.AgentStatusLine, DID)
    row.expires_at = T0 + dt.timedelta(minutes=30)        # the session came back and set a line again
    db.sync.commit()
    assert await W.sweep_once(db, redis, now=T0 + dt.timedelta(minutes=29), notify=told) == 0
    assert await W.sweep_once(db, redis, now=T0 + dt.timedelta(minutes=31), notify=told) == 1
    assert len(told.calls) == 2


@pytest.mark.asyncio
async def test_two_sessions_two_notices_and_an_unnamed_agent_reads_by_its_did_tail():
    db = _db([(DID, "building (al)", T0 - dt.timedelta(minutes=3)), (DID2, "pair proof", T0 - dt.timedelta(minutes=1))],
             room=False)
    told = Told()
    assert await W.sweep_once(db, Redis(), now=T0, notify=told) == 2
    titles = [kw["title"] for _t, _d, kw in told.calls]
    assert titles == ["session-release went quiet", "agent …0000test went quiet"]   # oldest lapse first
    assert all(kw["click"] == "/ui#/pocket/ourchat" for _t, _d, kw in told.calls)   # no room: the list


def test_the_catalog_says_it_fires():
    from agentvault_registry.services import notification_catalog as nc
    assert nc.get_type("org.session_offline").emitter is True
    assert nc.get_type("chat.progress_finished").emitter is True
