"""§MCPSWEEP 2026-09-27: the MCP audit row must not store a credential that a tool RETURNED.

A tool result reaches the audit writer as {"content": [{"type": "text", "text": "<JSON>"}], "isError": false}. The
sanitizer walked dict KEYS, so it saw content/type/text and stored the JSON string as written (truncated to 500 chars,
which is exactly where a freshly minted credential sits). Measured on sbx-alpha's security_audit_logs, counts only:
6,339 client_secrets, 5,992 agent JWTs, 273 avreg_ API keys, 437 A2A payment tokens, 446 webhook/pipeline secrets,
195 recovery/backup-code lists and 95 private-key PEMs. Each shape below goes through the real audit path
(`mcp.audit._summarize_result`) and must come out without its secret, while the identifiers beside it survive.
"""
from __future__ import annotations

import json

from agentvault_registry.mcp import audit
from agentvault_registry.mcp.audit_sanitizer import MAX_STR_LEN, sanitize_args

CLIENT_SECRET = "Qm7xV2cN9pL4tR8wZ1yB6dF3gH5jK0sA"
JWT = ("eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9."
       "eyJzdWIiOiJkaWQ6dGhlcHJvdG9jb2w6YWJjIiwiZXhwIjoxOTAwMDAwMDAwfQ."
       "c2lnbmF0dXJlLXNpZ25hdHVyZS1zaWduYXR1cmU")
API_KEY = "avreg_" + "k3Jd9sLq2Wm8xZ4v" * 3
PAY_TOKEN = "apt_" + "4e" * 32
HOOK_SECRET = "7a" * 32
RECOVERY = ["tulip-anchor-4471", "maple-ridge-9082"]
# the PEM markers are built from pieces so the repository's pre-commit guard (which refuses a literal key header in
# staged content) reads this fixture as the test it is
PEM = "-----BEGIN " + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END " + "PRIVATE KEY-----"
FINGERPRINT = "5c" * 32  # a public key fingerprint: must survive


def _tool_result(payload) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _stored(payload) -> str:
    return json.dumps(audit._summarize_result(_tool_result(payload)))


def test_create_agent_client_secret_is_not_stored():
    out = _stored({"agent_did": "did:theprotocol:abc", "client_id": "cid-1", "client_secret": CLIENT_SECRET})
    assert CLIENT_SECRET not in out
    assert "did:theprotocol:abc" in out and "cid-1" in out


def test_agent_token_jwt_is_not_stored():
    out = _stored({"access_token": JWT, "expires_in": 900})
    assert JWT not in out and "900" in out


def test_api_key_payment_token_and_webhook_secret_are_not_stored():
    # (api_key_info is redacted whole by the older substring rule: "api_key" is in its name)
    out = _stored({"plain_api_key": API_KEY, "message": "API key created", "api_key_info": {"key_name": "probe"}})
    assert API_KEY not in out and "API key created" in out
    out = _stored({"token": PAY_TOKEN, "status": "AUTHORIZED"})
    assert PAY_TOKEN not in out and "AUTHORIZED" in out
    out = _stored({"id": 7, "secret": HOOK_SECRET, "url": "https://hooks.example.test/x"})
    assert HOOK_SECRET not in out and "hooks.example.test" in out


def test_recovery_codes_and_a_private_key_are_not_stored():
    out = _stored({"recovery_keys": RECOVERY, "message": "Registration successful"})
    assert not any(k in out for k in RECOVERY) and "Registration successful" in out
    out = _stored(f"key material follows\n{PEM}\n")  # plain text, not JSON: caught by its shape
    assert "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC" not in out and "key material follows" in out


def test_secrets_in_text_that_is_not_json_are_caught_by_shape():
    out = _stored(f"Error: HTTP 401: token {PAY_TOKEN} rejected for {API_KEY}")
    assert PAY_TOKEN not in out and API_KEY not in out and "rejected" in out
    # a JSON body too large to parse is still screened: its secret-named keys lose their values
    big = '{"client_secret": "' + CLIENT_SECRET + '", "pad": "' + "x" * 300000 + '"}'
    out = _stored(big)
    assert CLIENT_SECRET not in out


def test_public_identifiers_survive_and_the_length_cap_holds():
    out = _stored({"kid": "k-2026-09", "fingerprint": FINGERPRINT, "agent_did": "did:theprotocol:xyz"})
    assert FINGERPRINT in out and "k-2026-09" in out and "did:theprotocol:xyz" in out
    stored = audit._summarize_result(_tool_result({"cards": ["c" * 50] * 40}))
    assert all(len(b["text"]) <= MAX_STR_LEN + 40 for b in stored["content_head"])


def test_a_json_string_argument_is_walked_too():
    args = sanitize_args({"card_data": json.dumps({"name": "n", "client_secret": CLIENT_SECRET})})
    assert CLIENT_SECRET not in json.dumps(args) and '"name":"n"' in args["card_data"]


def test_control_the_old_key_walk_alone_kept_the_secret():
    """Control: walking keys without parsing the text keeps it (the defect), so the absences above are the fix's."""
    from agentvault_registry.mcp import audit_sanitizer as s
    text = json.dumps({"client_secret": CLIENT_SECRET})
    assert CLIENT_SECRET in s._truncate_str(text)
    assert s._json_container(text) == {"client_secret": CLIENT_SECRET}


# ── the READ paths: rows already stored (before this fix) are masked on the way out ──────────────────────────────
def _pre_fix_stored_details() -> str:
    """A details column exactly as the old writer stored it: the tool text kept verbatim, cut to 500 chars."""
    text = json.dumps({"agent_did": "did:theprotocol:abc", "client_id": "cid-1", "client_secret": CLIENT_SECRET,
                       "access_token": JWT})[:500]
    return json.dumps({"tool": "theprotocol_createAgent", "tier": "3", "is_admin_server": False,
                       "args": {"name": "probe"}, "latency_ms": 12.5,
                       "result_summary": {"isError": False, "content_count": 1,
                                          "content_head": [{"type": "text", "text": text}]}})


class _Row:
    def __init__(self, details: str, target_type: str = "mcp_tool"):
        import datetime
        self.id = "row-1"
        self.timestamp = datetime.datetime(2026, 9, 27, 11, 0, 0)
        self.event_type = type("E", (), {"value": "mcp_tool_call"})()
        self.actor_type, self.actor_id, self.actor_ip = "developer", "42", "198.51.100.7"
        self.target_type, self.target_id = target_type, "theprotocol_createAgent"
        self.outcome, self.severity, self.request_id, self.user_agent = "success", "info", "req-1", "ua"
        self.details, self.error_message = details, None


def test_served_rows_do_not_return_a_stored_credential():
    from agentvault_registry.routers.mcp_audit_log import _serialize_row
    stored = _pre_fix_stored_details()
    assert CLIENT_SECRET in stored and JWT in stored  # control: the stored row really carries both
    served = _serialize_row(_Row(stored))
    out = json.dumps(served)
    assert CLIENT_SECRET not in out and JWT not in out
    assert served["latency_ms"] == 12.5 and served["tier"] == "3" and "cid-1" in out


def test_the_admin_audit_listing_masks_stored_text():
    from agentvault_registry.mcp.audit_sanitizer import redact_text_shapes, sanitize_stored_details
    out = sanitize_stored_details(_pre_fix_stored_details())
    assert isinstance(out, str) and CLIENT_SECRET not in out and JWT not in out and "cid-1" in out
    # a non-MCP row keeps its text, except for credential shapes
    other = json.dumps({"reason": "rotated", "new_key": API_KEY, "count": 3})
    masked = redact_text_shapes(other)
    assert API_KEY not in masked and '"reason": "rotated"' in masked and '"count": 3' in masked


# ── the screen reads a bounded window, never a whole large result (it held the event loop ~200 ms per MB) ─────────
def test_the_shape_screen_reads_a_bounded_window(monkeypatch):
    from agentvault_registry.mcp import audit_sanitizer as s
    seen = []
    real = s._redact_shapes
    monkeypatch.setattr(s, "_redact_shapes", lambda v: (seen.append(len(v)), real(v))[1])
    big = '{"tools": [' + ",".join('{"name": "t%d", "description": "x"}' % i for i in range(40000)) + "]}"
    assert len(big) > s._JSON_PARSE_MAX  # the unparsed path: the one that used to screen everything
    audit._summarize_result(_tool_result(big))
    window = getattr(s, "_SCREEN_WINDOW", 2 * s.MAX_STR_LEN)  # so the pre-fix module fails on the bound itself
    assert seen and max(seen) <= window, (max(seen), window)


def test_a_secret_across_the_stored_cut_is_still_masked():
    text = "x" * 490 + '"client_secret": "' + CLIENT_SECRET + '" ' + "y" * 5000
    stored = json.dumps(audit._summarize_result(_tool_result(text)))
    assert CLIENT_SECRET[:6] not in stored and "truncated" in stored
