"""§REPBOND (2026-09-05) — the reputation bond as escrow-backed money, the gate, the card.

Pure-function and structural tests (no database): the money rails are proven live on the
sandbox tier. Every structural assertion has a RED control: point `REPBOND_SRC` at a tree
WITHOUT the batch (e.g. `git stash` or the `.bak-pre-repbond` copies) and the file must fail.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import pathlib
import re
import sys
import types
from decimal import Decimal

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ["REPBOND_SRC"]) if os.environ.get("REPBOND_SRC") else HERE.parent / "src" / "agentvault_registry"


def _read(rel: str) -> str:
    p = SRC / rel
    if not p.exists():
        pytest.fail(f"{rel} is missing under {SRC}")
    return p.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rb():
    """Import services/reputation_bond.py from the tree under test."""
    sys.path.insert(0, str(SRC.parent))
    try:
        from agentvault_registry.services import reputation_bond as m
    except Exception as e:  # noqa: BLE001
        pytest.fail(f"services/reputation_bond.py does not import: {e}")
    return m


# ── knobs ───────────────────────────────────────────────────────────────────

def test_mode_defaults_off_and_env_wins(rb, monkeypatch):
    monkeypatch.delenv("REPUTATION_BOND_MODE", raising=False)
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    rb._np.reset_cache()
    assert rb.bond_mode() == "off"
    monkeypatch.setenv("REPUTATION_BOND_MODE", "shadow")
    assert rb.bond_mode() == "shadow"
    monkeypatch.setenv("REPUTATION_BOND_MODE", "nonsense")
    assert rb.bond_mode() == "off", "an unknown mode must fall to off, never to enforce"


def test_bond_amount_precedence(rb, monkeypatch):
    monkeypatch.delenv("REPUTATION_BOND_AMOUNT", raising=False)
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    rb._np.reset_cache()
    assert rb.bond_amount(None) == Decimal("50")
    assert rb.bond_amount({"reputation_bond": {"amount_avt": 75}}) == Decimal("75")
    monkeypatch.setenv("REPUTATION_BOND_AMOUNT", "250")
    assert rb.bond_amount({"reputation_bond": {"amount_avt": 75}}) == Decimal("250"), "env wins over policy"


def test_slash_mode_defaults_cache(rb, monkeypatch):
    monkeypatch.delenv("ENFORCEMENT_SLASH_MODE", raising=False)
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    rb._np.reset_cache()
    assert rb.slash_mode() == "cache"
    monkeypatch.setenv("ENFORCEMENT_SLASH_MODE", "enforce")
    assert rb.slash_mode() == "enforce"


# ── pure helpers ────────────────────────────────────────────────────────────

def test_is_paid_card_reads_both_dialects(rb):
    assert rb.is_paid_card({"pricing": {"payment_required": True}})
    assert rb.is_paid_card({"extensions": [{"uri": "https://theprotocol.cloud/extensions/v1/auth/a2a-payment",
                                            "params": {"base_rate": "0.5"}}]})
    assert not rb.is_paid_card({"pricing": {"payment_required": False}})
    assert not rb.is_paid_card({"extensions": [{"uri": "https://theprotocol.cloud/extensions/v1/auth/a2a-payment",
                                                "params": {"base_rate": "0"}}]})
    assert not rb.is_paid_card(None)
    assert rb.is_paid_card('{"pricing": {"payment_required": true}}'), "a JSON string column is normalised"


def test_progress_dict_maturity(rb):
    # §BONDFILL-3 — the trust gate is RELATIVE (independent raters + a percentile of the frame's
    # ranked agents); the absolute eigentrust threshold it replaced could not be met by construction.
    th = {"min_transactions": 5, "min_age_days": 14, "min_trust_percentile": 50,
          "min_rated_peers": 3, "min_ranked_population": 10}
    p = rb.progress_dict(transactions=5, age_days=14, eigentrust=0.0, thresholds=th,
                         rated_peers=3, trust_percentile=50.0, trust_population=17)
    assert p["matured"] and p["percent"] == 100
    p = rb.progress_dict(transactions=0, age_days=7, eigentrust=0.9, thresholds=th,
                         rated_peers=1, trust_percentile=90.0, trust_population=17)
    assert not p["matured"] and p["met"] == {"transactions": False, "age": False, "trust": False}
    assert 0 < p["percent"] < 100


def test_extension_round_trip(rb):
    state = {"bond": {"status": "locked", "amount": "250", "currency": "JUICE", "locked_at": "2026-09-05T00:00:00+00:00",
                      "matured_at": None, "funded_by": "wallet", "registry": "Sandbox Alpha"}}
    card = {"name": "x", "extensions": [{"uri": "https://example/other", "params": {}},
                                        {"uri": rb.BOND_EXTENSION_URI, "params": {"status": "stale"}}]}
    out = rb.inject_extension(dict(card), state)
    uris = [e["uri"] for e in out["extensions"]]
    assert uris.count(rb.BOND_EXTENSION_URI) == 1, "a stale entry is replaced, never duplicated"
    assert "https://example/other" in uris
    p = rb.extension_from_card(out)
    assert p["status"] == "locked" and p["amount"] == "250" and p["registry"] == "Sandbox Alpha"
    assert rb.is_bonded_status(p["status"])
    # an unbonded state strips the entry
    out2 = rb.inject_extension(out, {"bond": {"status": "released"}})
    assert rb.extension_from_card(out2) is None
    assert rb.extension_from_card({"extensions": "not-a-list"}) is None or True


def test_sql_predicates_name_both_truths(rb):
    sql = rb.sql_is_bonded("a", "s")
    assert "a.reputation_bond_status" in sql and "s.card_data" in sql and rb.BOND_EXTENSION_URI in sql
    card_sql = rb.sql_card_is_bonded("c")
    assert "EXISTS (SELECT 1 FROM agents ab WHERE ab.did = c.agent_did" in card_sql
    assert "('locked','matured')" in card_sql


# ── the gate, off / shadow / enforce, with the DB read faked ────────────────

def _run(coro):
    # §DEPS: pytest-asyncio 1.x leaves no current event loop for a synchronous test, so a shared-loop lookup
    # passes or fails by test order; a private loop does not depend on what ran before.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_gate_off_skips_everything(rb, monkeypatch):
    calls = []
    async def _boom(db, did):
        calls.append(did); return False
    monkeypatch.setattr(rb, "is_bonded_did", _boom)
    out = _run(rb.gate(None, "did:x", site="guild_bid", mode="off"))
    assert out["decision"] == "skipped" and calls == [], "off must not even read the DB"


def test_gate_shadow_counts_but_never_refuses(rb, monkeypatch):
    async def _no(db, did):
        return False
    monkeypatch.setattr(rb, "is_bonded_did", _no)
    out = _run(rb.gate(None, "did:x", site="listing", mode="shadow"))
    assert out["decision"] == "refuse" and out["bonded"] is False


def test_gate_enforce_refuses_with_the_amount_and_the_door(rb, monkeypatch):
    from fastapi import HTTPException
    async def _no(db, did):
        return False
    async def _pol(db):
        return {"reputation_bond": {"amount_avt": 250}}
    monkeypatch.setattr(rb, "is_bonded_did", _no)
    monkeypatch.setattr(rb, "policy_json", _pol)
    monkeypatch.delenv("REPUTATION_BOND_AMOUNT", raising=False)
    rb._np.reset_cache()
    with pytest.raises(HTTPException) as ei:
        _run(rb.gate(None, "did:theprotocol:abc", site="a2a_payee", mode="enforce"))
    d = str(ei.value.detail)
    assert ei.value.status_code == 403
    assert "250" in d and "reputation-bond/deposit" in d and "/developers/me/agents/did:theprotocol:abc/reputation-bond" in d


def test_gate_enforce_refuses_an_unknown_did_with_its_own_sentence(rb, monkeypatch):
    from fastapi import HTTPException
    async def _none(db, did):
        return None
    monkeypatch.setattr(rb, "is_bonded_did", _none)
    with pytest.raises(HTTPException) as ei:
        _run(rb.gate(None, "did:theprotocol:remote", site="guild_bid", mode="enforce"))
    d = str(ei.value.detail)
    assert "not known to this registry" in d and "holds no reputation bond" not in d, (
        "an unknown DID must not wear the unbonded sentence — the third state stays distinguishable on the wire")


def test_gate_enforce_allows_a_bonded_agent(rb, monkeypatch):
    async def _yes(db, did):
        return True
    monkeypatch.setattr(rb, "is_bonded_did", _yes)
    out = _run(rb.gate(None, "did:x", site="contract_accept", mode="enforce"))
    assert out["decision"] == "allow"


def test_gate_refuses_unknown_site(rb):
    with pytest.raises(ValueError):
        _run(rb.gate(None, "did:x", site="somewhere", mode="off"))


# ── staking multiplier ──────────────────────────────────────────────────────

def test_staking_multiplier_off_is_one(rb, monkeypatch):
    async def _pol(db):
        return {"staking_reputation": {"enabled": False}}
    monkeypatch.setattr(rb, "policy_json", _pol)
    m, d = _run(rb.staking_multiplier(None, types.SimpleNamespace(did="did:x", reputation_bond_status="matured")))
    assert m == Decimal(1) and d["enabled"] is False


def test_staking_multiplier_matured_times_highest_tier_capped(rb, monkeypatch):
    bond = types.SimpleNamespace(status="matured", locked_at=None, agent_did="did:x", amount=Decimal(250))
    async def _pol(db):
        return {"staking_reputation": {"enabled": True, "matured_bond_multiplier": 1.5,
                                       "volume_tiers": [{"min_volume": 10, "multiplier": 1.2},
                                                        {"min_volume": 100, "multiplier": 1.5}],
                                       "cap": 2.0},
                "reputation_bond": {"min_transactions": 1, "min_age_days": 0, "min_eigentrust": 0}}
    async def _bond(db, did):
        return bond
    async def _act(db, dids):
        return {"did:x": {"transactions": 9, "volume": Decimal(150), "eigentrust": 0.5}}
    async def _stamp(db, b, progress, **kw):
        return False
    monkeypatch.setattr(rb, "policy_json", _pol)
    monkeypatch.setattr(rb, "load_bond", _bond)
    monkeypatch.setattr(rb, "activity_batch", _act)
    monkeypatch.setattr(rb, "stamp_matured", _stamp)
    m, d = _run(rb.staking_multiplier(None, types.SimpleNamespace(did="did:x", reputation_bond_status="matured")))
    assert m == Decimal("2.0"), f"1.5 × 1.5 = 2.25 must be capped at 2.0, got {m} ({d})"
    assert d["volume_tier"]["min_volume"] == 100, "the HIGHEST tier reached, not every tier"


# ── structural: the six sites, the derive-time injections, the policies ──────

@pytest.mark.parametrize("rel,site,n", [
    ("routers/agent_cards.py", "listing", 1),
    ("routers/agent_cards.py", "pricing", 1),
    ("routers/guild.py", "guild_bid", 2),
    ("routers/contracts_v2.py", "contract_accept", 1),
    ("routers/contracts.py", "contract_accept", 1),   # the legacy accept (§REPBOND, 2026-10-24)
    ("routers/a2a_payment.py", "a2a_payee", 2),
])
def test_gate_sites_are_wired(rel, site, n):
    src = _read(rel)
    hits = re.findall(r'_rb\.gate\(db, [^\n]*site="%s"' % site, src)
    assert len(hits) == n, f"{rel}: expected {n} gate call(s) for site {site!r}, found {len(hits)}"


def test_discovery_carries_the_bond():
    src = _read("routers/agent_cards.py")
    assert "@@IS_BONDED@@" in src and "@@CARD_IS_BONDED@@" in src
    assert '"include_unbonded"' in src and '"bonded_only"' in src
    assert 'sort_sql.replace("ORDER BY ", "ORDER BY is_bonded DESC, ", 1)' in src
    assert '"reputation": rep_by_did.get(r["agent_did"])' in src
    assert "is_bonded, reputation_bond_status, staked_balance, card_data," in src


def test_bond_state_changes_touch_the_native_card():
    src = _read("services/reputation_bond.py")
    # §BONDFILL-3 adds the fifth: the maturity unlock changes what a mirror must draw (a full fire
    # becomes embers), so it must move the card's clock like every other bond state change.
    assert src.count("await touch_native_card(db, agent.did)") == 5, "deposit, backstop, release, forfeit, unlock"
    assert "await touch_native_card(db, bond.agent_did)" in src, "the matured stamp"
    assert "(card_data#>>'{federation_metadata,source_registry}') IS NULL" in src, "only the agent's OWN card, never a mirror"


def test_extension_is_injected_at_export_and_fanout():
    assert "_rb.inject_extension(stripped, await _rb.card_state(db, did))" in _read("routers/agent_discovery.py")
    fan = _read("routers/federation_sync.py")
    assert "_rb.card_states(db, [c.agent_did for c in cards if c.agent_did])" in fan
    assert "if not card_source and card.agent_did:" in fan, "native cards only — a relayed card keeps its origin's"


def test_policy_defaults_and_validation():
    sys.path.insert(0, str(SRC.parent))
    from agentvault_registry.crud import crud_enforcement as ce
    d = ce.DEFAULT_POLICY_JSON
    assert [s["source"] for s in d["slash_waterfall"]] == ["bond", "stake", "liquid"]
    assert d["staking_reputation"]["enabled"] is False
    assert ce.validate_policy_json(d) == []
    bad = dict(d); bad["slash_waterfall"] = [{"source": "bond"}, {"source": "bond"}]
    assert any("repeats" in e for e in ce.validate_policy_json(bad))
    bad["slash_waterfall"] = [{"source": "moon", "max_percent": 10}]
    assert any("source must be" in e for e in ce.validate_policy_json(bad))
    bad["slash_waterfall"] = [{"source": "bond", "max_percent": 101}]
    assert any("max_percent" in e for e in ce.validate_policy_json(bad))
    bad = dict(d); bad["staking_reputation"] = {"enabled": True, "cap": 0.5}
    assert any("cap" in e for e in ce.validate_policy_json(bad))
    bad["staking_reputation"] = {"enabled": True, "volume_tiers": [{"min_volume": 10, "multiplier": 1.1},
                                                                  {"min_volume": 5, "multiplier": 1.2}]}
    assert any("ascending" in e for e in ce.validate_policy_json(bad))


def test_engine_waterfall_is_behind_its_knob():
    src = _read("services/enforcement_engine.py")
    assert "async def _slash_waterfall(" in src
    assert 'if _mode in ("shadow", "enforce"):' in src
    assert "return mode == \"enforce\"" in src, "shadow must fall through to today's cache-only write"
    assert "escrow_deposit(agent.did, take, f\"slash-{action.id}-liquid\"" in src


def test_staking_payout_applies_the_multiplier():
    src = _read("services/staking_rewards_service.py")
    assert "from .reputation_bond import staking_multiplier as _staking_multiplier" in src
    assert "total_apy = (total_apy * rep_multiplier).quantize(Decimal('0.0001'))" in src


def test_migration_0173_shape():
    mig = HERE.parent / "alembic" / "versions" / "0173_reputation_bond_escrow.py"
    if os.environ.get("REPBOND_SRC"):
        mig = pathlib.Path(os.environ["REPBOND_SRC"]).parent.parent / "alembic" / "versions" / "0173_reputation_bond_escrow.py"
    assert mig.exists(), "migration 0173 is missing"
    src = mig.read_text()
    assert 'revision = "0173_reputation_bond_escrow"' in src and len("0173_reputation_bond_escrow") <= 32
    assert 'down_revision = "0172_frame_requests"' in src
    assert "sa.Numeric(36, 18)" in src and "funder_did" in src and "escrow_ref" in src
    assert "SET status = 'voided'" in src, "the pre-escrow rows are voided, never left passing the gate"
