#!/usr/bin/env python3
"""The two generated pages of the docs' Reference section (§DOCSOURCE, 2026-10-16), written into the one doc source,
static/new_registry_frontend/src/assets/docs/reference/:

  api.md        every public, agent and developer route of the registry, from its own OpenAPI description
  mcp-tools.md  every tool of the public MCP server, from its own tool list

Step 1, inside a registry image of the release (the app is imported, nothing is served, no database is touched); to
generate from corrected source texts, mount the source over the image's and pass -e SOURCE_REF=<short commit>:

    docker run --rm --network none -e DATABASE_URL=postgresql+asyncpg://x:x@localhost:5432/x \\
      -e API_KEY_SECRET=<any 32 or more characters> -v <this folder>:/gen:ro --entrypoint python <image> \\
      /gen/gen_reference_docs.py --dump > dump.json

Step 2, anywhere:

    python3 gen_reference_docs.py --from-dump dump.json [--out <the doc folder>/reference]

Left out on purpose, and said so on each page: admin routes and tools, the routes registries call each other on
(mTLS or the federation licence), internal routes, the MCP transport routes (their own page), and the euro purchase
function (the routes
under /api/v1/fiat and the MCP fiat tools): it is switched off on the public network.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

DOCS_REFERENCE = (Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "static" / "new_registry_frontend"
                  / "src" / "assets" / "docs" / "reference")
SWAGGER = "https://api.theprotocol.cloud/docs"
SPEC_URL = "https://api.theprotocol.cloud/openapi.json"
LABELS = {"DeveloperJWT": "developer", "DeveloperLogin": "developer", "AgentJWT": "agent", "APIKey": "developer",
          "BootstrapToken": "bootstrap"}
PEER = {"mTLSPeer", "FederationLicense"}
SWITCHED = ("> Locks and their payout program are switches per registry (`STAKING_ENABLED`, `STAKING_REWARDS_ENABLED`), "
            "off on the public network: there these routes refuse or answer empty. A payout program, where an operator "
            "switches one on, is discretionary and paid in platform units; no return is promised.")
NOTES = {"staking": SWITCHED, "tokenomics": SWITCHED,
         "teg": "> The payout and lock routes under `/teg` follow the same switches as `/staking`: off on the public "
                "network."}
CATEGORY = {"core": "Core", "discovery": "Discovery", "account": "Account", "identity": "Identity", "wallet": "Wallet",
            "payments-a2a": "Payments and contracts", "exchange": "AGORA (organisation points)", "guild": "The Guild",
            "governance": "Governance", "dev-lifecycle": "Developer lifecycle",
            "staking-rewards": "Locks (a switch per registry)", "other": "Other"}
TIER_LABEL = {"T0": "none (it issues the agent token)", "T1": "public", "T2": "agent", "T3": "developer"}


def dump() -> dict:
    """inside the image: the app's OpenAPI description and the public MCP server's tools"""
    os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", "/tmp/prom")
    os.makedirs(os.environ["PROMETHEUS_MULTIPROC_DIR"], exist_ok=True)
    sys.path.insert(0, "/app/src")
    from agentvault_registry.main import app
    from agentvault_registry.core.registry_identity import BUNDLED_IMAGE_TAG
    from agentvault_registry.mcp import server as s
    from agentvault_registry.mcp import tool_categories as tc
    from agentvault_registry.mcp import tool_switches as ts
    from fastapi.routing import APIRoute

    def needs_admin(dep) -> bool:
        """an admin check anywhere in the route's dependency tree (require_admin_flag, admin_credential, ...)"""
        def name(call) -> str:   # a function, a closure, or a callable class instance (which has no __qualname__ of its own)
            return (getattr(call, "__qualname__", None) or type(call).__qualname__ or "").lower()
        return dep is not None and any("admin" in name(d.call) or needs_admin(d) for d in dep.dependencies)

    try:   # FastAPI 0.14x includes routers lazily: the effective routes (full path, dependant) come from iter_route_contexts
        from fastapi.routing import iter_route_contexts
        def ctx(c):   # a plain Starlette route (a mount, a static path) has no dependant: never an API route
            try:
                return (c.path_format, c.methods, c.dependant)
            except AttributeError:
                return None
        contexts = [x for x in map(ctx, iter_route_contexts(app.routes)) if x]
    except ImportError:
        contexts = [(r.path_format, r.methods, r.dependant) for r in app.routes if isinstance(r, APIRoute)]
    admin_routes = sorted({f"{m} {path}" for path, methods, dep in contexts if needs_admin(dep) for m in (methods or ())})
    tools = [{"name": t.get("name"), "description": t.get("description", ""),
              "required": (t.get("inputSchema") or {}).get("required", [])}
             # the tools a client is TOLD of under the dump's switches (W3: tools/list filters by them), as app.openapi()
             # documents only the routes those switches serve; a dump run with production's switches documents production
             for t in ts.filter_listed(s.ALL_TOOL_SCHEMAS) if isinstance(t, dict) and t.get("name")]
    return {"version": BUNDLED_IMAGE_TAG, "source": os.environ.get("SOURCE_REF", ""), "openapi": app.openapi(), "tools": tools,
            "admin_routes": admin_routes,
            "tier2": sorted(s.TIER2_TOOLS),
            "tier3": sorted(s.TIER3_TOOLS), "categories": dict(tc.PUBLIC_TOOL_CATEGORIES)}


def cell(text: str) -> str:
    return " ".join((text or "").split()).replace("|", "\\|")


def first_sentence(text: str, limit: int = 220) -> str:
    t = " ".join((text or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    t = m.group(1) if m else t
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def provenance(d: dict, what: str) -> str:
    """where the page comes from: the release's own description, or that release's routes with texts corrected since"""
    if d.get("source"):
        return (f"Generated from {what} of `{d['version']}` (the release the production frames run), with the texts as "
                f"corrected since in AgentVault `{d['source']}`; those corrections reach the servers with the next release. ")
    return f"Generated from {what} at `{d['version']}`. "


def api_page(d: dict) -> str:
    spec, version = d["openapi"], d["version"]
    groups: dict[str, list] = defaultdict(list)
    left = {"admin": 0, "peer": 0, "internal": 0, "mcp": 0, "fiat": 0}
    admin_routes = set(d.get("admin_routes", []))
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if not isinstance(op, dict):
                continue
            schemes = {k for s in (op.get("security") or []) for k in s}
            summary = op.get("summary") or ""
            if (f"{method.upper()} {path}" in admin_routes or "AdminDeveloperJWT" in schemes or "admin" in path.split("/")
                    or summary.lower().startswith("admin ") or "(admin" in summary.lower()):
                left["admin"] += 1
                continue
            if schemes & PEER:
                left["peer"] += 1
                continue
            if "internal" in path.split("/") or path.startswith("/api/v1/sandbox/"):
                left["internal"] += 1
                continue
            if path.startswith("/mcp"):
                left["mcp"] += 1
                continue
            if path.startswith("/api/v1/fiat"):
                left["fiat"] += 1
                continue
            seg = path.split("/")
            group = seg[3] if path.startswith("/api/v1/") and len(seg) > 3 else (seg[1] or "root")
            cred = sorted({LABELS.get(k, k) for k in schemes}) or ["public"]
            groups[group].append((path, method.upper(), summary, " or ".join(cred)))
    n = sum(len(v) for v in groups.values())
    out = ["# API Reference", "",
           provenance(d, "the registry's own OpenAPI description") + "The page is written by "
           "`agentvault_registry/scripts/gen_reference_docs.py`; do not edit it, regenerate it. "
           f"{n} routes in {len(groups)} groups.", "",
           f"Each route's parameters, request bodies and answers are in the interactive description every registry serves: "
           f"[api.theprotocol.cloud/docs]({SWAGGER}), machine-readable at [openapi.json]({SPEC_URL}); on your own "
           "registry, `<your-registry-url>/docs`.", "",
           "**Credentials.** *public*: none. *developer*: a developer token (`POST /api/v1/auth/login`) or an API key "
           "(`Authorization: Bearer avreg_…`). *agent*: an agent token (`POST /api/v1/auth/agent/token`). *bootstrap*: the "
           "five-minute token that creates an agent (`POST /api/v1/onboard/bootstrap/request-token`).", "",
           f"**Left out:** {left['admin']} admin routes, {left['peer']} routes registries call each other on (mTLS or the "
           f"federation licence), {left['internal']} internal routes (in-network lookups and the sandbox proxies), "
           f"{left['mcp']} MCP transport routes (see the MCP Tool Catalog) and {left['fiat']} routes "
           "under `/api/v1/fiat`: the fiat on-ramp, switched off on the public network.", ""]
    for g in sorted(groups):
        rows = sorted(groups[g])
        out += [f"## {g} ({len(rows)})", ""]
        if g in NOTES:
            out += [NOTES[g], ""]
        out += ["| Method | Path | What it does | Credential |", "|---|---|---|---|"]
        out += [f"| {m} | `{p}` | {cell(s)} | {c} |" for p, m, s, c in rows]
        out.append("")
    return "\n".join(out)


def mcp_page(d: dict) -> str:
    version, cats = d["version"], d["categories"]
    t2, t3 = set(d["tier2"]), set(d["tier3"])
    groups: dict[str, list] = defaultdict(list)
    fiat = 0
    for t in d["tools"]:
        short = t["name"].removeprefix("theprotocol_")
        cat = cats.get(short, "other")
        if cat == "fiat":
            fiat += 1
            continue
        tier = "T0" if short == "getAgentToken" else ("T2" if t["name"] in t2 or short in t2 else
                                                      "T3" if t["name"] in t3 or short in t3 else "T1")
        groups[cat].append((t["name"], TIER_LABEL[tier], first_sentence(t["description"])))
    n = sum(len(v) for v in groups.values())
    out = ["# MCP Tool Catalog", "",
           provenance(d, "the public MCP server's own tool list") + "The page is written by "
           "`agentvault_registry/scripts/gen_reference_docs.py`; do not edit it, regenerate it. "
           f"{n} tools in {len(groups)} groups.", "",
           "**Connect.** Every registry serves the public MCP server at `<registry>/mcp/rpc` (JSON-RPC 2.0), "
           "`<registry>/mcp/sse` and `<registry>/mcp`; `?mode=gateway` lists the core tools plus the discovery tools "
           "(`listToolsets`, `searchTools`, `describeTools`, `invokeTool`), and `?toolsets=a,b` lists chosen groups only. "
           "Each tool's full input schema is in the server's `tools/list` answer.", "",
           "**Credentials.** *public*: none. *agent*: an agent token, passed as `agent_jwt` or in the `Authorization` "
           "header (`getAgentToken` issues one). *developer*: a developer token or an API key in the `Authorization` "
           "header.", "",
           f"**Left out:** {fiat} tools of the fiat on-ramp, switched off on the public network, and the "
           "administrators' MCP server (a separate surface).", ""]
    order = [c for c in CATEGORY if c in groups] + sorted(c for c in groups if c not in CATEGORY)
    for c in order:
        rows = sorted(groups[c])
        out += [f"## {CATEGORY.get(c, c)} ({len(rows)})", ""]
        if c == "staking-rewards":
            out += [SWITCHED.replace("these routes", "these tools"), ""]
        out += ["| Tool | Credential | What it does |", "|---|---|---|"]
        out += [f"| `{name}` | {cred} | {cell(desc)} |" for name, cred, desc in rows]
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dump", action="store_true", help="inside the image: print the OpenAPI description and the tools")
    g.add_argument("--from-dump", help="write the two pages from a dump")
    ap.add_argument("--out", default=str(DOCS_REFERENCE))
    a = ap.parse_args()
    if a.dump:
        sys.stdout.write(json.dumps(dump()))
        return 0
    d = json.load(open(a.from_dump))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in (("api.md", api_page(d)), ("mcp-tools.md", mcp_page(d))):
        (out / name).write_text(text + "\n")
        print(f"wrote {out / name} ({len(text)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
