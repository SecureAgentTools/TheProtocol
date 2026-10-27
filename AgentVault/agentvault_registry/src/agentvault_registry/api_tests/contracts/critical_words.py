"""§MCPTEST30 W6 (agentvault2-aa, 2026-10-25): the critical words, for the MCP tester's listing check and answers census.

His words that day to agentvault2-69: "i dont want the critical wording. only compliant ones" and "i want the illegal
wording completly gone before opening" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md: W6 checks tool names,
descriptions and answers for the words on a frame with production's switches). The list is the console's own gate
(static/new_registry_frontend/src/i18n/vocabulary.test.ts: WORDS for stake, CRITICAL for the rest), held here for the
MCP surface: the stake words, the critical words, and a token only in its value sense (tokenomics, a utility token, a
token economy, supply, balance, price or transfer). A sign-in token (bootstrap, session, OAuth, pull, API, access,
refresh, invitation, reset) is a credential and keeps its name, as the console gate keeps its sign-in keys.

Not critical, as the plan keeps them: earning trust, non-profit, the cryptographic words, investigating, and "returns" as
a verb (only "returns on" and annual, expected, guaranteed or high returns count).
"""
from __future__ import annotations

import re
from contextvars import ContextVar, Token
from typing import Any, Dict, Iterable, List, Optional, Set

_CRITICAL = re.compile(
    r"\b(?:rewards?|rewarded|rewarding|yields?|APY|APR|dividends?|shares|stocks?|IPO|invest(?!igat)\w*|profits?|revenues?|"
    r"earn(?:s|ed|ing|ings)?|crypto(?!graph)\w*|insurance|insured|premiums?|tokenomics|banks?|banking|on-chain|"
    r"utility tokens?|returns? on|(?:annual|expected|guaranteed|high|investment) returns?|"
    r"(?:un)?stak(?:e|ed|es|er|ers|ing)|tokens? (?:economy|supply|balances?|prices?|transfers?|holders?)|"
    r"(?:value|governance|reward|staking) tokens?)\b", re.I)
_ALLOW = re.compile(r"\bearn(?:s|ed|ing)? (?:the |their |its |your )?trust\b|\bnon-profit\b", re.I)


def prose(text: str) -> str:
    """The words a person reads in a sentence: code spans, {placeholders}, paths, snake_case and camelCase or CamelCase
    identifiers (an event name like TokensTransferred, a field like staked_balance) are left out."""
    s = re.sub(r"`[^`]*`", " ", text or "")
    s = re.sub(r"\{[^{}]*\}", " ", s)
    s = re.sub(r"(^|[\s\"'(=>])/[\w\-.{}:]+(?:/[\w\-.{}:]*)*", r"\1 ", s)
    s = re.sub(r"[^\W_]+(?:_[^\W_]+)+", " ", s)
    # an identifier has a lower-case letter before an upper-case one (getMyEarnings, TokensTransferred); APY and IPO stay
    s = re.sub(r"\b[A-Za-z]*[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*\b", " ", s)
    return _ALLOW.sub(" ", s)


def in_text(text: str) -> List[str]:
    """The critical words a sentence holds, lower-cased, sorted, once each."""
    return sorted({m.group(0).lower() for m in _CRITICAL.finditer(prose(text))})


def in_name(name: str) -> List[str]:
    """The critical words a tool's name holds: theprotocol_getMyEarnings reads "get my earnings"."""
    bare = name[len("theprotocol_"):] if name.startswith("theprotocol_") else name
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", bare)
    return sorted({m.group(0).lower() for m in _CRITICAL.finditer(_ALLOW.sub(" ", spaced))})


def strings_of(value: Any, depth: int = 0) -> Iterable[str]:
    """Every string value in an answer (keys are names, not words)."""
    if depth > 12:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings_of(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from strings_of(v, depth + 1)


def in_answer(value: Any) -> List[str]:
    """The critical words in an answer's strings."""
    found = set()
    for s in strings_of(value):
        found.update(in_text(s))
    return sorted(found)


def listing_findings(tools: Iterable[dict]) -> List[dict]:
    """[{tool, name: [...], description: [...]}] for every listed tool whose name or description holds a word."""
    out = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        n = str(t.get("name") or "")
        nw, dw = in_name(n), in_text(str(t.get("description") or ""))
        if nw or dw:
            out.append({"tool": n, "name": nw, "description": dw})
    return out


# ── the answers census: every MCP answer a run receives, scanned for the words (a ContextVar, as credential_exposure's) ──
LISTING_ROW = "wording: the listings"
ANSWERS_ROW = "wording: the answers"

_COLLECT: ContextVar[Optional[Dict[str, Any]]] = ContextVar("mcp_wording_census", default=None)


def begin() -> Token:
    return _COLLECT.set({"responses": 0, "scan_errors": 0, "tools": {}})


def end(token: Token) -> Dict[str, Any]:
    box = _COLLECT.get() or {"responses": 0, "scan_errors": 0, "tools": {}}
    try:
        _COLLECT.reset(token)
    except (ValueError, LookupError):
        _COLLECT.set(None)
    return box


def record(tool: str, parsed: Any) -> None:
    """Scan one tool answer into the running census. A no-op outside a census; never raises."""
    box = _COLLECT.get()
    if box is None:
        return
    try:
        box["responses"] += 1
        found = in_answer(parsed)
        if found:
            box["tools"].setdefault(str(tool), set()).update(found)
    except Exception:  # noqa: BLE001 — the census never breaks the sweep; it counts what it could not read
        box["scan_errors"] += 1


def answers_summary(box: Dict[str, Any], limit: int = 40) -> Dict[str, Any]:
    tools: Dict[str, Set[str]] = box.get("tools") or {}
    shown = {t.replace("theprotocol_", ""): sorted(w) for t, w in sorted(tools.items())[:limit]}
    words: Dict[str, int] = {}
    for w in tools.values():
        for x in w:
            words[x] = words.get(x, 0) + 1
    return {"responses_scanned": box.get("responses", 0), "scan_errors": box.get("scan_errors", 0),
            "tools_with_a_word": len(tools), "by_word": dict(sorted(words.items(), key=lambda kv: -kv[1])),
            "tools": shown, "more": max(0, len(tools) - limit)}


def listing_reason(f: dict) -> str:
    parts = []
    if f.get("name"):
        parts.append("its name says " + ", ".join(f["name"]))
    if f.get("description"):
        parts.append("its description says " + ", ".join(f["description"]))
    return "WORDING: the listing names a critical word (" + "; ".join(parts) + ")"


def old_names_listed(tools: Iterable[dict]) -> List[str]:
    """The renamed tools' old names a listing still advertises (mcp/tool_aliases.TOOL_ALIASES: an old name executes, it is
    never listed). Read from the listing alone: calling an old name would count kind="mcp_w3", the instrument for
    dropping the old names once it reads zero."""
    try:
        from agentvault_registry.mcp.tool_aliases import TOOL_ALIASES
    except Exception:  # noqa: BLE001 — an older target has no aliases module; nothing to judge
        return []
    return sorted(str(t.get("name")) for t in tools if isinstance(t, dict) and t.get("name") in TOOL_ALIASES)
