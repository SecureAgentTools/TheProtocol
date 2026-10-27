"""§FESUITE: the support ticket lists page on a unique order (CLAUDE.md §DIRFEED-2).

`updated_at` alone is not unique, so LIMIT/OFFSET pages over it are not a partition: two tickets touched in one instant
can show twice or never. Pinned by compiling the statement, never by paging a fixture (three rows with distinct
timestamps pass with or without the tiebreak).
"""
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from agentvault_registry import models
from agentvault_registry.routers import support


def test_ticket_pages_break_ties_on_the_id():
    sql = str(select(models.SupportTicket).order_by(*support.TICKET_PAGE_ORDER).compile(dialect=postgresql.dialect()))
    assert "ORDER BY support_tickets.updated_at DESC, support_tickets.id DESC" in sql


def test_both_ticket_lists_use_the_page_order():
    import inspect
    src = inspect.getsource(support)
    assert src.count(".order_by(*TICKET_PAGE_ORDER)") == 2
    assert ".order_by(models.SupportTicket.updated_at.desc())" not in src
