"""§COCKPITDESK (2026-10-15): GET /exchange/listings read five statements PER LISTING (875 for sbx-alpha's 175; the AGORA
desk asks every 30 s). listings_stats reads five for all of them, and builds each answer with the same _stats_from as
listing_stats (measured equal on sbx-alpha's 175 listings, 0 differences). Pinned here: the read count does not grow with
the listings, and a listing with no trade and no order answers what the single read answers. Since 2026-10-24 the last
print is one index probe per listing, never a sort of every trade (measured equal on sbx-alpha and sbx-beta)."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from agentvault_registry.services import exchange_service as svc


class _Rows:
    def all(self):
        return []


class _DB:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(str(stmt.compile(dialect=postgresql.dialect())))
        return _Rows()


def _listing(i, ipo_price=Decimal("2")):
    return SimpleNamespace(id=f"L{i}", ipo_price=ipo_price, total_shares=1000, ipo_float=100, ipo_sold=1)


def test_five_reads_whatever_the_listing_count():
    for n in (1, 3, 40):
        db = _DB()
        out = asyncio.run(svc.listings_stats(db, [_listing(i) for i in range(n)]))
        assert len(db.statements) == 5, (n, len(db.statements))
        assert sorted(out) == sorted(f"L{i}" for i in range(n))


def test_the_first_print_of_the_day_is_distinct_on_the_listing():
    # bounded by a day's trades, as the 24 h aggregate beside it is
    db = _DB()
    asyncio.run(svc.listings_stats(db, [_listing(0)]))
    distinct = [s for s in db.statements if "DISTINCT ON (exchange_trades.listing_id)" in s]
    assert len(distinct) == 1
    assert "ORDER BY exchange_trades.listing_id, exchange_trades.seq ASC" in distinct[0]
    assert "exchange_trades.created_at >=" in distinct[0]


def test_the_last_print_is_one_index_probe_per_listing_never_a_sort_of_every_trade():
    # 2026-10-24: a DISTINCT ON over every trade the listings ever printed (sbx-beta 274,836: an on-disk sort, 22 s under
    # load behind /my-agents). The probe orders by (listing_id, seq DESC) behind a RANGE on listing_id: an equality lets
    # the planner drop the column and walk the seq index backwards past every other listing's trades.
    db = _DB()
    asyncio.run(svc.last_prices(db, ["L0", "L1", "L0"]))
    assert len(db.statements) == 1
    sql = db.statements[0]
    assert "DISTINCT" not in sql
    assert "FROM (VALUES" in sql and sql.count("::VARCHAR)") == 2, "one row per listing asked, each once"
    assert "WHERE exchange_trades.listing_id BETWEEN asked.id AND asked.id" in sql
    assert "ORDER BY exchange_trades.listing_id, exchange_trades.seq DESC" in sql
    assert "LIMIT" in sql


class _Answer:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _AnsweringDB(_DB):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    async def execute(self, stmt):
        await super().execute(stmt)
        return _Answer(self.rows)


def test_a_listing_with_no_print_is_left_out_as_before():
    # the DISTINCT ON answered only listings with a trade; the probe answers every listing asked, NULL where none
    got = asyncio.run(svc.last_prices(_AnsweringDB([("L0", Decimal("3.5")), ("L1", None)]), ["L0", "L1"]))
    assert got == {"L0": Decimal("3.5")}


def test_a_quiet_listing_answers_what_the_single_read_answers():
    l = _listing(0)
    out = asyncio.run(svc.listings_stats(_DB(), [l]))["L0"]
    assert out == svc._stats_from(l, None, (0, 0, 0, None, None), None, None, None)
    assert out["last"] == "2" and out["volume_24h_qty"] == "0" and out["trades_24h"] == 0 and out["ipo_remaining"] == 99


def test_no_listing_no_read():
    db = _DB()
    assert asyncio.run(svc.listings_stats(db, [])) == {}
    assert db.statements == []
