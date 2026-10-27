"""§DIRFEED-2: GET /discover pages on ONE total order (the nightly pair nt261011, 2026-10-11).

The MCP tool discoverAgents reads GET /api/v1/discover (routers/agent_discovery.py), not the console's
/agent-cards/discover, whose sorts V0585 gave a unique tiebreak (test_discover_pages_break_ties.py). This route had no
ORDER BY at all: LIMIT/OFFSET pages were whatever order each plan produced, and the MCP tester's `pagination:
discoverAgents` row read two pages of 3 that were not a partition of one page of 6 (one row on neither, one from outside
it). Pinned by compiling the STATEMENT, never by paging a fixture (a few rows in insertion order page cleanly with or
without an ORDER BY); the control proves the check can fail.
"""
from sqlalchemy.dialects import postgresql

from agentvault_registry.routers.agent_discovery import discover_statement

ORDER = "ORDER BY agents.id DESC, agent_cards.id DESC"


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_the_discover_page_is_cut_from_one_total_order():
    sql = _sql(discover_statement("did:").limit(3).offset(3))
    assert ORDER in sql
    assert sql.index(ORDER) < sql.index("LIMIT")


def test_the_order_is_the_statements_own_and_survives_the_search_term():
    for q in ("did:", "abc", "100%_off"):
        assert _sql(discover_statement(q)).count("ORDER BY") == 1


class _Result:   # an empty answer in every shape the route reads
    def all(self):
        return []

    def scalar(self):
        return 0

    def scalars(self):
        return self

    def mappings(self):
        return self

    def first(self):
        return None


class _DB:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        return _Result()


def test_the_route_cuts_its_page_from_the_ordered_statement():
    # the ROUTE, not only its builder: a gate that never calls the rail cannot see what the rail runs (§DISCECHO)
    import asyncio
    from agentvault_registry.routers.agent_discovery import discover_agents
    db = _DB()
    out = asyncio.run(discover_agents(query="did:", registry_id=None, limit=3, offset=3, db=db, current_developer=None))
    page = _sql(db.statements[0])
    assert ORDER in page and page.index(ORDER) < page.index("LIMIT")
    assert isinstance(out, dict)


def test_the_check_can_fail():
    # the statement as V0593 shipped it: no ORDER BY at all
    assert ORDER not in _sql(discover_statement("did:").order_by(None).limit(3).offset(3))
