"""§FRAMELIC findings row 169 — a SOVEREIGN tier lives on the AGENT, so a caller must not
pre-filter on the DEVELOPER's tier.

`_build_flare_sidecar` was deliberately widened at §COSMETICS-ORIGIN to ship when EITHER side
has a tier ("gating its export on the developer was always the wrong question"). Three callers
in `agent_cards.py` kept asking the old question as a cheap pre-filter, so every agent whose OWN
tier is sovereign — and whose developer holds no tier — lost its flare on all three LOCAL read
paths while the federated export carried it correctly. A peer frame showed the ring; home did not.

MEASURED on EU before the fix: eleven sovereigns, `agents.flare_tier='sovereign'` with variant and
overlay set, owner `svc-market` with `flare_tier` NULL → `/agent-cards/discover` returned
encirclement_variant=None for all eleven, and zero "dropping unowned sovereign claim" warnings
(nothing was being stripped — nothing was ever injected).

⚠ These legs FAIL against the pre-fix file, which is the only reason they are worth having.
"""
import asyncio
import types

import pytest

from agentvault_registry.routers import agent_cards as ac


class _FakeResult:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return types.SimpleNamespace(all=lambda: self._rows)
    def scalar_one_or_none(self): return self._rows[0] if self._rows else None


class _FakeDB:
    """Answers exactly one query: the agents lookup the injectors make."""
    def __init__(self, rows): self.rows = rows; self.calls = 0
    async def execute(self, *_a, **_k):
        self.calls += 1
        return _FakeResult(self.rows)


def _sovereign_agent(did):
    return types.SimpleNamespace(
        did=did, flare_tier="sovereign",
        flare_encirclement_variant="panopticon", flare_encirclement_overlay="glitch",
        flare_corner_variant=None, bears_corner_flare=False, bears_encirclement_flare=False,
        flare_granted_at=None,
    )


def _tierless_developer():
    """The owner is a service account: it holds no flare of its own. This is the shape the
    pre-filter mistook for 'nothing to inject'."""
    return types.SimpleNamespace(
        id=7, flare_tier=None, flare_encirclement_variant=None,
        flare_encirclement_overlay=None, flare_corner_variant=None,
    )


def _card(did):
    return types.SimpleNamespace(id="c1", agent_did=did, developer=_tierless_developer())


def test_single_card_inject_ships_an_agent_owned_sovereign_flare():
    did = "did:theprotocol:agentvault.com:sov-1"
    resp = {"card_data": {"name": "SYBIL"}}
    asyncio.run(ac._inject_flare_into_card_data(_FakeDB([_sovereign_agent(did)]), resp, _card(did)))
    flare = resp["card_data"].get("flare")
    assert flare, "the agent's own sovereign tier was dropped because its developer has none"
    assert flare["encirclement_variant"] == "panopticon"
    assert flare["tier"] == "sovereign"


def test_batch_inject_ships_an_agent_owned_sovereign_flare():
    did = "did:theprotocol:agentvault.com:sov-2"
    items = [{"card_data": {"name": "MOIRA"}}]
    asyncio.run(ac._inject_flare_into_card_data_batch(
        _FakeDB([_sovereign_agent(did)]), items, [_card(did)]))
    flare = items[0]["card_data"].get("flare")
    assert flare, "batch path dropped an agent-owned sovereign tier"
    assert flare["encirclement_variant"] == "panopticon"


def test_the_builder_still_refuses_when_neither_side_has_a_tier():
    """The control: widening the CALLERS must not turn the sidecar into something every card
    gets. A plain agent under a plain developer still ships nothing."""
    did = "did:theprotocol:agentvault.com:plain-1"
    plain = types.SimpleNamespace(
        did=did, flare_tier=None, flare_encirclement_variant=None,
        flare_encirclement_overlay=None, flare_corner_variant=None,
        bears_corner_flare=False, bears_encirclement_flare=False, flare_granted_at=None,
    )
    resp = {"card_data": {"name": "plain"}}
    asyncio.run(ac._inject_flare_into_card_data(_FakeDB([plain]), resp, _card(did)))
    assert "flare" not in resp["card_data"], "a tierless agent must ship no sidecar"


def test_no_caller_pre_filters_on_the_developer_tier_alone():
    """Structural: the old question, asked at a call site, is the defect itself. Pins the class
    so a future 'cheap pre-filter' cannot silently reintroduce it."""
    import inspect
    src = inspect.getsource(ac)
    bad = [l.strip() for l in src.splitlines()
           if 'flare_tier' in l and 'dev' in l and ('not dev' in l or 'continue' in l or 'return' in l)
           and 'models.Developer' not in l and '#' not in l.split('flare_tier')[0]]
    assert not bad, f"a caller is pre-filtering on the developer tier again: {bad}"
