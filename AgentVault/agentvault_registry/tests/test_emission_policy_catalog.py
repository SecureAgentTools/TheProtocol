"""W3 (agentvault2-d6, 2026-10-25; his word: "the event emission policy which needs hardening"): the code, the catalog and
the policy rows pinned together, and the registry gate's modes.

Read on 2026-10-25: ASIA's event_emission_policies held 180 rows and lacked 106 of the types the registry and the TEG
emit; EU's store held 28 types with no row (the event store logs each as unknown), and the TEG dropped its own
NegativeEscrowLockClamped on production (no row: its gate fails closed). Here:
- core/event_catalog.py equals what an AST walk of the source emits, both ways (a new emit needs its catalog entry and a
  row; a removed one takes its entry with it);
- every emitted type has a row in some migration's EMISSION_POLICY_ROWS (0196 seeds them all);
- no row skips a balance type, and no row lets both the registry and the TEG emit a type both of them emit;
- the gate: an unreadable table decides nothing (allowed in every mode), a missing row is allowed in "off", allowed and
  counted in "shadow" (the default), refused in "enforce" (and under EVENT_EMITTER_FAIL_CLOSED=true), and a row's
  emit_from_registry=false is refused in every mode;
- the boot check names the missing rows; the view's matrix names each finding.
RED control: against bddf8fd6's tree the catalog and migration 0196 do not exist, and an empty cache under
EVENT_EMITTER_FAIL_CLOSED=true refused every type.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re

import pytest

from agentvault_registry import event_emitter as ee
from agentvault_registry.core.event_catalog import ALL_EMITTED, REGISTRY_EMITS, TEG_ALWAYS_ALLOWED, TEG_EMITS
from agentvault_registry.services import emission_policy_view as view

_HERE = pathlib.Path(__file__).resolve()
REG_SRC = pathlib.Path(ee.__file__).resolve().parent
VERSIONS = _HERE.parents[1] / "alembic" / "versions"
BALANCE = frozenset(ee.BALANCE_MOVING_EVENT_TYPES) | {"LedgerBalanceChanged"}


def _teg_src() -> pathlib.Path | None:
    for cand in (_HERE.parents[2] / "agentvault_teg_layer_mvp" / "src" / "teg_core_service",
                 pathlib.Path("/agentvault_teg_layer_mvp/src/teg_core_service"),
                 pathlib.Path("/w/teg_src/teg_core_service")):
        if (cand / "event_emitter.py").is_file():
            return cand
    return None


# ── the scan (the same walk that wrote core/event_catalog.py) ────────────────────────────────────────────────────────
EMIT_METHODS = {"emit": 0, "emit_background": 0, "emit_event": 1, "emit_or_report": None}
TYPE_RX = re.compile(r"^[A-Z][A-Za-z0-9]+$")


def _literals(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        a, b = _literals(node.body), _literals(node.orelse)
        if a is not None and b is not None:
            return a | b
    return None


def _arg(call, pos, kw):
    for k in call.keywords:
        if k.arg == kw:
            return k.value
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return None


def scan(root: pathlib.Path, depth: int = 3):
    """Every literal event type emitted under root: emitter calls, then the helpers that pass a type on (a parameter of
    the enclosing function, positional or keyword-only), then a local name the function assigns literals to."""
    trees = {}
    for p in sorted(root.rglob("*.py")):
        s = str(p)
        if "/tests/" in s or "/api_tests/" in s or p.name.startswith("test_") or p.name == "webhook_service.py":
            continue
        try:
            trees[p] = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
    parents = {}
    for p, tree in trees.items():
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Call):
                        parents.setdefault((p, id(node)), fn)
    types, unresolved = {}, []
    targets = {m: (pos, "event_type") for m, pos in EMIT_METHODS.items()}
    seen = set(targets)
    for level in range(depth):
        helpers = {}
        for p, tree in trees.items():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name not in targets:
                    continue
                pos, kw = targets[name]
                arg = _arg(node, pos, kw)
                if arg is None:
                    continue
                site = f"{p.relative_to(root)}:{node.lineno}"
                lits = _literals(arg)
                if lits is not None:
                    for v in lits:
                        if TYPE_RX.match(v):
                            types.setdefault(v, set()).add(site)
                    continue
                fn = parents.get((p, id(node)))
                if isinstance(arg, ast.Name) and fn is not None:
                    params = [a.arg for a in fn.args.posonlyargs + fn.args.args]
                    kwonly = [a.arg for a in fn.args.kwonlyargs]
                    if arg.id in params or arg.id in kwonly:
                        idx = None
                        if arg.id in params:
                            idx = params.index(arg.id) - (1 if params and params[0] in ("self", "cls") else 0)
                        if fn.name not in seen:
                            helpers[fn.name] = (idx, arg.id)
                        continue
                    assigned = set()
                    for sub in ast.walk(fn):
                        if isinstance(sub, ast.Assign) and any(isinstance(t, ast.Name) and t.id == arg.id for t in sub.targets):
                            lv = _literals(sub.value)
                            if lv is not None:
                                assigned |= {v for v in lv if TYPE_RX.match(v)}
                    if assigned:
                        for v in assigned:
                            types.setdefault(v, set()).add(site)
                        continue
                if level == 0:
                    unresolved.append(site)
        if not helpers:
            break
        targets = helpers
        seen |= set(helpers)
    return types, unresolved


def _migration_rows():
    """Every migration's EMISSION_POLICY_ROWS, read from its AST (no alembic import)."""
    out = {}
    for p in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in tree.body:
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EMISSION_POLICY_ROWS"
                                                     for t in node.targets)):
                for k, v in ast.literal_eval(node.value).items():
                    out[k] = (tuple(v), p.name)
    return out


# ── the catalog is its source ────────────────────────────────────────────────────────────────────────────────────────
def test_the_registry_catalog_is_its_source():
    found, unresolved = scan(REG_SRC)
    assert len(found) > 200, f"the scan found {len(found)} types: the walk read nothing like the tree"
    new, gone = sorted(set(found) - REGISTRY_EMITS), sorted(REGISTRY_EMITS - set(found))
    assert not new, f"emitted, not in core/event_catalog.py REGISTRY_EMITS (add it, and its row in a migration): {new}"
    assert not gone, f"in REGISTRY_EMITS, emitted nowhere any more (take it out): {gone}"
    # the two sites no level resolves are the outbox drainer (it replays stored events) and emit_background's *args
    assert all(s.startswith(("background_tasks/es_emit_outbox_drainer.py:", "event_emitter.py:")) for s in unresolved), unresolved


def test_the_teg_catalog_is_its_source():
    teg = _teg_src()
    if teg is None:
        pytest.skip("the TEG's source is not mounted here (CI: /w/teg_src; image runs: /agentvault_teg_layer_mvp) — NOT MEASURED")
    found, unresolved = scan(teg)
    assert not unresolved, unresolved
    assert set(found) == TEG_EMITS, (sorted(set(found) - TEG_EMITS), sorted(TEG_EMITS - set(found)))
    assert "LedgerBalanceChanged" in TEG_ALWAYS_ALLOWED
    teg_emitter = (teg / "event_emitter.py").read_text(encoding="utf-8")
    assert '_teg_policy_cache["LedgerBalanceChanged"] = True' in teg_emitter, "the TEG's own allow moved: TEG_ALWAYS_ALLOWED follows it"


# ── every emitted type has its row, and the rows are safe ────────────────────────────────────────────────────────────
def test_every_emitted_type_has_a_migration_row():
    rows = _migration_rows()
    assert rows, "no migration defines EMISSION_POLICY_ROWS"
    missing = sorted(ALL_EMITTED - set(rows))
    assert not missing, f"emitted with no row in any migration's EMISSION_POLICY_ROWS: {missing}"


def test_no_row_skips_a_balance_type():
    bad = sorted(t for t, ((reg, teg, skip), _f) in _migration_rows().items() if skip and t in BALANCE)
    assert not bad, f"balance types the projection would skip (the event store refuses such writes): {bad}"


def test_no_row_lets_both_emitters_record_one_type():
    both = REGISTRY_EMITS & TEG_EMITS
    assert both, "no type is emitted by both: the guard below would measure nothing"
    bad = sorted(t for t, ((reg, teg, _skip), _f) in _migration_rows().items() if t in both and reg and teg)
    assert not bad, f"rows letting the registry AND the TEG emit a type both emit (one event recorded twice): {bad}"


def test_the_teg_own_rows_let_the_teg_emit():
    rows = _migration_rows()
    for t in ("LedgerBalanceChanged", "NegativeEscrowLockClamped", "CrossTEGStaleSwept"):
        reg, teg, skip = rows[t][0]
        assert teg and not reg, (t, rows[t])
    assert rows["LedgerBalanceChanged"][0][2] is False, "the projection counts LedgerBalanceChanged"


# ── the gate's modes ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def gate(monkeypatch):
    monkeypatch.delenv("EVENT_EMITTER_FAIL_CLOSED", raising=False)
    monkeypatch.delenv("EVENT_EMITTER_POLICY_MODE", raising=False)
    monkeypatch.setattr(ee, "_emission_policy_cache", {"TokensTransferred": {
        "emit_from_teg": False, "emit_from_registry": True, "skip_in_projection": False},
        "AgentCreated": {"emit_from_teg": False, "emit_from_registry": False, "skip_in_projection": True}})
    monkeypatch.setattr(ee, "_shadow_logged", set())
    return monkeypatch


def test_the_default_mode_is_shadow_and_allows_a_missing_row_counted(gate):
    assert ee.emission_policy_mode() == "shadow"
    assert ee._get_emission_policy("NoSuchRowType", "registry") is True
    assert "NoSuchRowType" in ee._shadow_logged, "shadow logs the refusal enforce would make"


@pytest.mark.parametrize("env,mode,missing_allowed", [
    ({"EVENT_EMITTER_POLICY_MODE": "off"}, "off", True),
    ({"EVENT_EMITTER_POLICY_MODE": "shadow"}, "shadow", True),
    ({"EVENT_EMITTER_POLICY_MODE": "enforce"}, "enforce", False),
    ({"EVENT_EMITTER_FAIL_CLOSED": "true"}, "enforce", False),
    ({"EVENT_EMITTER_POLICY_MODE": "nonsense"}, "shadow", True),
])
def test_each_mode_on_a_missing_row(gate, env, mode, missing_allowed):
    for k, v in env.items():
        gate.setenv(k, v)
    assert ee.emission_policy_mode() == mode
    assert ee._get_emission_policy("NoSuchRowType", "registry") is missing_allowed
    assert ee._get_emission_policy("TokensTransferred", "registry") is True
    assert ee._get_emission_policy("AgentCreated", "registry") is False, "a row's own refusal holds in every mode"
    assert ee._get_emission_policy("TokensTransferred", "teg") is False


def test_an_unreadable_table_decides_nothing_even_in_enforce(monkeypatch):
    monkeypatch.setenv("EVENT_EMITTER_FAIL_CLOSED", "true")
    monkeypatch.setattr(ee, "_emission_policy_cache", {})
    assert ee._get_emission_policy("TokensTransferred", "registry") is True
    assert ee._get_emission_policy("NoSuchRowType", "registry") is True


def test_the_boot_check_names_the_missing_rows(monkeypatch):
    rows = {t: {"emit_from_teg": False, "emit_from_registry": True, "skip_in_projection": False}
            for t in sorted(ALL_EMITTED) if t not in ("AgentSpawned", "NegativeEscrowLockClamped")}

    async def fake_load():
        monkeypatch.setattr(ee, "_emission_policy_cache", dict(rows))
    monkeypatch.setattr(ee, "_load_emission_policies", fake_load)
    out = asyncio.new_event_loop().run_until_complete(ee.emission_policy_boot_check())
    assert out["read"] is True
    assert out["missing"] == {"registry": ["AgentSpawned"], "teg": ["NegativeEscrowLockClamped"]}

    async def empty_load():
        monkeypatch.setattr(ee, "_emission_policy_cache", {})
    monkeypatch.setattr(ee, "_load_emission_policies", empty_load)
    assert asyncio.new_event_loop().run_until_complete(ee.emission_policy_boot_check())["read"] is False


# ── the view's matrix ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_matrix_names_each_finding():
    r = lambda reg, teg, skip: {"emit_from_registry": reg, "emit_from_teg": teg, "skip_in_projection": skip}  # noqa: E731
    rows = {"TokensTransferred": r(True, False, False), "TokensIssued": r(True, True, False),
            "TransactionFeeCollected": r(True, False, True), "HagridGiniSnapshot": r(True, False, True),
            "AgentCreated": r(False, False, True)}
    m = {e["event_type"]: e for e in view.matrix(rows, mode="shadow", balance_types=frozenset(ee.BALANCE_MOVING_EVENT_TYPES),
                                                 store_counts={"OnlyInStore": 3, "TokensTransferred": 10},
                                                 shadow={"AgentSpawned": 2})}
    assert m["TokensTransferred"]["registry"] == "allow" and m["TokensTransferred"]["teg"] == "refuse"
    assert m["TokensTransferred"]["projection"] == "balance" and m["TokensTransferred"]["store_count"] == 10
    assert m["TokensTransferred"]["findings"] == [], "the TEG's refusal is by design: the registry records it"
    assert "both-may-emit" in m["TokensIssued"]["findings"]
    assert "balance-type-skipped" in m["TransactionFeeCollected"]["findings"]
    assert m["HagridGiniSnapshot"]["findings"] == ["row-without-emitter"]
    assert m["HagridGiniSnapshot"]["projection"] == "skipped"
    assert "registry-emits-refused" in m["AgentCreated"]["findings"]
    assert m["OnlyInStore"]["findings"] == ["in-store-without-row"] and m["OnlyInStore"]["emitted_by"] == []
    assert m["AgentSpawned"]["registry"] == "no-row-shadow"
    assert set(m["AgentSpawned"]["findings"]) == {"emitted-without-row", "shadow-would-refuse"}
    assert m["LedgerBalanceChanged"]["teg"] == "always-allowed" and "emitted-without-row" not in m["LedgerBalanceChanged"]["findings"]
    assert m["NegativeEscrowLockClamped"]["teg"] == "no-row-refused"
    assert "teg-emits-refused" in m["NegativeEscrowLockClamped"]["findings"], "nobody records it: lost"
    # the store unread: no type claims to be absent from it
    unread = {e["event_type"]: e for e in view.matrix(rows, mode="enforce", balance_types=frozenset(), store_counts=None,
                                                      shadow=None)}
    assert unread["TokensTransferred"]["store_count"] is None and unread["AgentSpawned"]["registry"] == "no-row-refused"
    assert all("in-store-without-row" not in e["findings"] for e in unread.values())


def test_drift_names_what_differs():
    a = {"X": {"emit_from_registry": True, "emit_from_teg": False, "skip_in_projection": False},
         "Y": {"emit_from_registry": True, "emit_from_teg": False, "skip_in_projection": False}}
    b = {"X": {"emit_from_registry": True, "emit_from_teg": True, "skip_in_projection": False},
         "Z": {"emit_from_registry": False, "emit_from_teg": True, "skip_in_projection": True}}
    d = view.drift(a, b)
    assert d["only_here"] == ["Y"] and d["only_there"] == ["Z"]
    assert d["differing"] == [{"event_type": "X", "here": a["X"], "there": {
        "emit_from_registry": True, "emit_from_teg": True, "skip_in_projection": False}}]
