"""V0666 (the maintainer's word, room seq 4478: "a switch for bond need yes or not ... new frames can use it and switch it later when the bonds matured"):
GOVERNANCE_MEMBER_BOND_REQUIRED, beside GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS in services/membership.py.

Default true: today's rule, nothing changes (and what the docs recommend for a network of strangers). False: NO bond is needed: a developer is a member from the day their first
active agent exists (verified, not suspended, not deleted, not a federation shadow, as for every member), and a bond that exists counts at once, with no minimum age and no
maturity. Asked for, room seq 4481: no approval guard and no protection against many accounts for the development and starter configuration. Pure: no database here (the SQL is
driven by a real Postgres, scratchpad/contributor-track/pg_verify_switch.py); the settings and the rules.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "agentvault_registry"
UTC = dt.timezone.utc
T0 = dt.datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
KNOBS = ("GOVERNANCE_WEIGHT_MODE", "GOVERNANCE_MEMBER_BOND_REQUIRED", "GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS", "GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND", "NETWORK_PROFILE")


@pytest.fixture(scope="module")
def m():
    sys.path.insert(0, str(SRC.parent))
    from agentvault_registry.services import membership as mod
    return mod


@pytest.fixture(autouse=True)
def _clean_knobs(monkeypatch, m):
    for k in KNOBS:
        monkeypatch.delenv(k, raising=False)
    m._np.reset_cache()
    yield
    m._np.reset_cache()


def _row(**kw):
    base = {"status": "locked", "funded_by": "self", "locked_at": T0, "matured_at": None, "agent_status": "active", "enforcement_status": "active"}
    base.update(kw)
    return base


def _since(m, row):
    return m.member_since_from_rows([row], now=T0 + dt.timedelta(days=400), min_age_days=m.min_bond_age_days(), requires_matured=m.requires_matured_bond())


def test_the_bond_is_required_by_default_and_a_typo_keeps_it(m, monkeypatch):
    assert m.bond_required() is True
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "flase")
    m._np.reset_cache()
    assert m.bond_required() is True                                                    # a typo never lowers the door
    for word in ("false", "0", "no", "off"):
        monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", word)
        m._np.reset_cache()
        assert m.bond_required() is False, word


def test_with_the_bond_required_today_s_waiting_rules_hold(m, monkeypatch):
    assert m.min_bond_age_days() == 30 and m.requires_matured_bond() is False
    monkeypatch.setenv("GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS", "7")
    monkeypatch.setenv("GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND", "true")
    m._np.reset_cache()
    assert m.min_bond_age_days() == 7 and m.requires_matured_bond() is True
    assert _since(m, _row(matured_at=None)) is None                                       # a locked bond is not matured: not a member yet


def test_with_it_off_membership_does_not_wait_for_the_bond_whatever_the_age_knobs_say(m, monkeypatch):
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "false")
    monkeypatch.setenv("GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS", "30")
    monkeypatch.setenv("GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND", "true")
    m._np.reset_cache()
    assert m.min_bond_age_days() == 0 and m.requires_matured_bond() is False
    just_locked = m.member_since_from_rows([_row()], now=T0, min_age_days=m.min_bond_age_days(), requires_matured=m.requires_matured_bond())
    assert just_locked == T0                                                              # a member from the moment the bond is locked


def test_a_bond_locked_today_waits_thirty_days_with_the_switch_on_and_not_with_it_off(m, monkeypatch):
    on = m.member_since_from_rows([_row()], now=T0 + dt.timedelta(days=29), min_age_days=m.min_bond_age_days(), requires_matured=m.requires_matured_bond())
    assert on is None
    on30 = m.member_since_from_rows([_row()], now=T0 + dt.timedelta(days=30), min_age_days=m.min_bond_age_days(), requires_matured=m.requires_matured_bond())
    assert on30 == T0 + dt.timedelta(days=30)
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "false")
    m._np.reset_cache()
    off = m.member_since_from_rows([_row()], now=T0, min_age_days=m.min_bond_age_days(), requires_matured=m.requires_matured_bond())
    assert off == T0


@pytest.mark.parametrize("row", [
    _row(funded_by="treasury"),                      # a bond the treasury funded is a demonstration, never a membership
    _row(status="released"),                         # a bond that ended
    _row(status="forfeited"),
    _row(agent_status="suspended"),                  # an agent the registry suspended
    _row(enforcement_status="revoked"),
    _row(locked_at=None),
], ids=["treasury", "released", "forfeited", "suspended", "revoked", "never-locked"])
def test_switching_the_wait_off_never_lets_a_bad_bond_in(m, monkeypatch, row):
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "false")
    m._np.reset_cache()
    assert m.member_since_from_rows([row], now=T0 + dt.timedelta(days=400), min_age_days=m.min_bond_age_days(), requires_matured=m.requires_matured_bond()) is None


def _agent(**kw):
    base = {"status": "active", "enforcement_status": "active", "created_at": T0}
    base.update(kw)
    return base


def test_with_the_bond_not_required_an_active_agent_makes_a_member_from_the_day_it_exists_with_no_bond_at_all(m, monkeypatch):
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "false")
    m._np.reset_cache()
    assert m.member_since_without_bond([_agent()], now=T0 + dt.timedelta(days=1)) == T0
    assert m.member_since_without_bond([_agent(created_at=T0 + dt.timedelta(days=5)), _agent()], now=T0 + dt.timedelta(days=9)) == T0       # the earliest agent
    assert m.member_since_without_bond([_agent(created_at=T0 + dt.timedelta(days=5))], now=T0) is None                                    # not before it exists


@pytest.mark.parametrize("agents", [[], [_agent(status="suspended")], [_agent(status="revoked")], [_agent(enforcement_status="suspended")],
                                    [_agent(enforcement_status="revoked")], [_agent(created_at=None)]], ids=["none", "suspended", "revoked", "enforced-suspended", "enforced-revoked", "no-date"])
def test_without_an_active_agent_there_is_no_membership_even_with_no_bond_needed(m, monkeypatch, agents):
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "false")
    m._np.reset_cache()
    assert m.member_since_without_bond(agents, now=T0 + dt.timedelta(days=400)) is None


def test_the_no_bond_path_is_only_for_the_switch_off(m, monkeypatch):
    assert m.no_bond_membership() is False                                               # required (the default): a member needs a bond that has aged
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "off")
    m._np.reset_cache()
    assert m.no_bond_membership() is True
    txt = (SRC / "services" / "membership.py").read_text()
    for fn in ("async def members(", "async def member_since_for(", "async def status_for_developer("):
        body = txt.split(fn, 1)[1].split("\nasync def ", 1)[0].split("\ndef ", 1)[0]
        assert "no_bond_membership()" in body, fn                                         # every reader of membership asks the same one place


def test_the_sentence_a_non_member_reads_is_true_in_both_states(m, monkeypatch):
    assert "30 days" in m.not_a_member_sentence()
    monkeypatch.setenv("GOVERNANCE_MEMBER_BOND_REQUIRED", "false")
    m._np.reset_cache()
    s = m.not_a_member_sentence()
    assert "0 days" not in s and "days old" not in s and "active agent" in s and "bond" in s


def test_the_public_numbers_name_the_switch_and_show_the_effective_waiting_rules():
    txt = (SRC / "services" / "membership.py").read_text()
    stats = txt.split("async def stats(", 1)[1].split("\n\n\n", 1)[0]
    assert '"bond_required": bond_required()' in stats
    assert '"min_bond_age_days": min_age' in stats                                        # min_age is min_bond_age_days(): the effective value
    commons = (SRC / "services" / "commons.py").read_text()
    assert "_membership.min_bond_age_days()" in commons                                     # the commons rules echo the same effective value


def test_the_switch_is_read_in_one_place():
    txt = (SRC / "services" / "membership.py").read_text()
    assert txt.count("GOVERNANCE_MEMBER_BOND_REQUIRED") >= 1
    for p in (SRC / "services").rglob("*.py"):
        if p.name != "membership.py":
            assert "GOVERNANCE_MEMBER_BOND_REQUIRED" not in p.read_text(), p.name
