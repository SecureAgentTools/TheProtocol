"""§TWOAGENT #11 (2026-09-23) — `GET /agent-cards/?include_federated=true` answers the question it was asked.

Measured live on ASIA (V0425) before the change: `search=Scrivener&include_federated=true` returned 30 rows, 3 that
matched and 27 peer rows that did not (Boris, Sheldon, the FX router, ...). Every peer row carried an EMPTY agent_did,
and ASIA's own agent came back labelled origin "amsterdam", the EU operator whose mirror of it answered the fan-out.
Cause: `federation_helper.query_peer_registry` accepted search/tags/has_tee/tee_type and sent only `{"limit"}` to the
peer's SYNC feed (which takes no search at all), then mapped each card to {id, name, description, origin=<the peer>}.
The merge in the router then deduplicated by NAME, so two different agents that share a name collapsed into one.

(The fan-out tests are async on purpose: `asyncio.run()` in a sync test leaves the NEXT test file without a loop.)
RED on V0429: the fan-out returns the non-matching cards, the rows have no agent_did, the mirrored card is labelled
with the answering peer, and `dedup_federated_rows` / `peer_card_matches` / `peer_card_summary` do not exist.
The two fan-out controls (a native peer card keeps the peer's name; an unlisted card stays out) pass on both trees.
`dedup_federated_rows` is new, so its legacy-name control (which mirrors V0429's inline name rule) is red there too.
"""
from __future__ import annotations

import types

import pytest

from agentvault_registry import federation_helper as fh


def _card(cid, name, *, did=None, desc="", tags=None, tee=None, home=None, unlisted=False):
    cd = {"name": name, "description": desc}
    if did:
        cd["did"] = did
    if tags is not None:
        cd["tags"] = tags
    if tee is not None:
        cd["capabilities"] = {"teeDetails": tee}
    if home:
        cd["federation_metadata"] = {"source_registry": f"spiffe://{home.lower()}.test/registry/{home.lower()}",
                                     "origin_registry_name": home}
    return {"id": cid, "name": name, "description": desc, "is_active": True, "card_data": cd,
            "updated_at": "2026-09-23T10:00:00+00:00", "unlisted": unlisted}


CARDS = [
    _card("11111111-1111-4111-8111-111111111111", "Scrivener of Brussels", did="did:theprotocol:eu.test:aaa",
          desc="writes abstracts", tags=["writing"]),
    _card("22222222-2222-4222-8222-222222222222", "Backstabbing Boris", did="did:theprotocol:eu.test:bbb",
          desc="a showcase agent", tags=["demo"]),
    _card("33333333-3333-4333-8333-333333333333", "Straits Assay", did="did:theprotocol:asia.test:ccc",
          desc="assays text", home="ASIA"),
    _card("44444444-4444-4444-8444-444444444444", "Hidden Scrivener", did="did:theprotocol:eu.test:ddd",
          desc="dark", unlisted=True),
]


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return CARDS


class _Client:
    def __init__(self, **kw):
        self.kw = kw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        _Client.last_params = dict(params or {})
        return _Resp()


async def _run_peer_query(monkeypatch, **filters):
    monkeypatch.setattr(fh.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fh.svid_client, "get_spiffe_id", lambda: "spiffe://test/registry")
    import agentvault_registry.routers.teg_integration as ti
    monkeypatch.setattr(ti, "_to_internal_mtls_url", lambda u: u)
    peer = types.SimpleNamespace(id=1, name="amsterdam", base_url="http://amsterdam.test", status="ACTIVE")
    stats: dict = {}
    kwargs = dict(peer=peer, outcomes={}, **filters)
    try:
        rows = await fh.query_peer_registry(stats=stats, **kwargs)
    except TypeError:          # V0429 has no `stats` parameter: measure it the old way
        rows = await fh.query_peer_registry(**kwargs)
    return rows, stats


async def test_the_fan_out_applies_the_search_it_was_given(monkeypatch):
    rows, _ = await _run_peer_query(monkeypatch, search="scrivener")
    names = sorted(r["name"] for r in rows)
    assert names == ["Scrivener of Brussels"], names   # Boris and Straits Assay do not match; the dark one stays out


async def test_every_peer_row_carries_its_did(monkeypatch):
    rows, _ = await _run_peer_query(monkeypatch)
    assert rows and all(r.get("agent_did") for r in rows), rows


async def test_a_mirrored_card_is_labelled_with_its_home_not_the_peer_that_answered(monkeypatch):
    rows, _ = await _run_peer_query(monkeypatch, search="assay")
    assert [(r["name"], r["origin_registry_name"]) for r in rows] == [("Straits Assay", "ASIA")]


async def test_control_a_native_peer_card_keeps_the_peers_name(monkeypatch):
    rows, _ = await _run_peer_query(monkeypatch)          # no filter: this control must not depend on the search fix
    by_name = {r["name"]: r["origin_registry_name"] for r in rows}
    assert by_name["Backstabbing Boris"] == "amsterdam"


async def test_control_an_unlisted_card_never_leaves_the_fan_out(monkeypatch):
    rows, _ = await _run_peer_query(monkeypatch)
    assert "Hidden Scrivener" not in {r["name"] for r in rows}


def test_tags_and_tee_are_the_local_listings_rules():
    assert fh.peer_card_matches(CARDS[0], tags=["writing"]) is True
    assert fh.peer_card_matches(CARDS[0], tags=["writing", "demo"]) is False       # ALL tags, like JSONB contains
    tee_card = _card("55555555-5555-4555-8555-555555555555", "Enclave", did="did:x:e", tee={"type": "Intel SGX"})
    assert fh.peer_card_matches(tee_card, has_tee=True) and not fh.peer_card_matches(CARDS[0], has_tee=True)
    assert fh.peer_card_matches(CARDS[0], has_tee=False) and not fh.peer_card_matches(tee_card, has_tee=False)
    assert fh.peer_card_matches(tee_card, tee_type="intel sgx") and not fh.peer_card_matches(tee_card, tee_type="SEV")


async def test_the_fan_out_reports_what_it_read_and_kept(monkeypatch):
    _, stats = await _run_peer_query(monkeypatch, search="scrivener")
    assert stats == {"fetched": 4, "matched": 1}


def test_dedup_is_by_did_and_two_agents_sharing_a_name_both_survive():
    from agentvault_registry.routers.agent_cards import dedup_federated_rows
    local = {"id": "l1", "name": "Echo", "agent_did": "did:x:1", "origin_registry_name": "Local"}
    same_did_from_peer = {"id": "p1", "name": "Echo", "agent_did": "did:x:1", "origin_registry_name": "EU"}
    other_echo = {"id": "p2", "name": "Echo", "agent_did": "did:x:2", "origin_registry_name": "EU"}
    rows, dropped = dedup_federated_rows([local, same_did_from_peer, other_echo])
    assert [r["id"] for r in rows] == ["l1", "p2"] and dropped == 1


def test_control_rows_without_a_did_keep_the_legacy_name_rule():
    from agentvault_registry.routers.agent_cards import dedup_federated_rows
    rows, dropped = dedup_federated_rows([{"id": "a", "name": "X"}, {"id": "b", "name": "x "}])
    assert [r["id"] for r in rows] == ["a"] and dropped == 1
