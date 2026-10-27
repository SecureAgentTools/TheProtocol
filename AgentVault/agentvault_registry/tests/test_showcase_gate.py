"""§SHOWCASEGATE (2026-09-09) — the showcase-availability answer lives in ONE place.

His word: "just deactivate our chat showcase on eu-asia frame on landingpage … can stay for
frame-a b c network", and "it should work in future with other frames automatically so maybe
make it scalable".

The scalable shape is a runtime, server-derived flag: the console asks
`/public/registry-config.showcase_chat_enabled`, and that field is computed by the SAME
predicate `/public/showcase/onboard` refuses on. These tests pin that they cannot drift apart —
which is the actual defect class (§COSMETICS-ORIGIN: one fact computed in two places, each
exposed by fixing the other).

They are STRUCTURAL on purpose and they say so: a source gate cannot see ordering or binding
(§DISCECHO). The behavioural proof is the live cross-frame control run at the roll — Frame A
answers enabled/200 and EU/ASIA answer disabled/503 on the same build.
"""
import ast
import pathlib

MAIN = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "main.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def _funcdefs(name):
    return [n for n in ast.walk(TREE)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]


def test_the_predicate_is_defined_exactly_once():
    """Two definitions would be two opinions about whether the showcase works."""
    assert len(_funcdefs("_showcase_chat_unavailable_reason")) == 1


def test_the_predicate_names_both_states_not_just_a_bool():
    """'disabled' (switched off) and 'unconfigured' (no payer here) are different facts and the
    endpoint says which on screen. A bool would be the §29e class — a verdict that cannot tell
    two states apart."""
    fn = _funcdefs("_showcase_chat_unavailable_reason")[0]
    returned = {n.value.value for n in ast.walk(fn)
                if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)}
    assert "disabled" in returned and "unconfigured" in returned
    assert None in returned, "the available case must return None, not a falsy string"


def test_registry_config_publishes_the_flag_from_that_predicate():
    """The console's gate must read the server's own answer, never re-derive it."""
    assert '"showcase_chat_enabled": _showcase_chat_unavailable_reason() is None' in SRC


def test_onboard_refuses_through_the_same_predicate():
    """CONTROL for the pair: if the guard ever stops calling it, the config rail could say
    'enabled' about a rail that refuses — the blank-promise shape."""
    fn = [n for n in ast.walk(TREE)
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "showcase_onboard"]
    assert len(fn) == 1
    calls = {n.func.id for n in ast.walk(fn[0])
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_showcase_chat_unavailable_reason" in calls
    # and it must NOT have kept its own copy of the conjunction
    body = ast.get_source_segment(SRC, fn[0]) or ""
    assert "_SHOWCASE_CLIENT_SECRET and _SHOWCASE_AGENT_DID" not in body, \
        "showcase_onboard re-derives the predicate instead of calling it"
