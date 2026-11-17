"""V0665 (order gwo_fbadffa68e593603d0c59b66, session-lead's note on gwo_fc4ec96d: every card read "Proposed by did:theprotocol...d1bb1"): the code change reads
carry the proposer's agent NAME beside proposer_did and each review its reviewer's PUBLIC name, read in batches (no query per card), never an email.

  - the agent's name is its active card's name (the lookup the admin agents list uses), else its latest card's name; proposer_gone is true only when the
    agent itself is gone (no agent row, or the registry revoked it): an agent whose card is briefly inactive or unnamed is not "gone";
  - a reviewer's public name is the developer's display name, else "Member #<id>" (it tells two reviewers apart; the ids are public in the flare reads),
    never the account name and never anything that is an email address (session-lead, seq 4373: public pages are read without a session);
  - the list reads every name for every card in two batched statements (one for the agents, one for the developers) plus one for the reviewers' ids, and a view
    inside the list asks the store's cache again, so the count of statements does not grow with the number of cards.
Red before this order: the reads named nobody.
"""
from __future__ import annotations

import asyncio
import pathlib

from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import FakeStore, _accept, _deliver, _maintainer_and_release_line, _propose, _review, run   # noqa: F401 (the autouse fixture sets the checker key)

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


class NamedStore(FakeStore):
    """FakeStore with the names() of the real store: agents by DID, developers by id; a missing entry is a name nobody has."""

    def __init__(self, *a, agent_names=None, dev_names=None, gone=None, **kw):
        super().__init__(*a, **kw)
        self.agent_names = agent_names if agent_names is not None else {"did:a:proposer": "Ada's builder"}
        self.dev_names = dev_names if dev_names is not None else {7: "Grace", 8: "Linus"}
        self.gone_dids = set(gone or ())
        self.name_calls = []

    async def gone(self, dids):
        return {d for d in dids if d in self.gone_dids}

    async def names(self, dids, developer_ids):
        self.name_calls.append((list(dids), list(developer_ids)))
        return ({d: self.agent_names.get(d) for d in dids}, {i: self.dev_names.get(i) for i in developer_ids})


def _view(store, cid):
    return run(cc.CodeChangeFlow(store).view(cid))


def test_a_change_names_its_proposers_agent():
    st = NamedStore()
    cid = _propose(st)["id"]
    v = _view(st, cid)
    assert v["proposer_name"] == "Ada's builder" and v["proposer_gone"] is False
    assert v["proposer_did"] == "did:a:proposer"                           # the DID is still there, beside the name


def test_an_agent_that_is_gone_is_said_so_not_left_empty():
    st = NamedStore(agent_names={}, gone={"did:a:proposer"})
    cid = _propose(st)["id"]
    v = _view(st, cid)
    assert v["proposer_name"] is None and v["proposer_gone"] is True


def test_an_agent_with_no_name_to_show_is_not_called_gone():
    """session-volume's finding 3: the card briefly inactive (republished) or empty read "gone"; only the agent itself being gone says it."""
    st = NamedStore(agent_names={})
    cid = _propose(st)["id"]
    v = _view(st, cid)
    assert v["proposer_name"] is None and v["proposer_gone"] is False


def test_each_review_carries_its_reviewers_public_name():
    st = NamedStore()
    cid = _propose(st)["id"]
    oid = st.rows[cid]["order_id"]
    _deliver(st, oid)
    _accept(st, cid)
    _review(st, cid, 7)
    _review(st, cid, 8)
    v = _view(st, cid)
    assert [r["reviewer_name"] for r in v["reviews"]] == ["Grace", "Linus"]
    assert [r["reviewer_developer_id"] for r in v["reviews"]] == [7, 8]


def test_a_reviewer_the_store_has_no_name_for_has_none():
    st = NamedStore(dev_names={7: None, 8: "Linus"})
    cid = _propose(st)["id"]
    _deliver(st, st.rows[cid]["order_id"])
    _accept(st, cid)
    _review(st, cid, 7)
    assert _view(st, cid)["reviews"][0]["reviewer_name"] is None


def test_a_store_without_names_reads_exactly_as_before():
    st = FakeStore()
    cid = _propose(st)["id"]
    v = _view(st, cid)
    assert "proposer_name" not in v and "proposer_gone" not in v


def test_a_developers_public_name_is_the_display_name_else_member_number_never_the_account_name_never_an_email():
    f = cc.public_developer_name
    assert f("Grace Hopper", 7) == "Grace Hopper"
    assert f(None, 7) == "Member #7"                                       # no display name: the number, never the account name
    assert f("  ", 7) == "Member #7"
    assert f("grace@example.org", 7) == "Member #7"                        # an email as a display name is not shown
    assert f(None, None) is None                                           # nobody to name
    assert f("Grace Hopper", None) == "Grace Hopper"


# --- the real store: batched, cached, active cards only ---------------------------------------------------------------------

class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)


class _CountingDb:
    """Answers the four reads the name lookup makes from canned rows and records every statement's text."""

    def __init__(self):
        self.statements = []

    async def execute(self, stmt, *a, **k):
        text = str(stmt)
        self.statements.append(text)
        if "agent_cards" in text:
            # (did, agent status, card name, card is_active): did:a:1 has an active card; did:a:2 only an older inactive one; did:a:3 was revoked
            return _Result([("did:a:1", "active", "Ada's builder", True), ("did:a:2", "active", "Old name", False),
                            ("did:a:2", "active", "Older name", False), ("did:a:3", "revoked", None, None)])
        if "FROM developers" in text:
            return _Result([(7, "Grace Hopper"), (8, None), (9, "x@y.org")])
        if "code_change_reviews" in text:
            return _Result([(7,), (8,), (7,)])
        raise AssertionError("unexpected statement: " + text[:80])


def test_the_store_reads_names_in_batches_and_remembers_them():
    db = _CountingDb()
    st = cc.DbStore(db)
    agents, devs = asyncio.run(st.names(["did:a:1", "did:a:2", "did:a:3", "did:a:gone"], [7, 8, 9]))
    assert agents == {"did:a:1": "Ada's builder", "did:a:2": "Old name", "did:a:3": None, "did:a:gone": None}   # an inactive card still names its agent
    assert devs == {7: "Grace Hopper", 8: "Member #8", 9: "Member #9"}     # no display name (or only an email): the number
    assert len(db.statements) == 2                                         # one for the agents, one for the developers
    assert asyncio.run(st.gone(["did:a:1", "did:a:2", "did:a:3", "did:a:gone"])) == {"did:a:3", "did:a:gone"}   # revoked, and no agent row at all
    asyncio.run(st.names(["did:a:1"], [7, 8]))
    assert len(db.statements) == 2                                         # asked again: answered from what it remembers (gone() too)


def test_the_list_prefetches_so_the_statement_count_does_not_grow_with_the_cards():
    db = _CountingDb()
    st = cc.DbStore(db)
    rows = [{"id": f"cc_{i}", "proposer_did": "did:a:1"} for i in range(30)]
    asyncio.run(st.prefetch(rows))
    n = len(db.statements)
    assert n == 3                                                          # the reviewers' ids, the agents, the developers: whatever the number of cards
    for r in rows:
        asyncio.run(st.names([r["proposer_did"]], [7, 8]))
    assert len(db.statements) == n


def test_the_agent_lookup_asks_for_active_cards_and_the_developer_lookup_selects_no_email_column():
    txt = (SRC / "services" / "code_changes.py").read_text()
    body = txt.split("async def names(", 1)[1].split("    async def ", 1)[0]
    assert "AgentCard.is_active" in body and "Agent.did.in_" in body
    assert "Developer.email" not in body and ".email" not in body
    assert "Developer.name" not in body                                    # the account name is never read for a public page


def test_the_list_route_prefetches_before_it_views_each_card():
    txt = (SRC / "routers" / "code_changes.py").read_text()
    seg = txt.split("async def list_changes(", 1)[1].split("@router", 1)[0]
    assert "prefetch" in seg and seg.index("prefetch") < seg.index("flow.view")
