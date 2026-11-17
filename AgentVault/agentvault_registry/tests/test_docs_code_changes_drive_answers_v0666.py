"""V0666 (session-code, docs order gwo_625e48367c502d57578bb2e9 item 1: "every example run against the sandbox before it is
written"): the Code changes section of chapter 06 carries the answers of the steps after the check, as the governed-code drive
read them on sbx-alpha on 16 November 2026 (order gwo_f7faa8d343d9a6446f3d9a7b, scratchpad/govcode/gc_drive.py, its answers in
run-20261115.answers.jsonl): the accepted record, an approval's verdict, the opened ballot and where its tally is read, the vote
refused without the governor role, and the check's three refusals. Each string below is a measured answer, never a written one.
RED on 0498fd307: the section stops at the refusals before the check.
"""
from __future__ import annotations

import re
from pathlib import Path

CHAPTER = (Path(__file__).resolve().parent.parent / "src" / "agentvault_registry" / "static" / "new_registry_frontend" / "src"
           / "assets" / "docs" / "oracle" / "06_governance.md")


def _section() -> str:
    text = CHAPTER.read_text(encoding="utf-8")
    m = re.search(r"\n## Code Changes: Members Vote on the Code\n(.*?)(?=\n## )", text, re.S)
    assert m, "no Code changes section in chapter 06"
    return m.group(1)


MEASURED = (
    '"state": "accepted"',
    '"review_verdict": {"approvals": 1, "needed": 1, "blockers": [], "ok": true}',
    '"state": "balloting"',
    '"proposal_id"',
    "GET /api/v1/governance/proposals/{id}",
    '{"detail": "Agent lacks required permission: gov.vote"}',
    '{"code": "key", "detail": "signed by a key this registry does not hold for its checker"}',
    "Admin flag required: admin_platform",
    '{"code": "reviews_short", "detail": "1 of 2 independent approval(s) on the accepted commit"}',
)


def test_the_steps_after_the_check_carry_their_measured_answers():
    s = _section()
    missing = [m for m in MEASURED if m not in s]
    assert not missing, missing


def test_the_answers_are_said_to_be_read_from_a_sandbox_drive():
    s = _section()
    # its own phrase: "16 November 2026" alone is already in the section (the OPA paragraph), so it could not fail
    assert "read on a sandbox registry on 16 November 2026" in s


# The ballot's close and the go after it, read on sbx-alpha on 17 November 2026 (gc_drive.py status and go; the change
# cc_f2bee2d81b67f9791cb21331, its Guild order read back cancelled): the members' ballot failed on its quorum, and with 27 real
# members the bootstrap rule no longer lets the maintainer's go pass it.
MEASURED_CLOSE = (
    '"status": "FAILED"',
    '"votes_for": 300',
    '"quorum_percent": 10.0',
    '{"code": "bootstrap_closed", "detail": "the frame has 27 real members, not fewer than 10: the members\' ballot decides"}',
    '"status": "cancelled"',
)


def test_the_ballots_close_and_the_go_after_it_carry_their_measured_answers():
    s = _section()
    missing = [m for m in MEASURED_CLOSE if m not in s]
    assert not missing, missing
    assert "nothing merges" in s and "returns to its poster" in s


# session-lead, room seq 5790 (the docs order's review): the FAILED status and the votes are the ballot's proposal, not the change's
# record (the record reads its own state: "state": "failed", read on the drive's change); and the bootstrap rule's limit is a change
# whose ballot MISSED ITS QUORUM, never one its members rejected (a rejected ballot is never overridden at any size).
def test_the_close_names_whose_answer_each_is_and_the_bootstrap_rules_limit():
    s = _section()
    assert 'the ballot\'s proposal reads `"status": "FAILED"`' in s
    assert 'the change\'s record reads `"state": "failed"`' in s
    assert 'the change\'s record reads `"status"' not in s, "the proposal's status was put on the change's record"
    assert "a change whose ballot missed its quorum" in s
    assert "a change its members failed" not in s
    assert "a ballot the members rejected is never overridden, at any size" in s
