"""V0652 (af) (order gwo_3b80091fe506da824c40f903, agentvault2-14, 2026-10-31): each new event emitted where its action
happens, once, to the people it concerns. The catalog half (declared, routed by the preferences, only decisions cross
quiet hours) is test_notification_catalog_v0652.py.

Where an action happens once by construction (a guarded status claim, a unique accept, a commit), the test pins that the
notice follows it; where a worker could say it again (a reminder each turn, two tallies, two releases), the notice is
claimed on its occasion, and the test runs the worker twice. Each case fails on 05441be31 (the V0651 recut).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import types

import pytest

from agentvault_registry.background_tasks import push_notify


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sent(monkeypatch):
    """Every notice, as (type, recipients, title, message); claims held in memory; spawned notices run on flush()."""
    class _Sent(list):
        pass
    out, claimed = _Sent(), set()

    async def _notify(type_key, devs, **kw):
        out.append((type_key, tuple(sorted(devs)), kw.get("title"), kw.get("message")))
        return 1

    async def _owners(type_key, dids, **kw):
        out.append((type_key, tuple(sorted(dids)), kw.get("title"), kw.get("message")))
        return 1

    async def _claim(key, ttl):
        if key in claimed:
            return False
        claimed.add(key)
        return True

    async def _audience(type_key, **kw):
        out.append((type_key, ("admins",), kw.get("title"), kw.get("message")))
        return 1

    pending = []
    monkeypatch.setattr(push_notify, "notify", _notify)
    monkeypatch.setattr(push_notify, "notify_agent_owners", _owners)
    monkeypatch.setattr(push_notify, "notify_audience", _audience)
    monkeypatch.setattr(push_notify, "claim_once", _claim)
    monkeypatch.setattr(push_notify, "spawn_notice", lambda coro: pending.append(coro))

    def flush():
        while pending:
            run(pending.pop(0))
    out.flush = flush
    return out


class _Result:
    def __init__(self, rows=None, scalar=None):
        self._rows, self._scalar = rows or [], scalar

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar

    def mappings(self):
        return self


class _DB:
    """A session that answers each execute from a list, in order."""
    def __init__(self, *answers):
        self.answers, self.sql = list(answers), []

    async def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        return self.answers.pop(0) if self.answers else _Result()

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


# ── the Guild ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_guild_owners_are_told_once_each(monkeypatch):
    from agentvault_registry.routers import guild
    calls = []

    async def _owners(type_key, dids, **kw):
        calls.append((type_key, list(dids), kw["click"]))

    monkeypatch.setattr(push_notify, "notify_agent_owners", _owners)

    async def go():
        guild._notify_owners("guild.bid_declined", ["did:a", "did:b", "did:a", None], "t", "m")
        await asyncio.sleep(0)
        guild._notify_owners("guild.bid_declined", [], "t", "m")   # nobody: nothing
        await asyncio.sleep(0)
    run(go())
    assert calls == [("guild.bid_declined", ["did:a", "did:b"], "/ui/#/guild")]


def test_the_losing_bids_hear_it_after_the_award_claim():
    from agentvault_registry.routers import guild
    src = inspect.getsource(guild.award)
    assert "RETURNING bidder_did, home_registry_url" in src
    claim, commit, told = (src.index("WHERE id=:o AND status='open'"), src.index("await db.commit()"),
                           src.index('_notify_owners("guild.bid_declined"'))
    assert claim < commit < told
    # a remote bidder is told by its own registry, and the winner never hears "not chosen"
    assert 'if not r[1] and r[0] != bid["bidder_did"]' in src


def test_a_cancelled_orders_bidders_hear_it_with_the_reason():
    from agentvault_registry.routers import guild
    src = inspect.getsource(guild.cancel)
    claim, told = src.index("UPDATE guild_work_orders SET status='cancelled'"), src.index('_notify_owners("guild.order_cancelled"')
    assert claim < src.rindex("await db.commit()", 0, told) < told
    assert 'if reason else' in src and 'd != o["poster_did"]' in src


def test_a_deadline_is_said_once_a_day_before(monkeypatch, sent):
    from agentvault_registry.background_tasks import guild_order_reaper as gr
    when = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)
    rows = [{"id": "gwo_1", "title": "Port the docs", "status": "awarded", "poster_did": "did:p", "worker_did": "did:w",
             "deadline": when},
            {"id": "gwo_2", "title": None, "status": "open", "poster_did": "did:p", "worker_did": None, "deadline": when}]
    monkeypatch.setattr(gr, "AsyncSessionLocal", lambda: _DB(_Result(rows)))
    assert run(gr.remind_deadlines()) == 2
    monkeypatch.setattr(gr, "AsyncSessionLocal", lambda: _DB(_Result(rows)))
    assert run(gr.remind_deadlines()) == 0   # the next turn: already said
    assert [(t, d) for t, d, *_ in sent] == [("guild.deadline_soon", ("did:w",)), ("guild.deadline_soon", ("did:p",))]
    assert "submit the work" in sent[0][3] and "unless you award it" in sent[1][3]


def test_a_contracts_deadline_reaches_both_parties_once(monkeypatch, sent):
    from agentvault_registry.background_tasks import contract_reaper as cr
    when = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)
    rows = [{"id": "ctr_1", "title": "Audit", "client_did": "did:c", "provider_did": "did:v", "deadline": when}]
    monkeypatch.setattr(cr, "get_db_context", lambda: _DB(_Result(rows)))
    assert run(cr.remind_deadlines()) == 1
    monkeypatch.setattr(cr, "get_db_context", lambda: _DB(_Result(rows)))
    assert run(cr.remind_deadlines()) == 0
    assert sent[0][:2] == ("contract.deadline_soon", ("did:c", "did:v"))
    src = inspect.getsource(cr.remind_deadlines)
    assert "origin_surface NOT IN ('guild', 'legacy')" in src   # a Guild order's mirror is told by the Guild


def test_the_reapers_carry_their_reminders():
    from agentvault_registry.background_tasks import contract_reaper, guild_order_reaper
    assert "await remind_deadlines()" in inspect.getsource(guild_order_reaper._loop)
    assert "await remind_deadlines()" in inspect.getsource(contract_reaper._loop)


# ── organizations ────────────────────────────────────────────────────────────────────────────────────────────────────

# a reactor registers its leader_key when constructed (a second instance is refused): its handler runs on a stand-in
_SELF = types.SimpleNamespace(name="test")


def _org_reactors(monkeypatch, admins=(1, 2, 3)):
    from agentvault_registry.background_tasks import reactor_org_lifecycle_notification as r
    toasts = []

    async def _toast(**kw):
        toasts.append(kw["audience"])

    async def _name(_db, oid):
        return "TheProtocol Sessions"

    async def _admins(_db, oid):
        return list(admins)

    async def _dev(_db, d):
        return f"dev{d}"

    monkeypatch.setattr(r, "broadcast_notification", _toast)
    monkeypatch.setattr(r, "_org_name", _name)
    monkeypatch.setattr(r, "_org_admin_dev_ids", _admins)
    monkeypatch.setattr(r, "_dev_name", _dev)
    monkeypatch.setattr(r, "get_db_context", lambda: _DB())
    return r, toasts


def test_an_invitee_hears_the_invitation(monkeypatch, sent):
    r, _ = _org_reactors(monkeypatch)
    run(r.OrgMemberInvitedReactor.handle_event(_SELF, {"org_id": "o1", "invitee_developer_id": 6}))
    assert [(t, d) for t, d, *_ in sent] == [("org.invitation_received", (6,))]


def test_the_inviter_hears_it_was_accepted_and_the_admins_that_someone_joined(monkeypatch, sent):
    r, _ = _org_reactors(monkeypatch, admins=(1, 2, 9))
    run(r.OrgMemberJoinedReactor.handle_event(_SELF, {"org_id": "o1", "developer_id": 9, "invited_by": 2}))
    assert sorted((t, d) for t, d, *_ in sent) == [("org.invitation_accepted", (2,)), ("org.member_joined", (1,))]
    assert "dev9" in sent[0][2] or "dev9" in sent[0][3]


def test_a_removed_member_and_the_admins_hear_it(monkeypatch, sent):
    r, _ = _org_reactors(monkeypatch, admins=(1, 5))
    run(r.OrgMemberRemovedReactor.handle_event(_SELF, {"org_id": "o1", "developer_id": 5}))
    assert sorted((t, d) for t, d, *_ in sent) == [("org.member_left", (1,)), ("org.member_left", (5,))]


def test_a_peer_frames_bridged_event_tells_nobody_here(monkeypatch, sent):
    r, toasts = _org_reactors(monkeypatch)
    for cls, ev in ((r.OrgMemberJoinedReactor, {"org_id": "o1", "developer_id": 9, "invited_by": 2}),
                    (r.OrgMemberRemovedReactor, {"org_id": "o1", "developer_id": 5})):
        run(cls.handle_event(_SELF, {**ev, "_foreign_frame_id": "asia"}))
    assert sent == [] and toasts == []   # its developer 9 is not ours


def test_the_joined_event_names_the_inviter():
    from agentvault_registry.services import organization_service
    src = inspect.getsource(organization_service.InvitationService.accept_invitation)
    assert '"invited_by": invitation.invited_by' in src


# ── security ─────────────────────────────────────────────────────────────────────────────────────────────────────────

FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:144.0) Gecko/20100101 Firefox/144.0"
FIREFOX_NEXT = "Mozilla/5.0 (X11; Linux x86_64; rv:145.0) Gecko/20100101 Firefox/145.0"
SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Version/18.1 Mobile/15E148 Safari/604.1"


def test_a_browser_update_is_not_a_new_device():
    from agentvault_registry.services import security_notices as sn
    assert sn.device_key(FIREFOX) == sn.device_key(FIREFOX_NEXT) != sn.device_key(SAFARI)
    assert sn.device_label(FIREFOX) == "Firefox on Linux" and sn.device_label(SAFARI) == "Safari on iOS"


def _login(monkeypatch, sent, seen, ua):
    from agentvault_registry.services import admin_audit
    from agentvault_registry.services import security_notices as sn
    logged = []

    async def _log(db, **kw):
        logged.append(kw)

    monkeypatch.setattr(admin_audit, "log_session_action", _log)
    told = run(sn.note_login(_DB(_Result([(k,) for k in seen])), 6, "198.51.100.7", ua))
    sent.flush()
    return told, logged


def test_the_first_recorded_sign_in_says_nothing(monkeypatch, sent):
    told, logged = _login(monkeypatch, sent, [], FIREFOX)
    assert told is False and sent == [] and logged[0]["target_type"] == "device"


def test_a_known_device_says_nothing_and_a_new_one_is_said(monkeypatch, sent):
    from agentvault_registry.services import security_notices as sn
    told, _ = _login(monkeypatch, sent, [sn.device_key(FIREFOX)], FIREFOX_NEXT)
    assert told is False and sent == []
    told, _ = _login(monkeypatch, sent, [sn.device_key(FIREFOX)], SAFARI)
    assert told is True
    assert sent[0][:2] == ("security.new_login", (6,)) and "Safari on iOS" in sent[0][3] and "198.51.100.7" in sent[0][3]


def test_every_sign_in_and_every_password_route_carries_it():
    from agentvault_registry.routers import auth_2fa, auth_secure, push_login
    assert "security_notices.note_login(db, developer.id" in inspect.getsource(auth_secure.login_for_access_token)
    for fn in (auth_2fa.validate_two_factor, auth_2fa.recover_with_backup_code):
        assert "security_notices.note_login(db, developer.id, effective_client_ip(http_request)" in inspect.getsource(fn)
    assert "security_notices.note_login(db, dev.id, req_ip, req_ua)" in inspect.getsource(push_login.redeem_token)
    for fn in (auth_secure.change_password, auth_secure.reset_password_via_email,
               auth_secure.set_new_password_after_recovery):
        src = inspect.getsource(fn)
        assert src.index("await db.commit()") < src.index("security_notices.tell_password_changed(")


def test_a_password_change_is_said(sent):
    from agentvault_registry.services import security_notices as sn
    sn.tell_password_changed(6, "with a reset link sent to your email")
    sent.flush()
    assert sent[0][:3] == ("security.password_changed", (6,), "Your password was changed")


def test_an_api_key_is_said_once_before_it_expires(sent):
    from agentvault_registry.services import security_notices as sn
    exp = dt.datetime(2026, 11, 10, tzinfo=dt.timezone.utc)
    rows = [(41, 6, "avreg_ab", "nightly sync", exp), (42, 7, "avreg_cd", None, exp)]
    assert run(sn.remind_api_keys(_DB(_Result(rows)))) == 2
    assert run(sn.remind_api_keys(_DB(_Result(rows)))) == 0
    assert [(t, d) for t, d, *_ in sent] == [("security.api_key_expiring", (6,)), ("security.api_key_expiring", (7,))]
    assert "nightly sync" in sent[0][3] and "avreg_cd" in sent[1][3] and "2026-11-10" in sent[0][3]


class _Redis:
    def __init__(self):
        self.kv = {}

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, **kw):
        self.kv[k] = v
        return True


def test_the_terms_are_said_once_per_version_and_not_at_the_first_pass(monkeypatch, sent):
    from agentvault_registry.background_tasks import leader
    from agentvault_registry.core import legal_versions as lv
    from agentvault_registry.services import security_notices as sn
    r = _Redis()

    async def _redis():
        return r

    monkeypatch.setattr(leader, "get_redis", _redis)
    devs = [(6, "2.3"), (7, lv.TOS_VERSION), (8, None)]
    assert run(sn.tell_terms_updated(_DB(_Result(devs)))) == 0          # the first pass records the version
    assert run(sn.tell_terms_updated(_DB(_Result(devs)))) == 0          # the same version: nothing
    r.kv[sn._LEGAL_MARK] = "2.0"                                         # the set moved on since the last pass
    assert run(sn.tell_terms_updated(_DB(_Result(devs)))) == 2          # who accepts again at the next sign-in
    assert sent[0][:2] == ("legal.terms_updated", (6, 8)) and lv.EFFECTIVE_LABEL in sent[0][3]


def test_the_daily_worker_carries_both():
    from agentvault_registry.background_tasks import account_deletion_worker as w
    assert "_sn.daily_pass(_ndb)" in inspect.getsource(w)


# ── money and work ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_payment_authorized_tells_the_payee_but_not_on_the_buy_rail():
    from agentvault_registry.routers import a2a_payment
    src = inspect.getsource(a2a_payment.authorize_payment)
    assert src.index("await db.commit()") < src.index('"a2a.payment_authorized"')
    assert 'request.headers.get("x-a2a-rail") != "buy"' in src
    assert '"X-A2A-Rail": "buy"' in inspect.getsource(a2a_payment)


def test_an_expired_authorization_tells_the_payer_and_an_unpaid_payee(monkeypatch):
    from agentvault_registry.background_tasks import a2a_payment_expiry as ex
    calls = []

    async def _owners(type_key, dids, **kw):
        calls.append((type_key, tuple(dids), kw["title"]))

    monkeypatch.setattr(push_notify, "notify_agent_owners", _owners)

    async def go():
        ex._tell_expired([("did:payer", "did:svc"), ("did:payer", "did:svc2")], [("did:payer2", "did:svc")])
        await asyncio.sleep(0)
    run(go())
    titles = {(d[0], t) for _k, d, t in calls}
    assert ("did:payer", "A payment authorization expired unused") in titles
    assert ("did:payer2", "A payment authorization expired before it was settled") in titles
    assert ("did:svc", "Work went unpaid: its authorization expired") in titles
    assert len(calls) == 3 and {k for k, *_ in calls} == {"a2a.payment_expired"}


def test_a_bond_release_is_said_once_to_owner_and_funder(monkeypatch, sent):
    from agentvault_registry.services import reputation_bond as rb

    async def _devs(dids):
        return sorted({"did:agent": 6, "did:funder": 7}[d] for d in dids)

    monkeypatch.setattr(push_notify, "resolve_developer_ids_for_dids", _devs)
    for _ in range(2):   # two concurrent releases share their release_ref
        run(rb._tell_bond("did:agent", "did:funder", "bond.released:rel-1", "Reputation bond released", "m"))
        sent.flush()
    assert [(t, d) for t, d, *_ in sent] == [("bond.released", (6, 7))]
    for fn in (rb.release, rb.unlock):
        src = inspect.getsource(fn)
        assert src.index("await db.commit()") < src.index("await _tell_bond(")


# ── operations ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_failing_webhook_is_said_before_it_is_switched_off(sent):
    from agentvault_registry.services.webhook_service import WebhookService
    wh = types.SimpleNamespace(id=12, developer_id=6, is_active=True, failure_count=4,
                               url="https://hooks.example.org/t/SECRET-TOKEN?sig=abc")
    WebhookService._tell_failing(wh)
    assert sent == []                                 # four failures: nothing yet
    wh.failure_count = 5
    WebhookService._tell_failing(wh)
    wh.failure_count = 6
    WebhookService._tell_failing(wh)                  # the same day: once
    sent.flush()
    assert len(sent) == 1 and sent[0][:2] == ("webhook.failing", (6,))
    assert "hooks.example.org" in sent[0][3] and "SECRET" not in sent[0][3] and "sig=" not in sent[0][3]
    wh.is_active = False
    WebhookService._tell_failing(wh)
    sent.flush()
    assert len(sent) == 1                             # switched off: the switch-off has its own mail


def test_both_delivery_paths_tell_after_their_commit():
    import importlib
    src = inspect.getsource(importlib.import_module("agentvault_registry.services.webhook_service"))
    assert src.count("self._tell_failing(webhook)   # V0652 (af)") == 2


def test_an_unreadable_card_is_said_at_the_third_failure_in_a_row(sent):
    from agentvault_registry.background_tasks import agent_card_pullsync as ps
    row = types.SimpleNamespace(agent_did="did:a", developer_id=6, pull_failures=0)
    for status in ("timeout", "5xx", "timeout", "timeout"):
        ps._stamp_attempt(row, status, False)
    sent.flush()
    assert [(t, d) for t, d, *_ in sent] == [("agent.card_unreachable", (6,))]
    assert "did not answer in time" in sent[0][3]
    mirror = types.SimpleNamespace(agent_did="did:m", developer_id=None, pull_failures=2)
    ps._stamp_attempt(mirror, "timeout", False)      # a mirror nobody here owns
    skipped = types.SimpleNamespace(agent_did="did:s", developer_id=7, pull_failures=2)
    ps._stamp_attempt(skipped, "skipped", False)     # never read at all: not "unreadable"
    sent.flush()
    assert len(sent) == 1


# ── governance and commons ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_voters_are_the_members_or_the_stakers(monkeypatch):
    from agentvault_registry.services import governance_notices as gn
    from agentvault_registry.services import membership

    async def _members(db, now=None):
        return {6: None, 9: None}

    monkeypatch.setattr(membership, "members", _members)
    monkeypatch.setattr(membership, "member_mode", lambda: True)
    assert run(gn.voters(_DB())) == [6, 9]
    monkeypatch.setattr(membership, "member_mode", lambda: False)
    db = _DB(_Result([(7,), (8,)]))
    assert run(gn.voters(db)) == [7, 8] and "FROM stakes" in db.sql[0]


def test_a_new_proposal_reaches_every_voter_but_its_proposer(monkeypatch, sent):
    from agentvault_registry import database
    from agentvault_registry.services import governance_notices as gn

    async def _voters(db):
        return [6, 7, 9]

    monkeypatch.setattr(gn, "voters", _voters)
    monkeypatch.setattr(database, "get_db_context", lambda: _DB(_Result(scalar=7)))
    gn.tell_opened(3, "Raise the bond", dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc), "did:proposer")
    sent.flush()
    assert sent[0][:2] == ("governance.proposal_opened", (6, 9))


def test_a_result_is_said_once_whichever_tally_runs(monkeypatch, sent):
    from agentvault_registry import database
    from agentvault_registry.services import governance_notices as gn
    monkeypatch.setattr(database, "get_db_context", lambda: _DB(_Result([(6,), (9,)]), _Result(scalar=7)))
    for _ in range(2):   # the manual tally and the worker's
        gn.tell_result(3, "Raise the bond", "PASSED", 2, 1, "did:proposer")
        sent.flush()
    assert [(t, d) for t, d, *_ in sent] == [("governance.result", (6, 7, 9))]
    assert "passed (2 for, 1 against)" in sent[0][3]


def test_a_closing_vote_reminds_who_has_not_voted_once(monkeypatch, sent):
    from agentvault_registry.services import governance_notices as gn

    async def _voters(db):
        return [6, 7, 9]

    async def _voted(db, pid):
        return {7}

    monkeypatch.setattr(gn, "voters", _voters)
    monkeypatch.setattr(gn, "_voted", _voted)
    end = dt.datetime(2026, 11, 1, 20, 0, tzinfo=dt.timezone.utc)
    assert run(gn.remind_closing(_DB(_Result([(3, "Raise the bond", end)])))) == 1
    assert run(gn.remind_closing(_DB(_Result([(3, "Raise the bond", end)])))) == 0
    assert [(t, d) for t, d, *_ in sent] == [("governance.vote_closing", (6, 9))]


def test_governance_is_wired_where_its_actions_happen():
    from agentvault_registry.background_tasks import auto_tally
    from agentvault_registry.routers import governance
    assert "governance_notices.tell_opened(" in inspect.getsource(governance.create_proposal)
    assert "governance_notices.tell_result(" in inspect.getsource(governance.tally_proposal_votes)
    src = inspect.getsource(auto_tally.AutoTallyWorker._tally_cycle)
    assert "await governance_notices.remind_closing(db)" in src and "governance_notices.tell_result(" in src


def test_commons_notices_follow_their_commits(sent):
    from agentvault_registry.services import commons
    commons._tell("commons.award", [6, 6, None], "A commons award for your work", "m", once_key="commons.award:1:did:a")
    commons._tell("commons.award", [6], "A commons award for your work", "m", once_key="commons.award:1:did:a")
    sent.flush()
    assert [(t, d) for t, d, *_ in sent] == [("commons.award", (6,))]
    src = inspect.getsource(commons)
    assert '_tell("commons.season_opened"' in src and src.count('_tell("commons.season_paid"') == 2


# ── frame admins, applicants, approvals ──────────────────────────────────────────────────────────────────────────────

def test_an_operator_application_reaches_the_admins_and_its_decision_the_applicant(sent):
    from agentvault_registry.routers import operator_applications as oa
    oa._tell_application("operator.application_received", None, "Operator application received", "m")
    oa._tell_application("operator.application_decided", 6, "Your operator application was approved", "m")
    oa._tell_application("operator.application_decided", None, "x", "m")   # no linked account: nobody to tell
    sent.flush()
    assert [(t, d) for t, d, *_ in sent] == [("operator.application_received", ("admins",)),
                                            ("operator.application_decided", (6,))]
    src = inspect.getsource(oa)
    assert src.count('_tell_application("operator.application_decided", app_record.developer_id') == 2


def test_a_frames_request_to_federate_reaches_the_admins():
    from agentvault_registry.routers import frame_invitations
    src = inspect.getsource(frame_invitations)
    assert '"federation.invitation_received"' in src
    assert src.index("await db.commit()") < src.index('"federation.invitation_received"')


def test_an_approver_hears_their_approval_used():
    from agentvault_registry.routers import chat
    src = inspect.getsource(chat)
    i = src.index("used_at = await ca.mark_consumed(")
    j = src.index('"chat.approval_used_production" if prod else "chat.approval_used"')
    assert i < src.index("await db.commit()", i) < j
