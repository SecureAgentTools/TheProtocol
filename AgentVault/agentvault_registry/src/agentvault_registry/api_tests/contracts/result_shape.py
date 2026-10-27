"""§MCPTEST30 (2026-10-01) — the result shape census: is a tool's answer the shape the protocol promises?

Every tools/call response the sweep receives passes through the flow's JSON-RPC helpers, which call `record(tool,
parsed)` beside the credential exposure census. Two questions, each a MUST of the MCP spec (2025-11-25) or of this
server's own dispatch rule:

  * SUCCESS REPORTED AS FAILURE: isError true with the text `Error: None` (or a blank or false error). The dispatchers
    called any result carrying an `error` KEY a failure, so a route whose success body says `"error": null` reached the
    client as a failure with its structured content dropped (mcp/tool_result.py; the tester read it on executeTutorial
    in every round, scored healthy by an "any" probe).
  * OUTPUT SCHEMA: a tool that declares an outputSchema (mcp/tool_metadata.OUTPUT_SCHEMAS, imported, never copied) must
    return structuredContent on success, and it must validate against that schema.

And one count that is not a red: a REASONLESS REFUSAL, an error whose whole text is `<route> returned HTTP <code>` (or
`HTTP <code>`), so the caller cannot learn why it was refused. Round 5 counted 47 tools answering so; V0514 appends the
route's own reason in one place (mcp/refusal.py). What remains is listed per tool with its status codes: a refusal
whose route sends no reason at all is the route's to fix, and the census shows where.

Findings keep the tool, the check, and a JSON path or a schema keyword: never a value (a jsonschema message quotes the
instance, so only `validator` and the path are read from it).
"""
from __future__ import annotations

import re
from contextvars import ContextVar, Token
from typing import Any, Dict, List, Optional

CENSUS_ROW = "mcp_tester: result_shape_census"
_FALSE_FAILURE = re.compile(r"^Error:\s*(None|False|null)?\s*$")
# §MCPTEST30 (V0523): "<route> returned 500" with no HTTP word names no reason either (six discover-module tools
# answered so, unseen by the census until a NUL made one of them answer 500)
_REASONLESS = re.compile(r"^Error:\s*(?:.+\s)?(?:returned\s+(?:HTTP\s+)?|HTTP\s+)(\d{3})\s*$")

try:  # one definition of the declared schemas: the product's own
    from agentvault_registry.mcp.tool_metadata import OUTPUT_SCHEMAS as _SCHEMAS
except Exception:  # noqa: BLE001 — the schema half then says it could not measure
    _SCHEMAS = None
try:
    import jsonschema as _jsonschema
except Exception:  # noqa: BLE001
    _jsonschema = None

_COLLECT: ContextVar[Optional[Dict[str, Any]]] = ContextVar("mcp_result_shape_census", default=None)


def schema_for(tool: str) -> Optional[Dict[str, Any]]:
    if not _SCHEMAS or not str(tool).startswith("theprotocol_"):
        return None
    return _SCHEMAS.get(str(tool)[len("theprotocol_"):])


def begin() -> Token:
    return _COLLECT.set({"responses": 0, "schema_checked": 0, "findings": {}, "scan_errors": 0, "reasonless": {}})


def end(token: Token) -> Dict[str, Any]:
    box = _COLLECT.get() or {"responses": 0, "schema_checked": 0, "findings": {}, "scan_errors": 0, "reasonless": {}}
    try:
        _COLLECT.reset(token)
    except (ValueError, RuntimeError):
        _COLLECT.set(None)
    return box


def check(tool: str, parsed: Any) -> List[str]:
    """The findings for one JSON-RPC response of `tool` (empty: nothing wrong, or nothing this census reads)."""
    if not isinstance(parsed, dict):
        return []
    result = parsed.get("result")
    if not isinstance(result, dict) or "content" not in result:
        return []          # a JSON-RPC error, a task handle or a non-tools/call answer: not this census's question
    found: List[str] = []
    content = result.get("content") or []
    text = content[0].get("text") if content and isinstance(content[0], dict) else None
    if result.get("isError") and isinstance(text, str) and _FALSE_FAILURE.match(text.strip()):
        found.append("success reported as failure: isError with an empty error (`Error: None`)")
    schema = schema_for(tool)
    if schema is not None and not result.get("isError"):
        sc = result.get("structuredContent")
        if not isinstance(sc, dict):
            found.append("outputSchema declared, no structuredContent on a success")
        elif _jsonschema is not None:
            for err in _jsonschema.Draft202012Validator(schema).iter_errors(sc):
                path = "/".join(str(p) for p in err.absolute_path) or "(root)"
                found.append(f"outputSchema violation: `{err.validator}` at {path}")
    return found


def reasonless(parsed: Any) -> Optional[str]:
    """The status code of a refusal that names no reason (`Error: <route> returned HTTP 404`), or None."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("result"), dict):
        return None
    result = parsed["result"]
    content = result.get("content") or []
    text = content[0].get("text") if content and isinstance(content[0], dict) else None
    if not result.get("isError") or not isinstance(text, str):
        return None
    m = _REASONLESS.match(text.strip())
    return m.group(1) if m else None


def record(tool: str, parsed: Any) -> None:
    """Read one tool response into the running census. A no-op outside a census; never raises."""
    box = _COLLECT.get()
    if box is None:
        return
    try:
        box["responses"] += 1
        if schema_for(tool) is not None:
            box["schema_checked"] += 1
        for f in check(str(tool), parsed):
            box["findings"].setdefault(str(tool), set()).add(f)
        code = reasonless(parsed)
        if code:
            box.setdefault("reasonless", {}).setdefault(str(tool), set()).add(code)
    except Exception:  # noqa: BLE001 — the census never breaks the sweep; it counts what it could not read
        box["scan_errors"] += 1


def summarize(box: Dict[str, Any]) -> Dict[str, Any]:
    findings = {t: sorted(v) for t, v in sorted((box.get("findings") or {}).items())}
    reasonless_ = {t: sorted(v) for t, v in sorted((box.get("reasonless") or {}).items())}
    return {"measured": (box.get("responses") or 0) > 0, "responses_scanned": box.get("responses") or 0,
            "reasonless_refusals": reasonless_,
            "schema_checked": box.get("schema_checked") or 0, "scan_errors": box.get("scan_errors") or 0,
            "schemas_available": _SCHEMAS is not None, "validator_available": _jsonschema is not None,
            "findings": findings}


def verdict_text(summary: Dict[str, Any], limit: int = 6) -> Optional[str]:
    bad = summary.get("findings") or {}
    if not bad:
        return None
    named = "; ".join(f"{t.replace('theprotocol_', '')} ({', '.join(v[:2])})" for t, v in list(bad.items())[:limit])
    more = f"; and {len(bad) - limit} more" if len(bad) > limit else ""
    return f"BUG-FIND: result shape: {len(bad)} tool(s) answered outside the protocol's promise: {named}{more}"


def row_reason(findings: List[str]) -> str:
    return f"BUG-FIND: result shape: {'; '.join(findings[:3])} (§MCPTEST30 result shape census)"
