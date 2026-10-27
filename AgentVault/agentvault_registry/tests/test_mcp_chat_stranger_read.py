"""§MCPTEST30 (V0556): a chat thread is read by its participants and their households only.

The chat lifecycle opens three threads from one developer's agent K to three agents R1-R3 of the runner's developer.
R3 is no participant in R1's thread, and the runner's developer holds no developer seat there, so readThread asked by R3
must be refused (403, the household rule of chat_service.resolve_membership) with nothing of the thread in the answer.
The row is `chat: a thread read by an agent that is no participant`; its judge is pure and pinned here, and its prefix
must reach the run (the flow drops a synthetic row whose prefix it does not list).
"""
from __future__ import annotations

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


def _refused(code, said):
    return True, {"_text": f"Error: HTTP {code}: {said}"}   # expect_status="any": a refusal still reads ok


@pytest.mark.parametrize("code", [403, 404])
def test_a_clean_refusal_is_healthy(code):
    ok, inner = _refused(code, "you are not a participant in this conversation")
    healthy, why, ev = L.judge_stranger_thread_read(ok, inner)
    assert healthy and why is None and ev["status"] == code and ev["messages_in_answer"] is None


def test_a_thread_handed_to_a_stranger_is_a_privacy_bug_find():
    healthy, why, ev = L.judge_stranger_thread_read(True, {"conversation_id": "c1", "messages": [{"seq": 1}, {"seq": 2}]})
    assert not healthy and why.startswith("BUG-FIND: chat: an agent that is no participant") and ev["messages_in_answer"] == 2
    # an empty page that LANDED is still a read the stranger should not have been granted
    healthy, why, _ev = L.judge_stranger_thread_read(True, {"conversation_id": "c1", "messages": []})
    assert not healthy and why.startswith("BUG-FIND")


def test_a_refusal_that_still_carries_messages_is_a_bug_find():
    healthy, why, ev = L.judge_stranger_thread_read(False, {"_text": "Error: HTTP 403: no", "messages": [{"seq": 1}]})
    assert not healthy and why.startswith("BUG-FIND") and ev["messages_in_answer"] == 1


@pytest.mark.parametrize("code", [500, 401, 422])
def test_an_unclean_refusal_is_named_not_passed(code):
    ok, inner = _refused(code, "something else")
    healthy, why, ev = L.judge_stranger_thread_read(ok, inner)
    assert not healthy and why.startswith("the stranger's thread read was not refused cleanly") and ev["status"] == code


def test_no_answer_at_all_is_named():
    healthy, why, ev = L.judge_stranger_thread_read(False, {})
    assert not healthy and "no answer" in why and ev["status"] == 0


def test_the_row_reaches_the_run():
    assert L.CHAT_STRANGER_READ.startswith(L._CHAT) and L._CHAT in F._SYNTHETIC_ROW_PREFIXES
