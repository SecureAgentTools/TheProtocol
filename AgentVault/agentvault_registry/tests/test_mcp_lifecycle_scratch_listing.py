"""§AGORAFIX (2026-09-28): the lifecycle's scratch AGORA listing redraws its random symbol when the venue says 409.

V0486's tester-self (57a8390dffa540ef) drew P3C494, a listing an earlier run had made on 2026-09-05, and scored the venue's
correct 409 "symbol taken" as a hard failure (the run's fresh org held no listing). Pinned: a 409 draws again, bounded;
any other failure does not; the recorder's last row is the one that stands, so three collisions still read red; and the
phase-3 fixture really calls the helper.
RED control: the tree before §AGORAFIX has no _create_scratch_listing, so every test here fails.
"""
from __future__ import annotations

import inspect
import types

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as m

TOOL = "theprotocol_createAgoraListing"


def _venue(statuses):
    """A fake `_call`: answers the scripted statuses in turn and records each attempt the way the real recorder does
    (one row per tool, the last write wins)."""
    outcomes, symbols = {}, []

    async def call(tool, args, jwt):
        st = statuses[min(len(symbols), len(statuses) - 1)]
        symbols.append(args["symbol"])
        outcomes[tool] = types.SimpleNamespace(status_code=st)
        return {"symbol": args["symbol"]} if st == 200 else None
    return call, outcomes, symbols


async def test_a_taken_symbol_is_drawn_again_and_the_clean_row_stands():
    call, outcomes, symbols = _venue([409, 200])
    sym = await m._create_scratch_listing(call, outcomes, "org", "did:x", "jwt")
    assert len(symbols) == 2 and sym == symbols[-1]
    assert outcomes[TOOL].status_code == 200


async def test_any_other_failure_is_not_redrawn():
    call, outcomes, symbols = _venue([500])
    await m._create_scratch_listing(call, outcomes, "org", "did:x", "jwt")
    assert len(symbols) == 1 and outcomes[TOOL].status_code == 500


async def test_three_collisions_still_read_red():
    call, outcomes, symbols = _venue([409, 409, 409, 200])
    await m._create_scratch_listing(call, outcomes, "org", "did:x", "jwt")
    assert len(symbols) == 3 and outcomes[TOOL].status_code == 409


async def test_every_draw_is_a_six_character_p3_symbol():
    call, outcomes, symbols = _venue([409, 409, 409])
    await m._create_scratch_listing(call, outcomes, "org", "did:x", "jwt")
    assert all(len(s) == 6 and s.startswith("P3") and s == s.upper() for s in symbols)


def test_the_phase3_fixture_uses_the_helper():
    src = inspect.getsource(m._phase3_setup_entities)
    assert "await _create_scratch_listing(_call, setup_outcomes, _org" in src
