"""
MCP tool metadata — titles, behavior annotations, curated output schemas,
and task-support markers for every tool (2026-07-14 reference-grade pass).

Spec (MCP 2025-11-25):
  * `title`        — human display name (tools/list).
  * `annotations`  — readOnlyHint / destructiveHint / idempotentHint /
                     openWorldHint. HINTS ONLY — never used for auth (the
                     tier system in security remains the only authz layer).
                     Spec defaults when absent: readOnly=false,
                     destructive=TRUE, idempotent=false, openWorld=TRUE.
                     We emit COMPACT deviations only (see _compact()), which
                     keeps the full 400-tool listing payload small.
  * `outputSchema` — declared ONLY for the curated set below whose wrappers
                     return endpoint JSON verbatim. Spec: results MUST
                     conform to a declared outputSchema, so every schema
                     here is deliberately LOOSE (additionalProperties true,
                     no required) — informative typing that cannot be
                     violated by benign response drift.
  * `execution.taskSupport = "optional"` — the genuinely long-running tools
    that may be invoked as async tasks (see mcp_tasks.py).

Derivation over enumeration: annotations/titles are computed from the tool
name with a small override map — the same architecture as tool_categories.py
(which owns bucketing). Everything here is LISTING metadata; changing it can
never grant or deny a call.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# camelCase handling
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+[A-Za-z]*")

# Display casing for acronyms/domain terms (lowercase word → display form)
_ACRONYMS = {
    "api": "API", "mcp": "MCP", "did": "DID", "teg": "TEG", "fx": "FX",
    "ipo": "IPO", "a2a": "A2A", "apy": "APY", "anp": "ANP", "acir": "ACIR",
    "jwks": "JWKS", "dns": "DNS", "ssl": "SSL", "cicd": "CI/CD", "hri": "HRI",
    "id": "ID", "svid": "SVID", "mtls": "mTLS", "oauth": "OAuth",
    "spire": "SPIRE", "url": "URL", "2fa": "2FA", "zkp": "ZKP", "avt": "AVT",
    "sse": "SSE", "jwt": "JWT", "toml": "TOML", "eigentrust": "EigenTrust",
    "ironhand": "IRONHAND", "js": "JS", "agora": "AGORA",   # §AGORAWORDS: "Buy AGORA Launch", not "Buy Agora Launch"
}


def _words(bare: str) -> List[str]:
    """Split a bare camelCase tool name into lowercase words."""
    return [w.lower() for w in _SPLIT_RE.findall(bare)]


def _bare(name: str) -> str:
    return name[len("theprotocol_"):] if name.startswith("theprotocol_") else name


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------

TITLE_OVERRIDES: Dict[str, str] = {
    "smartSend": "Smart Send (auto-routing transfer)",
    "getMcpStdioBridgeJs": "Download MCP stdio Bridge (JS)",
    "getMcpStdioBridgeAdminJs": "Download Admin MCP stdio Bridge (JS)",
}


def derive_title(name: str) -> str:
    bare = _bare(name)
    if bare in TITLE_OVERRIDES:
        return TITLE_OVERRIDES[bare]
    # Merge digit-led fragments produced by the splitter ("verify2FA" → verify, 2, fa)
    words = _words(bare)
    merged: List[str] = []
    for w in words:
        if merged and merged[-1].isdigit():
            merged[-1] = merged[-1] + w          # "2"+"fa" → "2fa"
        else:
            merged.append(w)
    return " ".join(_ACRONYMS.get(w, w.capitalize()) for w in merged)


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

# First-word verbs that mark a PURE READ (no state change server-side).
READ_VERBS = frozenset({
    "get", "list", "discover", "search", "describe", "preview", "estimate",
    "download", "validate", "check", "probe",
})

# Word stems (startswith-match on any word) that mark a DESTRUCTIVE or
# high-caution operation: data loss, credential invalidation, enforcement,
# money creation, or service halts. Over-flagging is the SAFE direction —
# clients use destructiveHint to gate human confirmation.
# "issue" since the three unit-issuing tools lost "mint" from their names (2026-10-25): issuing units creates money,
# so they stay destructive (the tripwire below pins tegTreasuryIssue).
DESTRUCTIVE_STEMS = (
    "delete", "deletion", "remove", "revoke", "slash", "suspend", "burn",
    "teardown", "blacklist", "quarantine", "reject", "retract", "halt",
    "delist", "stop", "force", "rotate", "disable", "mint", "issue", "reset",
    "purge", "deactivate", "hide", "expire",
)

# First-word verbs whose repeat with identical args converges to the same
# state (idempotentHint=true). Still writes.
IDEMPOTENT_VERBS = frozenset({
    "update", "set", "patch", "toggle", "mark", "enable", "assign",
    "unassign", "activate", "reinstate", "unhide", "unblock", "restore",
    "acknowledge", "resume", "pause", "equip", "unequip", "select",
})

# Per-tool overrides (bare name → final annotation dict, pre-compaction).
ANNOTATION_OVERRIDES: Dict[str, Dict[str, bool]] = {
    # Protective/benign despite destructive-looking stems
    "cancelAccountDeletion": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "liftQuarantine":        {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    # moves a stored baseline (the previous one is kept in the record and on the ledger); a second call with the same
    # hash answers "unchanged"
    "acceptComplianceBaseline": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    # Reads that the verb rules miss
    "compositeHealthCheck":            {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    "oauthIntrospect":                 {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    "oauthRevoke":                     {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
    "oauthFederationTrustList":        {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "mcpPassthroughGetAgentProfile":   {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    # Writes that must NOT read as destructive-by-stem, or vice versa
    "restoreFromUpload": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},  # overwrites live state
    "runAllApiTests":    {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},  # heavy; exec-gated (V0051)
    "agentHeartbeat":    {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    "logoutSession":     {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    # moves escrow to the funder, once per bond, and ends the burning state: a client should confirm
    "unlockReputationBond": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    # §MEMBERSHIP phase B (2026-10-02): the commons' admin steps that cannot be undone, and the one that moves money
    "adminCommonsPaySeason":        {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "adminCommonsCloseSeason":      {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "adminCommonsStrikeSubmission": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "adminCommonsWriteOffAward":    {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    "adminCommonsCancelSeason":     {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    # V0650 (l): a decision is final (a repeat of the same decision answers already: true), and it may unlock what an
    # agent asked for, so a client should confirm it; a request repeats idempotently on its client_ref
    "decideChatApproval":  {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
    "requestChatApproval": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    # invokeTool proxies ANY tool — flag conservatively (the inner tool's own
    # annotations are what a careful client should consult via describeTools).
    "invokeTool": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
}

# Safety tripwire — these MUST derive destructive=true (asserted at import).
_MUST_BE_DESTRUCTIVE = (
    "slashAgent", "bulkSuspendAgents", "tegTreasuryIssue",
    "deleteMyAgent", "revokeApiKey", "quarantineRegistry",
    "suspendDeveloper", "softDeleteDeveloper", "ironhandRevokeAgent",
    "requestAccountDeletion",
)
_MUST_BE_READONLY = (
    "getNetworkStats", "getMyBalance", "discoverAgents", "listAgentCards",
    "previewSlash", "getRevokedIdentities",
)


def derive_annotations(name: str) -> Dict[str, bool]:
    """Full 4-flag annotation dict for a tool name (pre-compaction)."""
    bare = _bare(name)
    if bare in ANNOTATION_OVERRIDES:
        return dict(ANNOTATION_OVERRIDES[bare])
    words = _words(bare)
    first = words[0] if words else ""
    # openWorld is false for the whole surface: every tool talks to OUR
    # registry/TEG/ES domain, not the open web.
    if first in READ_VERBS:
        return {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    if any(w.startswith(stem) for w in words for stem in DESTRUCTIVE_STEMS):
        return {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}
    if first in IDEMPOTENT_VERBS:
        return {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    # Default: additive write (create/submit/transfer/stake/vote/…)
    return {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}


def _compact(ann: Dict[str, bool]) -> Dict[str, bool]:
    """Drop fields that match the spec's absent-annotation defaults
    (readOnly=false, destructive=true, idempotent=false, openWorld=true) —
    EXCEPT destructiveHint on writers, which we keep explicit on purpose: on
    a money API the flag should be visible, not inferred from absence. For
    read-only tools the spec says destructive/idempotent are meaningful only
    when readOnlyHint is false, so they are omitted entirely."""
    if ann.get("readOnlyHint"):
        return {"readOnlyHint": True, "openWorldHint": False}
    out: Dict[str, bool] = {"destructiveHint": bool(ann.get("destructiveHint"))}
    if ann.get("idempotentHint"):
        out["idempotentHint"] = True
    if not ann.get("openWorldHint", True):
        out["openWorldHint"] = False
    return out


# Import-time tripwire (cheap; fails the build loudly, never silently ships
# a mis-flagged enforcement tool).
for _n in _MUST_BE_DESTRUCTIVE:
    assert derive_annotations(_n)["destructiveHint"], f"{_n} must be destructive"
for _n in _MUST_BE_READONLY:
    assert derive_annotations(_n)["readOnlyHint"], f"{_n} must be readOnly"


# ---------------------------------------------------------------------------
# Curated output schemas — LOOSE by design (see module docstring)
# ---------------------------------------------------------------------------

def _obj(props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": True}

_NUMSTR = {"type": ["number", "string"]}

OUTPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "getMyBalance": _obj({
        "agent_did": {"type": "string"}, "balance": _NUMSTR,
        "currency": {"type": "string"},
    }),
    "getNetworkStats": _obj({
        "total_agents": {"type": "integer"}, "active_agents": {"type": "integer"},
        "total_developers": {"type": "integer"},
    }),
    "getAgentToken": _obj({
        "access_token": {"type": "string"}, "token_type": {"type": "string"},
        "expires_in": {"type": "integer"},
    }),
    "transferUnits": _obj({
        "transaction_id": {"type": ["string", "integer"]}, "status": {"type": "string"},
        "amount": _NUMSTR, "fee": _NUMSTR,
    }),
    "getLockPayoutTiers": _obj({"tiers": {"type": "array"}}),
    "getRegistryCard": _obj({
        "name": {"type": "string"}, "registry_id": {"type": "string"},
        "capabilities": {"type": "object"},
    }),
    "getMyLocks": _obj({"stakes": {"type": "array"}, "total_staked": _NUMSTR}),
    "getAgoraListings": _obj({"listings": {"type": "array"}}),
    "getMyTegTransactions": _obj({"transactions": {"type": "array"}}),
    "discoverAgents": _obj({"agents": {"type": "array"}, "total": {"type": "integer"}}),
    "guildListOrders": _obj({"orders": {"type": "array"}}),
    "getTrustScore": _obj({"agent_did": {"type": "string"}, "trust_score": _NUMSTR}),
}


# ---------------------------------------------------------------------------
# Async-task support (mcp_tasks.py implements the lifecycle)
# ---------------------------------------------------------------------------

TASK_TOOLS_PUBLIC = frozenset({
    "tegCrossRegistryTransferDirect", "bridgeTransfer", "crossTegBalanceSync",
    "exportTegTransactions", "agentBulkExport", "triggerFederationSync",
    "agentBuilderGenerate",
})
TASK_TOOLS_ADMIN = frozenset({
    "testApiFlow", "testApiCategory", "runAllDiagnostics", "federationDriftScan",
    "bulkRefreshAgentCards",
    "triggerEigentrustComputation", "resyncFrameEventStore",
})


def task_tools(is_admin: bool) -> frozenset:
    return TASK_TOOLS_ADMIN if is_admin else TASK_TOOLS_PUBLIC


# ---------------------------------------------------------------------------
# Decoration entry point
# ---------------------------------------------------------------------------

def decorate_schemas(schemas: List[Dict[str, Any]], is_admin: bool = False) -> None:
    """Stamp title/annotations (+outputSchema/taskSupport where curated) onto
    every schema IN PLACE. Idempotent — gateway meta-tool schema objects are
    shared between the public and admin servers, so double-decoration must be
    a no-op. Never touches name/description/inputSchema."""
    tasky = task_tools(is_admin)
    for s in schemas:
        name = s.get("name", "")
        if not name:
            continue
        bare = _bare(name)
        if "title" not in s:
            s["title"] = derive_title(name)
        if "annotations" not in s:
            s["annotations"] = _compact(derive_annotations(name))
        if bare in OUTPUT_SCHEMAS and "outputSchema" not in s:
            s["outputSchema"] = OUTPUT_SCHEMAS[bare]
        if bare in tasky and "execution" not in s:
            s["execution"] = {"taskSupport": "optional"}
