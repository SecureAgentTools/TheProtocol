"""§CLOUDOPMCP2 2026-09-05 — `_wrapped_http_status` must see B6's envelope.

WHY. The MCP dispatcher renders ANY tool result carrying `error` as isError+text
and drops the rest, so B6 converted both wrapper lanes to return
`{status_code, upstream_error, body|detail, path}` instead -- deliberately WITHOUT
an `error` key, so the RFC7807 detail survives.

That removes every key the old scan looked at (`_text`, `error`, and for the
public lane `detail` too), so a refused tool would parse as "no wrapped error" and
the sweep would record a FALSE 200/healthy. That is the exact class this function
exists to prevent -- its docstring counts 176 such rows on 2026-05-28 --
reintroduced under a new key. It is worse than a false FAIL: the gate-marker
branch runs only for `not healthy`, so a genuinely REFUSED tool would never reach
it and would be counted as a pass. A green that cannot go red.

The old shapes must keep working: the tier is not rebuilt yet, so both lanes still
answer the old text today. This file pins BOTH.
"""
import json
import sys

sys.path.insert(0, "/app/src")
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (  # noqa: E402
    _wrapped_http_status,
)


def rpc(payload: dict) -> dict:
    """A tools/call envelope carrying `payload` as the tool's JSON result."""
    return {"result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def rpc_text(text: str) -> dict:
    """A tools/call envelope carrying non-JSON text (the isError+text shape)."""
    return {"result": {"content": [{"type": "text", "text": text}]}}


# ── B6 envelope, the NEW shape (V0223) ─────────────────────────────────────
def test_public_lane_envelope_yields_upstream_status():
    """tools_discovery._public_get on a non-2xx. No `error`, no `_text`, no
    `detail` -- `body` and `upstream_error` are all there is."""
    assert _wrapped_http_status(rpc({
        "status_code": 403,
        "upstream_error": "getForgeStatus returned HTTP 403",
        "body": "GODEL FORGE is not enabled on this registry (FORGE_ENABLED)",
        "path": "/api/v1/forge/status",
    })) == 403


def test_admin_lane_envelope_yields_upstream_status():
    assert _wrapped_http_status(rpc({
        "status_code": 404,
        "upstream_error": "/api/v1/admin/diagnostics/config/registry returned HTTP 404",
        "detail": "No such target",
        "path": "/api/v1/admin/diagnostics/config/registry",
    })) == 404


def test_envelope_status_code_wins_over_the_string():
    """The envelope STATES the status; trust it over parsing prose. The two
    disagree here on purpose -- the structured field must win."""
    assert _wrapped_http_status(rpc({
        "status_code": 503,
        "upstream_error": "something returned HTTP 500",
    })) == 503


# ── the OLD shapes must keep working (the tier is not rebuilt yet) ─────────
def test_legacy_text_error_still_detected():
    assert _wrapped_http_status(rpc_text("Error: getForgeStatus returned HTTP 403")) == 403


def test_legacy_error_key_still_detected():
    assert _wrapped_http_status(rpc({"error": "Error: HTTP 404: no such contract"})) == 404


# ── it must still stay silent on a genuine success ─────────────────────────
def test_healthy_payload_is_untouched():
    """A real 200 body that merely mentions numbers must not be read as a status."""
    assert _wrapped_http_status(rpc({"forge_enabled": True, "quorum": 404})) is None


def test_status_code_alone_is_not_the_envelope():
    """CONTROL for the guard: a payload with a `status_code` field but NO
    `upstream_error` is somebody's ordinary data, not B6's envelope. Reading it
    as an upstream refusal would fail healthy tools -- the mirror-image bug."""
    assert _wrapped_http_status(rpc({"status_code": 404, "note": "last probe result"})) is None


# ── the SECOND site: err_msg derivation in _evaluate_contract ──────────────
# Same envelope, same blind spot: the fallback scanned ("_text","error","detail",
# "message"), so on V0223 an expect_error_message_contains contract would find no
# message at all and fail with "no message" -- losing the diagnostic exactly where
# B6's conversion was meant to ADD one. `body` is searched before `upstream_error`
# because `body` carries the upstream RFC7807 detail (the gate phrase), while
# `upstream_error` is only the "X returned HTTP N" summary.
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (  # noqa: E402
    _evaluate_contract,
)
from agentvault_registry.api_tests.contracts.mcp_contracts import (  # noqa: E402
    McpContract, McpFixtureBag,
)

_TOOL = {"name": "theprotocol_getForgeStatus", "inputSchema": {"type": "object", "properties": {}}}
_BAG = McpFixtureBag(sentinel_did="did:theprotocol:test", sentinel_jwt="x")


def test_gate_phrase_in_envelope_body_satisfies_an_error_contract():
    """The whole point of B6: the gate phrase survives to the caller. A contract
    asserting it must now be satisfiable from the envelope alone."""
    ok, why = _evaluate_contract(
        _TOOL,
        McpContract(tier="1", arguments={}, expect_status="error_4xx",
                    expect_error_message_contains=["not enabled on this registry"]),
        # The RPC helper has already applied _wrapped_http_status by this point:
        # it flips ok->False and rewrites the code to the upstream 403 (see the
        # tests above, which pin exactly that). So the two fixes compose -- the
        # first makes the envelope produce (False, "403"), the second makes the
        # gate phrase inside it reachable.
        False, "403",
        rpc({"status_code": 403,
             "upstream_error": "getForgeStatus returned HTTP 403",
             "body": "GODEL FORGE is not enabled on this registry (FORGE_ENABLED)",
             "path": "/api/v1/forge/status"}),
        _BAG, has_explicit_contract=True,
    )
    assert ok, f"gate phrase not reachable from the envelope: {why}"
