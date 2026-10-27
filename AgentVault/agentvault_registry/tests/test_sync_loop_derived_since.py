"""§SYNCLOOP (2026-09-26): a relayed card whose only change is a DERIVED clock is not a change.

Measured on the sandbox tier while deciding whether the card sync could run more often (his words: "you can increase
agent card synch intervall too if the synch now doesnt synch uselessly all cards"): no native card had changed in ten
minutes, yet every node rewrote 12 to 35 COPIES of other frames' cards on every cycle, all within one second. Across a
cycle the copies differed in exactly two places: `federation_metadata.last_sync_timestamp` (which the §2026-06-16 gate
already ignores) and `params.since` of the listing (or enforcement) extension, which a relaying registry derives from
its OWN copy's `updated_at`, and every write moves that. So each hop saw a change, rewrote, and passed it on.

The gate now drops that derived `since` before comparing; the STATE (`unlisted`, `status`, `registry`) is still
compared. RED control: the tree before §SYNCLOOP fails every test here (no `drop_derived_since`, and `_norm_card` does
not call it).
"""
from __future__ import annotations

import ast
import copy
import os
import pathlib

from agentvault_registry.crud.crud_peer_registry import drop_derived_since
from agentvault_registry.services.enforcement_propagation import ENFORCEMENT_EXTENSION_URI
from agentvault_registry.services.listing_propagation import LISTING_EXTENSION_URI

_HERE = pathlib.Path(__file__).resolve()
_PKG = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
CRUD = _PKG / "crud" / "crud_peer_registry.py"
BOND = "https://theprotocol.cloud/extensions/v1/reputation-bond"


def _card(since="2026-09-26T13:47:20.150526+00:00", synced="2026-09-26T13:48:06.501247+00:00", unlisted=True,
          status=None):
    exts = [{"uri": "https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed",
             "params": {"lifetimeSec": 300, "supportedAlgos": ["EdDSA"]}},
            {"uri": LISTING_EXTENSION_URI,
             "params": {"unlisted": unlisted, "since": since, "registry": "sandbox-beta", "version": 1}},
            {"uri": BOND, "params": {"amount": "250", "status": "locked", "locked_at": "2026-09-20T10:00:00+00:00"}}]
    if status:
        exts.append({"uri": ENFORCEMENT_EXTENSION_URI,
                     "params": {"status": status, "since": since, "registry": "sandbox-beta", "version": 1}})
    return {"name": "canary receiver", "extensions": exts,
            "federation_metadata": {"source_registry": "spiffe://sandbox-b.theprotocol.cloud/registry/sandbox-beta",
                                    "last_sync_timestamp": synced}}


def _norm_card():
    """The REAL nested `_norm_card` from upsert_agent_cards_from_peer, compiled on its own with the module's helper."""
    tree = ast.parse(CRUD.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_norm_card")
    ns = {"drop_derived_since": drop_derived_since}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(CRUD), "exec"), ns)
    return ns["_norm_card"]


def test_only_the_derived_clock_of_the_two_extensions_is_dropped():
    cd = _card(status="suspended")
    cd["extensions"].append({"uri": "https://example.test/other", "params": {"since": "keep me"}})
    drop_derived_since(cd)
    by_uri = {e["uri"]: e["params"] for e in cd["extensions"]}
    assert "since" not in by_uri[LISTING_EXTENSION_URI] and "since" not in by_uri[ENFORCEMENT_EXTENSION_URI]
    assert by_uri[LISTING_EXTENSION_URI] == {"unlisted": True, "registry": "sandbox-beta", "version": 1}
    assert by_uri[ENFORCEMENT_EXTENSION_URI]["status"] == "suspended"
    assert by_uri[BOND]["locked_at"] == "2026-09-20T10:00:00+00:00", "another extension's clock is not touched"
    assert by_uri["https://example.test/other"] == {"since": "keep me"}
    for odd in ({}, {"extensions": None}, {"extensions": ["x", {"uri": LISTING_EXTENSION_URI}]}):
        drop_derived_since(odd)                 # tolerated, no raise


def test_two_hops_of_the_measured_card_compare_equal():
    norm = _norm_card()
    first = _card()
    second = _card(since="2026-09-26T13:49:20.880245+00:00", synced="2026-09-26T13:50:07.515576+00:00")
    for sticky in (True, False):
        assert norm(first, include_sticky=sticky) == norm(second, include_sticky=sticky)
    assert first == _card(), "comparison never edits the stored card"


def test_a_real_change_of_state_still_compares_different():
    norm = _norm_card()
    base = norm(_card(), include_sticky=True)
    assert norm(_card(unlisted=False), include_sticky=True) != base, "listed again is a change"
    assert norm(_card(status="suspended"), include_sticky=True) != norm(_card(status="revoked"), include_sticky=True)
    moved = copy.deepcopy(_card())
    moved["extensions"][1]["params"]["registry"] = "sandbox-alpha"
    assert norm(moved, include_sticky=True) != base, "the registry that states it is compared"
    renamed = _card()
    renamed["name"] = "someone else"
    assert norm(renamed, include_sticky=True) != base


def test_the_gate_calls_the_helper():
    tree = ast.parse(CRUD.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_norm_card")
    calls = [c for c in ast.walk(node) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "drop_derived_since"]
    assert len(calls) == 1
