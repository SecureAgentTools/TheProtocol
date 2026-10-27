"""§ADMINMATRIX — which admin tools a wrong-tier probe may safely call.

The admin surface had no wrong-tier matrix at all: 321 tools, every one of them
gate-tested by nobody, and the five `never_probe_wrong_tier` declarations there
were a declaration with no consumer. Adding the matrix means CALLING each tool
with a wrong-tier credential — and a probe only reaches a tool BODY when that
tool's gate is broken, which is simultaneously the finding the matrix exists to
produce and the action it would perform.

Measured on the tier before any probe was written:

  * the admin surface answers 401 `-32001 requires admin auth` to an empty AND a
    garbage bearer, for a no-arg tool and a required-args tool alike, so the gate
    runs BEFORE argument binding;
  * a tool with required args is refused at dispatch anyway (`-32602 Invalid
    params`) — 166 of 321;
  * a VALID non-admin developer JWT is refused by getAdminDashboard,
    getAdminDevelopers, getEnforcementPolicy;
  * `invokeTool`, the gateway escape hatch, is REFUSED for a non-admin — had it
    not been, every other gate would be bypassable.

So the reachable set is the 155 tools with no required args, and within it the
ones whose name says they ACT are skipped. This pins that rule, including the
control that it does not simply answer one way for everything.
"""
import pytest

_admin_probe_is_safe = None
try:
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (
        _admin_probe_is_safe,
    )
except ImportError:  # pragma: no cover - only on an image predating §ADMINMATRIX
    pass

pytestmark = pytest.mark.skipif(
    _admin_probe_is_safe is None,
    reason="this image predates §ADMINMATRIX: the sweep has no _admin_probe_is_safe",
)


def _tool(name, required=None):
    return {"name": name, "inputSchema": {"required": list(required or [])}}


@pytest.mark.parametrize("name", [
    "theprotocol_rotateRegistrySigningKey",
    "theprotocol_startSimulation",
    "theprotocol_stopSimulation",
    "theprotocol_fundSimulationAgents",
    "theprotocol_issueFrameBSimulation",
    "theprotocol_crossRegTransferTest",
    "theprotocol_cloudOperatorSelfRestart",
    "theprotocol_adminCanaryFleetPause",
    "theprotocol_adminCanaryFleetResume",
    "theprotocol_resetApiTestSandbox",
    "theprotocol_triggerProjectionSnapshot",
])
def test_no_arg_acting_tools_are_never_probed(name):
    # These take NO required args, so a broken gate means the probe performs the
    # act. Not an acceptable price for the finding.
    assert _admin_probe_is_safe(_tool(name)) is False


@pytest.mark.parametrize("name", [
    "theprotocol_getAdminDashboard",
    "theprotocol_getAdminDevelopers",
    "theprotocol_getCollusionRings",
    "theprotocol_getFeeCollectorInfo",
])
def test_no_arg_reads_are_probed(name):
    assert _admin_probe_is_safe(_tool(name)) is True


@pytest.mark.parametrize("name", [
    "theprotocol_teardownCloudOperator",
    "theprotocol_provisionCloudOperator",
    "theprotocol_slashAgent",
])
def test_required_args_make_even_a_destructive_tool_probe_safe(name):
    # The body is unreachable: dispatch refuses `{}` with -32602 whatever the gate
    # does. Skipping these would cost coverage for no safety.
    assert _admin_probe_is_safe(_tool(name, ["target_id"])) is True


def test_the_control_it_does_not_answer_one_way_for_everything():
    # Without this, both tests above pass for a function that returns a constant.
    safe = _admin_probe_is_safe(_tool("theprotocol_getAdminDashboard"))
    unsafe = _admin_probe_is_safe(_tool("theprotocol_rotateRegistrySigningKey"))
    assert safe is True and unsafe is False


def test_an_unnamed_tool_is_treated_as_safe_not_skipped():
    # A tool the list returned without a name is caught earlier by the sweep (it
    # returns before calling this); pinning the shape so a future refactor that
    # reorders those checks fails here rather than silently skipping everything.
    assert _admin_probe_is_safe({"inputSchema": {}}) is True
