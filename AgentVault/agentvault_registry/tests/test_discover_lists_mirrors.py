"""V0640 (agentvault2-aa, 2026-10-25): GET /discover lists the mirrors, under discovery's one population rule.

The pair proof nt261025x1 (V0639) failed the federation row discover_agents_lists_federated_agents: both pair
operators answered 0 to the MCP discoverAgents tool while each held 146 mirrored cards, and the console's
/agent-cards/discover listed 20 there. GET /discover (routers/agent_discovery.py, the route the tool reads) took for
its federated half only cards with agent_did NULL, and every mirror federation_sync stores carries agent_did
(uix_agent_cards_agent_did): no mirror was ever listed. The row had passed for weeks on the operators' only local
agents, the opmoney pair, which V0639's tester retires once its verdict is in.

The fix: the mirrors pass the console's own rule (agent_cards.CARD_POPULATION_SQL, one predicate both routes ask),
and the answer is ONE bounded sequence (the local agents in discover_statement's order, then the mirrors, newest
card first, the card id breaking a tie), so `limit` bounds it and two pages of 3 partition one page of 6. Before,
every matching federated card was appended whatever the limit. Driven through the ROUTE with a database double that
answers each statement the route runs as a database holding locals and mirrors would (§DISCECHO: a gate that never
calls the rail cannot see what the rail runs). The control (V0639's route) fails these tests.
"""
import asyncio
import datetime
import inspect
import types

from sqlalchemy.dialects import postgresql

from agentvault_registry.routers import agent_cards
from agentvault_registry.routers.agent_discovery import discover_agents
from agentvault_registry.services import enforcement_propagation as _ep
from agentvault_registry.services import reputation_bond as _rb

T0 = datetime.datetime(2026, 10, 25, 7, 0, 0)
SOURCE = "nt261025x1a"


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def _reads_mirrors(stmt) -> bool:
    """A statement over the mirrors: it indexes card_data by 'federation_metadata' (a bound value, never SQL text)."""
    return "federation_metadata" in [str(v) for v in stmt.compile(dialect=postgresql.dialect()).params.values()]


def _bound(clause):
    v = getattr(clause, "value", None)
    return v if isinstance(v, int) else None


def _window(stmt):
    """(offset, limit) a statement asks for; (0, None) when it asks for no window."""
    return _bound(getattr(stmt, "_offset_clause", None)) or 0, _bound(getattr(stmt, "_limit_clause", None))


class _Rows:
    def __init__(self, rows=(), scalar=None):
        self._rows, self._scalar = list(rows), scalar

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


def _local(i):
    agent = types.SimpleNamespace(did=f"did:theprotocol:local-{i}", reputation_score=0.5, created_at=T0,
                                  last_active_at=None, status="active")
    card = types.SimpleNamespace(name=f"local {i}", description="a local agent", card_data={"tags": []})
    return agent, card


def _mirror(i):
    # a mirror as federation_sync stores it: the DID in agent_did, none in card_data
    return types.SimpleNamespace(
        agent_did=f"did:theprotocol:mirror-{i}", name=f"mirror {i}", description="a peer's agent", created_at=T0,
        card_data={"federation_metadata": {"source_registry": SOURCE, "origin_registry_name": SOURCE}, "tags": []})


class _DB:
    """Answers GET /discover's statements as a database holding `n_local` local agents and `n_mirror` mirrors would:
    the local page and the mirror page honour their own OFFSET and LIMIT, the counts count everything."""

    def __init__(self, n_local=2, n_mirror=5):
        self.locals = [_local(i) for i in range(n_local)]
        self.mirrors = [_mirror(i) for i in range(n_mirror)]
        self.statements = []

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        sql = _sql(stmt)
        off, lim = _window(stmt)

        def cut(xs):
            return xs[off:] if lim is None else xs[off:off + lim]
        if "peer_registries" in sql:
            return _Rows()
        if _reads_mirrors(stmt):
            return _Rows(scalar=len(self.mirrors)) if "count(" in sql else _Rows(cut(self.mirrors))
        if "count(" in sql:
            return _Rows(scalar=len(self.locals))
        if "FROM agents" in sql:
            return _Rows(cut(self.locals))
        return _Rows()


def _page(db, limit, offset, registry_id=None):
    return asyncio.run(discover_agents(query="did:", registry_id=registry_id, limit=limit, offset=offset, db=db,
                                       current_developer=None))


def _mirror_page_sql(db):
    return next(_sql(s) for s in db.statements if _reads_mirrors(s) and "count(" not in _sql(s))


def test_a_page_holds_at_most_its_limit_and_counts_every_mirror():
    out = _page(_DB(2, 5), 3, 0)
    assert [a["did"] for a in out["agents"]] == [
        "did:theprotocol:local-0", "did:theprotocol:local-1", "did:theprotocol:mirror-0"]
    assert out["total"] == 7 and out.get("federated_total") == 5 and out["federated_count"] == 1


def test_pages_partition_the_locals_then_the_mirrors():
    whole = [a["did"] for a in _page(_DB(2, 5), 6, 0)["agents"]]
    halves = [a["did"] for off in (0, 3) for a in _page(_DB(2, 5), 3, off)["agents"]]
    assert halves == whole and len(set(whole)) == 6, (halves, whole)
    assert [d.rsplit(":", 1)[-1].split("-")[0] for d in whole] == ["local"] * 2 + ["mirror"] * 4
    past_the_locals = [a["did"] for a in _page(_DB(2, 5), 2, 5)["agents"]]
    assert past_the_locals == ["did:theprotocol:mirror-3", "did:theprotocol:mirror-4"]


def test_a_mirror_answers_with_its_own_did():
    out = _page(_DB(0, 2), 5, 0)
    assert [a["did"] for a in out["agents"]] == ["did:theprotocol:mirror-0", "did:theprotocol:mirror-1"]
    assert all(a.get("federated") is True and a["source_registry"] == SOURCE for a in out["agents"])


def test_the_mirrors_pass_discoverys_one_rule():
    db = _DB(0, 2)
    _page(db, 5, 0)
    sql = _mirror_page_sql(db)
    assert "agent_did IS NULL" not in sql.replace("agent_did IS NOT NULL", ""), "a mirror carries its agent_did"
    assert "c.is_active = TRUE AND c.agent_did IS NOT NULL" in sql and "c.unlisted = FALSE" in sql
    assert _rb.sql_card_is_bonded("c") in sql and _ep.sql_card_is_enforced("c") in sql
    assert "agents.did = c.agent_did" in sql, "a card a local agent holds belongs to the local half"
    # a total order: the id is unique
    assert "ORDER BY c.created_at DESC NULLS LAST, c.id DESC" in sql and "LIMIT" in sql


def test_both_routes_ask_one_rule():
    assert agent_cards.CARD_POPULATION_SQL in agent_cards._DISCOVER_SLIM_CTE
    assert "**card_population_params(viewer_is_admin, include_unbonded)," in inspect.getsource(
        agent_cards.discover_agent_cards)


def test_the_rule_binds_under_enforce_and_this_route_asks_as_the_public(monkeypatch):
    monkeypatch.setenv("REPUTATION_BOND_MODE", "shadow")
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "shadow")
    assert agent_cards.card_population_params() == {
        "include_unlisted": False, "include_unbonded": True, "include_enforced": True}
    monkeypatch.setenv("REPUTATION_BOND_MODE", "enforce")
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "enforce")
    assert agent_cards.card_population_params() == {
        "include_unlisted": False, "include_unbonded": False, "include_enforced": False}
    assert agent_cards.card_population_params(True, True) == {
        "include_unlisted": True, "include_unbonded": True, "include_enforced": True}
    assert agent_cards.card_population_params(True, None)["include_unbonded"] is False
    db = _DB(0, 1)
    _page(db, 5, 0)
    stmt = next(s for s in db.statements if _reads_mirrors(s) and "count(" not in _sql(s))
    params = stmt.compile(dialect=postgresql.dialect()).params
    assert (params["include_unlisted"], params["include_unbonded"], params["include_enforced"]) == (False, False, False)


def test_a_peer_filter_is_applied_in_sql_so_the_page_and_its_total_agree():
    db = _DB(2, 3)
    out = _page(db, 10, 0, registry_id=SOURCE.upper())
    assert out["total"] == 3 and all(a.get("federated") for a in out["agents"]), out
    assert "lower(trim(" in _mirror_page_sql(db)
