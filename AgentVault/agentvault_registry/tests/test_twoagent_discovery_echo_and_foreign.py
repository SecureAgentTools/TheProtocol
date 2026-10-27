"""§TWOAGENT #8 and #9 (2026-09-23) — two discovery answers a stranger reads as facts.

#8. `GET /agent-cards/discover` echoed `applied_filters.include_unbonded` as the RAW request value. Under
    REPUTATION_BOND_MODE=enforce that parameter binds for an ADMIN viewer only, so a non-admin who sent `true` read
    "include_unbonded: true" above a page with no unbonded agent in it (measured on EU: total 0 for the trial's own
    unbonded DID, echo true). The echo now reports the value that BOUND.

#9. `GET /agent-cards/?foreign_only=true` matched `card_data.federation_metadata.origin_registry_name IN (peer names)`
    case-sensitively. EU's ACTIVE frame row is `asia`; all 24 ASIA-native mirrors on EU say `ASIA` (the registry-card
    fan-out re-inserts a peer frame under its UPPERCASE card name). The listing showed 2 operator-homed cards and
    none of ASIA's own, while discover showed 12 paid ASIA agents. It now compares lower-cased names.

RED on the pre-change tree: the #8 pins and both #9 tests.
"""
from __future__ import annotations

import asyncio
import inspect
import types

from sqlalchemy.dialects import postgresql

from agentvault_registry.routers import agent_cards as mod


# ── #8 ────────────────────────────────────────────────────────────────────────────────────────

def test_the_echo_does_not_carry_the_raw_include_unbonded():
    src = inspect.getsource(mod.discover_agent_cards)
    echo = src.split("applied_filters = {")[1].split("}")[0]
    assert '"include_unbonded": include_unbonded' not in echo, "the echo still names the raw request value"


def test_the_echo_reports_the_bound_value_after_it_is_decided():
    src = inspect.getsource(mod.discover_agent_cards)
    bind = 'applied_filters["include_unbonded"] = bool(base_params["include_unbonded"])'
    assert bind in src
    assert src.index("base_params = {") < src.index(bind), "the echo must be written after the bound value exists"


# ── #9 ────────────────────────────────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _Db:
    """Answers the peer read, captures the card statement."""

    def __init__(self, peers):
        self.peers = peers
        self.card_stmt = None

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        if "peer_registries" in sql:
            return _Res(self.peers)
        self.card_stmt = stmt
        return _Res([])


def _peer(name, ccy):
    return types.SimpleNamespace(name=name, status="ACTIVE", trust_domain=f"{name.lower()}.example",
                                 cached_registry_card={"fees": {"settlement_currency": ccy}})


def _run(peers, monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    db = _Db(peers)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(mod._list_focused_subset(db, bearing_encirclement=False, foreign_only=True, limit=50))
    finally:
        loop.close()
    assert db.card_stmt is not None, "the listing never queried the cards"
    return db.card_stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})


def test_foreign_only_compares_origin_names_case_insensitively(monkeypatch):
    sql = str(_run([_peer("asia", "ACU"), _peer("amsterdam", "ECU")], monkeypatch))
    assert "LOWER(card_data->'federation_metadata'->>'origin_registry_name') IN" in sql
    assert "'asia'" in sql and "'amsterdam'" not in sql          # only the foreign-currency peer, lower-cased


def test_an_uppercase_peer_row_name_is_lowered_too(monkeypatch):
    sql = str(_run([_peer("ASIA", "ACU")], monkeypatch))
    assert "'asia'" in sql and "'ASIA'" not in sql
