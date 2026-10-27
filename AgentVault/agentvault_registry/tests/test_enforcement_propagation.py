"""§ENFPROP (2026-09-05) — an agent's enforcement state rides its card to every mirror (the bond pattern).

Measured on the sandbox pair (§BATCH4 item 8): a suspension never reached a mirror. These tests pin the
four halves: the derived extension, the ONE predicate (both truths), the gate's three modes, and the
source-level wiring (touch at every flip, inject at both export points, the six sites, discover's filter).
"""
import inspect
import pathlib
import re

import pytest
from fastapi import HTTPException

from agentvault_registry.services import enforcement_propagation as ep

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def _read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


# ── knob ─────────────────────────────────────────────────────────────────────

def test_mode_defaults_shadow_and_never_falls_to_enforce(monkeypatch):
    monkeypatch.delenv("ENFORCEMENT_PROPAGATION_MODE", raising=False)
    monkeypatch.delenv("NETWORK_PROFILE", raising=False)
    assert ep.propagation_mode() == "shadow"
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "enforce")
    assert ep.propagation_mode() == "enforce"
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "nonsense")
    assert ep.propagation_mode() == "shadow", "an unknown mode must fall to shadow, never to enforce"
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "OFF")
    assert ep.propagation_mode() == "off"


# ── the derived extension ────────────────────────────────────────────────────

def test_extension_round_trip_and_stale_strip():
    card = {"name": "x", "extensions": [{"uri": ep.ENFORCEMENT_EXTENSION_URI, "params": {"status": "suspended"}},
                                        {"uri": "https://theprotocol.cloud/extensions/v1/reputation-bond", "params": {"status": "locked"}}]}
    out = ep.inject_extension(dict(card), {"status": "revoked", "since": "2026-09-05T15:28:57+00:00", "registry": "Frame A"})
    exts = [e for e in out["extensions"] if e["uri"] == ep.ENFORCEMENT_EXTENSION_URI]
    assert len(exts) == 1 and exts[0]["params"]["status"] == "revoked" and exts[0]["params"]["registry"] == "Frame A"
    assert any(e["uri"].endswith("reputation-bond") for e in out["extensions"]), "other extensions survive"
    p = ep.extension_from_card(out)
    assert p and p["status"] == "revoked" and p["since"].startswith("2026-09-05")
    # a reinstated agent exports a card WITHOUT the block (that is how a mirror clears)
    clean = ep.inject_extension(dict(out), {"status": "active"})
    assert not [e for e in clean["extensions"] if e["uri"] == ep.ENFORCEMENT_EXTENSION_URI]
    assert ep.extension_from_card(clean) is None
    assert ep.inject_extension("not a card", None) == "not a card"


def test_is_enforced_status():
    assert ep.is_enforced_status("suspended") and ep.is_enforced_status("REVOKED")
    assert not ep.is_enforced_status("active") and not ep.is_enforced_status(None) and not ep.is_enforced_status("")


# ── the ONE predicate, both truths ───────────────────────────────────────────

def test_sql_predicates_name_both_truths():
    a = ep.sql_is_enforced("a", "s")
    assert "a.status" in a and "'suspended','revoked'" in a and "s.card_data" in a and ep.ENFORCEMENT_EXTENSION_URI in a
    c = ep.sql_card_is_enforced("c")
    assert "EXISTS (SELECT 1 FROM agents ab WHERE ab.did = c.agent_did" in c and "c.card_data" in c


# ── the gate ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_off_skips_everything(monkeypatch):
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "off")

    async def _boom(db, did):
        raise AssertionError("off must not even look")
    monkeypatch.setattr(ep, "is_enforced_did", _boom)
    r = await ep.gate(None, "did:theprotocol:x", site="listing")
    assert r["decision"] == "skipped"


@pytest.mark.asyncio
async def test_gate_shadow_counts_but_never_refuses(monkeypatch):
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "shadow")

    async def _yes(db, did):
        return True
    monkeypatch.setattr(ep, "is_enforced_did", _yes)
    r = await ep.gate(None, "did:theprotocol:x", site="guild_bid")
    assert r["decision"] == "refuse" and r["enforced"] is True  # counted, logged, allowed through


@pytest.mark.asyncio
async def test_gate_enforce_refuses_with_the_sentence_and_allows_the_unknown(monkeypatch):
    monkeypatch.setenv("ENFORCEMENT_PROPAGATION_MODE", "enforce")

    async def _yes(db, did):
        return True

    async def _block(db, did):
        return {"status": "suspended", "since": "2026-09-05T15:28:57+00:00", "registry": "Frame A", "source": "card"}
    monkeypatch.setattr(ep, "is_enforced_did", _yes)
    monkeypatch.setattr(ep, "enforcement_block", _block)
    with pytest.raises(HTTPException) as ei:
        await ep.gate(None, "did:theprotocol:x", site="a2a_payee")
    assert ei.value.status_code == 403 and "suspended by Frame A since 2026-09-05" in ei.value.detail and "a2a_payee" in ei.value.detail

    async def _unknown(db, did):
        return None
    monkeypatch.setattr(ep, "is_enforced_did", _unknown)
    r = await ep.gate(None, "did:theprotocol:nobody", site="a2a_payee")
    assert r["decision"] == "unknown", "a DID this registry cannot see is the bond gate's business, not a refusal here"

    async def _no(db, did):
        return False
    monkeypatch.setattr(ep, "is_enforced_did", _no)
    assert (await ep.gate(None, "did:theprotocol:ok", site="a2a_payee"))["decision"] == "allow"
    with pytest.raises(ValueError):
        await ep.gate(None, "did:x", site="not-a-site")


# ── the wiring (source gates: RED on any image without §ENFPROP) ─────────────

def test_every_flip_touches_the_native_card():
    cs = _read("services/coordinated_suspension.py")
    assert cs.count("_ep.touch_native_card_no_commit(db, agent.did)") == 2, "suspend AND reinstate"
    ag = _read("routers/agents.py")
    assert "_ep.touch_native_card_no_commit(db, current_agent.did)" in ag, "self-delete (revoked, card stays active)"
    assert ag.index("touch_native_card_no_commit") < ag.index('await db.commit()\n\n    logger.info(f"Agent {current_agent.did} has been revoked")'), \
        "the touch must land in the same commit as the flip"


def test_both_export_points_inject_the_block():
    fs = _read("routers/federation_sync.py")
    assert "_ep.card_states(db, [c.agent_did for c in cards if c.agent_did])" in fs
    assert "_ep.inject_extension(export_card_data, _enf_card_state.get(card.agent_did))" in fs
    ad = _read("routers/agent_discovery.py")
    assert "_ep.inject_extension(stripped, await _ep.card_state(db, did))" in ad


def test_the_six_sites_call_the_gate():
    sites = {
        "routers/a2a_payment.py": ['_ep.gate(db, req.target_agent_did, site="a2a_payee")'],
        "routers/contracts_v2.py": ['_ep.gate(db, provider_did, site="contract_accept")'],   # the provider of record (D6-274)
        "routers/contracts.py": ['_ep.gate(db, provider_did, site="contract_accept")'],   # the legacy accept
        "routers/guild.py": ['_ep.gate(db, agent.did, site="guild_bid")', '_ep.gate(db, body.bidder_did, site="guild_bid")'],
        "routers/agent_cards.py": ['_ep.gate(db, db_card.agent_did, site="listing")', '_ep.gate(db, db_card.agent_did, site="pricing")'],
    }
    for rel, needles in sites.items():
        src = _read(rel)
        for n in needles:
            assert n in src, f"{rel} lacks {n}"
    ac = _read("routers/agent_cards.py")
    assert "OR NOT @@CARD_IS_ENFORCED@@" in ac and "@@IS_ENFORCED@@ AS is_enforced" in ac
    assert '"include_enforced"' in ac and '"is_enforced": bool(r["is_enforced"])' in ac
    assert '("@@CARD_IS_ENFORCED@@", _ep.sql_card_is_enforced("c"))' in ac


def test_the_predicate_sql_is_substituted_into_the_discover_template():
    """The discover renderer refuses an unsubstituted @@token@@ at request time; prove the two new tokens
    render through the SAME loop the bond tokens use (never by grep alone)."""
    from agentvault_registry.routers import agent_cards
    src = inspect.getsource(agent_cards)
    m = re.search(r'for token, sql in \(\("@@IS_BONDED@@".*?\):\n', src, re.S)
    assert m and "@@IS_ENFORCED@@" in m.group(0) and "@@CARD_IS_ENFORCED@@" in m.group(0)


def test_reputation_endpoint_carries_the_block():
    """The half that is measurable anywhere: the router asks both answers."""
    rb = _read("routers/reputation_bond.py")
    assert rb.count("_ep.enforcement_block(db, did)") == 2, "native AND mirrored answers"


def test_the_knob_is_in_the_profile_table():
    """The half that needs `scripts/`, which the IMAGE does not ship.

    §EVTYPES8 2026-09-06: split out rather than left to fail. Unguarded, this read
    made the whole test red in every image — measured identically on the tier's
    existing image, so it was never a regression, just permanent noise in front of
    the one assertion above that CAN be checked there. Skipping loudly keeps the
    router assertion green in-image and still enforces the knob row wherever
    `scripts/` is present (CI checkout, or /w).
    """
    knobs = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "network_profile_knobs.py"
    if not knobs.is_file():
        knobs = pathlib.Path("/w/scripts/network_profile_knobs.py")
    if not knobs.is_file():
        pytest.skip("scripts/ not shipped in the image — NOT MEASURED")
    src = knobs.read_text(encoding="utf-8")
    assert 'name="ENFORCEMENT_PROPAGATION_MODE"' in src and "services/enforcement_propagation.py::propagation_mode" in src
