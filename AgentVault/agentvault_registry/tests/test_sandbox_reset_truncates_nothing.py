"""§RESETTRUNCATE (2026-09-29): the sandbox self-reset truncates nothing, and no SQL string in the registry source starts
with TRUNCATE.

The reset used to TRUNCATE 38 tables in one transaction. It reaches sbx-alpha, a long-lived federated sandbox frame, at
the start and the end of every MCP tester run, and it wiped nothing only because the fourth table it named (`webhooks`)
exists in no migration: PostgreSQL aborted the transaction there and rolled every TRUNCATE back, while the log said "All
tables truncated". A savepoint per table would have "fixed" that and emptied the frame. The reseed and the sentinel are
what every run actually did; this pins the reset to that, and pins the rest of the source to no TRUNCATE at all, so a new
one is a decision somebody writes down here rather than a line that slips in. The scan reads the AST, never the text, so
a comment that mentions the word does not count.
"""
import ast
import pathlib
import re
import sys
import types

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
# the SQL statement, in either case convention; prose such as "Truncate DID for display" is not one
SQL_TRUNCATE = re.compile(r"^\s*(?:TRUNCATE\b|truncate\s+table\b)")


def _string_starts(tree):
    """(lineno, text) of every string literal and the leading piece of every f-string."""
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant) \
                and isinstance(node.values[0].value, str):
            yield node.lineno, node.values[0].value
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def _truncates(tree):
    """The lines that hold one (an f-string's leading piece is also walked as a string of its own, so once per line)."""
    return sorted({ln for ln, s in _string_starts(tree) if SQL_TRUNCATE.match(s)})


def test_no_sql_string_in_the_registry_source_starts_with_truncate():
    scanned, hits = 0, []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        scanned += 1
        hits += [f"{path.relative_to(SRC)}:{ln}" for ln in _truncates(tree)]
    assert scanned > 300, f"the scan read {scanned} modules; it is looking in the wrong place"
    assert not hits, "a TRUNCATE in the registry source (the sandbox reset lost its only guard to an accident): " + ", ".join(hits)


def test_the_detector_sees_both_shapes_and_ignores_prose():
    """Control: without this the gate could pass by recognising nothing."""
    tree = ast.parse('a = text(f"TRUNCATE TABLE {t} CASCADE")\nb = "  truncate table agent_cards"\n'
                     'c = "TRUNCATE agents"\nd = "Truncate DID for display"\ne = "TRUNCATED"\n# TRUNCATE in a comment\n')
    assert _truncates(tree) == [1, 2, 3]


async def test_the_reset_opens_no_database_session(monkeypatch):
    """Behaviour: a reset with the sandbox switches on re-seeds and never opens a database session."""
    monkeypatch.setenv("SANDBOX_MODE", "true")
    monkeypatch.setenv("SANDBOX_RESET_SECRET", "unit-test-reset-secret")
    import agentvault_registry.routers.admin_api_test as mod
    import agentvault_registry.database as database

    opened = []

    class _Recorder:
        def __call__(self, *a, **k):
            opened.append("session")
            raise AssertionError("the reset opened a database session")

    monkeypatch.setattr(database, "AsyncSessionLocal", _Recorder())
    seeded = []

    async def _seed():
        seeded.append(True)

    monkeypatch.setitem(sys.modules, "agentvault_registry.test_seed", types.SimpleNamespace(seed=_seed))

    class _NoLogin:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return types.SimpleNamespace(json=lambda: {}, status_code=401)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _NoLogin)
    monkeypatch.setattr(mod, "_last_self_reset", 0.0)
    request = types.SimpleNamespace(headers={"X-Reset-Secret": "unit-test-reset-secret"})
    out = await mod.self_reset(request)
    assert seeded == [True] and opened == []
    assert out["status"] == "success" and "No table is truncated" in out["message"]
