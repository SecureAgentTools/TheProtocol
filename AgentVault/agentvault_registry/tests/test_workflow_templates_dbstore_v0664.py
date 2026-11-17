"""V0664 "Migrate a system", M4 (order gwo_e97a483512cfaf2151f17b7a): services/workflow_templates.DbStore's own SQL,
executed (on SQLite through a small adapter: the statements are plain SQL, and executing them is the only check that
sees a wrong join or a status the query forgets; the migration test pins the same columns on the Postgres side).

  counts     instantiations and certified count DISTINCT DEVELOPERS (the agents' creator), so one developer with many
             agents counts once (session-lead, room seq 3873: "certified by N developers"); an agent this registry
             does not know counts as itself; kit downloads count every download
  purchases  a purchase is recorded pending before its deposit (price, share, currency, the two payees) and becomes
             done after its payouts; only a done purchase is a purchase (the files right, a developer's buyer); done
             flips once (one event); a clean decline withdraws a pending record and never a done one; a purchase
             finished after its record was withdrawn by a concurrent attempt is written back done
Red on 26533115d: the counts are per agent and the store has no recorded purchase.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import pathlib
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

try:
    from agentvault_registry.services import workflow_templates as wt
except ImportError:
    wt = None

pytestmark = pytest.mark.skipif(wt is None, reason="the module does not exist")

ALEMBIC = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
T0 = dt.datetime(2026, 11, 14, 16, tzinfo=dt.timezone.utc)

DDL = (
    "CREATE TABLE agents (did TEXT PRIMARY KEY, creator_developer_id INTEGER, organization_id TEXT)",
    "CREATE TABLE workflow_templates (id TEXT PRIMARY KEY, forked_from_template_id TEXT)",
    "CREATE TABLE workflow_template_uses (id INTEGER PRIMARY KEY AUTOINCREMENT, template_id TEXT NOT NULL, "
    "version INTEGER, agent_did TEXT, kind TEXT NOT NULL, reference TEXT, at TIMESTAMP)",
    "CREATE UNIQUE INDEX uq_wtpl_uses_certified ON workflow_template_uses (template_id, agent_did) "
    "WHERE kind = 'certified'",
    "CREATE TABLE workflow_template_purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, template_id TEXT NOT NULL, "
    "buyer_did TEXT NOT NULL, price NUMERIC NOT NULL, share NUMERIC NOT NULL DEFAULT 0, currency TEXT, "
    "author_did TEXT NOT NULL, parent_did TEXT, status TEXT NOT NULL DEFAULT 'pending', created_at TIMESTAMP, "
    "done_at TIMESTAMP, UNIQUE (template_id, buyer_did))",
)
PURCHASE_COLUMNS = ("price", "share", "currency", "author_did", "parent_did", "status", "done_at")


class SqliteDb:
    """The two calls DbStore makes on its session (execute, commit), on a synchronous SQLite connection."""

    def __init__(self) -> None:
        self.conn = create_engine("sqlite://").connect()
        for stmt in DDL:
            self.conn.execute(text(stmt))
        self.conn.commit()

    async def execute(self, stmt, params=None):
        # sqlite3 binds no Decimal (asyncpg does): its text, as the NUMERIC column stores it
        return self.conn.execute(stmt, {k: str(v) if isinstance(v, Decimal) else v for k, v in (params or {}).items()})

    async def commit(self):
        self.conn.commit()

    def rows(self, sql, **params):
        return [dict(r) for r in self.conn.execute(text(sql), params).mappings().all()]


def run(c):
    return asyncio.run(c)


def store():
    db = SqliteDb()
    db.conn.execute(text("INSERT INTO workflow_templates (id) VALUES ('wtpl_a')"))
    for did, dev in (("did:a:one", 7), ("did:a:two", 7), ("did:a:three", 8)):
        db.conn.execute(text("INSERT INTO agents (did, creator_developer_id) VALUES (:d, :v)"), {"d": did, "v": dev})
    db.conn.commit()
    return wt.DbStore(db), db


def use(s, did, kind, ref=None):
    run(s.add_use({"template_id": "wtpl_a", "version": 1, "agent_did": did, "kind": kind, "reference": ref, "at": T0}))


def test_the_counts_are_distinct_developers_not_agents():
    s, _ = store()
    for did in ("did:a:one", "did:a:two", "did:a:one", "did:a:three"):
        use(s, did, "instantiate")
        use(s, did, "kit")
    for did in ("did:a:one", "did:a:two"):
        use(s, did, "certified", ref=f"att-{did}")
    counts = run(s.counts("wtpl_a"))
    assert int(counts["instantiations"]) == 2, "developer 7's two agents count once, developer 8 once"
    assert int(counts["certified"]) == 1, "certified by 1 developer"
    assert int(counts["kit_downloads"]) == 4, "every download counts"
    use(s, "did:far:unknown", "certified", ref="att-far")
    assert int(run(s.counts("wtpl_a"))["certified"]) == 2, "an agent with no row here counts as itself"


def test_the_listing_query_carries_the_same_counts():
    s, db = store()
    db.conn.execute(text("ALTER TABLE workflow_templates ADD COLUMN visibility TEXT DEFAULT 'public'"))
    db.conn.execute(text("ALTER TABLE workflow_templates ADD COLUMN created_at TIMESTAMP"))
    db.conn.commit()
    for did in ("did:a:one", "did:a:two"):
        use(s, did, "instantiate")
    rows = run(s.list_public({}))
    assert [int(r["instantiations"]) for r in rows] == [1]


def _pending(**over):
    return {"template_id": "wtpl_a", "buyer_did": "did:a:three", "price": Decimal("10"), "share": Decimal("2"),
            "currency": "ECU", "author_did": "did:a:one", "parent_did": "did:a:parent", "at": T0, **over}


def test_a_recorded_purchase_is_pending_until_finished_and_only_a_done_one_counts():
    s, db = store()
    run(s.insert_pending_purchase(_pending()))
    row = run(s.purchase_row("wtpl_a", "did:a:three"))
    assert row["status"] == "pending" and Decimal(str(row["price"])) == 10 and Decimal(str(row["share"])) == 2
    assert (row["author_did"], row["parent_did"], row["currency"]) == ("did:a:one", "did:a:parent", "ECU")
    assert run(s.purchased("wtpl_a", "did:a:three")) is False and run(s.developer_bought(8, "wtpl_a")) is False
    run(s.insert_pending_purchase(_pending(price=Decimal("20"))))      # a second first attempt keeps the first record
    assert Decimal(str(run(s.purchase_row("wtpl_a", "did:a:three"))["price"])) == 10
    assert run(s.finish_purchase(row, T0)) is True
    assert run(s.finish_purchase(row, T0)) is False, "done flips once"
    assert run(s.purchased("wtpl_a", "did:a:three")) is True and run(s.developer_bought(8, "wtpl_a")) is True
    run(s.withdraw_pending_purchase("wtpl_a", "did:a:three"))
    assert run(s.purchase_row("wtpl_a", "did:a:three"))["status"] == "done", "a done purchase is never withdrawn"


def test_a_withdrawn_record_is_gone_and_a_finish_after_it_writes_the_purchase_back_done():
    s, db = store()
    run(s.insert_pending_purchase(_pending()))
    row = run(s.purchase_row("wtpl_a", "did:a:three"))
    run(s.withdraw_pending_purchase("wtpl_a", "did:a:three"))
    assert run(s.purchase_row("wtpl_a", "did:a:three")) is None
    assert run(s.finish_purchase(row, T0)) is True
    back = run(s.purchase_row("wtpl_a", "did:a:three"))
    assert back["status"] == "done" and Decimal(str(back["price"])) == 10


def test_the_migration_carries_the_recorded_purchase():
    mig = (ALEMBIC / "0228_workflow_templates.py").read_text()
    start = mig.index('"workflow_template_purchases"')
    block = mig[start:mig.index("op.create_table", start)]
    for col in PURCHASE_COLUMNS:
        assert f'sa.Column("{col}"' in block, col
    assert "status IN ('pending', 'done')" in block and "uq_wtpl_purchase" in block
