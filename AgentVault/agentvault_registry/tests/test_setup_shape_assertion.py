"""§EVTYPES8 — controls for the setup-path shape assertion.

WHY THIS FILE EXISTS. The MCP sweep decides each row by lifecycle > setup >
contract, so a tool the phase-3 setup creates never evaluates its own contract.
That is right for the CALL (a create must not run twice) and wrong for the
ASSERTION: 19 hand-written `expect_keys` sat on setup-path tools and were
discarded, and 10 of those are also fixture-skipped on the cloud operators, so
their assertion executed on no node in the fleet. `_setup_shape_failure` applies
the success-shape half against the response setup already holds.

The function has two deliberate narrowings, and a control that only proves the
happy path would let either of them rot into a no-op:

  * a REFUSAL contract must be ignored here (setup calls with valid arguments and
    is answered 2xx; the contract describes a refusal to junk ones), and
  * a tool with no hand-written contract must be ignored (`get_contract` back-fills
    `expect_keys` from the harvest file, which was never harvested from setup's
    arguments).

So each direction is asserted, and the subjects are DERIVED from the live contract
table rather than hardcoded — with a population assertion, because a sweep over an
empty list passes without measuring anything.
"""
from __future__ import annotations

import inspect

import pytest

from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS, get_contract
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import (
    test_flow_mcp_lifecycle as _flow_module,
)
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (
    _setup_shape_failure,
)

# The tools phase-3 creates through `_call`, i.e. the ones whose row the setup
# outcome decides. Kept as a literal on purpose: if the setup grows a new create,
# this list going stale is a smaller problem than a test that re-derives the
# product's own control flow and therefore measures itself.
_SETUP_TOOLS = (
    "theprotocol_authorizePayment", "theprotocol_createAgent", "theprotocol_createApiKey",
    "theprotocol_createBundle", "theprotocol_createAgoraListing",
    "theprotocol_createOrganization", "theprotocol_createOrganizationTeam",
    "theprotocol_createPipeline", "theprotocol_createProposal", "theprotocol_createTegPolicy",
    "theprotocol_createTegPoliciesBatch",   # §MCPTEST30 (V0641): phase 16 makes the delete subject through it
    "theprotocol_createVersion", "theprotocol_createWebhook",
    "theprotocol_depositReputationBond", "theprotocol_getAgentToken",
    "theprotocol_getCircuits", "theprotocol_getMyAgents", "theprotocol_guildAward",
    "theprotocol_guildBid", "theprotocol_guildGetOrder", "theprotocol_guildPostOrder",
    "theprotocol_guildSubmitWork", "theprotocol_listAgentTemplates",
    "theprotocol_logTegDispute", "theprotocol_placeAgoraOrder", "theprotocol_lockUnits",
    "theprotocol_submitFundingRequest", "theprotocol_submitSupportTicket",
)


def _shape_subjects():
    out = []
    for t in _SETUP_TOOLS:
        if t not in MCP_CONTRACTS:
            continue
        c = get_contract(t)
        if c.skip_reason or c.expect_status in ("error_4xx", "error_5xx"):
            continue
        if c.expect_keys:
            out.append((t, list(c.expect_keys)))
    return out


def _refusal_subjects():
    return [t for t in _SETUP_TOOLS
            if t in MCP_CONTRACTS and get_contract(t).expect_status in ("error_4xx", "error_5xx")]


def test_setup_path_has_shape_contracts_to_assert():
    """The population this whole mechanism exists for is not empty."""
    subjects = _shape_subjects()
    assert len(subjects) >= 5, (
        "expected the setup path to carry hand-written expect_keys contracts; found "
        f"{len(subjects)}. If the setup no longer creates these entities, retire the "
        "assertion instead of leaving a control that sweeps an empty list."
    )


@pytest.mark.parametrize("tool,keys", _shape_subjects())
def test_complete_response_passes(tool, keys):
    """GREEN control: a response carrying every declared key asserts clean."""
    inner = {k: "value" for k in keys}
    assert _setup_shape_failure(tool, inner) is None


@pytest.mark.parametrize("tool,keys", _shape_subjects())
def test_missing_key_fails_and_names_it(tool, keys):
    """RED control: drop one declared key and the reason must name it."""
    dropped = keys[0]
    inner = {k: "value" for k in keys if k != dropped}
    reason = _setup_shape_failure(tool, inner)
    assert reason, f"{tool}: dropping {dropped!r} produced no failure — the assertion is inert"
    assert dropped in reason, f"{tool}: reason does not name the missing key: {reason}"


@pytest.mark.parametrize("tool", _refusal_subjects())
def test_refusal_contract_is_not_applied_to_a_successful_create(tool):
    """A refusal contract describes junk arguments the setup never sends.

    Applying it here would fail a create for having worked. Empty response =
    worst case; still no complaint.
    """
    assert _setup_shape_failure(tool, {}) is None


def test_refusal_population_is_not_empty():
    assert _refusal_subjects(), (
        "no refusal contract sits on the setup path any more — delete the narrowing "
        "and its control together rather than keeping a check that guards nothing."
    )


def test_tool_without_handwritten_contract_is_ignored():
    """Harvested expect_keys must not become a floor for setup's response."""
    assert "theprotocol_notARealToolEVTYPES8" not in MCP_CONTRACTS
    assert _setup_shape_failure("theprotocol_notARealToolEVTYPES8", {}) is None


def test_non_object_result_is_reported_not_raised():
    subjects = _shape_subjects()
    tool = subjects[0][0]
    reason = _setup_shape_failure(tool, ["not", "an", "object"])
    assert reason and "not an object" in reason


# ─────────────────────────────────────────────────────────────────────────────
# §EVTYPES8 — the wrong-tier auth matrix opt-out
#
# The matrix calls every tool with `{}` and a wrong-tier credential on the
# stated assumption that the auth gate fires before argument validation — the
# assumption the matrix exists to falsify. `skip_reason` stops the sweep and was
# never read by the matrix, so contracts saying "not probed — tears down real
# containers" / "recursive, would loop" were probed regardless. Where an open
# gate would cost infrastructure rather than a refusal, the contract opts out.
# ─────────────────────────────────────────────────────────────────────────────
import pathlib


def _flagged():
    return sorted(n for n in MCP_CONTRACTS if get_contract(n).never_probe_wrong_tier)


def test_optout_population_is_not_empty():
    """A field nothing sets is a field that proves nothing."""
    assert _flagged(), (
        "no contract opts out of the wrong-tier matrix any more — if that is "
        "deliberate, delete the field and this control together."
    )


def test_optout_defaults_off():
    """Every other contract must still be gate-probed."""
    off = [n for n in MCP_CONTRACTS if not get_contract(n).never_probe_wrong_tier]
    assert len(off) > len(_flagged()) * 10, (
        "the opt-out has spread far enough to gut the matrix; it is for tools "
        "whose open gate destroys something, not for tools that are merely noisy"
    )


def test_optout_tools_also_carry_a_skip_reason():
    """The two exclusions must agree.

    A tool the SWEEP is willing to invoke has no business refusing the far
    cheaper gate probe — and a tool excluded from both should say why once.
    """
    for name in _flagged():
        assert get_contract(name).skip_reason, (
            f"{name} opts out of the wrong-tier matrix but the sweep still calls "
            f"it — decide which is true and make both say it"
        )


def test_matrix_actually_reads_the_optout():
    """The flag must be load-bearing where it claims to act.

    A source assertion on purpose: the matrix is an inner async closure over a
    live registry, so the only honest cheap check that it HONOURS the field is
    that the early return exists in the function that does the probing.
    """
    # ⚠ Locate the module by IMPORT, never by walking up from __file__. The
    # tree puts the source at <repo>/agentvault_registry/src/... with tests at
    # <repo>/agentvault_registry/tests/, and the IMAGE puts it at /app/src/...
    # with tests at /app/tests/ — a relative walk that is right in one layout
    # raises FileNotFoundError in the other, which is a failure about the path
    # and not about the thing under test. (Measured: this control passed on the
    # tree and failed inside the image on the same commit.)
    src_file = inspect.getsourcefile(_flow_module)
    assert src_file, "cannot locate the flow module's source — is it a compiled/zip import?"
    src = pathlib.Path(src_file)
    text = src.read_text()
    marker = "async def _sweep_one_authmatrix"
    assert marker in text, "the auth-matrix sweep was renamed — re-point this control"
    body = text.split(marker, 1)[1].split("\n        # ── DRIVER")[0]
    assert "never_probe_wrong_tier" in body, (
        "the auth matrix no longer reads never_probe_wrong_tier — every contract "
        "that opted out on safety grounds is being probed again"
    )
    assert "auth_matrix_not_probed" in body, (
        "the matrix excludes tools without recording which — an invisible "
        "coverage gap is the thing this change existed to remove"
    )
