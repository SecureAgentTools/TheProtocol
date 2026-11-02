"""V0652 (af) (order gwo_3b80091fe506da824c40f903, agentvault2-14, 2026-10-31): the notification catalog complete.

The maintainer's word in the sessions' room (seq 269, developer 6): "ok add the missing ones. also the ones that were
missed and are not in todays features ... approved." The list is session-lead's NOTIFICATION_GAPS_2026-10-31.md
(sha256 a4a0027f951b99b9...). Its rules: each event is emitted where its action happens, on the existing rails; each sits
on the existing preferences (channels, quiet hours, per category); only "decide" events cross quiet hours. No email by
default (the maintainer, seq 313).

This file holds the catalog's half: every event of the list is declared, each routes by its defaults, the decisions cross
quiet hours and nothing else does. The emitters' tests sit beside it (test_notification_emitters_v0652.py). Each case
fails on 05441be31 (the V0651 recut), whose catalog has none of these.
"""
from __future__ import annotations

import pytest

from agentvault_registry.services import notification_catalog as nc
from agentvault_registry.services import notification_prefs as np_

# the gaps file, word for word (its two tables and its lists), plus the production half of "approval used" (its row
# says "in-app; push for production acts": the push is its own type, so a person can turn either off)
GAPS_CHAT = ["chat.approval_requested", "chat.choice_requested", "chat.mention", "chat.direct", "chat.approval_used",
             "chat.progress_finished", "org.session_offline", "chat.message"]
GAPS_BEFORE = [
    "governance.proposal_opened", "governance.vote_closing", "governance.result",
    "commons.season_opened", "commons.award", "commons.season_paid",
    "org.invitation_received", "org.invitation_accepted", "org.member_joined", "org.member_left",
    "federation.invitation_received", "operator.application_received", "operator.application_decided",
    "security.api_key_expiring", "security.password_changed", "security.new_login",
    "a2a.payment_authorized", "a2a.payment_expired", "guild.order_cancelled", "guild.bid_declined",
    "guild.deadline_soon", "contract.deadline_soon", "bond.released",
    "webhook.failing", "agent.card_unreachable",
    "legal.terms_updated",
]
DECIDE = {"chat.approval_requested", "chat.choice_requested"}
PUSHED = {   # the types a device with default settings receives (the rest: in-app, or desktop only)
    "chat.approval_requested", "chat.choice_requested", "chat.mention", "chat.direct", "chat.request",
    "chat.approval_used_production", "commons.award", "org.invitation_received", "federation.invitation_received",
    "operator.application_decided", "security.password_changed", "security.new_login",
}


def _decide(entry, channel, *, hour=12, prefs=None, admin=False):
    ctx = np_.DevCtx(dev_id=6, notification_prefs=prefs or {}, is_admin=admin)
    return np_.decide(entry, channel, ctx=ctx, device_prefs=None, amount=None, now_hour=hour)


def test_the_catalog_lists_every_event_of_the_gaps_file():
    missing = [k for k in GAPS_CHAT + GAPS_BEFORE + ["chat.approval_used_production"] if nc.get_type(k) is None]
    assert missing == []


# V0652 left two to a later card (the choice cards (ab) fire chat.choice_requested). V0653 fires both: a progress
# card's verdict (chat_service.notify_progress_finished) and a lapsed status line (session_offline_watch)
NOT_YET: set = set()


def test_every_new_event_has_its_emitter_but_the_cards_that_bring_theirs():
    new = GAPS_CHAT + GAPS_BEFORE + ["chat.approval_used_production"]
    assert {k for k in new if not nc.get_type(k).emitter} == NOT_YET


def test_an_external_agents_certificate_has_no_expiry_to_say():
    # 30 minutes by default, renewed by calling enable-mtls again, its expiry recorded nowhere: not declared
    assert nc.get_type("agent.mtls_expiring") is None


def test_the_new_categories_exist_and_each_event_sits_in_one():
    assert {"governance", "organizations", "legal"} <= set(nc.CATEGORIES)
    cat = {k: nc.get_type(k).category for k in GAPS_BEFORE}
    assert {k for k, c in cat.items() if c == "governance"} == {
        "governance.proposal_opened", "governance.vote_closing", "governance.result",
        "commons.season_opened", "commons.award", "commons.season_paid"}
    assert {k for k, c in cat.items() if c == "organizations"} == {
        "org.invitation_received", "org.invitation_accepted", "org.member_joined", "org.member_left"}
    assert cat["legal.terms_updated"] == "legal"
    assert cat["security.new_login"] == cat["security.password_changed"] == cat["security.api_key_expiring"] == "security"


@pytest.mark.parametrize("key", GAPS_CHAT + GAPS_BEFORE + ["chat.approval_used_production"])
def test_each_event_routes_by_its_defaults(key):
    entry = nc.get_type(key)
    admin = entry.audience == "admin"
    assert not entry.mandatory, key   # every one stays a person's preference
    for channel in ("push_mobile", "push_desktop"):
        send, _reason, _ = _decide(entry, channel, admin=admin)
        if key == "chat.message":
            assert send is False
        elif channel == "push_mobile":
            assert send is (key in PUSHED), (key, channel)
    assert _decide(entry, "inapp", admin=admin)[0] is True, key
    # no email by default (the maintainer, the room seq 313)
    assert _decide(entry, "email", admin=admin)[0] is False, key


@pytest.mark.parametrize("key", sorted(PUSHED))
def test_only_a_decision_crosses_quiet_hours(key):
    entry = nc.get_type(key)
    quiet = {"quiet_hours_start": 22, "quiet_hours_end": 6}
    send, reason, _ = _decide(entry, "push_mobile", hour=23, prefs=quiet, admin=entry.audience == "admin")
    if key in DECIDE:
        assert send is True, reason
    else:
        assert (send, reason) == (False, "quiet")
    assert {t.key for t in nc.CATALOG if t.crosses_quiet_hours} == DECIDE


def test_an_admin_event_never_reaches_a_plain_developer():
    for key in ("federation.invitation_received", "operator.application_received"):
        assert _decide(nc.get_type(key), "inapp", admin=False) == (False, "audience", None)
    # the applicant is a plain developer: the decision on an application reaches them
    assert _decide(nc.get_type("operator.application_decided"), "inapp", admin=False)[0] is True
