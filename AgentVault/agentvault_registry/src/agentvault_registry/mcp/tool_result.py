"""One rule for when a tool's result is a failure, for both MCP servers (§MCPTEST30, 2026-10-01).

A tool wrapper reports a failure by returning {"error": "<why>"}. A route's SUCCESS body may itself carry an `error`
field that says there was none: `"error": null` (VerifyResponse, the tutorial proxy, the api-test runners, the health
probes). The dispatchers asked whether the KEY was present, so every such success reached the MCP client as the text
`Error: None` with isError true and its structuredContent dropped. verifyPayment's wrapper renamed the key to get past
it (tools_agent.verify_payment); the others never did, and the MCP tester read `Error: None` on executeTutorial in
every round. A failure is an error VALUE: a non-blank string, or any other truthy value.
"""
from __future__ import annotations

from typing import Any


def is_failure(result: Any) -> bool:
    """True when a tool result reports a failure: a dict whose `error` is set to something (not None, not blank)."""
    if not isinstance(result, dict) or "error" not in result:
        return False
    err = result["error"]
    if isinstance(err, str):
        return bool(err.strip())
    return bool(err)
