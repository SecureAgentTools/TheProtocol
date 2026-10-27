"""A pull carries the card's name and description into the row's listed columns (agentvault2-66, 2026-10-25).

`agent_cards.name` and `agent_cards.description` are copies of the card that discovery lists, searches and filters
on (`routers/agent_cards.py` selects `c.description`), and the pull-sync only ever rewrote `card_data`. Measured on EU
2026-10-25 through the public discovery feed and the public card route: all eleven sovereign agents listed the role
line `scripts/hetzner_demo/onboard_sovereign_agents.py` minted them with (Greedy Gregory "Autonomous yield optimizer.")
while their cards carried what the agents publish ("Ledger watcher with an appetite. ..."); an agent onboarded through
the stub keeps "Awaiting first pull-sync ..." as its listed text the same way.

RED before the change: the 304, the 200 with drift, the 200 without drift and the single-card refresh all leave the
columns as minted. THE CONTROLS pass both before and after: a card that says nothing leaves the column alone, and a
column that already agrees is not written. The bound is new with the change: both columns carry a btree index (an
entry cannot exceed about 2.7 KB) and a cycle commits all its rows at once, so one long card must not fail them all.
"""
import asyncio
import contextlib
import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

import httpx  # noqa: E402

from agentvault_registry.background_tasks import agent_card_pullsync as ps  # noqa: E402

URL = "https://agent.probe-fixture.net/api/gregory/cross-frame"
MINTED = "Autonomous yield optimizer."
OWN = ("Ledger watcher with an appetite. Gregory watches balances across all three sovereign frames and the live "
       "FX corridor between them.")


def _card(description=OWN, name="Greedy Gregory"):
    card = {"name": name, "description": description, "url": URL,
            "supportedInterfaces": [{"url": URL, "protocolBinding": "REST", "protocolVersion": "1.0"}],
            "federation_metadata": {}}
    if description is None:
        card.pop("description")
    return ps.canonicalize_card_data(card)


def _row(card=None, etag=None, name="Greedy Gregory", description=MINTED):
    """A row as EU holds Gregory: the card current, the listed columns as the onboarding script minted them."""
    return SimpleNamespace(agent_did="did:theprotocol:eu.theprotocol.cloud:3e9521db", card_data=card or _card(),
                           name=name, description=description, last_pulled_at=None, last_pulled_etag=etag,
                           last_pull_attempt_at=None, last_pull_status=None, pull_failures=0)


def _stats():
    # the shape tests/test_agent_card_pullsync.py hands the worker: without the new key, which must not matter
    return {"candidates": 0, "fetched_200": 0, "fetched_304": 0, "fetched_4xx": 0, "fetched_5xx": 0, "fetched_timeout": 0,
            "skipped_internal": 0, "drift_agents": 0, "drift_field_counts": {}, "errors": 0, "last_pull_per_agent": {}}


def _run(handler, row):
    stats = _stats()

    async def no_emit(*_a, **_k):   # a drift event would retry an event store this test has none of
        return None

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await ps.AgentCardPullSync()._pull_one(None, client, row, stats)
    emit, ps._emit_drift_event = ps._emit_drift_event, no_emit
    try:
        asyncio.run(go())
    finally:
        ps._emit_drift_event = emit
    return stats


# ── the defect, on the worker's three outcomes ─────────────────────────────────────────────────────────────────────────
def test_a_304_carries_the_stored_card_into_the_listed_columns():
    """EU's case: the card is current, the agent answers 304, and the listing still says what it was minted with."""
    r = _row(etag='W/"v2"')
    st = _run(lambda req: httpx.Response(304), r)
    assert st["fetched_304"] == 1
    assert r.description == OWN, f"the listing kept the minted text: {r.description!r}"
    assert st.get("listed_synced") == 1


def test_a_200_with_drift_carries_the_new_text_into_both_places():
    newer = _card(description=OWN + " Now with the lock terms of every frame.", name="Greedy Gregory II")
    r = _row()
    st = _run(lambda req: httpx.Response(200, json=newer, headers={"etag": 'W/"v3"'}), r)
    assert st["drift_agents"] == 1
    assert r.card_data["description"] == newer["description"]
    assert r.description == newer["description"] and r.name == "Greedy Gregory II"


def test_a_200_without_drift_still_heals_a_stale_column():
    r = _row()
    st = _run(lambda req: httpx.Response(200, json=_card(), headers={"etag": 'W/"v2"'}), r)
    assert st["drift_agents"] == 0, "the fixture should be a no-drift pull"
    assert r.description == OWN and st.get("listed_synced") == 1


# ── the single-card refresh (admin refresh, drift accept, the first pull after onboarding) ──────────────────────────────
class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Db:
    def __init__(self, row):
        self.row, self.commits = row, 0

    async def execute(self, *_a, **_k):
        return _Result(self.row)

    async def commit(self):
        self.commits += 1


def _trigger(monkeypatch, row, response):
    db = _Db(row)

    @contextlib.asynccontextmanager
    async def fake_ctx():
        yield db

    async def fake_fetch(client, url, headers):
        return response

    async def no_emit(*_a, **_k):
        return None

    monkeypatch.setattr(ps, "get_db_context", fake_ctx)
    monkeypatch.setattr(ps, "fetch_agent_card", fake_fetch)
    monkeypatch.setattr(ps, "_emit_drift_event", no_emit)
    out = asyncio.run(ps.trigger_pull_for_did(row.agent_did))
    return out, db


def test_the_single_card_refresh_heals_on_304_and_says_so(monkeypatch):
    r = _row(etag='W/"v2"')
    out, db = _trigger(monkeypatch, r, httpx.Response(304))
    assert out["status"] == "ok" and out["http"] == 304 and db.commits == 1
    assert r.description == OWN and out.get("listed_columns") == ["description"]


def test_the_single_card_refresh_heals_on_200(monkeypatch):
    r = _row()
    out, _ = _trigger(monkeypatch, r, httpx.Response(200, json=_card(), headers={"etag": 'W/"v2"'}))
    assert out["status"] == "ok" and out["http"] == 200
    assert r.description == OWN and out.get("listed_columns") == ["description"]


# ── the bound ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_long_description_is_bounded_at_a_character_boundary():
    long = ("Ä€漢" * 900) + " the end"          # 2, 3 and 3 bytes: a byte cut lands inside a character
    r = _row(card=_card(description=long))
    assert ps._sync_listed_columns(r, r.card_data) == ["description"]
    raw = r.description.encode("utf-8")
    assert len(raw) <= ps._LISTED_TEXT_MAX_BYTES, len(raw)
    assert r.description.endswith("…") and long.startswith(r.description[:-1])
    raw.decode("utf-8")  # whole characters only


# ── the controls (pass before and after) ─────────────────────────────────────────────────────────────────────────────
def test_control_a_card_that_says_nothing_leaves_the_column_alone():
    for silent in (None, "", "   "):
        r = _row(card=_card(description="stored text"))
        _run(lambda req, s=silent: httpx.Response(200, json=_card(description=s), headers={"etag": 'W/"v4"'}), r)
        assert r.description == MINTED, f"a card silent about its text ({silent!r}) rewrote the listed column"


def test_what_is_not_a_card_changes_nothing():
    r = _row()
    assert ps._sync_listed_columns(r, None) == [] and ps._sync_listed_columns(r, ["not", "a", "card"]) == []
    assert r.description == MINTED and r.name == "Greedy Gregory"


def test_control_a_column_that_agrees_is_not_written():
    r = _row(description=OWN)
    st = _run(lambda req: httpx.Response(304), r)
    assert r.description == OWN and r.name == "Greedy Gregory"
    assert st.get("listed_synced", 0) == 0, "an agreeing row was counted as carried"
