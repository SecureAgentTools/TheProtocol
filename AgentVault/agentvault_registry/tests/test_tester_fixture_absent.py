"""§TESTBED (2026-09-19): on a fresh frame the MCP tester's two HAND-SEEDED fixtures (the exchange listing, the support review
grant) do not exist. A 404 in the server's own phrase, with the fixture's variable UNSET, is a named skip; a 404 on a
fixture the frame named, a different phrase, or any other status still fails. Measured on the first kit sandbox run."""
import ast
import pathlib

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as flow

SRC = pathlib.Path(flow.__file__)


def test_the_exchange_listing_absent_is_a_skip_only_while_unnamed():
    fail = "expected success but got HTTP 404: {\"error\":{\"detail\":\"listing 'TUTCO' not found\"}}"
    why = flow._fixture_absent_reason("theprotocol_getAgoraTrades", False, None, 404, fail, env={})
    assert why and "API_TEST_EXCHANGE_LISTING" in why
    assert flow._fixture_absent_reason("theprotocol_getAgoraTrades", False, None, 404, fail,
                                       env={"API_TEST_EXCHANGE_LISTING": "LRCX"}) is None   # named and missing: a real red
    assert flow._fixture_absent_reason("theprotocol_getAgoraTrades", False, None, 500, fail, env={}) is None
    assert flow._fixture_absent_reason("theprotocol_getAgoraTrades", False, None, 404, "route not found", env={}) is None
    assert flow._fixture_absent_reason("theprotocol_getMyContracts", False, None, 404, fail, env={}) is None


def test_the_review_grant_absent_is_a_skip_only_while_unnamed():
    fail = "expected success but got HTTP 404: upstream HTTP 404: No such review grant"
    assert flow._fixture_absent_reason("theprotocol_adminReviewMessages", False, None, 404, fail, env={})
    assert flow._fixture_absent_reason("theprotocol_adminReviewMessages", False, None, 404, fail,
                                       env={"API_TEST_SUPPORT_GRANT_ID": "g-1"}) is None


def test_a_healthy_or_already_skipped_row_is_left_alone():
    fail = "listing 'TUTCO' not found"
    assert flow._fixture_absent_reason("theprotocol_getAgoraTrades", True, None, 404, fail, env={}) is None
    assert flow._fixture_absent_reason("theprotocol_getAgoraTrades", False, "policy", 404, fail, env={}) is None


def test_the_admin_sweep_skips_an_unresolved_fixture_before_calling():
    """Pinned on the source: in _sweep_one_admin the unresolved check sits BEFORE the admin call."""
    text = SRC.read_text()
    fn = text[text.index("async def _sweep_one_admin(tool):"):]
    fn = fn[:fn.index("# ── DRIVER: bounded-concurrent admin bridge sweep")]
    assert fn.index("unresolved_fixtures(adm_args)") < fn.index("await _mcp_rpc_call_admin(")
    ast.parse(text)
