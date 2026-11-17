"""V0666 D3 (order gwo_542285271416c653ca39af3f, session-tester): a code distribution's change in OurChat. Design:
sessionlogs2026/DESIGN_2026-11-15_DISTRIBUTIONS.md section 5 (the chat command). A change proposed into an organization's
release line may name one of that organization's rooms (`room_id`); the change's live card (`code.change.live`, rail-only:
built and verified by the registry, never client text) is posted there and updated in place as the change moves, and each
state change posts one short line to that room (the team's development log). The pure rules here; the post, the update and
the line on a real Postgres in tests/test_code_change_card_v0666_db.py. Red on 27775eacd: nothing of it exists.

  the card    built from the change's public view: state, the line, the checker, the reviews, the ballot (never a
              reader's own vote: the card is everyone's; the reader's vote is read by the reader)
  the room    only a line's change, only into its own organization's room the proposer's agent may post in
  the line    one sentence per state, posted only when the state the room last saw changes
  the reader  the view tells a signed-in reader whether they decide this ballot and whether they may review
Nothing here moves value: a bounty stays a Guild order.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.services import chat_live_cards as lc
from agentvault_registry.services import chat_service as cs
from agentvault_registry.services import code_changes as cc
from tests.test_code_changes_flow_v0663 import SHA
from tests.test_code_distributions_v0666 import (ADMIN, DOC, ORG, PROPOSER, LineStore, _balloting, _env, _flow, _line,  # noqa: F401
                                                 _proposed, _refused, _vote, run)

ROOM = "conv-lyceum-room"


class RoomStore(LineStore):
    """LineStore plus the one room question the flow asks the store: may this proposer announce in that room."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.rooms = {ROOM: ORG, "conv-other-org": "org-other", "conv-no-org": None}

    async def room_refusal(self, room_id, proposer_did, organization_id):
        if room_id not in self.rooms:
            return "room_id names no conversation on this registry"
        if self.rooms[room_id] != organization_id:
            return "a line's change is announced only in a room of the line's organization"
        return None


def _view(**over):
    v = {"id": "cc_1", "title": "A clearer page", "state": "balloting", "sensitive": False, "commit": SHA,
         "paths": [DOC], "acceptance": {"ok": True}, "reviews": [{"commit": SHA, "verdict": "approve"}],
         "review_verdict": {"approvals": 1, "needed": 1, "blockers": [], "ok": True},
         "code_distribution": {"slug": "lyceum", "title": "Lyceum's line", "release_name": "V0666_lyceum",
                               "branch": "distribution/V0666_lyceum",
                               "organization_id": ORG, "organization_name": "Lyceum Labs", "state": "active"},
         "line_ballot": {"ends": "2026-11-17T09:30:00+00:00", "result": None, "votes": 1, "deciders_now": 3,
                         "deciders_note": None, "my_vote": "FOR"}}
    v.update(over)
    return v


# --- the card ------------------------------------------------------------------------------------------------------

def test_the_card_is_built_from_the_view_and_never_carries_a_readers_own_vote():
    card = lc.code_change_card(_view())
    assert card["type"] == "code.change.live" and card["refs"] == {"code_change_id": "cc_1"}
    d = card["data"]
    assert (d["change_id"], d["title"], d["state"]) == ("cc_1", "A clearer page", "balloting")
    assert d["line"] == {"slug": "lyceum", "title": "Lyceum's line", "release_name": "V0666_lyceum",
                         "organization_name": "Lyceum Labs", "paused": False}
    assert d["checker"] == {"state": "ok", "reasons": []}
    assert d["reviews"] == {"count": 1, "approvals": 1, "needed": 1, "blockers": 0}
    assert d["ballot"] == {"votes": 1, "deciders": 3, "ends": "2026-11-17T09:30:00+00:00", "result": None,
                           "sentence": None, "note": None}
    assert "my_vote" not in str(card), "a reader's own vote is the reader's to read, never on a card everyone sees"
    assert cs.validate_card(card, rail_author=True) is None


def test_the_card_says_a_failed_check_and_a_closed_ballot():
    d = lc.code_change_card(_view(state="failed", acceptance={"ok": False, "reasons": ["CI is not green", "x" * 300]},
                                  line_ballot={"votes": 1, "deciders_now": 3, "result": {
                                      "status": "FAILED", "sentence": "1 of 3 deciders voted, below the quorum of 50 percent"}}))["data"]
    assert d["checker"]["state"] == "failed" and d["checker"]["reasons"][0] == "CI is not green"
    assert len(d["checker"]["reasons"][1]) <= 200
    assert d["ballot"]["result"] == "FAILED" and d["ballot"]["sentence"].startswith("1 of 3 deciders voted")
    assert lc.code_change_card(_view(acceptance=None))["data"]["checker"] == {"state": "none", "reasons": []}


def test_a_client_cannot_author_the_card_and_its_data_is_checked():
    card = lc.code_change_card(_view())
    reason = cs.validate_card(card)
    assert reason and "the code changes rail" in reason, reason
    bad = {"v": 1, "type": "code.change.live", "data": {**card["data"], "change_id": "gwo_1"}}
    assert "data.change_id" in cs.validate_card(bad, rail_author=True)
    bad = {"v": 1, "type": "code.change.live", "data": {**card["data"], "state": "almost"}}
    assert "data.state" in cs.validate_card(bad, rail_author=True)
    assert lc.UPDATABLE["code.change.live"] == "rail"


def test_the_card_closes_when_the_change_ends():
    for st in ("merged", "failed", "vetoed", "withdrawn"):
        assert lc.closed_reason({"type": "code.change.live", "data": {"state": st}}) == f"the change is {st}"
    for st in ("proposed", "accepted", "balloting", "passed"):
        assert lc.closed_reason({"type": "code.change.live", "data": {"state": st}}) is None


def test_the_room_list_reads_the_card_in_words():
    card = lc.code_change_card(_view())
    assert cs._card_sentence(card) == "Code change balloting: A clearer page"


# --- the state line --------------------------------------------------------------------------------------------------

def test_one_line_per_state_and_none_when_the_room_already_saw_it():
    v = _view(state="balloting")
    assert lc.code_change_state_line(None, v) is None, "the card itself announces the change"
    assert lc.code_change_state_line("balloting", v) is None, "the same state: nothing new to say"
    assert lc.code_change_state_line("accepted", v) == ("A clearer page: the line's ballot is open; "
                                                        "its deciders vote (V0666_lyceum).")
    words = {s: lc.code_change_state_line("proposed", _view(state=s)) for s in cc.STATES if s != "proposed"}
    assert words["accepted"].endswith("the signed checks passed; it waits for its reviews.")
    assert words["passed"].endswith("passed; the veto window runs.")
    assert words["merged"].endswith("merged into distribution/V0666_lyceum.")
    assert words["failed"].endswith("did not pass.")
    assert words["vetoed"].endswith("vetoed.")
    assert words["withdrawn"].endswith("withdrawn.")
    for line in words.values():
        assert len(line) <= 300 and "payout" not in line.lower()


# --- the room, named at propose ----------------------------------------------------------------------------------------

def test_a_lines_change_names_its_organizations_room_and_nothing_else():
    s = RoomStore(members=(1,))                        # the proposer is also a frame member: the main line's refusal is the room's
    _line(s)
    out = _proposed(s, room_id=ROOM)
    assert s.rows[out["id"]]["announce_conversation_id"] == ROOM
    assert "announce_conversation_id" not in out and "announce_message_id" not in out and "announce_state" not in out
    assert out["announced_in_room"] is True
    _refused(_flow(s).propose(PROPOSER, {"repository": "theprotocol/AgentVault", "paths": [DOC], "title": "T",
                                         "problem": "P", "branch": "b", "commit": SHA, "room_id": ROOM}), 409,
             "main_line_room")
    _refused(_flow(s).propose(PROPOSER, {**_body(), "room_id": "conv-other-org"}), 422, "room")
    _refused(_flow(s).propose(PROPOSER, {**_body(), "room_id": "conv-nosuch"}), 422, "room")
    assert _proposed(s)["announced_in_room"] is False


def _body():
    return {"repository": "theprotocol/AgentVault", "paths": [DOC], "title": "T2", "problem": "P", "branch": "b2",
            "commit": SHA, "code_distribution": "lyceum"}


# --- the reader --------------------------------------------------------------------------------------------------------

def test_the_view_tells_a_reader_whether_they_decide_and_whether_they_may_review():
    s = RoomStore()
    cid = _balloting(s)
    f = _flow(s)
    assert run(f.view(cid, reader_developer_id=2))["line_ballot"]["i_decide"] is True       # the owner
    assert run(f.view(cid, reader_developer_id=6))["line_ballot"]["i_decide"] is False      # a plain member
    assert run(f.view(cid))["line_ballot"]["i_decide"] is False
    v = run(f.view(cid, reader_developer_id=6))
    assert v["reader_may_review"] is True, "a non-guest member of the organization who did not write it"
    assert run(f.view(cid, reader_developer_id=1))["reader_may_review"] is False, "the proposer reviews no own change"
    assert run(f.view(cid, reader_developer_id=5))["reader_may_review"] is False, "a guest neither reviews nor decides"
    assert run(f.view(cid, reader_developer_id=8))["reader_may_review"] is False, "not in the organization"
    assert run(f.view(cid))["reader_may_review"] is False


def test_the_cards_states_are_the_changes_states():
    assert lc.CODE_CHANGE_STATES == cc.STATES
