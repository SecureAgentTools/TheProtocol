"""§MCPSWEEP 2026-09-27 (run b487126bc7274966): the probes that replaced eight dispatcher refusals must stay REFUSALS.

Each was chosen after reading its route for the ORDER of its refusal and its side effects (sessionlogs2026/FINDINGS_2026-
09-27_MCPTESTER_A4.md § 2). These pins keep a later edit from turning a probe into an action, the refusal-becomes-an-action
hazard (§FANCLAIM): a positive bridge amount LOCKS funds at the TEG before the dial fails; an agent_did in a balance-sync
notification rewrites that agent's balance cache; a real defendant files a dispute; a hex nonce reaches a handler that
dials the bundle URL. Static, read from source (no import of the app).
"""
import ast
import pathlib
import re
from decimal import Decimal

import pytest

SRC = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "api_tests" / "contracts"
       / "mcp_lifecycles.py")
# the TEG's own list (agentvault_teg_layer_mvp .../api/v1/endpoints_governance.py); the TEG tree is not in this image
TEG_POLICY_TYPES = {"attestation", "governance", "compliance", "economic"}
HEX_NONCE = re.compile(r"^[a-fA-F0-9]{16,64}$")   # schemas.py `_HEX_NONCE_RE`, the frame-invitation schema
REFUSALS = ["bridgeTransfer", "crossTegBalanceSync", "applyReputationSignal", "submitDispute", "createTegPolicy",
            "createFrameInvitation", "federationSlashConfirmation"]


def _callee(n):
    return n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else "")


def _steps(tool):
    """Every _exec_step or refusal_step call for `tool`: (tier, {argument: ast node}, {keyword: source}).
    §MCPTEST30 (V0636): a probe moved to earned_fixtures.refusal_step files its row under `refusal: <tool> <what>`
    and is always held to a refusal (error_4xx), so it reads here as an error_4xx step."""
    out = []
    for n in ast.walk(ast.parse(SRC.read_text())):
        if isinstance(n, ast.Call) and _callee(n) in ("_exec_step", "refusal_step") and len(n.args) >= 5 \
                and isinstance(n.args[2], ast.Constant) and n.args[2].value == f"theprotocol_{tool}" \
                and isinstance(n.args[4], ast.Dict):
            tier = n.args[3].value if isinstance(n.args[3], ast.Constant) else None
            args = {k.value: v for k, v in zip(n.args[4].keys, n.args[4].values) if isinstance(k, ast.Constant)}
            kws = {k.arg: ast.unparse(k.value) for k in n.keywords}
            if _callee(n) == "refusal_step":
                kws.setdefault("expect_status", "'error_4xx'")
            out.append((tier, args, kws))
    assert out, f"no _exec_step or refusal_step for {tool}: the reader is not seeing the lifecycle"
    return out


def _lit(node):
    return ast.literal_eval(node)


@pytest.mark.parametrize("tool", REFUSALS)
def test_each_refusal_probe_expects_the_refusal(tool):
    """error_4xx, never "any": an invalid probe the route ACCEPTS must fail loudly, not read healthy."""
    for _tier, _args, kws in _steps(tool):
        assert kws.get("expect_status") == "'error_4xx'", (tool, kws.get("expect_status"))


def test_the_bridge_probe_moves_nothing():
    for _t, args, _k in _steps("bridgeTransfer"):
        assert Decimal(_lit(args["amount"])) <= 0   # gt=0 refuses it before the handler; a positive one LOCKS funds
        assert "target_frame" not in args


def test_the_balance_sync_probe_names_no_agent():
    for _t, args, _k in _steps("crossTegBalanceSync"):
        note = _lit(args["notification"])
        assert "agent_did" not in note and "sender_did" not in note


def test_the_dispute_probe_accuses_no_one_who_exists():
    for _t, args, _k in _steps("submitDispute"):
        assert _lit(args["defendant_did"]).startswith("did:theprotocol:phase5-")   # a literal, never a live agent


def test_the_policy_probe_names_a_type_the_teg_refuses():
    for tier, args, _k in _steps("createTegPolicy"):
        assert tier == "3" and _lit(args["policy_type"]) not in TEG_POLICY_TYPES


def test_the_invitation_probe_cannot_reach_the_handler_or_a_real_host():
    for _t, args, _k in _steps("createFrameInvitation"):
        assert not HEX_NONCE.match(_lit(args["initiator_nonce"]))
        for key in ("bundle_endpoint_url", "federation_endpoint_url"):
            host = _lit(args[key]).split("://", 1)[1].split("/", 1)[0].split(":")[0]
            assert host.endswith(".invalid"), (key, host)


def test_the_slash_probe_is_tier3_without_an_agent_token():
    for tier, args, _k in _steps("federationSlashConfirmation"):
        assert tier == "3" and "agent_jwt" not in args


def test_the_signal_probe_names_a_transaction_that_does_not_exist():
    for _t, args, _k in _steps("applyReputationSignal"):
        assert _lit(args["transaction_id"]).startswith("phase5-") and _lit(args["signal_value"]) in (-1, 1)


def test_the_eigentrust_seed_transfers_do_not_overwrite_the_measured_transfer():
    """That lifecycle runs LAST and outcomes are keyed by tool: recorded seeds overwrote the verified transfer's row."""
    seeds = [args for _t, args, k in _steps("transferUnits") if k.get("record_as_separate") == "False"]
    assert seeds, "the EigenTrust seed transfers must run with record_as_separate=False"
    for args in seeds:
        assert "recipient_did" in args and "receiver_agent_id" not in args
