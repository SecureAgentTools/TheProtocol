"""§COCKPITDESK (2026-10-15): the dispute list is a partition when paged. created_at alone is not unique; the id breaks a
tie, so the console's counting walk (limit 100, offset 0, 100, ...) sees every dispute once. Pinned by compiling the
statement: a fixture with distinct timestamps passes with or without the tiebreak (§DIRFEED-2)."""
from sqlalchemy.dialects import postgresql

from agentvault_registry.crud.crud_disputes import all_disputes_stmt


def _sql(**kw):
    return str(all_disputes_stmt(**kw).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_newest_first_with_the_id_breaking_a_tie():
    assert "ORDER BY disputes.created_at DESC, disputes.id DESC" in _sql(limit=100, offset=200)


def test_the_page_and_the_filters_still_apply():
    sql = _sql(status_filter="OPEN", defendant_did="did:x", limit=50, offset=100)
    assert "LIMIT 50" in sql and "OFFSET 100" in sql
    assert "disputes.status = 'OPEN'" in sql and "disputes.defendant_did = 'did:x'" in sql
