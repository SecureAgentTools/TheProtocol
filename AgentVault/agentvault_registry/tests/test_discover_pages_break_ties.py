"""§DIRFEED-2: every discover sort pages on a unique order (the nightly pair nt261008, 2026-10-08).

The discover sorts ended on `created_at` or a score, and none of those is unique: a fresh frame's agents tie on all of
them (one transaction stamps a whole seed with one `created_at`), so LIMIT/OFFSET pages over the tie are not a
partition. The MCP tester's `pagination: discoverAgents` row measured it on the first nightly pair that ran the current
image: two pages of 3 held two rows its page of 6 did not, and missed two it did. Pinned on the SQL text, never by paging
a fixture (rows with distinct timestamps pass with or without the tiebreak); the control proves the check can fail.
"""
import inspect

from agentvault_registry.routers import agent_cards

TIEBREAK = ", id DESC"


def _breaks_ties(order_by: str) -> bool:
    return order_by.rstrip().endswith(TIEBREAK)


def test_every_named_sort_ends_on_the_card_id():
    assert set(agent_cards._DISCOVER_SORTS) == {"relevance", "newest", "reputation", "price_low", "price_high"}
    for name, sql in agent_cards._DISCOVER_SORTS.items():
        assert _breaks_ties(sql), name


def test_the_query_ranking_ends_on_the_card_id():
    assert _breaks_ties(agent_cards._DISCOVER_SORT_RELEVANCE_Q)


def test_the_proven_ranking_ends_on_the_card_id():
    src = inspect.getsource(agent_cards.discover_agent_cards)
    assert '"is_live DESC, COALESCE(reputation_score,0) DESC, created_at DESC, id DESC"' in src


def test_the_check_can_fail():
    # the sorts as V0584 shipped them
    assert not _breaks_ties("ORDER BY is_live DESC, COALESCE(reputation_score,0) DESC, is_paid DESC, created_at DESC")
    assert not _breaks_ties("ORDER BY created_at DESC")
