"""V0667 the developer passport, step 1 (order gwo_fb84e57318de0802725ab511; sessionlogs2026/DESIGN_2026-11-16_DEVELOPER_PASSPORT.md
sections 2 to 5): a developer homed on another registry proposes and reviews on EU through their home, with no account on EU. The pure
rules of services/code_passport, pinned without a database:

  - the card a home signs for code governance discloses only what EU needs (no e-mail, no organisations) and names its purpose, so an
    exchange card can never be replayed here and this card never buys anything
  - the home's standing: active only for a verified developer, not suspended, with no deletion pending, and an active agent
  - EU refuses a card that is not for code governance, older than its age limit, or from the future
  - the presenter is BOUND to the card's home: the mTLS identity's trust domain names one ACTIVE peer row, whose name is the card's
    home registry, and whose licence verdict is not refused while the licence is enforced
  - a contributor's key in the rail's developer columns is the negative of its row id (one rule, here)
  - votes stay EU's members': no act but propose, review and the repository account's two (status, link) is accepted
  - phase 4 (session-lead seq 5367): a card says closed when the home deleted the developer; the governing registry moves a
    contributor's standing and queues their repository account's leg by one rule (pause, restore, close; closed never restores); the
    code host account names the home registry and the developer
RED: services/code_passport.py does not exist.
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace as NS

import pytest

from agentvault_registry.services import code_passport as cp

NOW = dt.datetime(2026, 11, 16, 12, 0, tzinfo=dt.timezone.utc)


def _dev(**kw):
    # the card carries the PUBLIC display name (the governing registry shows it on public records), never the account name
    base = dict(id=42, name="ada-account", display_name="Ada", email="ada@home.test", is_verified=True, is_suspended=False, deletion_status=None,
                deletion_requested_at=None, deleted_at=None)
    return NS(**{**base, **kw})


def _agent(**kw):
    return NS(**{**dict(did="did:theprotocol:asia:abc", status="active"), **kw})


def test_the_card_discloses_only_what_eu_needs_and_names_its_purpose():
    assert cp.card_payload(_dev(display_name="ada@home.test"), _agent(), "ASIA", NOW)["display_name"] is None    # never an address
    p = cp.card_payload(_dev(), _agent(), "ASIA", NOW)
    assert p == {"schema": "devcard/0.1", "purpose": "code_governance", "developer_ref": "42", "display_name": "Ada",
                 "home_registry": "ASIA", "standing": "active", "agent_did": "did:theprotocol:asia:abc",
                 "issued_at": NOW.isoformat()}


@pytest.mark.parametrize("dev,agent", [
    ({"is_verified": False}, {}), ({"is_suspended": True}, {}), ({"deletion_status": "pending"}, {}),
    ({"deletion_requested_at": NOW}, {}), ({}, {"status": "suspended"}),
])
def test_standing_is_active_only_in_good_standing(dev, agent):
    assert cp.home_standing(_dev(**dev), _agent(**agent)) == "suspended"
    assert cp.home_standing(_dev(), _agent()) == "active"


def test_a_deleted_developer_is_closed_not_suspended():
    assert cp.home_standing(_dev(deleted_at=NOW), _agent()) == "closed"
    assert cp.home_standing(_dev(deleted_at=NOW, is_suspended=True), _agent()) == "closed"


@pytest.mark.parametrize("current,card,want", [
    ("active", "active", ("active", None)),
    ("active", "suspended", ("paused", "pause")),
    ("paused", "suspended", ("paused", None)),
    ("paused", "active", ("active", "restore")),
    ("active", "closed", ("closed", "close")),
    ("paused", "closed", ("closed", "close")),
    ("closed", "closed", ("closed", None)),
    ("closed", "active", ("closed", None)),                       # a closed contributor is never restored
    ("closed", "suspended", ("closed", None)),
])
def test_one_rule_moves_the_standing_and_names_the_repository_leg(current, card, want):
    assert cp.standing_change(current, card) == want


def test_the_code_host_account_names_the_home_and_the_developer():
    assert cp.host_full_name("Ada", "ASIA", "42") == "Ada (ASIA, developer 42)"
    assert cp.host_full_name(None, "ASIA", "42") == "Developer 42 of ASIA"


def _env(**over):
    p = {**cp.card_payload(_dev(), _agent(), "ASIA", NOW), **over}
    return {"payload": p, "signature": {"alg": "EdDSA", "kid": "k#1", "value": "sig"}}


def test_a_fresh_card_for_code_governance_passes():
    assert cp.card_refusal(_env(), NOW) is None
    assert cp.card_refusal(_env(), NOW + dt.timedelta(seconds=cp.CARD_MAX_AGE_SECONDS - 1)) is None


@pytest.mark.parametrize("env,code", [
    (_env(purpose="exchange_participation"), "wrong_purpose"),
    (_env(purpose=None), "wrong_purpose"),
    (_env(schema="devcard/9"), "card_malformed"),
    (_env(issued_at="yesterday"), "card_malformed"),
    ({"payload": {}, "signature": {}}, "card_malformed"),
])
def test_a_card_not_for_code_governance_or_malformed_is_refused(env, code):
    assert cp.card_refusal(env, NOW)[:2] == (403, code)


def test_an_old_or_future_card_is_refused():
    assert cp.card_refusal(_env(), NOW + dt.timedelta(seconds=cp.CARD_MAX_AGE_SECONDS + 1))[:2] == (403, "card_expired")
    assert cp.card_refusal(_env(), NOW - dt.timedelta(seconds=cp.CARD_SKEW_SECONDS + 1))[:2] == (403, "card_not_yet_valid")


ROWS = [("ASIA", "frame", "ACTIVE", "asia.theprotocol.cloud", "licensed"),
        ("old-asia", "frame", "INACTIVE", "old.theprotocol.cloud", "licensed"),
        ("rogue", "frame", "ACTIVE", "rogue.example", "revoked")]


def test_the_presenter_is_bound_to_the_cards_home():
    assert cp.bind_presenter(ROWS, "spiffe://asia.theprotocol.cloud/service/registry", "ASIA", "enforce") == ("ASIA", None)
    assert cp.bind_presenter(ROWS, "spiffe://ASIA.theprotocol.cloud/service/registry", "asia", "enforce") == ("ASIA", None)


@pytest.mark.parametrize("spiffe,home,mode,code", [
    ("spiffe://nobody.example/service/registry", "ASIA", "enforce", "unknown_peer"),
    ("spiffe://old.theprotocol.cloud/service/registry", "old-asia", "enforce", "unknown_peer"),     # an INACTIVE row binds nothing
    ("spiffe://asia.theprotocol.cloud/service/registry", "EU", "enforce", "home_mismatch"),           # a peer relaying another home's card
    ("spiffe://rogue.example/service/registry", "rogue", "enforce", "licence_refused"),
    ("not-a-spiffe-id", "ASIA", "enforce", "unknown_peer"),
])
def test_a_presenter_that_is_not_the_cards_active_licensed_home_is_refused(spiffe, home, mode, code):
    name, refusal = cp.bind_presenter(ROWS, spiffe, home, mode)
    assert name is None and refusal[:2] == (403, code)


def test_a_refused_licence_only_logs_while_the_licence_is_observed():
    assert cp.bind_presenter(ROWS, "spiffe://rogue.example/service/registry", "rogue", "observe") == ("rogue", None)


def test_a_contributors_key_is_the_negative_of_its_row_id():
    assert cp.contributor_key(7) == -7
    assert cp.contributor_id_of(-7) == 7
    assert cp.contributor_id_of(7) is None and cp.contributor_id_of(None) is None


def test_only_propose_review_and_the_repository_account_are_relayed_and_a_vote_is_refused_with_a_sentence():
    assert cp.ACTS == ("propose", "review", "repo_status", "repo_link")
    status, code, sentence = cp.act_refusal("vote")
    assert (status, code) == (403, "votes_members_only") and "members" in sentence
    assert all(cp.act_refusal(a) is None for a in cp.ACTS)
    assert cp.act_refusal("merge")[:2] == (404, "unknown_act")


def test_main_mounts_the_routes_and_starts_the_standing_pull():
    import pathlib
    src = pathlib.Path(cp.__file__).resolve().parents[1]
    main = (src / "main.py").read_text()
    assert "routers import code_passport" in main and "code_passport_standing_loop" in main
    worker = (src / "background_tasks" / "code_passport_standing.py").read_text()
    # one leader pulls (the acquiring call, never the read-only check), reports an outcome, and only where code is governed
    assert "try_acquire_leadership(\"code_passport_standing\")" in worker and "_vitals.cycle(\"code_passport_standing\")" in worker
    assert "is_governing()" in worker and "pull_standing_once" in worker


def test_the_literal_standing_route_is_registered_before_the_act_route():
    from agentvault_registry.routers import code_passport as R
    paths = [r.path for r in R.router.routes]
    assert paths.index("/api/v1/federation/code-passport/standing") < paths.index("/api/v1/federation/code-passport/{act}")


async def test_with_no_governing_registry_named_there_is_no_passport(monkeypatch):
    # production today: CODE_CHANGES_GOVERNING_REGISTRY unset on every registry, so nobody governs code; the press must not offer a
    # place that does not exist (the governing sentence's default name is a place to go, never a registry to send cards to)
    monkeypatch.delenv("CODE_CHANGES_GOVERNING_REGISTRY", raising=False)

    async def first_agent(db, dev, did):
        return _agent()
    monkeypatch.setattr(cp, "_first_agent", first_agent)
    st = await cp.consent_state(None, _dev(code_passport_consent_at=None))
    assert st["available"] is False and st["preview"] is None
    status, out = await cp.relay(None, _agent(), "propose", {})
    assert (status, out["code"]) == (409, "no_governing_registry")
    monkeypatch.setenv("CODE_CHANGES_GOVERNING_REGISTRY", "EU")
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "ASIA")
    assert (await cp.consent_state(None, _dev(code_passport_consent_at=None)))["available"] is True
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "EU")                     # the governing registry itself offers no passport
    assert (await cp.consent_state(None, _dev(code_passport_consent_at=None)))["available"] is False
