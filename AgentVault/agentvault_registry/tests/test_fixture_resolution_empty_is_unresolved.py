"""§EVTYPES8 — an EMPTY fixture resolution must count as unresolved.

WHY. `McpFixtureBag.get` returns whatever is present, and both of its paths can
hand back an empty value that is not the `${name}` sentinel: a `flow_values` key
published as "" or None, or a declared dataclass field whose default IS "" —
`second_agent_did`, `sample_card_hri`, `developer_jwt_nonadmin` and friends.
`unresolved_fixtures` then sees a plain string, reports nothing missing, and the
sweep calls the tool with a meaningless argument. The row's colour is then about
the empty string rather than about the tool.

Measured before the fix: `flow_values.sample_card_hri` was None on the frame while
`getAgentCardByHRI` still RAN, answered 401, and carried `skip_reason: None`. That
401 looked like an auth finding on a tier-1 tool and was nothing of the sort.

Both directions are asserted, because the failure modes are symmetric: resolve
something that IS present (a real value must never be swallowed into a skip), and
refuse to resolve something that is only nominally present.
"""
from __future__ import annotations

import pytest

from agentvault_registry.api_tests.contracts.mcp_contracts import (
    McpFixtureBag, resolve_args, unresolved_fixtures,
)


def _bag(**flow):
    return McpFixtureBag(sentinel_did="did:theprotocol:real", sentinel_jwt="jwt-real",
                         flow_values=dict(flow))


def test_a_real_value_still_resolves():
    """GREEN control — the fix must not swallow a present fixture."""
    args = resolve_args({"did": "${sentinel_did}"}, _bag())
    assert args["did"] == "did:theprotocol:real"
    assert unresolved_fixtures(args) == []


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_an_empty_flow_value_is_unresolved(empty):
    """RED control — the case that produced a 401 nobody could explain."""
    args = resolve_args({"hri": "${sample_card_hri}"}, _bag(sample_card_hri=empty))
    assert args["hri"] == "${sample_card_hri}", (
        f"an empty flow_value ({empty!r}) resolved to itself and would have been sent"
    )
    assert unresolved_fixtures(args) == ["sample_card_hri"]


def test_a_dataclass_field_defaulting_to_empty_string_is_unresolved():
    """The second path into `bag.get`, and the one no flow_values key covers.

    `second_agent_did` is declared `= ""`, so `getattr` returns the empty string
    and the `${name}` sentinel never survives — invisible to every flow_values
    based test.
    """
    args = resolve_args({"did": "${second_agent_did}"}, _bag())
    assert args["did"] == "${second_agent_did}"
    assert unresolved_fixtures(args) == ["second_agent_did"]


def test_a_missing_fixture_is_still_unresolved():
    """The pre-existing behaviour must be unchanged."""
    args = resolve_args({"x": "${no_such_fixture_evtypes8}"}, _bag())
    assert unresolved_fixtures(args) == ["no_such_fixture_evtypes8"]


def test_non_fixture_values_pass_through_untouched():
    """Literals, numbers, dicts and lists are not fixture templates."""
    args = resolve_args(
        {"n": 1, "s": "plain", "d": {"a": 1}, "l": [1, 2], "empty_literal": ""}, _bag())
    assert args == {"n": 1, "s": "plain", "d": {"a": 1}, "l": [1, 2], "empty_literal": ""}
    assert unresolved_fixtures(args) == []


def test_zero_and_false_are_values_not_emptiness():
    """A falsy value that is not a string must NOT be treated as missing.

    `0` and `False` are legitimate fixture values; only None and a blank string
    mean 'nothing was published'. Getting this wrong would turn a real fixture
    into a skip, which is the same defect pointing the other way.
    """
    args = resolve_args({"a": "${zero}", "b": "${false}"}, _bag(zero=0, false=False))
    assert args["a"] == 0 and args["b"] is False
    assert unresolved_fixtures(args) == []
