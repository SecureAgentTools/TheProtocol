"""§MCPSWEEP 2026-09-27 — the tester's run record never keeps a credential a tool returned.

Every row of a sweep keeps an excerpt of the tool's result (the first five keys with their values), and the tester's
history keeps it for passing rows too, so createAgent's client_secret, createApiKey's plain_api_key or a token would
be kept as written. The excerpt now passes through the MCP audit sanitizer. Control: ordinary keys stay readable.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.contracts.mcp_lifecycles import result_excerpt  # noqa: E402

SECRET = "phase6-credential-value-that-must-not-be-kept"


def test_credential_fields_of_a_result_are_not_kept():
    out = result_excerpt({"agent_did": "did:theprotocol:x", "client_id": "agent-1", "client_secret": SECRET,
                          "access_token": SECRET, "plain_api_key": SECRET})
    assert SECRET not in str(out), out
    assert out["agent_did"] == "did:theprotocol:x" and out["client_id"] == "agent-1"


def test_control_an_ordinary_result_is_kept_as_it_was():
    r = {"status": "ok", "count": 3, "items": [1, 2], "detail": "Bundle not found"}
    assert result_excerpt(r) == r


def test_only_the_first_five_keys_and_only_dicts():
    assert list(result_excerpt({str(i): i for i in range(9)})) == ["0", "1", "2", "3", "4"]
    assert result_excerpt(["not", "a", "dict"]) == {} and result_excerpt(None) == {}
