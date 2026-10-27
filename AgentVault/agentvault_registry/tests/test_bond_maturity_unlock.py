"""§BONDFILL-3 (2026-09-11) — maturity unlocks capital, the trust gate is relative, one key per rule.

His decision: maturity should unlock capital instead of ending the business, the trust gate should
be relative, and it belongs in policy. Each test here names the defect it pins and carries a control
that must fail on the pre-fix tree — a test that cannot fail measures nothing.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agentvault_registry.core.base_network_params import BOUNDED_PARAMS
from agentvault_registry.services import frame_policy as fp
from agentvault_registry.services import reputation_bond as rb

TH = {"min_transactions": 10, "min_age_days": 30, "min_trust_percentile": 50,
      "min_rated_peers": 3, "min_ranked_population": 10, "releases_percent": 60}


def _trust(raters, pct, pop):
    return rb.progress_dict(transactions=10, age_days=30, eigentrust=0.0, thresholds=TH,
                            rated_peers=raters, trust_percentile=pct, trust_population=pop)


# ── 1. ONE KEY PER RULE ───────────────────────────────────────────────────────────────────────

def test_the_absolute_trust_gate_is_retired_and_the_relative_rules_are_bounded():
    """The retired bound guarded `enforcement.bond_min_eigentrust_at_maturity`, which NO CODE READ,
    while the gate read `reputation_bond.min_eigentrust`, which had no bound at all."""
    assert "enforcement.bond_min_eigentrust_at_maturity" not in BOUNDED_PARAMS
    assert BOUNDED_PARAMS["enforcement.bond_maturity_min_trust_percentile"] == {"min": 50, "max": 95}
    assert BOUNDED_PARAMS["enforcement.bond_maturity_min_rated_peers"] == {"min": 3, "max": 100}
    assert BOUNDED_PARAMS["enforcement.bond_maturity_releases_percent"] == {"min": 0, "max": 80}


def test_the_factory_default_validates_clean():
    """§FRAMEPOLICY's own control: the shipped default must pass the shipped validator. It did not
    once (DEFAULT_POLICY_JSON failed admission), which is why this is asserted, not assumed."""
    from agentvault_registry.crud.crud_enforcement import DEFAULT_POLICY_JSON
    assert fp.validate_document(DEFAULT_POLICY_JSON) == []


def test_a_frame_carrying_the_old_keys_still_validates():
    """EU's amended row holds BOTH copies of every bond rule, including the two retired trust keys.
    Refusing them would fail the frame's own document at its next governance vote."""
    eu_shaped = {
        "reputation_bond": {"amount_avt": 50, "min_transactions": 10, "min_age_days": 30,
                            "min_eigentrust": 0.1},
        "enforcement": {"reputation_bond_min_avt": 50, "bond_maturity_min_transactions": 10,
                        "bond_maturity_min_age_days": 30, "bond_min_eigentrust_at_maturity": 0.1},
    }
    assert fp.validate_document(eu_shaped) == []


def test_an_alias_is_bound_by_its_canonical_range():
    """THE HOLE THIS CLOSES: `_promote_aliases` turns an old-key value into the canonical value at
    resolve time, so an unchecked alias was a way round every bound — submit the old name, get the
    value the new one forbids. The canonical key refuses 2 settlements (floor 5); so must its alias."""
    problems = fp.validate_document({"reputation_bond": {"min_transactions": 2}})
    assert any("deprecated name of 'enforcement.bond_maturity_min_transactions'" in p for p in problems)
    # CONTROL: the same value under the canonical name was always refused.
    assert fp.validate_document({"enforcement": {"bond_maturity_min_transactions": 2}})
    # And an in-range alias passes.
    assert fp.validate_document({"reputation_bond": {"min_transactions": 12}}) == []


def test_the_gate_reads_the_canonical_key_and_honours_the_alias():
    assert rb.maturity_thresholds({"enforcement": {"bond_maturity_min_transactions": 14}})["min_transactions"] == 14
    # A frame that wrote only the old name meant it.
    assert rb.maturity_thresholds({"reputation_bond": {"min_transactions": 12}})["min_transactions"] == 12
    # Both present: the canonical one wins (it is the one the card publishes).
    both = {"enforcement": {"bond_maturity_min_transactions": 14}, "reputation_bond": {"min_transactions": 12}}
    assert rb.maturity_thresholds(both)["min_transactions"] == 14


def test_matured_can_never_mean_unbonded_whatever_the_source(monkeypatch):
    """The ceiling of 80 binds at USE time too: an env knob never passes through the validator,
    so a bound that only the validator enforced would bind one of three layers."""
    assert fp.validate_document({"enforcement": {"bond_maturity_releases_percent": 81}})
    monkeypatch.setenv("REPUTATION_BOND_MATURITY_RELEASES_PERCENT", "100")
    assert rb.maturity_thresholds({})["releases_percent"] == 80
    monkeypatch.setenv("REPUTATION_BOND_MATURITY_RELEASES_PERCENT", "-5")
    assert rb.maturity_thresholds({})["releases_percent"] == 0


# ── 2. THE TRUST GATE IS RELATIVE, AND CAN SAY WHEN IT CANNOT BE MEASURED ─────────────────────

def test_evidence_is_required_even_at_the_top_of_the_ranking():
    """Ten settlements with one friend is not ten opinions: the 100th percentile does not stand in
    for independent raters."""
    p = _trust(raters=2, pct=100.0, pop=17)
    assert p["met"]["trust"] is False
    assert _trust(raters=3, pct=100.0, pop=17)["met"]["trust"] is True


def test_standing_is_measured_against_the_frame_when_it_can_be():
    assert _trust(raters=5, pct=49.0, pop=17)["met"]["trust"] is False
    assert _trust(raters=5, pct=50.0, pop=17)["met"]["trust"] is True
    assert _trust(raters=5, pct=50.0, pop=17)["trust_percentile_state"] == "measured"


def test_a_population_too_small_to_rank_waives_standing_and_says_so():
    p = _trust(raters=3, pct=None, pop=9)
    assert p["trust_percentile_state"] == "waived"
    assert p["met"]["trust"] is True, "an agent must not fail for the network's youth"
    # but evidence is still the agent's to earn
    assert _trust(raters=2, pct=None, pop=9)["met"]["trust"] is False


def test_waived_and_unknown_are_different_states():
    """A waiver is a decision about a MEASURED fact (too few ranked). If the population was never
    measured there is nothing to decide about, and unknown must not pass."""
    unknown = _trust(raters=5, pct=None, pop=None)
    assert unknown["trust_percentile_state"] == "unknown"
    assert unknown["met"]["trust"] is False
    # CONTROL: the same agent with a MEASURED small population is waived, and passes.
    assert _trust(raters=5, pct=None, pop=3)["met"]["trust"] is True


def test_the_trust_segment_is_only_as_full_as_its_weaker_half():
    p = rb.progress_dict(transactions=10, age_days=30, eigentrust=0.0, thresholds=TH,
                         rated_peers=1, trust_percentile=90.0, trust_population=17)
    assert p["met"]["trust"] is False
    # tx 1.0, age 1.0, trust min(1/3, 1.0) -> percent = round(100 * 2.333 / 3) = 78
    assert p["percent"] == 78
    assert p["blocking"] == ["trust"]


def test_the_ranking_is_cume_dist_not_percent_rank():
    """MEASURED ON EU BEFORE SHIPPING: percent_rank put every bonded agent at the 0th percentile,
    including one already rated by three independent peers, because it ranks a TIE at the lowest
    position and a young network's agents mostly share one teleport-floor trust. Pinned by the
    STATEMENT (§DIRFEED-2): a fixture with distinct values passes with either function."""
    sql = str(rb._PROGRESS_SQL.text)
    assert "cume_dist() OVER" in sql
    assert "percent_rank" not in sql


def test_the_query_names_columns_that_exist_and_excludes_system_accounts():
    """`agents.developer_id` does not exist — it is `creator_developer_id` — and a guessed column
    inside discovery's try/except would blank every bond on the page with a log line. The treasury
    held 99.67 % of EU's vector with no incoming edge, so system accounts are out of both halves."""
    sql = str(rb._PROGRESS_SQL.text)
    assert "creator_developer_id" in sql and ".developer_id" not in sql.replace("creator_developer_id", "")
    assert sql.count("left(") >= 2, "system accounts excluded from the ranking AND from the raters"
    assert rb.SYSTEM_DID_PREFIX == "did:theprotocol:teg_system_"


# ── 3. THE SNAPSHOT A MIRROR RECEIVES ─────────────────────────────────────────────────────────

def test_snapshot_v2_carries_the_relative_gate_and_still_no_clock_fields():
    m = rb.maturity_params(_trust(raters=3, pct=82.4, pop=17))
    assert m["version"] == 2
    assert m["rated_peers"] == 3 and m["trust_percentile"] == 82.4 and m["trust_population"] == 17
    assert "age_days" not in m and "percent" not in m


def test_a_v1_snapshot_is_unknown_trust_never_guessed_from_the_retired_number():
    """An origin still on V0343/V0344 sends only the absolute eigentrust. Reading a gate from a
    number that no longer gates would be inventing an answer."""
    v1 = {"locked_at": "2026-09-08T00:00:00+00:00",
          "maturity": {"version": 1, "transactions": 4, "eigentrust": 0.9,
                       "thresholds": {"min_transactions": 10, "min_age_days": 30}}}
    r = rb.progress_from_card(v1)
    assert r["trust_percentile_state"] == "unknown" and r["met"]["trust"] is False


# ── 4. WHAT THE BAR SHOWS ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,unlocked,want", [
    ("locked", None, None),
    ("matured", None, "burning"),
    ("matured", "2026-10-10T00:00:00+00:00", "embers"),
    ("released", None, "extinguished"),
    ("forfeited", None, None),
    ("none", None, None),
])
def test_fire_state(status, unlocked, want):
    assert rb.fire_state(status, unlocked) == want


def _bond(**kw):
    base = dict(id="b1", agent_did="did:theprotocol:x", amount=Decimal("250"), status="matured",
                locked_at=datetime.now(timezone.utc) - timedelta(days=45),
                matured_at=datetime.now(timezone.utc) - timedelta(days=10),
                released_at=None, forfeited_at=None, funded_by="wallet", funder_did="did:theprotocol:w",
                escrow_ref="e", teg_transaction_id="t", release_ref=None, release_teg_transaction_id=None,
                partial_released_amount=None, partial_released_at=None, partial_release_ref=None,
                partial_release_teg_transaction_id=None, updated_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_unlock_readiness_names_the_one_reason():
    assert rb.unlock_block(_bond(), TH)["available"] is True
    ub = rb.unlock_block(_bond(), TH)
    assert ub["amount"] == "150" and ub["keeps"] == "100" and ub["percent"] == 60
    assert rb.unlock_block(_bond(status="locked"), TH)["reason"] == "not_matured"
    assert rb.unlock_block(_bond(partial_released_at=datetime.now(timezone.utc)), TH)["reason"] == "already_unlocked"
    assert rb.unlock_block(_bond(funded_by="treasury"), TH)["reason"] == "treasury_backstop"
    assert rb.unlock_block(_bond(), dict(TH, releases_percent=0))["reason"] == "frame_releases_nothing"
    fresh = _bond(matured_at=datetime.now(timezone.utc) - timedelta(hours=1))
    assert rb.unlock_block(fresh, TH)["reason"] == "cooldown"


def test_the_unlock_rounds_down_and_never_overpays():
    odd = rb.unlock_block(_bond(amount=Decimal("0.000000000000000003")), dict(TH, releases_percent=50))
    assert Decimal(odd["amount"]) + Decimal(odd["keeps"]) == Decimal("0.000000000000000003")
    assert Decimal(odd["amount"]) <= Decimal("0.0000000000000000015")


def test_bond_dict_carries_the_unlock_and_the_original():
    b = _bond(amount=Decimal("100"), partial_released_amount=Decimal("150"),
              partial_released_at=datetime.now(timezone.utc))
    d = rb.bond_dict(b, required=Decimal("250"), progress=None, thresholds=TH)
    assert d["original_amount"] == "250" and d["amount"] == "100"
    assert d["fire"] == "embers" and d["is_bonded"] is True
    assert d["unlock"]["reason"] == "already_unlocked"


def test_a_mirror_draws_embers_not_a_full_fire():
    """If the unlock did not travel, a mirror would draw a full fire for an agent that had taken
    its capital back — a costly signal counterfeited by omission."""
    b = _bond(amount=Decimal("100"), partial_released_amount=Decimal("150"),
              partial_released_at=datetime.now(timezone.utc))
    state = {"bond": rb.bond_dict(b, required=Decimal("250"), progress=None, thresholds=TH)}
    params = rb.extension_from_card(rb.inject_extension({}, state))
    assert params["partial_released_at"] and params["original_amount"] == "250"
    assert rb.fire_state(params["status"], params["partial_released_at"]) == "embers"


# ── 5. THE UNLOCK RAIL MOVES MONEY ONCE, AND STAYS BONDED ─────────────────────────────────────

class _DB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


def _wire(monkeypatch, bond, paid):
    async def load_bond(db, did):
        return bond

    async def activity_batch(db, dids):
        return {d: dict(rb._NO_ACTIVITY, transactions=12, rated_peers=4, trust_percentile=80.0,
                        trust_population=17) for d in dids}

    async def noop(*a, **k):
        return None

    async def payout(db, target, amount, ref, reason=""):
        # THE ORDERING THAT MAKES A RETRY SAFE: the ref is on the row before any money moves.
        assert bond.partial_release_ref == ref or bond.release_ref == ref
        paid.append((target, Decimal(str(amount)), ref, reason))
        return {"transaction_id": f"tx-{len(paid)}"}

    monkeypatch.setattr(rb, "load_bond", load_bond)
    monkeypatch.setattr(rb, "activity_batch", activity_batch)
    monkeypatch.setattr(rb, "touch_native_card", noop)
    monkeypatch.setattr(rb, "_emit", noop)
    import agentvault_registry.services.escrow as esc
    monkeypatch.setattr(esc, "escrow_payout", payout)


@pytest.mark.asyncio
async def test_unlock_pays_the_share_and_the_agent_stays_bonded(monkeypatch):
    bond, paid = _bond(), []
    agent = SimpleNamespace(did=bond.agent_did, reputation_bond_amount=Decimal("250"),
                            reputation_bond_status="matured")
    _wire(monkeypatch, bond, paid)
    out = (await rb.unlock(_DB(), agent, actor="test", policy={}))
    assert paid == [("did:theprotocol:w", Decimal("150"), bond.partial_release_ref, "bond_unlock")]
    assert out.amount == Decimal("100") and out.partial_released_amount == Decimal("150")
    assert out.status == "matured" and rb.is_bonded_status(out.status), "MATURED NEVER MEANS UNBONDED"
    assert agent.reputation_bond_amount == Decimal("100")
    assert rb.fire_state(out.status, out.partial_released_at) == "embers"


@pytest.mark.asyncio
async def test_a_second_unlock_is_refused_and_moves_nothing(monkeypatch):
    from fastapi import HTTPException
    bond, paid = _bond(), []
    agent = SimpleNamespace(did=bond.agent_did, reputation_bond_amount=Decimal("250"),
                            reputation_bond_status="matured")
    _wire(monkeypatch, bond, paid)
    (await rb.unlock(_DB(), agent, actor="test", policy={}))
    with pytest.raises(HTTPException) as e:
        (await rb.unlock(_DB(), agent, actor="test", policy={}))
    assert e.value.status_code == 409 and len(paid) == 1


@pytest.mark.asyncio
async def test_release_after_unlock_pays_the_remainder_and_is_the_exit(monkeypatch):
    bond, paid = _bond(), []
    agent = SimpleNamespace(did=bond.agent_did, reputation_bond_amount=Decimal("250"),
                            reputation_bond_status="matured")
    _wire(monkeypatch, bond, paid)
    (await rb.unlock(_DB(), agent, actor="test", policy={}))
    out = (await rb.release(_DB(), agent, actor="test", policy={}))
    assert [p[1] for p in paid] == [Decimal("150"), Decimal("100")], "250 back in total, never more"
    assert out.status == "released" and not rb.is_bonded_status(out.status)
    assert rb.fire_state(out.status, out.partial_released_at) == "extinguished"


@pytest.mark.asyncio
async def test_a_treasury_backstopped_bond_unlocks_nothing(monkeypatch):
    from fastapi import HTTPException
    bond, paid = _bond(funded_by="treasury"), []
    agent = SimpleNamespace(did=bond.agent_did, reputation_bond_amount=Decimal("250"),
                            reputation_bond_status="matured")
    _wire(monkeypatch, bond, paid)
    with pytest.raises(HTTPException) as e:
        (await rb.unlock(_DB(), agent, actor="test", policy={}))
    assert e.value.status_code == 409 and paid == []


# ── 6. A SHAPE CHANGE INSIDE A FIELD THAT ALREADY EXISTS MUST STILL TRAVEL ────────────────────

def _card_with_maturity(version):
    params = {"status": "locked", "amount": "250", "locked_at": "2026-09-08T00:00:00+00:00"}
    if version:
        params["maturity"] = {"version": version, "transactions": 4, "thresholds": {}}
    return {"extensions": [{"uri": rb.BOND_EXTENSION_URI, "params": params}]}


def test_ingest_lets_a_newer_snapshot_shape_through_and_never_an_older_one():
    """MEASURED ON ASIA AFTER V0345: its mirrors still held the v1 snapshot from 07:49. The V0343
    clause fired only when a card GAINED a maturity block, and every mirror already had one, so the
    v2 shape could never arrive until each agent's card happened to move for some other reason."""
    from agentvault_registry.crud.crud_peer_registry import _bond_maturity_version as v
    assert v(_card_with_maturity(2)) > v(_card_with_maturity(1)), "v1 -> v2 must be let through"
    assert v(_card_with_maturity(1)) > v(_card_with_maturity(None)), "absent -> v1 still is"
    # CONTROLS: the same shape is not new information, and an older one must never win.
    assert not v(_card_with_maturity(2)) > v(_card_with_maturity(2))
    assert not v(_card_with_maturity(1)) > v(_card_with_maturity(2)), "a stale relay must not downgrade"
    assert v(None) == 0 and v({"name": "no extensions"}) == 0


def test_the_export_version_moved_with_the_shape():
    """A receiver re-reads a peer from epoch only when the peer's published export version changes
    (§TRAVELREC). Without the bump the v2 snapshot exists on every exported card and no mirror asks."""
    import pathlib, re
    src = pathlib.Path(rb.__file__).resolve().parent.parent.joinpath("routers", "federation_sync.py").read_text()
    m = re.search(r'^CARD_EXPORT_VERSION = "([^"]+)"', src, re.M)
    assert m and m.group(1) != "2026-09-11.bondfill", "the V0343 shape version would hide the v2 snapshot"
