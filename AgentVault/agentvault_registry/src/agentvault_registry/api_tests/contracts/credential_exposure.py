"""§MCPTEST30 (2026-10-01) — the credential exposure census: which tools hand out a credential, and which should not.

Every MCP response the sweep receives (contract rows, lifecycle steps, refusal probes, the B frame, the admin bridge, the
cloud-op operators) passes through the flow's JSON-RPC helpers, which call `record(tool, parsed)`. The scanner looks at
VALUES, not key names: a key-name rule cannot tell `tokens_issued` (a count) from `access_token` (a bearer), which is why
the run record's own excerpt redaction marks both alike. It finds

  * credential SHAPES, as the product's MCP audit sanitizer defines them (`mcp/audit_sanitizer._SECRET_SHAPES`, imported,
    never copied: a second copy rots on its own): private-key PEMs, JWTs, prefixed keys and tokens (avreg_, apt_, dpt_,
    att_, whsec_, sk_, rk_), otpauth:// URIs. A JWT is classed by its own claims: one that carries `vc`/`vp` is a signed
    public document; one with `tv`, `type`, `purpose`, `scope`, `act` or `exp`+`sub` is a bearer;
  * credential FIELDS: an exact credential key (client_secret, plain_api_key, refresh_token, recovery_keys, ...) whose
    value is a real string, not a mask (`avreg_ab12****`), a redaction marker, a number or a flag;
  * STORED HASHES of secrets (hashed_client_secret, license_key_hash, ...).

and keeps only (kind, path): never a value, not even a prefix of one.

§MCPTEST30 (V0525): the same scan finds a DATABASE DRIVER'S OWN WORDS (kind `db_words`): the text an exception from
SQLAlchemy, asyncpg or psycopg2 carries, which holds the statement, a parameter's value, a table or a column name. A
route that catches an exception and puts its text in the answer hands all of that to its caller; measured on sbx-alpha
(V0521), getProposalDetail answered 500 "Failed to retrieve proposal: (sqlalchemy.dialects.postgresql.asyncpg.Error)
invalid input for query argument $1: 2147483648 (value out of int32 range)". On a tool anyone but an admin can call it is
UNEXPECTED; on an admin-only tool (log and event readers show stored errors by design) it is INFORMATIONAL.

Each finding is then classed: an ISSUER returning what it issues (createAgent's client_secret, getAgentToken's bearer),
an owner's own secret on read (a webhook's signing secret), a PROXY (adminRequest, invokeTool: what they return belongs
to what they proxied), INFORMATIONAL (a signed public document, a stored hash) or UNEXPECTED. An unexpected finding is a
BUG-FIND on that tool's row and turns the census row red; the rest is reported on the census row, so a person can see
every tool that hands out a credential and judge the list.
"""
from __future__ import annotations

import base64
import json
import re
from contextvars import ContextVar, Token
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

try:  # one definition of what a credential looks like: the product's own sanitizer
    from agentvault_registry.mcp.audit_sanitizer import _SECRET_SHAPES as _PRODUCT_SHAPES
except Exception:  # noqa: BLE001 — the census then says it could not measure, it never guesses
    _PRODUCT_SHAPES = None

CENSUS_ROW = "mcp_tester: credential_exposure_census"

# Exact credential keys (lowercased) whose string value IS the credential. Deliberately narrow: `token`, `key`, `code`
# alone name ids, counts and links far more often than secrets, and the shape scan already catches every shaped token.
CREDENTIAL_FIELDS = frozenset({
    "client_secret", "new_client_secret", "plain_api_key", "api_key", "secret", "webhook_secret", "signing_secret",
    "refresh_token", "access_token", "id_token", "developer_token", "agent_jwt", "bootstrap_token", "pull_token",
    "recovery_keys", "recovery_codes", "backup_codes", "secret_raw", "totp_secret", "private_key", "signing_key",
    "license_key", "licence_key", "activation_code", "password", "temporary_password", "new_password",
    # 2026-10-01, round 4: the API tester's flow values held these beside the refresh token the census caught; only the
    # refresh token has a shape, so a regression of the route's masking would have kept the other three out of sight
    "recovery_key", "recovery_token", "invitation_token", "accept_test_token", "reset_token", "verification_token",
    "email_verification_token",
})
_HASH_WORDS = ("secret", "password", "key", "token")
_MASK_MARKS = ("*", "…", "...", "<redacted")
_MIN_SECRET_LEN = 8
_MAX_DEPTH = 14
_MAX_LIST = 200
_JSON_MAX = 262144

# What each issuing tool may hand out. A tool listed here returning a kind outside its set is still UNEXPECTED.
_SESSION = frozenset({"jwt:bearer", "field:access_token", "field:refresh_token"})
_AGENT_CREDS = frozenset({"field:client_secret", "field:new_client_secret"})
_PULL = frozenset({"token:dpt", "field:pull_token"})
ISSUERS: Dict[str, frozenset] = {
    # sessions
    "theprotocol_getAgentToken": _SESSION,
    "theprotocol_adminGetDeveloperToken": _SESSION,
    "theprotocol_authRefresh": _SESSION,
    "theprotocol_authValidate2FA": _SESSION,
    "theprotocol_authRecover2FA": _SESSION,
    "theprotocol_authRecoverAccount": _SESSION | {"field:recovery_keys"},
    "theprotocol_authSetNewPassword": _SESSION,
    "theprotocol_authResetPassword": _SESSION,
    "theprotocol_oauthTokenExchange": _SESSION,
    "theprotocol_getAdminTestTokens": _SESSION | {"field:developer_token"},
    # account recovery material, shown once
    "theprotocol_authRegister": frozenset({"field:recovery_keys"}),
    "theprotocol_regenerateBackupCodes": frozenset({"field:backup_codes"}),
    "theprotocol_setup2FA": frozenset({"otpauth_uri", "field:secret", "field:secret_raw", "field:totp_secret",
                                       "field:backup_codes"}),   # the backup codes are issued with the secret, once
    # agent credentials, shown once
    "theprotocol_createAgent": _AGENT_CREDS,
    "theprotocol_cloneAgent": _AGENT_CREDS,
    "theprotocol_forkBundle": _AGENT_CREDS,
    "theprotocol_importAgent": _AGENT_CREDS,
    "theprotocol_restoreBundle": _AGENT_CREDS,
    "theprotocol_restoreFromUpload": _AGENT_CREDS,
    "theprotocol_resetAgentCredentialsOnboard": _AGENT_CREDS,
    "theprotocol_rotateAgentCredentials": _AGENT_CREDS,
    # the API tester's own sandbox fixture logins (an admin tool on the tester frame, by design)
    "theprotocol_getApiTestSandboxCredentials": _AGENT_CREDS | {"field:password"} | _SESSION,
    # API keys, shown once
    "theprotocol_createApiKey": frozenset({"token:avreg", "field:plain_api_key", "field:api_key"}),
    "theprotocol_createDeveloperApikeyMe": frozenset({"token:avreg", "field:plain_api_key", "field:api_key"}),
    # signing secrets at creation
    "theprotocol_createWebhook": frozenset({"token:whsec", "field:secret", "field:webhook_secret", "field:signing_secret"}),
    "theprotocol_createPipeline": frozenset({"token:whsec", "field:secret", "field:webhook_secret", "field:signing_secret"}),
    # the A2A payment token, shown once
    "theprotocol_authorizePayment": frozenset({"token:apt"}),
    # IRONHAND external enrolment (§EXTMTLS): the agent's own short-lived SVID and its key, delivered to that agent
    "theprotocol_enableMtls": frozenset({"pem_private_key"}),
    # signing keys, shown once (§MCPTEST30 V0637): an administrator's rotation of an agent's EdDSA key mints the new
    # pair and answers its private key once (agent_signing_keys_admin.rotate_signing_key), as rotateAgentCredentials
    # answers new credentials; first reached by V0636's earn_agent_admin, read by the census as a stranger's key
    "theprotocol_rotateAgentSigningKey": frozenset({"pem_private_key"}),
    # operator and federation credentials
    "theprotocol_rotateOperatorPullToken": _PULL,
    "theprotocol_backfillPullTokens": _PULL,
    "theprotocol_adminDownloadOperatorBundle": _PULL | {"field:license_key", "field:licence_key"},
    "theprotocol_getOperatorMyBundle": _PULL | {"field:license_key", "field:licence_key"},
    "theprotocol_generateFederationLicense": frozenset({"field:license_key", "field:licence_key"}),
    "theprotocol_rotateFederationLicenseSelf": frozenset({"field:license_key", "field:licence_key"}),
    "theprotocol_provisionCloudOperator": _PULL | _AGENT_CREDS | {"field:password", "field:license_key"},
    "theprotocol_selfProvisionOperator": _PULL | _AGENT_CREDS | {"field:password", "field:license_key"},
    "theprotocol_activateOperator": _PULL | _AGENT_CREDS | {"field:password", "field:license_key"},
}
# The caller's OWN secret, readable by design (a webhook's signing secret on its owner's read). Reported, not red; the
# owner-scoping sweep is what proves nobody else can read it.
OWNER_READ: Dict[str, frozenset] = {
    t: frozenset({"token:whsec", "field:secret", "field:webhook_secret", "field:signing_secret"})
    for t in ("theprotocol_getWebhook", "theprotocol_getMyWebhooks", "theprotocol_updateWebhook",
              "theprotocol_listDeveloperWebhooks", "theprotocol_listDeveloperWebhooksAlt",
              "theprotocol_updatePipeline", "theprotocol_getMyCicdPipelines")
}
# Generic proxies: what they return is whatever they were pointed at.
PROXIES = frozenset({"theprotocol_adminRequest", "theprotocol_invokeTool"})

# §MCPTEST30 (V0525): the words a database driver writes into an exception's text (one pattern for the tester; the
# product's own guard is errors._DB_ERROR_WORDS, and the two are pinned equal by tests/test_mcp_db_words_census.py).
DB_WORDS = re.compile(
    r"\((?:sqlalchemy|psycopg2?|asyncpg)\.[\w.]+\)"
    r"|\[SQL: "
    r"|\b(?:asyncpg\.exceptions|psycopg2?\.errors|sqlalchemy\.exc)\.")
DB_WORDS_KIND = "db_words"
# §MCPTEST30 (V0525): the words a raw Python exception carries (a traceback, a source path, an attribute or key error, an
# errno, an httpx transport class). 30 route catch-alls put `str(e)` in a 500's detail; V0525 withholds only a database
# driver's words. Kind `exception_words`, INFORMATIONAL for now: a round measures the population (which tools, how many)
# before it is allowed to turn a row red.
EXCEPTION_WORDS = re.compile(
    r"Traceback \(most recent call last\)"
    r"|File \"/(?:app|usr|opt|srv)/[^\"]+\.py\", line \d+"
    r"|'NoneType' object (?:has no attribute|is not subscriptable|is not iterable)"
    r"|object has no attribute '\w+'"
    r"|\[Errno -?\d+\]"
    r"|\b(?:ConnectError|ConnectTimeout|ReadTimeout|RemoteProtocolError|ClientConnectorError)\b"
    r"|\b(?:TypeError|KeyError|AttributeError|IndexError|UnboundLocalError|NameError|ZeroDivisionError): ")
EXCEPTION_WORDS_KIND = "exception_words"
_ADMIN_ONLY: Optional[Set[str]] = None


def admin_only_tools() -> Set[str]:
    """The tools only the admin bridge serves (admins may read stored errors: log and event readers)."""
    global _ADMIN_ONLY
    if _ADMIN_ONLY is None:
        try:
            from agentvault_registry.mcp import server as _S
            from agentvault_registry.mcp import server_admin as _SA
            public = {t.get("name") for t in _S.ALL_TOOL_SCHEMAS}
            _ADMIN_ONLY = {t.get("name") for t in _SA.ADMIN_TOOL_SCHEMAS} - public
        except Exception:  # noqa: BLE001 — unknown: every db_words finding then reads unexpected, never hidden
            _ADMIN_ONLY = set()
    return _ADMIN_ONLY


def available() -> bool:
    return bool(_PRODUCT_SHAPES)


def _b64json(seg: str) -> Optional[Dict[str, Any]]:
    try:
        raw = base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except Exception:  # noqa: BLE001
        return None


_BEARER_TYPES = frozenset({"refresh", "access", "agent", "developer", "bearer"})


def jwt_class(text: str) -> str:
    """'bearer' or 'document', from the token's own header and claims (decoded, never verified, never kept).

    A typed signed object (`typ` like `tp-licence+jws`, `vc+jwt`) is a document: calibration 2026-10-01 found the
    federation licence certificate on every registry card read as a bearer because its payload says `type: frame`."""
    parts = text.split(".")
    header = _b64json(parts[0]) if parts else None
    typ = str((header or {}).get("typ") or "").lower()
    if typ and typ not in ("jwt", "at+jwt") and (typ.endswith("+jws") or typ.endswith("+jwt")):
        return "document"
    claims = _b64json(parts[1]) if len(parts) >= 2 else None
    if not claims:
        return "bearer"           # unreadable: treat as the dangerous kind
    if "vc" in claims or "vp" in claims:
        return "document"
    if any(k in claims for k in ("tv", "purpose", "scope", "scp", "act", "access", "token_use")):
        return "bearer"
    if str(claims.get("type") or "").lower() in _BEARER_TYPES:
        return "bearer"
    if "exp" in claims and "sub" in claims:
        return "bearer"
    return "document"


def _shape_kind(match: str) -> str:
    if match.startswith("-----BEGIN"):
        return "pem_private_key"
    if match.startswith("eyJ"):
        return f"jwt:{jwt_class(match)}"
    if match.startswith("otpauth://"):
        return "otpauth_uri"
    return "token:" + match.split("_", 1)[0].lower()


def _masked(s: str) -> bool:
    return any(m in s for m in _MASK_MARKS)


def _strings_of(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value[:_MAX_LIST] if isinstance(v, str)]
    return []


def _field_kind(key: str, value: Any) -> Optional[str]:
    k = key.lower()
    vals = [v for v in _strings_of(value) if len(v.strip()) >= _MIN_SECRET_LEN and not _masked(v)]
    if not vals:
        return None
    if k in CREDENTIAL_FIELDS:
        return f"field:{k}"
    if "hash" in k and any(w in k for w in _HASH_WORDS) and any(len(v) >= 16 for v in vals):
        return f"stored_hash:{k}"
    return None


def _json_in(s: str) -> Any:
    t = s.strip()
    if not t or t[0] not in "{[" or len(t) > _JSON_MAX:
        return None
    try:
        out = json.loads(t)
    except ValueError:
        return None
    return out if isinstance(out, (dict, list)) else None


def scan(obj: Any, path: str = "", depth: int = 0) -> Iterator[Tuple[str, str]]:
    """Yield (kind, path) for every credential in a response. Never yields a value."""
    if depth > _MAX_DEPTH or not _PRODUCT_SHAPES:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            kind = _field_kind(str(k), v)
            if kind:
                yield kind, p
            yield from scan(v, p, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:_MAX_LIST]):
            yield from scan(v, f"{path}[{i}]", depth + 1)
    elif isinstance(obj, str):
        inner = _json_in(obj)
        if inner is not None:
            yield from scan(inner, path, depth + 1)
            return
        for rx in _PRODUCT_SHAPES:
            for m in rx.finditer(obj):
                yield _shape_kind(m.group(0)), path or "<text>"
        if DB_WORDS.search(obj):
            yield DB_WORDS_KIND, path or "<text>"
        elif EXCEPTION_WORDS.search(obj):
            yield EXCEPTION_WORDS_KIND, path or "<text>"


_ENVELOPE = re.compile(r"^(?:result\.content\[\d+\]\.text|result\.structuredContent|result)\.?")


def normalize(path: str) -> str:
    """A path relative to the tool's own result, list positions folded: `items[3].secret` -> `items[*].secret`."""
    p = _ENVELOPE.sub("", path or "")
    return re.sub(r"\[\d+\]", "[*]", p) or "<result>"


def classify(tool: str, kind: str) -> str:
    if kind == EXCEPTION_WORDS_KIND:
        return "informational"     # measured first (see EXCEPTION_WORDS); a later image may make it unexpected
    if kind == DB_WORDS_KIND:
        return "informational" if tool in admin_only_tools() else "unexpected"
    if kind == "jwt:document" or kind.startswith("stored_hash:"):
        return "informational"
    if tool in PROXIES:
        return "proxied"
    if kind in ISSUERS.get(tool, ()):
        return "issuer"
    if kind in OWNER_READ.get(tool, ()):
        return "owner_read"
    return "unexpected"


# ── the per-run collector (a ContextVar, so concurrent runs in one process never mix) ──────────────────────────
_COLLECT: ContextVar[Optional[Dict[str, Any]]] = ContextVar("mcp_credential_census", default=None)


def begin() -> Token:
    return _COLLECT.set({"tools": {}, "responses": 0, "scan_errors": 0})


def end(token: Token) -> Dict[str, Any]:
    box = _COLLECT.get() or {"tools": {}, "responses": 0, "scan_errors": 0}
    try:
        _COLLECT.reset(token)
    except (ValueError, RuntimeError):
        _COLLECT.set(None)
    return box


def record(tool: str, parsed: Any) -> None:
    """Scan one tool response into the running census. A no-op outside a census; never raises."""
    box = _COLLECT.get()
    if box is None:
        return
    try:
        box["responses"] += 1
        found = {(kind, normalize(path)) for kind, path in scan(parsed)}
        if found:
            box["tools"].setdefault(str(tool), set()).update(found)
    except Exception:  # noqa: BLE001 — the census never breaks the sweep; it counts what it could not read
        box["scan_errors"] += 1


def summarize(box: Dict[str, Any]) -> Dict[str, Any]:
    classes: Dict[str, Dict[str, List[str]]] = {c: {} for c in
                                                ("unexpected", "issuer", "owner_read", "proxied", "informational")}
    for tool in sorted(box.get("tools") or {}):
        for kind, path in sorted(box["tools"][tool]):
            classes[classify(tool, kind)].setdefault(tool, []).append(f"{kind} at {path}")
    return {"measured": available() and (box.get("responses") or 0) > 0,
            "responses_scanned": box.get("responses") or 0, "scan_errors": box.get("scan_errors") or 0,
            **classes}


def verdict_text(summary: Dict[str, Any], limit: int = 6) -> Optional[str]:
    """The BUG-FIND sentence for the census row, or None when nothing unexpected was handed out."""
    bad = summary.get("unexpected") or {}
    if not bad:
        return None
    creds = {t: [x for x in v if not x.startswith(DB_WORDS_KIND)] for t, v in bad.items()}
    creds = {t: v for t, v in creds.items() if v}
    words = {t: [x for x in v if x.startswith(DB_WORDS_KIND)] for t, v in bad.items()}
    words = {t: v for t, v in words.items() if v}
    said = []
    if creds:
        named = "; ".join(f"{t.replace('theprotocol_', '')} ({', '.join(v[:3])})" for t, v in list(creds.items())[:limit])
        more = f"; and {len(creds) - limit} more" if len(creds) > limit else ""
        said.append(f"BUG-FIND: credential exposure: {len(creds)} tool(s) returned a credential they do not issue: "
                    f"{named}{more}. Values are never recorded; the kind and the path are.")
    if words:
        named = ", ".join(t.replace("theprotocol_", "") for t in list(words)[:limit])
        more = f" and {len(words) - limit} more" if len(words) > limit else ""
        said.append(f"BUG-FIND: database words: {len(words)} tool(s) answered with a database driver's own error text "
                    f"(a statement, a value, a table or column name): {named}{more}. The text is never recorded.")
    return " ".join(said)


def row_reason(tool: str, findings: List[str]) -> str:
    creds = [f for f in findings if not f.startswith(DB_WORDS_KIND)]
    words = [f for f in findings if f.startswith(DB_WORDS_KIND)]
    said = []
    if creds:
        said.append(f"BUG-FIND: credential exposure: returned {', '.join(creds[:4])} — this tool is not an issuer of that "
                    "credential (§MCPTEST30 census; values are never recorded)")
    if words:
        said.append(f"BUG-FIND: database words: the answer carries a database driver's own error text ({', '.join(words[:3])}): "
                    "the route put an exception's text in its answer (§MCPTEST30 census; the text is never recorded)")
    return " ".join(said)
