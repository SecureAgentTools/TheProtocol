"""U3 (2026-09-05) — no test may hardcode a container or database name.

WHAT THIS PREVENTS. §APITEST found the retired sandbox tier named by literal in
five places. A `docker exec` against a container that still EXISTS but is Exited
is answered by Docker with `APIError 409`, not "no such container", so the MCP
sweep reported **0 tools in 0.36 s** — an empty run that reads like a clean one.
Those five were fixed by hand. This gate exists because nothing stopped the
sixth, and on 2026-09-05 a derived scan found NINE more:

  * 3 container literals in flow_cross_frame_blocklist_propagation (the target
    object was already bound twenty lines above the first one)
  * 6 database literals across flow_mcp_lifecycle and four flow_zkp_* files,
    every one of them naming `agentvault_registry_test` — a database that DOES
    NOT EXIST on the current tier, where it is `frame_test_registry`. Measured:
    psql answers `FATAL: database "agentvault_registry_test" does not exist`,
    and the caller reads that as "no rows".

⚠ SCOPE IS DERIVED, NOT LISTED. A gate with a hand-maintained scope passes
loudest about the files it cannot see — the §CAPSEARCH lesson, and the reason
the sibling json-column gate walks the tree too.

⚠ COMMENTS ARE NOT CODE. The scan reads string CONSTANTS out of the AST and
skips docstrings, so prose may name these containers freely (this file does).
Anything else would make the gate refuse its own explanation — the trap the
json-column gate fell into twice.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

_HERE = pathlib.Path(__file__).resolve().parent.parent
API_TESTS = _HERE / "src" / "agentvault_registry" / "api_tests"

# The files whose JOB is to hold a default. Every one of these reads its value
# from an env var first; the literal is the fallback, which is the whole point.
DEFAULT_HOLDERS = {
    "multiframe_helpers.py",     # SANDBOX_TARGET / operator targets
    "federation_suite/rig.py",   # the federation rig's registry map
    "db_verifier.py",            # one API_TEST_REG_DB_CONTAINER default
}

# Container- and database-name shapes on this box. Deliberately specific: an
# over-broad pattern matched the TAG "cloud-op-side" on the first run, and a
# gate that cries wolf gets switched off.
FORBIDDEN = re.compile(
    r"agentvault_registry_test(?:_b)?\b"
    r"|agentvault_registry_[ab]\b"
    r"|agentvault_(?:teg_layer|event_store)_(?:test|db)[a-z_]*\b"
    r"|agentvault_registry_db_test[a-z_]*\b"
    r"|cloud-op-(?:sandbox|sbx)[a-z0-9]*"
    r"|sbx-(?:alpha|beta)-[a-z]+(?:-[a-z]+)*"
    r"|frame_test_registry\b"
)


def _sources():
    for f in sorted(API_TESTS.rglob("*.py")):
        if ".bak" in f.name or "__pycache__" in str(f):
            continue
        yield f


def _rel(f: pathlib.Path) -> str:
    return str(f.relative_to(API_TESTS))


def _docstring_ids(tree: ast.AST) -> set:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def literals_in(path: pathlib.Path):
    """Yield (lineno, matched_text) for forbidden names in real string constants."""
    tree = ast.parse(path.read_text())
    skip = _docstring_ids(tree)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in skip):
            for m in FORBIDDEN.findall(node.value):
                yield node.lineno, m


@pytest.mark.parametrize("rel", [_rel(f) for f in _sources()])
def test_no_hardcoded_tier_names(rel):
    if rel in DEFAULT_HOLDERS:
        pytest.skip(f"{rel} is a sanctioned default-holder (env-first, literal as fallback)")
    hits = list(literals_in(API_TESTS / rel))
    assert not hits, (
        f"{rel} hardcodes tier name(s) "
        f"{sorted({m for _l, m in hits})} at line(s) {sorted({l for l, _m in hits})}. "
        f"Take the name from the target object (`target.b_registry_container`, "
        f"`rig` constants) or pass db_name=None so psql resolves $POSTGRES_DB. "
        f"A literal here does not fail loudly — Docker answers 409 for a stopped "
        f"container and psql answers FATAL for a missing database, and both read "
        f"as an empty result."
    )


def test_gate_sees_a_planted_literal(tmp_path):
    """RED control: the scan must catch a literal it is meant to catch."""
    bad = tmp_path / "planted.py"
    bad.write_text('X = exec_in_container("agentvault_registry_test_b", ["true"])\n')
    assert [m for _l, m in literals_in(bad)] == ["agentvault_registry_test_b"]


def test_gate_ignores_prose_and_tags(tmp_path):
    """GREEN control: comments, docstrings and unrelated hyphenated words pass.

    `cloud-op-side` is a real tag in test_critical.py; an earlier draft of this
    pattern matched it and would have failed a correct file.
    """
    ok = tmp_path / "innocent.py"
    ok.write_text(
        '"""Module doc mentioning agentvault_registry_test freely."""\n'
        '# comment naming cloud-op-sandboxalpha\n'
        'TAGS = ["peer-admission", "cloud-op-side"]\n'
        'NAME = target.b_registry_container\n'
    )
    assert list(literals_in(ok)) == []


def test_scope_is_derived_and_non_trivial():
    """A gate over zero files passes loudest. Count what it actually walks."""
    n = sum(1 for _ in _sources())
    assert n > 200, f"only {n} api_tests sources found — scope collapsed"
