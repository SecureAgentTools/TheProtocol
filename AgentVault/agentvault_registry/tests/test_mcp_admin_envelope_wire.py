"""§BATCH3 / B6 wire contract — an upstream non-2xx must reach the MCP client as the
documented envelope (status_code, response, ok), never as a bare "Error: …" string.

Found live on V0221 by agentvault2-07: tools_admin attached the upstream message under the
key `error`, and server_admin._admin_result_payload / _format_result treat ANY dict carrying
`error` as a pure tool failure (isError:true, text only, structuredContent dropped). The
RFC 7807 body an admin caller needs to read was thrown away one layer above the wrapper.

Two halves, both required:
  * the wrappers attach the message under `upstream_error` (source-pinned, RED on V0221)
  * the dispatcher keeps the envelope for such a dict (behaviour-pinned through the real
    functions) — and the control proves the SAME envelope under `error` IS flattened, so the
    test measures the key, not the formatter's mood.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

pytest.importorskip("agentvault_registry.mcp.server_admin")
from agentvault_registry.mcp import server_admin  # noqa: E402

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "mcp" / "tools_admin.py"

ENVELOPE = {
    "status_code": 404,
    "endpoint": "/api/v1/admin/agents/not-a-uuid",
    "method": "GET",
    "response": {"type": "https://docs.theprotocol.cloud/errors/not_found", "title": "Not Found",
                 "status": 404, "detail": "Agent not-a-uuid not found",
                 "error": {"detail": "Agent not-a-uuid not found", "type": "not_found"}},
    "ok": False,
    "upstream_error": "upstream HTTP 404: Agent not-a-uuid not found",
}


def test_wrappers_never_attach_the_upstream_message_under_error():
    src = SRC.read_text()
    assert 'out["error"] = err' not in src, "the V0221 shape: `error` collides with the dispatcher's failure rule"
    assert src.count('out["upstream_error"] = err') == 3, "adminRequest, adminQueryEventStore, adminGrafanaQuery"


def test_dispatcher_keeps_the_envelope_for_an_upstream_error():
    payload = server_admin._admin_result_payload(dict(ENVELOPE))
    assert payload["isError"] is False
    assert payload["structuredContent"]["status_code"] == 404
    assert payload["structuredContent"]["response"]["detail"] == "Agent not-a-uuid not found"
    text = payload["content"][0]["text"]
    body = json.loads(text)                      # the text half is the envelope too, not "Error: …"
    assert body["status_code"] == 404 and body["response"]["title"] == "Not Found"
    assert not text.startswith("Error:")


def test_control_the_same_envelope_under_error_is_flattened():
    """The class the fix closes: rename the key back and the RFC 7807 body is gone."""
    bad = dict(ENVELOPE); bad["error"] = bad.pop("upstream_error")
    payload = server_admin._admin_result_payload(bad)
    assert payload["isError"] is True
    assert "structuredContent" not in payload
    assert payload["content"][0]["text"] == "Error: upstream HTTP 404: Agent not-a-uuid not found"
    assert "Not Found" not in payload["content"][0]["text"]


def test_a_real_tool_failure_still_reads_as_an_error():
    """Timeouts / login failures keep the pre-existing contract: `error` key, isError true."""
    payload = server_admin._admin_result_payload({"error": "Request timed out after 30s", "endpoint": "/x"})
    assert payload["isError"] is True and payload["content"][0]["text"].startswith("Error: ")


def test_admin_get_helper_attaches_the_upstream_message_under_upstream_error():
    """§BATCH4 addendum: `_admin_get` (tools_admin.py, backs the reactor/diagnostics/… admin reads) returned
    {"error": "... returned HTTP 404", "detail": body} — the B6 shape the V0221 conversion missed (found by
    agentvault2-07 on a740cab7b297: getDiagnosticConfig's body, with its gate phrase, never reached the caller)."""
    import inspect, re
    from agentvault_registry.mcp import tools_admin
    src = inspect.getsource(tools_admin._admin_get)
    non200 = re.search(r"if r\.status_code != 200:(.*?)return r\.json\(\)", src, re.S)
    assert non200, "the non-200 branch of _admin_get not found"
    branch = non200.group(1)
    assert '"upstream_error"' in branch and '"status_code"' in branch and '"detail"' in branch
    assert '"error"' not in branch, "an upstream non-200 must never be attached under `error` (the dispatcher drops the body)"


def test_public_get_helper_and_the_public_formatter_keep_the_body():
    """B6, the public lane (§BATCH4 addendum, his "fix what's still open"): `tools_discovery._public_get`
    (68 public tools) attached the upstream body under `error`, and server.py's formatter dropped it."""
    import inspect, re
    from agentvault_registry.mcp import tools_discovery, server
    src = inspect.getsource(tools_discovery._public_get)
    non200 = re.search(r"if r\.status_code != 200:(.*?)return r\.json\(\)", src, re.S)
    assert non200 and '"upstream_error"' in non200.group(1) and '"status_code"' in non200.group(1)
    assert '"error"' not in non200.group(1)
    env = {"status_code": 403, "upstream_error": "getForgeStatus returned HTTP 403", "body": '{"detail":"flag off"}', "path": "/x"}
    payload = server._tool_result_payload(dict(env))
    assert payload["isError"] is False and payload["structuredContent"] == env, "the envelope must survive the public formatter"
    bad = dict(env); bad["error"] = bad.pop("upstream_error")
    flat = server._tool_result_payload(bad)
    assert flat["isError"] is True and "structuredContent" not in flat, "the control: under `error` the body vanishes"
