"""§CARDBOND (2026-09-11) — the signed card publishes the bond an agent is actually charged, and a
vote cannot target a rule an env var or the network profile decides.

Measured live on EU (V0349): the card's `policy.declared_params["enforcement.reputation_bond_min_avt"]`
read {"value": 50, "source": "policy"} while the bond rail charged 250, because `bond_amount()`
reads REPUTATION_BOND_AMOUNT (env > the network profile `lowsupply-2026` = 250 > the document) and
the card read only the document. EU's stored row carries 50 under BOTH names, so a policy_change to
either would have passed, been stored, and changed nothing an agent pays. ASIA (no row): the card
said 50 "default", charged 250.

Every test marked RED failed against V0349 and passes now; CONTROL passes against both.
"""
from __future__ import annotations

import json
import pathlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.core import network_profile as np
from agentvault_registry.services import frame_policy as fp
from agentvault_registry.services import reputation_bond as rb
from agentvault_registry.services.registry_card_builder import _build_policy_block

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
if not SRC.is_dir():
    SRC = pathlib.Path("/w/src/agentvault_registry")
if not SRC.is_dir():
    SRC = pathlib.Path("/app/src/agentvault_registry")

BOND = "enforcement.reputation_bond_min_avt"
# The rail's six knob-wrapped rules, as reputation_bond read them at V0349.
KNOBS = {
    "enforcement.reputation_bond_min_avt": "REPUTATION_BOND_AMOUNT",
    "enforcement.bond_maturity_min_transactions": "REPUTATION_BOND_MIN_TRANSACTIONS",
    "enforcement.bond_maturity_min_age_days": "REPUTATION_BOND_MIN_AGE_DAYS",
    "enforcement.bond_maturity_min_trust_percentile": "REPUTATION_BOND_MIN_TRUST_PERCENTILE",
    "enforcement.bond_maturity_min_rated_peers": "REPUTATION_BOND_MIN_RATED_PEERS",
    "enforcement.bond_maturity_releases_percent": "REPUTATION_BOND_MATURITY_RELEASES_PERCENT",
}
# EU's stored row, as far as the bond is concerned (read live 2026-09-11, version 2).
EU_ROW = {"enforcement": {"reputation_bond_min_avt": 50},
          "reputation_bond": {"amount_avt": 50, "min_transactions": 10, "min_age_days": 30}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for knob in KNOBS.values():
        monkeypatch.delenv(knob, raising=False)
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    monkeypatch.delenv("NETWORK_PROFILE_DIR", raising=False)
    np.reset_cache()
    yield
    np.reset_cache()


def _profile(tmp_path, monkeypatch, **knobs):
    (tmp_path / "network_profile.t.env").write_text("".join(f"{k}={v}\n" for k, v in knobs.items()))
    monkeypatch.setenv("NETWORK_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("NETWORK_PROFILE", "t")
    np.reset_cache()
    assert np.load() == {k: str(v) for k, v in knobs.items()}   # loaded, not merely selected


def _policy(row):
    return fp.ResolvedPolicy(doc=fp.resolve(row), version=(2 if row else 0),
                             source=("amended" if row else "factory_default"), _row_json=row)


def _card_entry(row):
    block = _build_policy_block(_policy(row))
    return block["declared_params"][BOND], block["bounded_params"][BOND]


# ── RED: the card ───────────────────────────────────────────────────────────────────────────────────

def test_eu_card_publishes_the_bond_the_profile_charges(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    charged = rb.bond_amount(_policy(EU_ROW).doc)
    assert charged == Decimal("250")
    entry, bounded = _card_entry(EU_ROW)
    assert entry["value"] == 250 == bounded
    assert entry["source"] == "default"      # the profile decided it, not this frame


def test_asia_card_with_no_row_publishes_the_same(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    entry, _ = _card_entry(None)
    assert (entry["value"], entry["source"]) == (250, "default")


def test_an_operator_env_value_is_the_frames_own_choice(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    monkeypatch.setenv("REPUTATION_BOND_AMOUNT", "300")
    entry, _ = _card_entry(EU_ROW)
    assert (entry["value"], entry["source"]) == (300, "policy")


def test_explain_names_who_decided(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    e = _policy(EU_ROW).explain(BOND)
    assert (e["value"], e["policy_value"], e["governed_by"], e["knob"]) == \
        (250, 50, "network_profile", "REPUTATION_BOND_AMOUNT")
    assert e["in_bounds"] is True


def test_every_knob_the_bond_rail_reads_is_in_the_table(monkeypatch):
    """One table, and the rail reads its knob names from it: for each rule, setting the knob named
    in the table moves both what the rail applies and what the card reads."""
    assert fp.KNOB_OVERRIDES == KNOBS
    distinct = {"REPUTATION_BOND_AMOUNT": "321", "REPUTATION_BOND_MATURITY_RELEASES_PERCENT": "70"}
    for path, knob in KNOBS.items():
        value = distinct.get(knob, "17")
        monkeypatch.setenv(knob, value)
        assert str(rb.applied_rule(path, None)) == value, path
        assert str(_policy(None).explain(path)["value"]) == value, path
        monkeypatch.delenv(knob)


# ── CONTROL: nothing moves where no knob is set, and nothing leaks into the document ──────────────

def test_no_knob_leaves_the_card_as_it_was():
    assert _card_entry(EU_ROW)[0] == {"value": 50, "source": "policy", "allowed": {"min": 50, "max": None}}
    assert _card_entry(None)[0]["source"] == "default"


def test_the_policy_hash_does_not_move_with_a_knob(tmp_path, monkeypatch):
    before = _policy(EU_ROW).hash()
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    assert _policy(EU_ROW).hash() == before


def test_the_entry_stays_inside_the_served_schema(tmp_path, monkeypatch):
    """No schema change: the entry's keys and its source word must be ones the served v0.6 schema
    already allows (peers do not validate against it today; the next one might)."""
    schema = json.loads((SRC / "static_schemas" / "registry_card_v0.6.schema.json").read_text())
    shape = schema["properties"]["policy"]["properties"]["declared_params"]["additionalProperties"]
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    for row in (EU_ROW, None):
        entry, _ = _card_entry(row)
        assert set(entry) <= set(shape["properties"]), entry
        assert entry["source"] in shape["properties"]["source"]["enum"]


# ── the vote ────────────────────────────────────────────────────────────────────────────────────────

class _Created(BaseException):
    """Raised where the proposal would be written, so reaching it is observable (BaseException, so
    the route's `except Exception` cannot turn it into a 500)."""


@pytest.fixture
def propose(monkeypatch):
    from agentvault_registry.crud import crud_governance
    from agentvault_registry.routers import governance

    async def _load(db):
        return _policy(EU_ROW)

    async def _create(**kw):
        raise _Created(kw.get("policy_diff"))

    monkeypatch.setattr(fp, "load", _load)
    monkeypatch.setattr(crud_governance, "create_proposal", _create)
    agent = SimpleNamespace(did="did:theprotocol:eu.theprotocol.cloud:voter", staked_balance=Decimal("1000"))

    async def _go(diff):
        p = governance.ProposalCreate(title="bond", description="change the bond", duration_seconds=3600,
                                      proposal_type="policy_change", policy_diff=diff)
        return await governance.create_proposal(p, None, agent)
    return _go


@pytest.mark.asyncio
async def test_a_vote_to_move_a_profile_governed_bond_is_refused(tmp_path, monkeypatch, propose):   # RED
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    with pytest.raises(HTTPException) as exc:
        await propose({"enforcement": {"reputation_bond_min_avt": 300}})
    assert exc.value.status_code == 409
    assert "knob_governed" in exc.value.detail and "REPUTATION_BOND_AMOUNT" in exc.value.detail


@pytest.mark.asyncio
async def test_the_deprecated_name_is_refused_too(tmp_path, monkeypatch, propose):   # RED
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    with pytest.raises(HTTPException) as exc:
        await propose({"reputation_bond": {"amount_avt": 300}})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_restating_todays_value_is_not_a_move(tmp_path, monkeypatch, propose):   # CONTROL
    """Diff-based: EU's row says 50, so a diff that restates 50 and changes something else is a
    real vote and must reach the proposal store."""
    _profile(tmp_path, monkeypatch, REPUTATION_BOND_AMOUNT=250)
    with pytest.raises(_Created):
        await propose({"enforcement": {"reputation_bond_min_avt": 50},
                       "governance": {"standard_quorum_percent": 15}})


@pytest.mark.asyncio
async def test_without_a_knob_the_same_vote_is_allowed(propose):   # CONTROL
    with pytest.raises(_Created):
        await propose({"enforcement": {"reputation_bond_min_avt": 300}})
