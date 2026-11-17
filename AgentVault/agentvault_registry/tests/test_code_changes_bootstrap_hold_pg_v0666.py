"""V0666 (order gwo_b4ab7b9b7b3595d6dad05e6b; session-lead, room seq 4639): THE BOOTSTRAP RULE THROUGH THE REAL STORE, ON POSTGRES.

The rule's suite passed on a fake store that carried tally_quorum_met itself, while the real DbStore never returned it, so on a
real registry every go answered rejected_by_vote. This proof runs the flow through DbStore on a real PostgreSQL database (every
table from the models), end to end:

  hold    a bounty change, delivered through its Guild order, takes the checker's signed acceptance, a member's review and its
          ballot (a real governance proposal); the tally fails it for lack of quorum; the code-change sweep holds the bounty and
          the Guild reaper's 7-day submitted sweep leaves the order alone; the maintainer's go passes the change (real member
          count, real quorum field); the merge, with the checker's signed release_line record, settles the order to the worker
  return  the same change whose tally was more than the hold ago: the sweep returns the bounty to the poster, and a go answers
          bounty_returned

The Guild's money primitives (the escrow payout, the royalty payout, the stakes, the reputation fold, the credential, the
events, the notices) are replaced by recorders, as tests/test_guild_settle_return_helpers_v0663.py does: no TEG is called.
Everything else is the registry's own code and SQL. Runs where CODE_CHANGES_TEST_DB names a throwaway database
(postgresql+asyncpg://..., its name starting with test_: the test recreates its public schema), as the other *_TEST_DB proofs
do; skipped, saying why, where not.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid
from decimal import Decimal
from urllib.parse import urlparse

import pytest

from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import (   # noqa: F401 (the autouse fixture sets the maintainer, the release line, the key)
    CHECK_SCHEMA, CONSOLE, REPO, SHA, _maintainer_and_release_line, sign_record)

PG = os.environ.get("CODE_CHANGES_TEST_DB", "")
if not PG:
    pytest.skip("needs a REAL Postgres it may wipe: set CODE_CHANGES_TEST_DB (a database whose name starts with test_). Skipped, "
                "never silently passed.", allow_module_level=True)

ADMIN = {"developer_id": 99, "admin": True}
PROPOSER = {"did": "did:a:proposer", "developer_id": 1}
RELEASE = "v0663/cut"


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _stamp(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _fresh_schema(conn):
    """An empty public schema (the models' foreign keys hold a cycle that drop_all cannot order)."""
    from sqlalchemy import text
    await conn.execute(text("DROP SCHEMA public CASCADE"))
    await conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture()
async def db(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from agentvault_registry import models
    name = urlparse(PG).path.lstrip("/")
    assert name.startswith("test_"), f"refusing to drop the tables of {name!r}: name a database whose name starts with test_"
    monkeypatch.setenv("GOVERNANCE_WEIGHT_MODE", "member")
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "false")     # members without a bond: a starter frame
    monkeypatch.setenv("CODE_CHANGES_BOOTSTRAP_MEMBERS", "10")
    monkeypatch.delenv("CODE_CHANGES_BOOTSTRAP_HOLD_HOURS", raising=False)
    engine = create_async_engine(PG)
    async with engine.begin() as c:
        await _fresh_schema(c)
        await c.run_sync(models.Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        then = _now() - dt.timedelta(days=60)
        for dev_id, name_, admin in ((1, "Proposer", False), (2, "Worker", False), (7, "Reviewer", False), (99, "Maintainer", True)):
            s.add(models.Developer(id=dev_id, name=name_, email=f"dev{dev_id}@example.invalid", hashed_password="x",
                                   is_verified=True, profile_visibility="public", admin_treasury=False, admin_support=False,
                                   admin_enforcement=False, admin_federation=False, admin_platform=admin,
                                   agents_unlisted_by_default=False, is_suspended=False, provisioning_months_total=0,
                                   created_at=then, updated_at=then))
        await s.flush()
        for did, dev_id in (("did:a:proposer", 1), ("did:a:worker", 2), ("did:a:r7", 7), ("did:a:m99", 99)):
            s.add(models.Agent(did=did, client_id=f"c-{dev_id}", hashed_client_secret="x", creator_developer_id=dev_id,
                               status="active", created_at=then, enforcement_status="active", reputation_bond_status="none",
                               mtls_enabled=False, is_canary=False, bears_corner_flare=False, bears_encirclement_flare=False))
        await s.commit()
        yield s
    async with engine.begin() as c:
        await _fresh_schema(c)
    await engine.dispose()


@pytest.fixture()
def money(monkeypatch):
    """The Guild's money primitives, recorded (no TEG). The order's own rows, claims and audit events are the real SQL."""
    from agentvault_registry.routers import guild as G
    log = []

    async def payout(db, payee, amount, oid):
        log.append(("payout", payee, str(amount), oid))

    async def escrow_payout(db, to_did, amount, oid, kind):
        log.append(("escrow", to_did, str(amount), oid, kind))

    async def nothing(*a, **k):
        return None

    async def credential(*a, **k):
        return None

    monkeypatch.setattr(G, "_payout_with_royalty", payout)
    monkeypatch.setattr(G.guild_escrow, "escrow_payout", escrow_payout)
    monkeypatch.setattr(G, "_resolve_worker_stake", nothing)
    monkeypatch.setattr(G, "_refund_all_stakes", nothing)
    monkeypatch.setattr(G.guild_reputation, "fold_work_reputation", nothing)
    monkeypatch.setattr(G.guild_reputation, "issue_work_credential", credential)
    monkeypatch.setattr(G.guild_contract_mirror, "sync_from_order", nothing)
    monkeypatch.setattr(G, "_tr_touch", nothing)
    monkeypatch.setattr(G, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(G, "_guild_webhook", lambda *a, **k: None)
    monkeypatch.setattr(G, "_notify_owners", lambda *a, **k: None)
    return log


async def _order_status(db, oid):
    from sqlalchemy import text
    return (await db.execute(text("SELECT status FROM guild_work_orders WHERE id = :o"), {"o": oid})).scalar_one()


async def _balloted_failed_for_quorum(db, *, tallied_ago: dt.timedelta) -> tuple:
    """A bounty change delivered through its order, accepted on the checker's signed record, reviewed by a member and balloted
    through the real store; then the tally fails it for lack of quorum, `tallied_ago` ago."""
    from sqlalchemy import text
    from agentvault_registry import models
    store = cc.DbStore(db)
    flow = cc.CodeChangeFlow(store)
    oid, cid = f"gwo_{uuid.uuid4().hex[:24]}", f"cc_{uuid.uuid4().hex[:20]}"
    db.add(models.GuildWorkOrder(id=oid, poster_did="did:a:proposer", title="A clearer order page", bounty=Decimal("10"),
                                 currency="SBXA", status="submitted", worker_did="did:a:worker",
                                 deliverable={"commits": [{"repo": REPO, "commit": SHA}]},
                                 submitted_at=_now() - dt.timedelta(days=8)))
    db.add(models.CodeChange(id=cid, repository=REPO, paths=[CONSOLE + "views/GuildBoard.vue"], title="A clearer order page",
                             problem="The order page hides who is paid.", mode="bounty", order_id=oid,
                             proposer_did="did:a:proposer", proposer_developer_id=1, sensitive=False, state="proposed"))
    await db.commit()
    rec = sign_record({"schema": CHECK_SCHEMA, "kind": "acceptance", "repository": REPO, "change_id": cid, "commit": SHA,
                       "issued_at": _stamp(_now() - dt.timedelta(minutes=5)), "ci_state": "success", "base": RELEASE,
                       "touched": [CONSOLE + "views/GuildBoard.vue"], "secret_findings": 0, "secret_paths": [],
                       "too_many_touched": False})
    assert (await flow.record_acceptance(ADMIN, cid, {"signed": rec}))["state"] == "accepted"
    await flow.review({"developer_id": 7}, cid, {"verdict": "approve", "commit": SHA, "findings": "read the diff"})
    out = await flow.open_ballot(PROPOSER, cid)
    assert out["state"] == "balloting"
    pid = out["proposal_id"]
    await db.execute(text("UPDATE governance_proposals SET status = 'FAILED', tally_quorum_met = false, tallied_at = :t "
                          "WHERE id = :p"), {"t": _now() - tallied_ago, "p": pid})
    await db.commit()
    assert (await flow.view(cid))["state"] == "failed"
    return flow, store, cid, oid


async def test_on_postgres_a_quorum_only_failure_holds_the_bounty_the_go_passes_it_and_the_merge_pays_the_worker(db, money):
    from agentvault_registry.background_tasks import guild_order_reaper
    flow, store, cid, oid = await _balloted_failed_for_quorum(db, tallied_ago=dt.timedelta(hours=1))
    assert await store.real_member_count() == 4                               # proposer, worker, reviewer, maintainer: fewer than 10
    assert (await store.proposal((await store.get(cid))["proposal_id"]))["tally_quorum_met"] is False
    await cc.sweep_ended(store)
    assert await _order_status(db, oid) == "submitted"                       # held, not returned
    await guild_order_reaper._sweep_abandoned_submitted(db)                    # submitted 8 days ago, past the 7-day timeout
    assert await _order_status(db, oid) == "submitted"                       # the reaper leaves a failed change's order alone
    view = await flow.view(cid)
    assert view["bounty_hold_until"] is not None
    out = await flow.go(ADMIN, cid)
    assert out["state"] == "passed" and out["bootstrap"]["members"] == 4
    signed = sign_record({"schema": CHECK_SCHEMA, "kind": "release_line", "repository": REPO, "change_id": cid, "commit": SHA,
                          "issued_at": _stamp(_now()), "branch": RELEASE, "contains": True})
    out = await flow.record_merge(ADMIN, cid, {"commit": SHA, "into": RELEASE, "signed": signed})
    assert out["state"] == "merged"
    assert await _order_status(db, oid) == "settled", "the worker's merged work was not paid"
    assert [e for e in money if e[0] == "payout"] and money[[e[0] for e in money].index("payout")][1] == "did:a:worker"
    assert not [e for e in money if e[0] == "escrow" and e[4] == "refund"]   # nothing went back to the poster


async def test_on_postgres_after_the_hold_the_sweep_returns_the_bounty_and_the_go_refuses(db, money):
    flow, store, cid, oid = await _balloted_failed_for_quorum(db, tallied_ago=dt.timedelta(hours=73))
    assert (await flow.view(cid))["bounty_hold_until"] is None
    await cc.sweep_ended(store)
    assert await _order_status(db, oid) == "cancelled"
    assert ("escrow", "did:a:proposer", "10.0000000000", oid, "refund") in money
    with pytest.raises(cc.CodeChangeRefusal) as e:
        await flow.go(ADMIN, cid)
    assert (e.value.status, e.value.code) == (409, "bounty_returned")
