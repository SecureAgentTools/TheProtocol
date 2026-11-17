"""V0667 follow-up (order gwo_751fa90f40e6eb499867e604, session-volume; found staging journal 55's figures on sbx-alpha): a passed content change is APPLIED ONCE, so its record's
`before` is what the space held before it and the one-step undo gives that back.

The defect: an applied change's `before` equalled its `after`, so "Undo this change" restored nothing. Every write of the store announces the change's room card, and the card's
refresh READS the change through the same flow (`view`), whose sync closes a passed ballot and applies it. The request that cast the closing vote and that refresh both saw a
ballot that had passed and was still `balloting`, both applied, and the second apply read the first one's value as its `before` and wrote it last.

Here the closing state is made on purpose (every decider has voted, nothing has closed it) and two readers look at the change at once, as the request and the card refresh do; the
apply is slowed so the second reader is certain to arrive while the first is writing. Skipped unless CODE_DISTRIBUTIONS_TEST_DB names a throwaway database it may WIPE.
"""
from __future__ import annotations

import asyncio
import os

import pytest

if not os.environ.get("CODE_DISTRIBUTIONS_TEST_DB"):         # this file's own skip: importing the module below would raise ITS skip, and CI counts skips by the file that raised them
    pytest.skip("needs a REAL Postgres database it may WIPE: set CODE_DISTRIBUTIONS_TEST_DB. Skipped, never silently passed.", allow_module_level=True)

from tests.test_content_changes_v0667_db import deciders_vote_for, propose, settings, world  # noqa: E402,F401  (world is the fixture)

from agentvault_registry.services import content_changes as cc  # noqa: E402


async def _passed_but_not_closed(w, value):
    """A policy value whose key already holds 7 days, proposed for `value`, every decider's vote on file, and nothing yet closing the ballot."""
    from sqlalchemy import text
    async with w.maker() as s:
        await s.execute(text("UPDATE organizations SET settings = CAST(:v AS JSON) WHERE id = :o"), {"v": '{"contract_offer_ttl_days": 7}', "o": w.org})
        await s.commit()
    r = await propose(w, "policy_value", "contract_offer_ttl_days", {"value": value})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    async with w.maker() as s:                      # the votes go straight to the store: no vote route runs the sync that would close the ballot
        store = cc.DbStore(s)
        for dev in (d for _name, d in [(n, w.devs[n]) for n, _v in await deciders_vote_for(w)]):
            await store.add_vote({"content_change_id": cid, "developer_id": dev, "vote": True, "agent_did": f"did:a:{dev}", "cast_at": store.now()})
    return cid


async def test_two_readers_of_a_passed_ballot_apply_it_once_and_the_record_keeps_what_it_replaced(world, monkeypatch):
    w = world
    cid = await _passed_but_not_closed(w, 14)
    calls = []
    real = cc.DbStore.apply

    async def slow_apply(self, *a, **k):
        calls.append(1)
        await asyncio.sleep(0.4)                    # the second reader arrives while the first is still writing
        return await real(self, *a, **k)

    monkeypatch.setattr(cc.DbStore, "apply", slow_apply)
    first, second = await asyncio.gather(w.call("GET", f"/api/v1/content-changes/{cid}"), w.call("GET", f"/api/v1/content-changes/{cid}"))
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert len(calls) == 1, f"the passed change was applied {len(calls)} times"
    rec = (await w.call("GET", f"/api/v1/content-changes/{cid}")).json()
    assert rec["state"] == "applied"
    assert rec["before"] == {"value": 7} and rec["after"] == {"value": 14}, (rec["before"], rec["after"])
    assert (await settings(w))["contract_offer_ttl_days"] == 14


async def test_the_undo_of_a_change_two_readers_closed_gives_back_what_it_replaced(world, monkeypatch):
    w = world
    cid = await _passed_but_not_closed(w, 14)
    real = cc.DbStore.apply

    async def slow_apply(self, *a, **k):
        await asyncio.sleep(0.4)
        return await real(self, *a, **k)

    monkeypatch.setattr(cc.DbStore, "apply", slow_apply)
    await asyncio.gather(w.call("GET", f"/api/v1/content-changes/{cid}"), w.call("GET", f"/api/v1/content-changes/{cid}"))
    u = await w.call("POST", f"/api/v1/content-changes/{cid}/undo", {"reason": "back"}, as_="owner")
    assert u.status_code == 200 and u.json()["state"] == "undone", u.text
    assert (await settings(w))["contract_offer_ttl_days"] == 7, "the undo restored what the change had replaced, not its own value"


async def test_a_claim_nobody_finished_is_taken_over_after_it_goes_stale(world, monkeypatch):
    """A reader that died between its claim and its record must not leave the passed change unapplied for ever."""
    from datetime import timedelta
    w = world
    cid = await _passed_but_not_closed(w, 14)
    async with w.maker() as s:
        store = cc.DbStore(s)
        won = await store.claim_apply(cid, {"status": "PASSED"}, store.now(), timedelta(seconds=120))
        assert won is True
        assert await store.claim_apply(cid, {"status": "PASSED"}, store.now(), timedelta(seconds=120)) is False, "a fresh claim is not taken over"
        late = store.now() + timedelta(seconds=121)
        assert await store.claim_apply(cid, {"status": "PASSED"}, late, timedelta(seconds=120)) is True, "a claim older than the window is"
