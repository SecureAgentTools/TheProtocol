"""V0652 (ab) (order gwo_dfa5e1d0ce56a8ceb0d1f61b, agentvault2-14, 2026-10-31): choice cards.

The maintainer's word (the sessions' room, seq 250): "tester and your suggestions all approved if they do not conflict".
When a session needs a decision that is not yes or no, it asks with up to five options; the room's owner or a named
approver taps one (the same authority and the same step-up setting as an approval); the decision records the option,
who and when, and reaches the asking session as an event it can wait on. A choice is an approval request with options:
the same rail records, decides, expires, signs and shows it.

The acceptance: an agent cannot choose, a choice is made once, an expired card cannot be chosen, the event reaches the
asker. Beside those: the options are checked, an approval is never chosen nor a choice approved, a choice opens no act,
its deciders are pushed chat.choice_requested. The routes run on the real chat router through test_chat_approvals'
harness (only the database, the conversation lookup and the card writer replaced). Each case fails on 05441be31.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

from agentvault_registry.services import chat_approvals as ca
from agentvault_registry.services import chat_service as cs
from tests.test_chat_approvals import AGENT, APPROVER, CONV, MEMBER, NOW, OWNER, _DB, _R, _row, ask, room  # noqa: F401

OPTS = ["Roll now", "Wait for V0652", "Roll the sandbox only"]


def _choice(aid, **kw):
    r = _row(aid, **kw)
    r.options, r.chosen_option = list(OPTS), None
    return r


class _ChoiceDB(_DB):
    """The approvals harness's database, which also keeps the option a choose writes."""

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if sql.startswith("UPDATE chat_approvals"):
            p = dict(params or {})
            res = await super().execute(stmt, params)
            if res.first() is not None:
                self.rows[p["id"]].chosen_option = p.get("co")
                return _R(first=(p["id"],))
            return res
        return await super().execute(stmt, params)


# ── the options ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, ok", [
    (["A", "B"], True), (OPTS, True), (["  Roll   now ", "Wait"], True),
    (["Only one"], False), (["a", "b", "c", "d", "e", "f"], False), (["Same", "same"], False),
    (["", "B"], False), (["x" * 81, "B"], False), ("A, B", False),
])
def test_a_choice_has_two_to_five_distinct_short_options(raw, ok):
    opts, why = ca.normalize_options(raw)
    assert (opts is not None) is ok and (why is None) is ok, (raw, opts, why)
    if ok:
        assert all(o == " ".join(o.split()) for o in opts)
    assert ca.normalize_options(None) == (None, None)   # an approval


def test_an_agent_asks_a_choice_and_its_options_are_the_record(ask):
    r = ask({"client_ref": "ref-choice-01", "title": "V0651 tonight?", "options": OPTS, "expires_in_seconds": 1800})
    assert r.status_code == 201, r.text
    saved = ask.state["saved"]
    assert saved.options == OPTS and saved.facts["options"] == OPTS
    card, _ref, rail = ask.state["sent"][0]
    assert card["type"] == "choice.request" and card["data"]["options"] == OPTS and rail is True
    assert ca.validate_card_data("choice.request", card["data"]) is None
    assert ask.state["audit"][0]["action"] == "choice.requested"
    assert r.json()["approval"]["options"] == OPTS and r.json()["approval"]["chosen"] is None


def test_an_approvals_facts_are_unchanged_by_choices(ask):
    r = ask({"client_ref": "ref-approval-1", "title": "Roll V0651"})
    assert r.status_code == 201 and "options" not in ask.state["saved"].facts
    assert ask.state["sent"][0][0]["type"] == "approval.request"


def test_options_that_cannot_stand_are_refused_by_name(ask):
    r = ask({"client_ref": "ref-choice-02", "title": "Which?", "options": ["Same", "SAME"]})
    assert r.status_code == 422 and "two options say the same" in r.text


# ── the decision ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_agent_cannot_choose(room):
    db = _ChoiceDB([_choice("apr_c1")])
    r = room(db, OWNER, {"decision": "choose", "approval_ids": ["apr_c1"], "option": 0}, real_auth=True,
             headers={"Authorization": "Bearer not-a-developer"})
    assert r.status_code in (401, 403) and db.updated == []


def test_the_owner_chooses_once_and_the_asker_hears_it(room):
    db = _ChoiceDB([_choice("apr_c1")])
    r = room(db, OWNER, {"decision": "choose", "approval_ids": ["apr_c1"], "option": 1})
    assert r.status_code == 200, r.text
    row = db.rows["apr_c1"]
    assert (row.status, row.chosen_option, row.decided_by_developer_id) == ("chosen", 1, OWNER)
    assert row.decision_statement["chosen"] == {"index": 1, "label": "Wait for V0652"}
    assert row.decision_statement["decision"] == "chosen"
    # the event the asking session waits on: a choice.decided card in reply to the request, which /chat/sync?for=me
    # wakes it for (it names one of its approval cards)
    card, ref, reply_to, rail = room.state["cards"][0]
    assert card["type"] == "choice.decided" and card["data"]["chosen"] == {"index": 1, "label": "Wait for V0652"}
    assert reply_to == "msg-apr_c1" and rail is True and ref == "aprdec-apr_c1"
    assert ca.validate_card_data("choice.decided", card["data"]) is None
    assert cs._card_approval_id(card) == "apr_c1"
    out = r.json()["decided"][0]
    assert out["status"] == "chosen" and out["chosen"] == {"index": 1, "label": "Wait for V0652"}
    # the same option again is the same decision; another option is refused: a choice is made once
    again = room(db, OWNER, {"decision": "choose", "approval_ids": ["apr_c1"], "option": 1})
    assert again.status_code == 200 and again.json()["already"] is True
    other = room(db, APPROVER, {"decision": "choose", "approval_ids": ["apr_c1"], "option": 0})
    assert other.status_code in (403, 409) and db.rows["apr_c1"].chosen_option == 1


def test_an_expired_choice_cannot_be_chosen(room):
    db = _ChoiceDB([_choice("apr_c2", minutes=-1)])
    r = room(db, OWNER, {"decision": "choose", "approval_ids": ["apr_c2"], "option": 0})
    assert r.status_code == 410 and db.updated == []


def test_none_of_them_is_a_deny(room):
    db = _ChoiceDB([_choice("apr_c3")])
    r = room(db, OWNER, {"decision": "deny", "approval_ids": ["apr_c3"]})
    assert r.status_code == 200 and db.rows["apr_c3"].status == "denied"
    card = room.state["cards"][0][0]
    assert card["type"] == "choice.decided" and card["data"]["decision"] == "denied" and "chosen" not in card["data"]


@pytest.mark.parametrize("body, want", [
    ({"decision": "approve", "approval_ids": ["apr_c4"]}, "choosing one of its options"),
    ({"decision": "choose", "approval_ids": ["apr_c4"], "option": 3}, "option must be 0 to 2"),
    ({"decision": "choose", "approval_ids": ["apr_c4"]}, "one choice request at a time"),
    ({"decision": "choose", "approval_ids": ["apr_c4", "apr_a1"], "option": 0}, "one choice request at a time"),
    ({"decision": "choose", "approval_ids": ["apr_a1"], "option": 0}, "not a choice"),
])
def test_a_choice_is_never_approved_nor_an_approval_chosen(room, body, want):
    db = _ChoiceDB([_choice("apr_c4"), _row("apr_a1")])
    r = room(db, OWNER, body)
    assert r.status_code in (409, 422) and want in r.text, r.text
    assert db.updated == []


def test_a_choice_opens_no_act():
    r = _choice("apr_c5", status="chosen", sha="a" * 64)
    why = ca.consume_refusal(r, agent_did=AGENT, act_sha256="a" * 64, now=NOW, role="owner")
    assert why is not None and why[0] == 409 and "a choice opens no act" in why[1]


def test_choosing_asks_for_presence_as_approving_does():
    assert ca.presence_required("all", "choose", False) is True
    assert ca.presence_required("production", "choose", True) is True
    assert ca.presence_required("all", "deny", True) is False


# ── the notice to its deciders, and the MCP tools ───────────────────────────────────────────────────────────────────

def test_a_choice_reaches_its_deciders_as_chat_choice_requested():
    card = ca.request_card(_choice("apr_" + "c6" * 16))   # an id this registry mints: the notice takes no other
    m = {"id": "m1", "seq": 4, "kind": "card", "body": None, "card": card}
    assert cs.notice_type_for(OWNER, m, "org", {OWNER}, False) == "chat.choice_requested"
    assert cs.notice_type_for(MEMBER, m, "org", {OWNER}, False) == "chat.message"
    notice = cs.approval_notice(m, "session-release")
    assert notice["approval_id"] == "apr_" + "c6" * 16 and "asks you to choose" in notice["title"]
    assert "Roll now / Wait for V0652" in notice["message"]


def test_the_rail_alone_writes_choice_cards():
    assert {"choice.request", "choice.decided"} <= cs.RAIL_ONLY_CARDS
    assert ca.validate_card_data("choice.decided", {"approval_id": "apr_" + "1" * 32, "title": "x", "options": OPTS,
                                                     "decision": "chosen", "decided_by_developer_id": 6,
                                                     "chosen": {"index": 0, "label": "Not one of them"}}) is not None


def test_the_mcp_tools_ask_and_choose(monkeypatch):
    from agentvault_registry.mcp import tools_chat_approvals as t
    calls = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"items": [{"id": "apr_a", "status": "pending"},
                              {"id": "apr_c", "status": "pending", "options": OPTS}]}

    async def _call(method, path, *, token, params=None, body=None, timeout=15.0):
        calls.append((method, path, body))
        return _Resp(), None

    monkeypatch.setattr(t, "_call", _call)
    monkeypatch.setattr(t, "require_agent_auth", lambda auth: None)
    monkeypatch.setattr(t, "require_developer_auth", lambda auth: None)
    auth = type("A", (), {"auth_type": "developer", "raw_token": "tok"})()
    asyncio_run = __import__("asyncio").run
    asyncio_run(t.request_chat_approval(auth, CONV, "Which?", "ref-mcp-0001", options=OPTS))
    assert calls[-1][2]["options"] == OPTS
    asyncio_run(t.decide_chat_approval(auth, CONV, "choose", approval_ids=["apr_c"], option=2))
    assert calls[-1][2]["decision"] == "choose" and calls[-1][2]["option"] == 2
    bad = asyncio_run(t.decide_chat_approval(auth, CONV, "choose", approval_ids=["apr_c"]))
    assert "the option's index" in bad["error"]
    asyncio_run(t.decide_chat_approval(auth, CONV, "approve"))   # approve all: the choice is left alone
    assert calls[-1][2]["approval_ids"] == ["apr_a"]
    schema = {s["name"]: s for s in t.CHAT_APPROVAL_AGENT_TOOL_SCHEMAS + t.CHAT_APPROVAL_DEVELOPER_TOOL_SCHEMAS}
    assert schema["theprotocol_requestChatApproval"]["inputSchema"]["properties"]["options"]["maxItems"] == 5
    assert "choose" in schema["theprotocol_decideChatApproval"]["inputSchema"]["properties"]["decision"]["enum"]


def test_the_migration_adds_the_two_columns():
    import importlib.util
    import pathlib
    import types
    p = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0204_chat_approval_choices.py"
    spec = importlib.util.spec_from_file_location("m0204", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert len(mod.revision) <= 32
    calls = []
    mod.op = types.SimpleNamespace(add_column=lambda tb, c: calls.append(("add", tb, c.name, c.nullable)),
                                   drop_column=lambda tb, c: calls.append(("drop", tb, c)))
    mod.upgrade()
    mod.downgrade()
    assert calls == [("add", "chat_approvals", "options", True), ("add", "chat_approvals", "chosen_option", True),
                     ("drop", "chat_approvals", "chosen_option"), ("drop", "chat_approvals", "options")]
    json.dumps(calls)
