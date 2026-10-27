"""§ECHOFLOOD (2026-10-09): a frame's own cards came back to it on every full read, and each one became a WARNING.

Measured on the sandbox (LogWarningStorm: 1,690 WARNING records a minute, 1,460 of them sbx-alpha's "OWL24: BLOCKED
peer ... from changing native card ..."; 7,198 distinct cards in three bursts):
  1. The agent-card feed holds back a relayed card whose recorded source is the registry asking for it. Since the
     per-service SVIDs (F5) a frame registry presents `spiffe://<td>/service/registry`, which names no registry, while
     its cards are recorded under `spiffe://<td>/registry/<name>`. canonical_equals() answered "different" (4,728 of
     sbx-alpha's cards on sbxalphaop alone), so the feed served sbx-alpha its own cards back.
  2. sbx-alpha's "is this echo unchanged?" test compared each copy (which keeps the export-derived reputation-bond
     block) with its stored native (which never holds it), so every echo counted as a change and logged a WARNING.
RED control: the tree before §ECHOFLOOD fails this file (no requester_source_forms, no drop_export_derived, and
_norm_card takes no native_echo).
"""
from __future__ import annotations

import ast
import asyncio
import copy
import os
import pathlib
from types import SimpleNamespace

from agentvault_registry.core import federation_auth as fa
from agentvault_registry.crud.crud_peer_registry import drop_derived_since, drop_export_derived
from agentvault_registry.services.enforcement_propagation import ENFORCEMENT_EXTENSION_URI
from agentvault_registry.services.listing_propagation import LISTING_EXTENSION_URI
from agentvault_registry.services.reputation_bond import BOND_EXTENSION_URI
from agentvault_registry.services.spiffe_canonical import canonical_equals
from agentvault_registry.services.track_record import TRACK_RECORD_EXTENSION_URI

_HERE = pathlib.Path(__file__).resolve()
_PKG = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
CRUD = _PKG / "crud" / "crud_peer_registry.py"
FEED = _PKG / "routers" / "federation_sync.py"

TD = "sandbox-a.theprotocol.cloud"
FRAME_SVID = f"spiffe://{TD}/service/registry"            # what sbx-alpha presents since F5
RECORDED_FRAME = f"spiffe://{TD}/registry/sandbox-alpha"   # how 4,728 of its cards were recorded on sbxalphaop
DID_JWT = "https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed"


class _FakeDb:
    """Answers the canonical query with the rows it was given (the SQL filter itself is pinned in test_s3_peer_binding)."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = 0

    async def execute(self, _query):
        self.queries += 1
        rows = self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(rows)))


def _row(name, peer_type="frame", spiffe_id=None, status="ACTIVE"):
    return SimpleNamespace(name=name, trust_domain=TD, peer_type=peer_type, spiffe_id=spiffe_id, status=status)


def _forms(spiffe_id, rows):
    return asyncio.run(fa.requester_source_forms(_FakeDb(rows), spiffe_id))


def _held_back(recorded, forms):
    return any(canonical_equals(recorded, f) for f in forms)


# ── 1. the feed's echo prevention ────────────────────────────────────────────────────────────────────────────────────

def test_the_per_service_id_alone_names_no_registry():
    # the measured cause: on its own, the presented id cannot be matched to the frame's recorded name
    assert canonical_equals(RECORDED_FRAME, FRAME_SVID) is False


def test_a_frame_requester_is_known_by_its_rows_name():
    forms = _forms(FRAME_SVID, [_row("Sandbox Alpha")])
    assert FRAME_SVID in forms, "the presented id stays a form"
    assert f"spiffe://{TD}/registry/sandbox-alpha" in forms
    assert _held_back(RECORDED_FRAME, forms)
    assert _held_back("spiffe://agentvault.com/ns/agentvault/sa/registry-sandbox-alpha", forms), "the legacy stamp too"
    assert _held_back(FRAME_SVID, forms), "a copy recorded under the per-service id is still held back"


def test_an_operator_of_the_same_trust_domain_is_not_mistaken_for_the_frame():
    forms = _forms(FRAME_SVID, [_row("Sandbox Alpha")])
    assert not _held_back(f"spiffe://{TD}/registry/sbxalphaop", forms)
    assert not _held_back(f"spiffe://{TD}/operator/sbxalphaop/registry", forms)
    assert not _held_back("spiffe://sandbox-b.theprotocol.cloud/registry/sandbox-beta", forms)


def test_an_operator_requester_is_known_by_its_name_and_only_its_own_row():
    svid = f"spiffe://{TD}/operator/sbxalphaop/registry"
    forms = _forms(svid, [_row("sbxalphaop", peer_type="cloud_operator"), _row("Sandbox Alpha")])
    assert f"spiffe://{TD}/registry/sbxalphaop" in forms
    assert _held_back(f"spiffe://{TD}/registry/sbxalphaop", forms)
    assert not _held_back(RECORDED_FRAME, forms), "the frame's row in the same domain is not the operator"


def test_a_stamped_spiffe_id_on_the_row_is_a_form():
    stamped = f"spiffe://{TD}/service/sbx-alpha-registry"
    assert stamped in _forms(FRAME_SVID, [_row("Sandbox Alpha", spiffe_id=stamped)])


def test_no_row_keeps_the_old_behaviour():
    assert _forms(FRAME_SVID, []) == {FRAME_SVID}
    db = _FakeDb([])
    assert asyncio.run(fa.requester_source_forms(db, "not-a-spiffe-id")) == {"not-a-spiffe-id"}
    assert db.queries == 0, "an identity that is not registry-class costs no query"


def test_the_feed_checks_every_form():
    tree = ast.parse(FEED.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_agent_cards_for_sync")
    src = ast.get_source_segment(FEED.read_text(encoding="utf-8"), fn)
    assert "await requester_source_forms(db, spiffe_id)" in src
    assert "any(_canon_eq(card_source, _f) for _f in _requester_forms)" in src
    assert "_canon_eq(card_source, spiffe_id)" not in src, "the single-form check is gone"


# ── 2. the receiving frame's native-echo test ───────────────────────────────────────────────────────────────────────

def _norm_card():
    """The REAL nested `_norm_card` from upsert_agent_cards_from_peer, compiled on its own with the module's helpers."""
    tree = ast.parse(CRUD.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_norm_card")
    ns = {"drop_derived_since": drop_derived_since, "drop_export_derived": drop_export_derived}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(CRUD), "exec"), ns)
    return ns["_norm_card"]


def _native(**over):
    cd = {"name": "Trader Theo", "skills": [{"id": "quote", "name": "Quote"}],
          "extensions": [{"uri": DID_JWT, "params": {"lifetimeSec": 300}}],
          "federation_metadata": {"origin_registry_name": "Sandbox Alpha"}}
    cd.update(over)
    return cd


def _echo(native):
    """A peer's copy of our native card as it comes back: the export-derived blocks kept, the sync's own fields added."""
    cd = copy.deepcopy(native)
    cd.setdefault("extensions", [])
    cd["extensions"] = cd["extensions"] + [
        {"uri": BOND_EXTENSION_URI, "params": {"amount": "250", "status": "locked",
                                                "maturity": {"as_of": "2026-10-09T18:14:00Z", "trust_population": 1418,
                                                             "transactions": 3}}},
        {"uri": ENFORCEMENT_EXTENSION_URI, "params": {"status": "active", "since": "2026-10-01T00:00:00Z"}},
        {"uri": TRACK_RECORD_EXTENSION_URI, "params": {"jobs": 0}},
        {"uri": LISTING_EXTENSION_URI, "params": {"unlisted": False, "since": "2026-10-01T00:00:00Z"}},
    ]
    cd["federation_metadata"] = {"source_registry": RECORDED_FRAME, "first_synced_from": RECORDED_FRAME,
                                 "last_sync_timestamp": "2026-10-09T18:14:47Z", "origin_registry_name": "Sandbox Alpha"}
    cd["did"] = "did:theprotocol:sandbox-a.theprotocol.cloud:00000000-0000-4000-8000-000000000000"
    cd["location"] = {"latitude": 50.1, "longitude": 8.6}
    return cd


def test_an_unchanged_echo_of_our_card_compares_equal():
    norm = _norm_card()
    native = _native()
    assert norm(_echo(native), include_sticky=False, native_echo=True) == norm(native, include_sticky=False,
                                                                               native_echo=True)
    bare = _native()
    bare.pop("extensions")
    assert norm(_echo(bare), include_sticky=False, native_echo=True) == norm(bare, include_sticky=False,
                                                                             native_echo=True), \
        "a native with no extensions at all and an echo carrying only derived blocks"
    assert native == _native(), "the comparison never edits the stored card"


def test_the_measured_case_failed_before_the_change():
    # the same pair under the pre-§ECHOFLOOD comparison (the derived blocks kept): this was every OWL24 WARNING
    norm = _norm_card()
    native = _native()
    assert norm(_echo(native), include_sticky=False) != norm(native, include_sticky=False)


def test_an_echo_that_changes_our_content_still_compares_different():
    norm = _norm_card()
    native = _native()
    for change in ({"name": "Someone Else"}, {"skills": [{"id": "quote", "name": "Price"}]},
                   {"extensions": [{"uri": DID_JWT, "params": {"lifetimeSec": 9999}}]}):
        echo = _echo(native)
        echo.update(change)
        assert norm(echo, include_sticky=False, native_echo=True) != norm(native, include_sticky=False,
                                                                          native_echo=True), change


def test_the_mirror_comparison_still_sees_a_change_of_the_homes_state():
    # a mirror must still be rewritten when its home's bond state moves (include_sticky=True, no native_echo)
    norm = _norm_card()
    a, b = _echo(_native()), _echo(_native())
    b["extensions"][1]["params"]["status"] = "released"
    assert norm(a, include_sticky=True) != norm(b, include_sticky=True)


def test_drop_export_derived_keeps_everything_else():
    cd = _echo(_native())
    cd["extensions"].append({"uri": "https://example.test/other", "params": {"x": 1}})
    drop_export_derived(cd)
    assert [e["uri"] for e in cd["extensions"]] == [DID_JWT, "https://example.test/other"]
    for odd in ({}, {"extensions": None}, {"extensions": ["x", {"uri": BOND_EXTENSION_URI}]}):
        drop_export_derived(odd)                  # tolerated, no raise
    only = {"extensions": [{"uri": BOND_EXTENSION_URI, "params": {}}]}
    drop_export_derived(only)
    assert "extensions" not in only


def test_the_native_guard_uses_the_echo_mode_and_the_mirror_path_does_not():
    tree = ast.parse(CRUD.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "upsert_agent_cards_from_peer")
    calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_norm_card"]
    echo = [c for c in calls if any(k.arg == "native_echo" and getattr(k.value, "value", None) is True
                                    for k in c.keywords)]
    sticky = [c for c in calls if any(k.arg == "include_sticky" and getattr(k.value, "value", None) is True
                                      for k in c.keywords)]
    assert len(echo) == 2, "both sides of the native comparison"
    assert len(sticky) == 2 and not any(c in echo for c in sticky), "the mirror comparison keeps the derived blocks"
