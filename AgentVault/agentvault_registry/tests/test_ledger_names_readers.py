"""W4 phase 1 (agentvault2-aa, 2026-10-25): every registry reader of a renamed ledger event asks the map.

His words that day to agentvault2-69: "i want the illegal wording completly gone before opening" and, on the ledger, "just
use the new wording and make it accept both or something" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md, W4).
Phase 2 lets an emitter write the new names (UnitsTransferred for TokensTransferred ...); a reader that compares against the
old literal alone would go blind that day without an error. So:

- a module that compares an event type against an old name, or asks the store for one by `params`, must ask
  core/ledger_names (the pin: a new literal comparison in a module that does not ask the map fails here);
- the readers changed for phase 1 read an event under either name the same way (push opt-in, the notification catalog's
  aliases, the activity titles, the tester's ledger counts).
The reactors' half is tests/reactors/test_reactor_ledger_names.py.
"""
from __future__ import annotations

import ast
import pathlib

from agentvault_registry.core import ledger_names

SRC = pathlib.Path(ledger_names.__file__).resolve().parents[1]
OLD = set(ledger_names.RENAMED) | set(ledger_names.AGORA_RENAMED) | set(ledger_names.LEGACY)


def _files():
    for p in sorted(SRC.rglob("*.py")):
        rel = p.relative_to(SRC).as_posix()
        if rel.startswith("static/") or "/tests/" in f"/{rel}" or "__pycache__" in rel or rel == "core/ledger_names.py":
            continue
        yield rel, p.read_text(encoding="utf-8")


def _lits(node) -> set:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out = set()
        for e in node.elts:
            out |= _lits(e)
        return out
    return set()


def _sites():
    """(rel, line, kind, names, asks_the_map) of every comparison against an old name and every `params` naming one."""
    for rel, src in _files():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        asks = "ledger_names" in src
        for n in ast.walk(tree):
            if isinstance(n, ast.Compare):
                names = _lits(n.left)
                for c in n.comparators:
                    names |= _lits(c)
                if names & OLD:
                    yield rel, n.lineno, "compare", sorted(names & OLD), asks
            elif isinstance(n, ast.Call):
                for kw in n.keywords:
                    if kw.arg == "params" and isinstance(kw.value, ast.Dict):
                        for k, v in zip(kw.value.keys, kw.value.values):
                            if (isinstance(k, ast.Constant) and k.value == "event_type"
                                    and isinstance(v, ast.Constant) and v.value in OLD):
                                yield rel, n.lineno, "store query", [v.value], asks


def test_the_scan_sees_the_shapes_it_pins():
    sites = list(_sites())
    assert any(s[0] == "routers/teg_transactions.py" and s[2] == "compare" for s in sites), "the normalized branches"


def test_every_reader_of_an_old_name_asks_the_map():
    bad = [f"{rel}:{line} {kind} {names}" for rel, line, kind, names, asks in _sites() if not asks]
    assert bad == [], "read the event under every name it may be written under (core/ledger_names)"


def test_no_store_query_names_one_old_name():
    bad = [f"{rel}:{line} {names}" for rel, line, kind, names, _ in _sites() if kind == "store query"]
    assert bad == [], "a GET for one old name misses the event under its new one: loop over ledger_names.live_names"


def test_a_transfer_push_opt_in_reads_either_name():
    from agentvault_registry.background_tasks.push_notify import _device_wants
    prefs = {"min_transfer_avt": 5}
    for t in ("TokensTransferred", "UnitsTransferred"):
        assert _device_wants(prefs, t, 10) is True and _device_wants(prefs, t, 1) is False, t
        assert _device_wants({}, t, 10) is False, f"{t}: transfer pushes stay strictly opt-in"


def test_the_notification_catalog_resolves_a_new_name_as_its_event():
    from agentvault_registry.services import notification_catalog as C
    old = C.get_type("TokensTransferred")
    assert old is not None and C.get_type("UnitsTransferred") is old
    assert C.get_type("NoSuchEventAnywhere") is None


def test_an_activity_title_reads_a_new_name_as_its_event():
    from agentvault_registry.routers.admin_health import _format_event_title
    for old, new in (("TokensTransferred", "UnitsTransferred"), ("TokensStaked", "UnitsLocked"),
                     ("RewardsDistributed", "LockPayoutsDistributed")):
        assert _format_event_title(new) == _format_event_title(old), new
    assert _format_event_title("AgentRegistered") == "Agent Registered"


def test_the_testers_ledger_count_counts_every_name(monkeypatch):
    from agentvault_registry.api_tests import multiframe_helpers as H
    asked = []

    def fake(container, sql):
        asked.append(sql)
        return 0, "7\n"
    monkeypatch.setattr(H, "run_psql_in_db_container", fake)
    assert H.query_event_count("es-db", "TokensTransferred") == 7
    assert "'TokensTransferred'" in asked[-1] and "'UnitsTransferred'" in asked[-1] and " IN (" in asked[-1]
    H.query_event_count("es-db", "AgentCreated")
    assert asked[-1] == "SELECT count(*) FROM events WHERE event_type IN ('AgentCreated');"
