"""§JSONCAST (2026-09-05) — raw SQL that applies a jsonb function to `agent_cards.card_data`
must cast it, because the column is `json` on the four older Frame-A operators and `jsonb`
everywhere else. Postgres resolves function types for the whole statement at parse time, so
one uncast `jsonb_typeof(s.card_data->'skills')` made `/agent-cards/discover` answer 500 on
those nodes from V0213 to V0217 — with no `q`, with the branch never taken.

Structural gate over the SOURCE text (no DB needed): every `jsonb_<fn>(` whose argument
mentions `card_data` must carry `::jsonb` inside that argument. Control: point
DISCOVER_SRC at a tree that still carries the uncast call (e.g. the V0217 image's
/app/src/agentvault_registry) and the test goes RED.
"""
import os
import pathlib
import re

import pytest

_HERE = pathlib.Path(__file__).resolve().parent.parent / "src" / "agentvault_registry"
SRC = pathlib.Path(os.environ.get("DISCOVER_SRC", str(_HERE)))
# ⚠ SCOPE IS DERIVED, NOT LISTED. The first version named four files by hand.
# Swept 2026-09-05 against the whole tree: two of those four carry no
# `card_data` + `jsonb_*(` combination at all, so the gate was partly vacuous —
# while the ONE file in the tree that still holds the uncast pattern
# (services/operator_renamer.py, two `jsonb_set(card_data, ...)` writes against
# the OPERATOR's own DB) sat outside it. A gate with a hand-maintained scope
# passes loudest about the files it cannot see; the count not moving IS the
# finding. Walk every module instead, so a new call site is covered the day it
# is written rather than the day someone remembers this list.
def _all_sources():
    return sorted(
        str(f.relative_to(SRC))
        for f in SRC.rglob("*.py")
        # node_modules: an installed FE dependency tree is not our SQL (§OSSRC 2026-09-14)
        if ".bak" not in str(f) and "__pycache__" not in str(f) and "node_modules" not in f.parts
    )
CALL = re.compile(r"jsonb_[a-z_]+\(")


_SQL_COMMENT = re.compile(r"--[^\n]*")


def _strip_python_comments(text: str) -> str:
    """Remove `#` comments without touching string literals.

    ⚠ THE GATE USED TO REFUSE THE VERY FIX IT ASKS FOR. It scans source TEXT, so
    a Python comment or docstring that spells the uncast call — exactly what one
    writes next to a cast to explain why the cast is there — trips it. That cost
    the other session two attempts, and it got worse when the scope widened from
    four files to every module. Tokenising is the honest fix: a `#` inside a
    string is not a comment, so a regex would eat SQL containing one.

    ⚠ THIS FIXES `#` COMMENTS ONLY, AND THE REST CANNOT BE FIXED. A docstring or
    any string literal that spells the call still trips the gate, BY
    CONSTRUCTION: the real SQL lives in Python strings, so a scan that ignored
    strings would ignore every actual call site. Measured both ways —
    `# jsonb_set(card_data, ...)` in a comment: 966 pass; the same words in a
    docstring: still red.

    So the discipline their friction paid for stands for docstrings and is now
    the gate's own rule, kept here because this file is where it gets re-read:
    prose beside a cast names the CLASS, never the call.
    """
    import io
    import tokenize
    try:
        out, last = [], (1, 0)
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                continue
            out.append(tok)
        return tokenize.untokenize(out)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text            # unparseable: scan it as-is rather than skip it


def _calls(text: str):
    """Yield (fn, argument_text) for every jsonb_* call, argument = balanced parens.

    Comments are stripped first — Python `#` ones because prose beside a cast
    legitimately quotes the bad form, SQL `--` ones because a comment inside an
    argument list carries commas and parens of its own and would unbalance the
    scan.
    """
    text = _SQL_COMMENT.sub("", _strip_python_comments(text))
    for m in CALL.finditer(text):
        depth, i, start = 1, m.end(), m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        yield m.group(0)[:-1], text[start:i - 1]


@pytest.mark.parametrize("rel", _all_sources())
def test_every_jsonb_call_on_card_data_is_cast(rel):
    path = SRC / rel
    if not path.exists():
        pytest.skip(f"{rel} absent in {SRC}")
    text = path.read_text()
    bad = []
    for fn, arg in _calls(text):
        first_arg = arg.split(",", 1)[0]
        if "card_data" in first_arg and "::jsonb" not in first_arg:
            bad.append(f"{fn}({first_arg.strip()[:80]}…)")
    assert not bad, f"{rel}: jsonb function applied to an uncast card_data — 500 on json-column nodes: {bad}"


def test_gate_sees_the_discover_skills_clause():
    """The gate must be looking at the clause that failed, not at an empty match."""
    text = (SRC / "routers/agent_cards.py").read_text()
    hits = [a for fn, a in _calls(text) if "skills" in a]
    assert hits, "the skills clause is not in agent_cards.py — the gate's subject moved"
