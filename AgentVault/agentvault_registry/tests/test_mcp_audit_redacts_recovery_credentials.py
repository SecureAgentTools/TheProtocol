"""§MCPSWEEP 2026-09-27 — an MCP tool's recovery and one-time credentials never reach the audit log as written.

Every tools/call writes its arguments, sanitized, into security_audit_logs. The sanitizer redacts a key whose name
carries a credential word (jwt, secret, password, token, ...), and none of those words is in `recovery_key`
(authRecoverAccount), `backup_code` (authRecover2FA), `activation_code` (activateOperator), `current_code`
(regenerateBackupCodes) or a licence key, so each of those arguments was recorded as written. Pinned with a control:
names that only look alike (a country code, a status code) stay readable.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.mcp.audit_sanitizer import sanitize_args  # noqa: E402

SECRET = "phase6-secret-value-that-must-not-survive"


def test_recovery_and_one_time_credentials_are_redacted():
    args = {"email": "a@example.invalid", "recovery_key": SECRET, "backup_code": SECRET, "activation_code": SECRET,
            "current_code": SECRET, "totp_code": SECRET, "federation_license_key": SECRET, "licence_key": SECRET}
    out = sanitize_args(args)
    leaked = sorted(k for k, v in out.items() if v == SECRET)
    assert not leaked, f"written to the audit row as-is: {leaked}"
    assert out["email"] == "a@example.invalid"


def test_control_lookalike_names_stay_readable():
    out = sanitize_args({"country_code": "DE", "status_code": 404, "code_version": "v1"})
    assert out == {"country_code": "DE", "status_code": 404, "code_version": "v1"}
