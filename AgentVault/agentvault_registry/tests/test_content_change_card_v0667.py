"""V0667 D5b (order gwo_efd89f2041bfda1eeb7e2cda): the `content.change.live` card, pure: what it carries, what it never carries, its validator, when it closes, the line each state posts, and the chat's own
vocabulary for it (a rail-only card with a preview sentence)."""
from __future__ import annotations

from agentvault_registry.services import chat_live_cards as lc
from agentvault_registry.services import chat_service as cs

VIEW = {"id": "ct_abc", "kind": "console_text", "target": "landing.tagline", "title": "A tagline", "state": "balloting", "organization_id": "org-1", "organization_name": "Lyceum",
        "content": {"text": "SECRET-LOOKING TEXT"}, "checker": {"ok": True, "rules": ["schema", "secrets"], "bytes": 20},
        "code_distribution": {"slug": "lyceum", "title": "Lyceum's line", "release_name": "V0666_lyceum", "state": "active"},
        "ballot": {"cast": 1, "deciders": 3, "ends": "2026-11-23T10:00:00+00:00", "result": None, "my_vote": "FOR", "can_vote": True}}


def test_the_card_carries_the_kind_the_state_the_line_the_checker_and_the_ballot_and_nothing_of_the_reader_or_the_text():
    card = lc.content_change_card(VIEW)
    d = card["data"]
    assert card["type"] == "content.change.live" and card["refs"] == {"content_change_id": "ct_abc"}
    assert (d["change_id"], d["kind"], d["state"], d["title"], d["applied"]) == ("ct_abc", "console_text", "balloting", "A tagline", False)
    assert d["line"] == {"slug": "lyceum", "title": "Lyceum's line", "release_name": "V0666_lyceum", "organization_name": "Lyceum", "paused": False}
    assert d["checker"] == {"state": "ok", "rules": ["schema", "secrets"]} and d["ballot"]["votes"] == 1 and d["ballot"]["deciders"] == 3
    flat = str(card)
    assert "SECRET-LOOKING TEXT" not in flat and "my_vote" not in flat and "can_vote" not in flat and "FOR" not in flat.replace("FORMAT", "")


def test_an_applied_change_is_marked_applied_and_a_passed_ballot_carries_its_sentence():
    v = {**VIEW, "state": "applied", "ballot": {**VIEW["ballot"], "result": {"status": "PASSED", "sentence": "2 for, 0 against, of 3 deciders: passed"}}}
    d = lc.content_change_card(v)["data"]
    assert d["applied"] is True and d["ballot"]["result"] == "PASSED" and d["ballot"]["sentence"].startswith("2 for")


def test_an_unknown_state_reads_as_balloting_and_a_paused_line_is_said():
    d = lc.content_change_card({**VIEW, "state": "weird", "code_distribution": {**VIEW["code_distribution"], "state": "paused"}})["data"]
    assert d["state"] == "balloting" and d["line"]["paused"] is True


def test_the_validator_takes_the_rails_card_and_names_what_is_wrong_with_another():
    good = lc.content_change_card(VIEW)["data"]
    assert lc.validate_content_change_live(good) is None
    assert "ct_" in lc.validate_content_change_live({**good, "change_id": "cc_abc"})
    assert "title" in lc.validate_content_change_live({**good, "title": ""})
    assert "state" in lc.validate_content_change_live({**good, "state": "merged"})
    assert "ballot" in lc.validate_content_change_live({**good, "ballot": None})


def test_a_card_closes_with_the_ends_but_an_applied_change_stays_open_for_its_undo():
    card = lambda state: lc.content_change_card({**VIEW, "state": state})        # noqa: E731
    for s in ("failed", "apply_failed", "undone", "withdrawn"):
        assert lc.closed_reason(card(s)) == f"the change is {s}"
    for s in ("balloting", "applied"):
        assert lc.closed_reason(card(s)) is None
    assert lc.UPDATABLE["content.change.live"] == "rail"


def test_each_state_posts_one_line_and_the_first_sight_and_a_repeat_post_none():
    line = lambda seen, state: lc.content_change_state_line(seen, {**VIEW, "state": state})          # noqa: E731
    assert line(None, "applied") is None and line("applied", "applied") is None and line("balloting", "balloting") is None
    assert line("balloting", "applied") == "A tagline: passed its ballot and is applied to the organization's own space; its deciders can undo it in one step."
    assert line("balloting", "failed") == "A tagline: did not pass its ballot; nothing was applied."
    assert "our checker refused it" in line("balloting", "apply_failed")
    assert line("applied", "undone") == "A tagline: undone; the organization's space is back as it was."
    assert line("balloting", "withdrawn") == "A tagline: withdrawn."


def test_the_chat_takes_the_card_from_the_rail_only_and_words_its_preview():
    card = lc.content_change_card(VIEW)
    assert "content.change.live" in cs.RAIL_ONLY_CARDS and "content.change.live" in cs.RAIL_ONLY_WRITERS
    assert cs.validate_card(card, rail_author=True) is None
    refusal = cs.validate_card(card)
    assert refusal is not None and "code changes rail" in refusal
    assert cs.validate_card({**card, "data": {**card["data"], "state": "merged"}}, rail_author=True) is not None
    assert cs.preview_for("card", None, card).startswith("Content change balloting: A tagline")
