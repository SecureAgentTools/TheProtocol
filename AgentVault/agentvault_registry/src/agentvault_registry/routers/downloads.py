"""§pass66.8 (2026-05-23) — Public download surface for the MCP stdio bridge.

Developers register on the registry, mint an API key (`/auth/api-keys`), then
need the JS bridge file to plug Claude Code or Claude Desktop into the
TheProtocol MCP server. Before this router the bridge lived only in the
repo root + Commander's local `.claude.json` — there was no way for a
developer to actually obtain it.

This router serves the bridge as a public static file. The JS itself
contains NO secrets (only protocol code + env-var reads); the developer
sets `THEPROTOCOL_API_KEY=<their_avreg_key>` themselves in the env block
of their `.claude.json` / `claude_desktop_config.json`.

Endpoints:
  GET /api/v1/downloads/mcp-stdio-bridge.js        — public bridge (Tier 1+2+3)
  GET /api/v1/downloads/mcp-stdio-bridge-admin.js  — admin bridge (Tier ADMIN)

Both are unauthenticated. The admin-tier bridge is still public code — the
admin TOOLS it proxies require an admin developer JWT at runtime, gating
happens server-side.
"""
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse

from agentvault_registry.core.public_url import public_base_url as _shared_public_base_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/downloads", tags=["Downloads"])

# Dockerfile copies the bridge .js files into /app/downloads/ at image build.
# See `PRODUCTION_DOCS/06_OPERATIONS/Automated_Operator_Provisioning_Cloud_Service.md`
# for the build pipeline note.
_DOWNLOADS_DIR = Path("/app/downloads")

# url path segment -> (filename on disk, description)
# §DOCSFIX CB-310: the descriptions say what the files are without a tool count or list: the files are copied into the
# image from the build context, and the counts and names written here had drifted from them (17 tools for a bridge that
# carries 16; support tools the admin bridge never had).
_BRIDGE_FILES = {
    "mcp-stdio-bridge.js":       ("mcp-stdio-bridge.js",       "Public MCP bridge for Claude Code and Claude Desktop (Node.js, stdio): set THEPROTOCOL_API_URL to the registry it talks to and THEPROTOCOL_API_KEY to your API key. Its tools take no credential, an agent token or your developer API key."),
    "mcp-stdio-bridge-admin.js": ("mcp-stdio-bridge-admin.js", "Admin MCP bridge (Node.js, stdio): a small set of admin tools (a developer token for an administrator, a generic admin request, reads of the event store, Prometheus and Grafana). Every call needs an admin developer token."),
    "CLAUDE.md":                 ("operator-CLAUDE.md",        "Operator manual for an AI assistant: how to sign in, create agents and move units on this registry, served with this registry's own address and settings filled in."),
}


def _public_base_url(request: Request) -> str:
    """This registry's public base URL. Thin alias — the rule lives in ONE place.

    Moved to ``core/public_url.py`` in §OPGUIDE-6 when the invite-code router
    turned out to need the identical logic and had quietly got it wrong.
    Behaviour here is unchanged.
    """
    return _shared_public_base_url(request)


def _live_facts_block(base_url: str) -> str:
    """The 'what am I connected to' table, computed at request time.

    The point of generating this rather than shipping placeholders: the reader is
    an AI assistant with no shell and no source. Currency, trust domain and
    whether minting is even possible are properties of THIS deployment, and an
    assistant that has to guess them guesses wrong.
    """
    try:
        from agentvault_registry.config import settings
        from agentvault_registry.core.mainframe_gate import is_mainframe

        name = str(getattr(settings, "REGISTRY_NAME", "") or "this registry")
        currency = (os.environ.get("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
        trust_domain = (os.environ.get("SPIRE_TRUST_DOMAIN", "") or "").strip() or "(not published)"
        mainframe = is_mainframe()
        role = "sovereign frame (mainframe)" if mainframe else "cloud operator (hosted under a parent frame)"
        # The registry-side mint gate is exactly is_mainframe(); the token layer
        # enforces MINTING_AUTHORITY independently. Report the gate we can read.
        mint = (
            "available to admins with `admin_treasury` (§6)"
            if mainframe else
            "**not available here**: it answers 404 `mainframe_only` by design (§6). Request funds from your parent frame instead (§7.1)."
        )
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        return (
            "> **This registry, as it answered at " + now + "**\n>\n"
            "> | | |\n> |---|---|\n"
            f"> | `REGISTRY_URL` | `{base_url}` |\n"
            f"> | Name | {name} |\n"
            f"> | Role | {role} |\n"
            f"> | Unit of account | **{currency}** |\n"
            f"> | Trust domain | `{trust_domain}` |\n"
            f"> | Minting | {mint} |\n"
            f"> | This file | `{base_url}/api/v1/downloads/CLAUDE.md` |\n>\n"
            "> Every `{REGISTRY_URL}` below has already been replaced with the value above,\n"
            "> so the requests are copy-pasteable as written. This file is generated per\n"
            "> request: re-fetch it after a configuration change rather than caching it."
        )
    except Exception:
        logger.exception("[downloads] live-facts block failed; serving URL substitution only")
        return f"> `REGISTRY_URL` = `{base_url}`"


@router.get(
    "/mcp-stdio-bridge.js",
    summary="Download the public MCP stdio bridge for Claude Code / Desktop",
    response_class=FileResponse,
)
async def download_public_bridge():
    """Serve `mcp-stdio-bridge.js`. Public, no auth."""
    path = _DOWNLOADS_DIR / "mcp-stdio-bridge.js"
    if not path.exists():
        logger.error(f"[downloads] Missing bridge file at {path}")
        raise HTTPException(503, "Bridge file not bundled in this image")
    return FileResponse(
        path,
        media_type="application/javascript",
        filename="mcp-stdio-bridge.js",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get(
    "/mcp-stdio-bridge-admin.js",
    summary="Download the admin MCP stdio bridge (its tools require an admin JWT at run time)",
    response_class=FileResponse,
)
async def download_admin_bridge():
    """Serve `mcp-stdio-bridge-admin.js`. Public file; tools require admin JWT at call time."""
    path = _DOWNLOADS_DIR / "mcp-stdio-bridge-admin.js"
    if not path.exists():
        logger.error(f"[downloads] Missing admin bridge file at {path}")
        raise HTTPException(503, "Admin bridge file not bundled in this image")
    return FileResponse(
        path,
        media_type="application/javascript",
        filename="mcp-stdio-bridge-admin.js",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get(
    "/CLAUDE.md",
    summary="Operator manual for an AI assistant, filled in for this registry",
    response_class=PlainTextResponse,
)
async def download_operator_claude_md(request: Request):
    """Serve the operator `CLAUDE.md`. Public, no auth.

    An operator is handed a registry and an admin login, and drives it through an
    AI assistant that has no source, no shell and no database. This is the file
    that assistant reads first. It is served rather than shipped as a static
    asset so `{REGISTRY_URL}` and the deployment's own capabilities are already
    substituted: the reader never has to fill in a placeholder or infer whether,
    say, issuance works here.

    Contains no secrets: it documents the public API surface and tells the reader
    where their own credentials come from.
    """
    path = _DOWNLOADS_DIR / "operator-CLAUDE.md"
    if not path.exists():
        logger.error(f"[downloads] Missing operator manual at {path}")
        raise HTTPException(503, "Operator manual not bundled in this image")

    base_url = _public_base_url(request)
    text = path.read_text(encoding="utf-8")
    # ORDER MATTERS. Substitute the template body FIRST, then splice in the facts
    # block — otherwise the substitution also rewrites the block's own explanatory
    # mention of `{REGISTRY_URL}` into the URL, leaving a circular sentence
    # ("Every https://… below has already been replaced with the value above").
    text = text.replace("{REGISTRY_URL}", base_url)
    if "<!-- LIVE_FACTS -->" in text:
        text = text.replace("<!-- LIVE_FACTS -->", _live_facts_block(base_url))
    else:
        # Marker removed by an edit: the URL is still substituted above, so we
        # serve a usable file rather than one full of placeholders. Degrade, never fail.
        logger.warning("[downloads] operator manual has no LIVE_FACTS marker")

    return PlainTextResponse(
        text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "Content-Disposition": 'inline; filename="CLAUDE.md"',
        },
    )


@router.get(
    "/manifest",
    summary="List available downloads + their descriptions",
)
async def downloads_manifest():
    """Discovery endpoint: a client can list what is available without hardcoding it."""
    files = []
    for url_name, (fname, desc) in _BRIDGE_FILES.items():
        p = _DOWNLOADS_DIR / fname
        files.append({
            "filename": url_name,
            "description": desc,
            "available": p.exists(),
            "size_bytes": p.stat().st_size if p.exists() else 0,
            "url": f"/api/v1/downloads/{url_name}",
        })
    return {"files": files}
