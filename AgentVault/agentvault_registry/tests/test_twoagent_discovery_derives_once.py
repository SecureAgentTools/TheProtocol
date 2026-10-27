"""§TWOAGENT (V0438, 2026-09-23) — Discovery's read states a card's home extensions once.

Measured on sbx-alpha after V0437 (warm, 5 runs each, the public list): 250 active cards with card data 6.5-7.9 s against
V0436's 3.6-4.7 s, 5,000 cards 13.7-16.6 s against 10.4-10.8 s. In-process, one derivation of a 5,000-card page costs
~1.3 s (the bond's maturity activity query ~0.7 s, the listing states ~0.5 s) and of a 250-card page ~35 ms. The
federated form of the list (`include_federated=true&include_card_data=true`, what Discovery reads) paid it TWICE: the
simple path derived `summaries`, then the federated branch rebuilt the local rows from the stored card_data and derived
them again, and threw the first result away. Now the federated branch carries the local rows' card_data as the simple
path stated it; the simple path keeps deriving, because its `summaries` are the answer when the federated branch fails.

The behaviour (the Discovery read states the bond its home holds on a local row) is the live leg
`the_discovery_read_states_it_too` of the federation-suite flow
`card_read_states_the_bond_its_home_holds_and_never_an_owners_claim`. RED on 6e04fbb3 (V0437): the first test.
"""
from __future__ import annotations

import ast
import pathlib

ROUTER = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "agent_cards.py"


def _calls_in(source: str, function: str, callee: str) -> int:
    for fn in ast.walk(ast.parse(source)):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == function:
            return sum(1 for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == callee)
    raise AssertionError(f"{function} not found")


def test_the_list_route_derives_the_page_once():
    assert _calls_in(ROUTER.read_text(), "list_agent_cards", "_state_home_extensions_batch") == 1


def test_the_federated_branch_still_stamps_flare_on_the_local_rows():
    """What the federated branch kept: the flare pass over the rows it rebuilt (unchanged since §pass12)."""
    assert _calls_in(ROUTER.read_text(), "list_agent_cards", "_inject_flare_into_card_data_batch") == 2


def test_control_the_count_sees_a_second_call():
    src = ("async def list_agent_cards(db, s, i):\n    await _state_home_extensions_batch(db, s, i)\n"
           "    if x:\n        await _state_home_extensions_batch(db, s, i)\n")
    assert _calls_in(src, "list_agent_cards", "_state_home_extensions_batch") == 2
