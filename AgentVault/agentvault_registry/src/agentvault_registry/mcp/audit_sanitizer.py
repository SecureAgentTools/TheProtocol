"""§pass68 (2026-05-23) — Sanitizer for MCP tool call audit logging.

Strategy: deny-list + length cap. Tools have ~23 different argument shapes
across the 25-tool surface; maintaining an allowlist per tool is high-toil
and any new tool ships unaudited until the allowlist updates. Deny-list is
forgiving and biased to "log something useful."

Sensitive field names are matched case-insensitively against the value side
of any dict, recursively. The set is small but comprehensive — covers all
known credential-bearing tool args (`agent_jwt`, `client_secret`, etc.) and
all credential-bearing response fields (`access_token`, `client_secret` on
agent-creation, etc.). When in doubt about a new field, add to SENSITIVE_KEYS.

Length caps prevent the audit row from ballooning past PG row-size limits
or making the audit table prohibitively large for an active agent. We cap
individual strings at 500 chars and the total `details` JSON at 4 KB.

NEVER raises — sanitizer errors must not block audit writes.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Union

logger = logging.getLogger(__name__)

# ── Field name matchers ──────────────────────────────────────────────────
#
# Substring match is used so that variants like `client_secret`, `client-secret`,
# `clientSecret`, `the_client_secret` all hit. The match is case-insensitive.
# A field is redacted if ANY of these substrings appears in its lowercased name.
_SENSITIVE_SUBSTRINGS = frozenset({
    "jwt",
    "secret",
    "password",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "authorization",
    "bearer",
    "session",
    "refresh",
    # §MCPSWEEP 2026-09-27: account-recovery and one-time credentials that none of the words above caught, so their
    # tools' arguments reached security_audit_logs as written (authRecoverAccount's recovery_key, authRecover2FA's
    # backup_code, activateOperator's activation_code, regenerateBackupCodes' current_code, a licence key)
    "recovery_key",
    "backup_code",
    "activation_code",
    "current_code",
    "totp",
    "license_key",
    "licence_key",
})

# Whitelist for keys that LOOK like they'd match SENSITIVE_SUBSTRINGS but are
# operationally fine to log (so they don't get redacted). Currently small —
# add entries only when a false-positive really matters.
_FORCE_KEEP = frozenset({
    "agent_jwt_required",   # boolean flag, not a token
})

# §MCPSWEEP 2026-09-27: a tool RESULT reaches this sanitizer as {"content": [{"type": "text", "text": "<JSON>"}]},
# so the key walk saw only content/type/text and every credential INSIDE the text was stored as written (truncated
# to 500 chars, which is where a freshly minted credential sits). Measured on sbx-alpha's security_audit_logs
# (213,599 mcp_tool success rows since 2026-09-03, counts only, no value read): 6,339 client_secrets (createAgent,
# cloneAgent, forkBundle), 5,992 agent JWTs (getAgentToken), 273 avreg_ API keys, 437 A2A payment tokens, 446
# webhook/pipeline secrets, 195 recovery/backup-code lists and 95 private-key PEMs (adminRequest). A string that
# holds a JSON object or array is now parsed and walked like any other value, and every string is screened for
# credential SHAPES, so a secret in text that is not JSON (an error message, a PEM) is caught too.
_JSON_PARSE_MAX = 262144  # a larger string is screened by shape only
_SECRET_SHAPES = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.DOTALL),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # a JWT
    re.compile(r"\b(?:avreg|apt|dpt|att|whsec|sk|rk)_[A-Za-z0-9_-]{16,}"),  # prefixed keys and tokens
    re.compile(r"otpauth://\S+"),
)
# a secret-named JSON key in text that could not be parsed (too large, or cut by a truncation): its value
_SECRET_KV = re.compile(
    r'("[^"]{0,60}?(?:secret|password|passwd|token|api_?key|private_?key|recovery_key|backup_code|jwt|licen[cs]e_key|'
    r'activation_code|current_code|totp|bearer|authorization)[^"]{0,60}?"\s*:\s*")(?!<redacted)([^"]{4,})("|$)',
    re.IGNORECASE)

# ── Caps ──────────────────────────────────────────────────────────────────
MAX_STR_LEN = 500
_SCREEN_WINDOW = 2 * MAX_STR_LEN  # what the shape screen reads of a string (only MAX_STR_LEN is kept)
MAX_DETAILS_BYTES = 4096
MAX_LIST_ITEMS = 5  # cap result lists to first N items + count


def _is_sensitive_key(key: str) -> bool:
    """Case-insensitive substring match against SENSITIVE_SUBSTRINGS."""
    if not isinstance(key, str):
        return False
    if key in _FORCE_KEEP:
        return False
    k_lower = key.lower()
    return any(s in k_lower for s in _SENSITIVE_SUBSTRINGS)


def _redact(value: Any) -> str:
    """Replace a sensitive value with a marker showing only its length class."""
    if value is None:
        return "<redacted:null>"
    s = str(value)
    return f"<redacted:{len(s)} chars>"


def _redact_shapes(value: str) -> str:
    """Redact every credential-shaped substring and every value of a secret-named JSON key left in text."""
    for rx in _SECRET_SHAPES:
        value = rx.sub(lambda m: _redact(m.group(0)), value)
    return _SECRET_KV.sub(lambda m: f"{m.group(1)}{_redact(m.group(2))}{m.group(3)}", value)


def _json_container(value: str) -> Any:
    """The parsed object or array a string holds, else None."""
    if len(value) > _JSON_PARSE_MAX:
        return None
    s = value.strip()
    if not s or s[0] not in "{[":
        return None
    try:
        parsed = json.loads(s)
    except ValueError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _truncate_str(value: str) -> str:
    """Cap a long string with a length-aware marker."""
    if len(value) <= MAX_STR_LEN:
        return value
    return value[:MAX_STR_LEN] + f"...<truncated:{len(value) - MAX_STR_LEN} more>"


def _sanitize_value(value: Any, key: str = "") -> Any:
    """Recursive sanitization. Public surface: sanitize_args / sanitize_result.

    The `key` argument carries the parent dict key for context — used to apply
    the substring deny-list. For list elements + scalars at the root level the
    key is "".
    """
    # Sensitive keys are redacted regardless of the value's type.
    if key and _is_sensitive_key(key):
        return _redact(value)

    # Dict: recurse per key/value
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            try:
                out[str(k)] = _sanitize_value(v, key=str(k))
            except Exception:  # noqa: BLE001 — sanitizer never raises
                out[str(k)] = "<sanitize-error>"
        return out

    # List/tuple: cap items and recurse
    if isinstance(value, (list, tuple)):
        items = list(value)
        capped = items[:MAX_LIST_ITEMS]
        out_list: List[Any] = []
        for item in capped:
            try:
                out_list.append(_sanitize_value(item, key=""))
            except Exception:  # noqa: BLE001
                out_list.append("<sanitize-error>")
        if len(items) > MAX_LIST_ITEMS:
            out_list.append(f"<truncated:{len(items) - MAX_LIST_ITEMS} more items>")
        return out_list

    # String: a JSON object or array inside is walked like any value; then credential shapes; then the length cap.
    # Only the first MAX_STR_LEN characters are ever stored, so the shape screen reads a window a little longer than
    # that (a secret crossing the cut is still caught) and never the whole text: over a 1 MB tool result the full
    # screen held the event loop ~200 ms per call (measured 2026-09-27 on V0468).
    if isinstance(value, str):
        parsed = _json_container(value)
        if parsed is not None:
            value = json.dumps(_sanitize_value(parsed, key=""), ensure_ascii=False, separators=(",", ":"),
                               default=str)
        full_len = len(value)
        screened = _redact_shapes(value[:_SCREEN_WINDOW])
        if full_len <= _SCREEN_WINDOW:
            return _truncate_str(screened)
        if len(screened) <= MAX_STR_LEN:  # the redaction shortened the window below the cap
            return screened + f"...<truncated:{full_len - _SCREEN_WINDOW} more>"
        return screened[:MAX_STR_LEN] + f"...<truncated:{full_len - MAX_STR_LEN} more>"

    # Numbers, bools, None: keep
    if isinstance(value, (int, float, bool)) or value is None:
        return value

    # Anything else (Pydantic model, custom object): stringify + cap
    try:
        return _truncate_str(repr(value))
    except Exception:  # noqa: BLE001
        return "<unserializable>"


def sanitize_args(args: Any) -> Any:
    """Sanitize the `arguments` payload of an MCP tool call."""
    try:
        return _sanitize_value(args, key="")
    except Exception:  # noqa: BLE001
        return {"_sanitize_failed": True}


def sanitize_result(result: Any) -> Any:
    """Sanitize a tool's result payload before logging.

    Same recursive logic but with `result_field=True` we are slightly more
    aggressive about list trimming (results can be huge: discoverAgents
    returns dozens of agent cards). Currently identical to sanitize_args;
    kept as a separate function so it can diverge later without rippling.
    """
    try:
        return _sanitize_value(result, key="")
    except Exception:  # noqa: BLE001
        return {"_sanitize_failed": True}


def redact_text_shapes(value: str) -> str:
    """Credential shapes and secret-named JSON values in any text (public: the read paths use it)."""
    try:
        return _redact_shapes(value) if isinstance(value, str) else value
    except Exception:  # noqa: BLE001
        return "<sanitize-failed>"


def sanitize_stored_details(details: Any) -> Any:
    """A stored MCP audit `details` (the dict, or the column's JSON text) as a read path may SERVE it.

    Rows written before 2026-09-27 hold the credentials a tool returned (see _SECRET_SHAPES), and three routes
    serve `details` as stored (/developers/me/mcp-audit-log, /admin/mcp-audit-log, /admin/audit-logs), so a
    developer's JWT or an admin could read back a client_secret or an API key that was meant to be shown once.
    Masking again on the way out closes that without rewriting a stored audit row. Same type out as in.
    """
    try:
        if isinstance(details, str):
            parsed = _json_container(details)
            if parsed is None:
                return _redact_shapes(details)
            return json.dumps(_sanitize_value(parsed, key=""), ensure_ascii=False, default=str)
        return _sanitize_value(details, key="")
    except Exception:  # noqa: BLE001 — never raises; a read must not fail on its sanitizer
        return "<sanitize-failed>" if isinstance(details, str) else {"_sanitize_failed": True}


def cap_details_json(details: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize details and check byte size. If over the cap, drop the
    largest contributor (result_summary, then args) and flag truncation.

    Returns a NEW dict — does not mutate input.
    """
    try:
        encoded = json.dumps(details, default=str, ensure_ascii=False)
        if len(encoded.encode("utf-8")) <= MAX_DETAILS_BYTES:
            return details

        # Too big. Make a shallow copy and start dropping fields.
        capped = dict(details)
        capped["_details_truncated"] = True

        # Drop result_summary first if present
        if "result_summary" in capped:
            capped.pop("result_summary", None)
            encoded = json.dumps(capped, default=str, ensure_ascii=False)
            if len(encoded.encode("utf-8")) <= MAX_DETAILS_BYTES:
                return capped

        # Drop args if still too big
        if "args" in capped:
            capped["args"] = "<dropped:size>"
            encoded = json.dumps(capped, default=str, ensure_ascii=False)
            if len(encoded.encode("utf-8")) <= MAX_DETAILS_BYTES:
                return capped

        # Last resort — keep only the bare metadata
        return {
            "tool": capped.get("tool"),
            "tier": capped.get("tier"),
            "outcome": capped.get("outcome"),
            "latency_ms": capped.get("latency_ms"),
            "_details_truncated": True,
            "_truncation_reason": "details exceeded cap even after dropping result+args",
        }
    except Exception as exc:  # noqa: BLE001
        # Never raise out of the sanitizer; return a minimal sentinel row.
        logger.debug("cap_details_json failed: %s", exc)
        return {"_details_truncated": True, "_sanitize_failed": True}
