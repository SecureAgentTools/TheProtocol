"""tp mcp serve — host-side MCP server for the 14 tp-operator CLI verbs.

Spec: PRODUCTION_DOCS/ROADMAP/Operator_MCP_Server_Strategy.md

Architecture (§3 of the strategy):
  - stdio MCP server (no network exposure)
  - subprocess each tool call to `tp operator <verb>` (clean separation)
  - reuses CLI's audit-log pipeline (--invoked-via mcp flag injected)
  - 20 tools across 5 confirmation tiers
  - 3-tier confirm model: AUTO (read-only) / SOFT (low-risk mutate) / HARD (destructive — requires confirm:true)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

import typer

logger = logging.getLogger("tp_operator.mcp_serve")


# ── tool inventory (§4 of strategy) ─────────────────────────
# Naming: tp_* prefix. Distinct from existing theprotocol_* tools.
# Tier: AUTO (no confirm), SOFT (Claude should ask), HARD (requires confirm:true).

TOOLS_AUTO: List[Dict[str, Any]] = [
    {
        "name": "tp_status",
        "description": (
            "Aggregate health snapshot of an operator's 9-container stack. Returns verdict "
            "(green/yellow/red), per-service state + health + image, evaluation timestamp. "
            "Read-only; safe to call freely. Use `all_operators=true` to aggregate across the host."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "all_operators": {"type": "boolean", "default": False},
                "detail": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "cli_verb": ["status"],
        "tier": "AUTO",
    },
    {
        "name": "tp_health",
        "description": (
            "Active HTTP probe of mainframe /health (and, with strict=true, its federation info and the supply "
            "invariant it reads from its ledger). Distinct from tp_status which observes docker; tp_health actively probes HTTP. "
            "Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "strict": {"type": "boolean", "default": False},
                "include_federation": {"type": "boolean", "default": False},
                "include_eventstore": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
        "cli_verb": ["health"],
        "tier": "AUTO",
    },
    {
        "name": "tp_logs",
        "description": (
            "Tail recent log lines from one Docker Compose service. Tail size capped at 1000 "
            "(MCP responses must stay under 64 KB). Use repeated calls to poll instead of streaming."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "service": {
                    "type": "string",
                    "enum": ["registry", "teg-layer", "db", "teg-db", "redis", "pgbouncer", "nginx-federation", "spire-agent", "cert-writer"],
                },
                "tail": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 100},
                "since": {"type": "string", "description": "duration like '15m', '2h', '2026-05-11T00:00'"},
            },
            "required": ["operator", "service"],
            "additionalProperties": False,
        },
        "cli_verb": ["logs"],
        "tier": "AUTO",
    },
    {
        "name": "tp_peers",
        "description": "Federation network stats — total registries, active count, network health, per-peer last-sync. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}},
            "additionalProperties": False,
        },
        "cli_verb": ["peers"],
        "tier": "AUTO",
    },
    {
        "name": "tp_doctor",
        "description": "Comprehensive operator-side diagnostic — docker, disk, services, license, mainframe reachability. Paste output to support if something's off. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}, "all_operators": {"type": "boolean", "default": False}},
            "additionalProperties": False,
        },
        "cli_verb": ["doctor"],
        "tier": "AUTO",
    },
    {
        "name": "tp_validate_config",
        "description": "Pre-flight check on .env.operator — required keys, coupling rules, example-value warnings. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}, "proposed_path": {"type": "string"}},
            "additionalProperties": False,
        },
        "cli_verb": ["validate-config"],
        "tier": "AUTO",
    },
    {
        "name": "tp_version",
        "description": "Print tp-operator CLI version + schema version. Useful for compat verification before other tool calls.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "cli_verb": ["version"],
        "tier": "AUTO",
    },
    {
        "name": "tp_license_show",
        "description": "Local license summary — operator DID, federation operator DID, license key prefix (12 chars), mainframe URL. Never returns the full key. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}},
            "additionalProperties": False,
        },
        "cli_verb": ["license", "show"],
        "tier": "AUTO",
    },
    {
        "name": "tp_license_verify",
        "description": ("Ask the parent frame to check the operator's federation licence (through the operator's "
                        "registry, on the parent's federation lane); verified only when the parent found it active. "
                        "Read-only."),
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}},
            "additionalProperties": False,
        },
        "cli_verb": ["license", "verify"],
        "tier": "AUTO",
    },
    {
        "name": "tp_spire_list",
        "description": ("List the SPIFFE IDs the parent registry has revoked (its public list for SDK polling). "
                        "It lists no enrollments. Read-only."),
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}},
            "additionalProperties": False,
        },
        "cli_verb": ["spire", "list"],
        "tier": "AUTO",
    },
]

TOOLS_SOFT: List[Dict[str, Any]] = [
    {
        "name": "tp_sync",
        "description": ("Ask the parent frame to run a federation sync cycle now (POST /api/v1/federation/sync/trigger "
                        "through the operator's registry, on the parent's federation lane; the parent runs at most one "
                        "every 30 seconds). Fails when the parent refuses. State-mutating but recoverable."),
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}},
            "required": ["operator"],
            "additionalProperties": False,
        },
        "cli_verb": ["sync"],
        "tier": "SOFT",
    },
    {
        "name": "tp_spire_enroll",
        "description": ("Ask the parent frame to create the SPIRE entry of an agent DID (through the operator's registry, on "
                        "the parent's federation lane). Gives the agent an mTLS SVID identity. Fails when the parent "
                        "refuses."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "agent_did": {"type": "string"},
                "parent_fingerprint": {"type": "string"},
            },
            "required": ["operator", "agent_did"],
            "additionalProperties": False,
        },
        "cli_verb": ["spire", "enroll"],
        "tier": "SOFT",
    },
    {
        "name": "tp_spire_revoke",
        "description": ("Ask the parent frame to delete the SPIRE entry of an agent DID (through the operator's registry, on "
                        "the parent's federation lane). The agent loses its mTLS identity within ~30 min (SVID TTL). "
                        "Fails when the parent refuses."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "agent_did": {"type": "string"},
            },
            "required": ["operator", "agent_did"],
            "additionalProperties": False,
        },
        "cli_verb": ["spire", "revoke"],
        "tier": "SOFT",
    },
    {
        "name": "tp_start",
        "description": "Bring up the operator's 9-container stack (docker compose up -d). Idempotent if already running.",
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}},
            "required": ["operator"],
            "additionalProperties": False,
        },
        "cli_verb": ["start"],
        "tier": "SOFT",
    },
    {
        "name": "tp_stop",
        "description": "Bring down the operator's stack (docker compose down). The operator goes offline.",
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}},
            "required": ["operator"],
            "additionalProperties": False,
        },
        "cli_verb": ["stop"],
        "tier": "SOFT",
    },
    {
        "name": "tp_restart",
        "description": (
            "Restart one or all services. service=null restarts the full 9-container stack. "
            "apply_env_changes=true uses force-recreate (HARD-equivalent: can lose in-flight). "
            "Use no_wait=true to skip the healthcheck poll."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "service": {"type": "string"},
                "apply_env_changes": {"type": "boolean", "default": False},
                "no_wait": {"type": "boolean", "default": False},
            },
            "required": ["operator"],
            "additionalProperties": False,
        },
        "cli_verb": ["restart"],
        "tier": "SOFT",
    },
    {
        "name": "tp_backup",
        "description": (
            "Atomic backup of an operator: pg_dump of registry + TEG DBs, configs, manifest with SHA-256 per entry. "
            "Non-destructive but takes ~30s. Output is a single .tar.gz archive."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "frame": {"type": "string", "description": "A FRAME stack dir instead of an operator (three dumps incl. the ledger, the signer and SPIRE volumes)"},
                "out_path": {"type": "string"},
                "include_volumes": {"type": "boolean", "default": False},
            },
            "required": [],
            "additionalProperties": False,
        },
        "cli_verb": ["backup"],
        "tier": "SOFT",
    },
    {
        "name": "tp_update_check",
        "description": "Check if a new bundle version is published at the static channel. Read-only.",
        "inputSchema": {
            "type": "object",
            "properties": {"operator": {"type": "string"}},
            "additionalProperties": False,
        },
        "cli_verb": ["update", "--check-only"],
        "tier": "SOFT",
    },
]

TOOLS_HARD: List[Dict[str, Any]] = [
    {
        "name": "tp_update_apply",
        "description": (
            "DESTRUCTIVE. Apply a release: pre-snapshot, pull its images (by digest from the verified channel), "
            "name them in .env.operator (VERSION, IMAGE_TAG, the image prefix), up -d, healthcheck wait, "
            "auto-rollback on failure. Requires explicit confirm:true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "to_version": {"type": "string"},
                "allow_major": {"type": "boolean", "default": False},
                "auto_rollback": {"type": "boolean", "default": True},
                "confirm": {"type": "boolean", "description": "MUST be true. Hard-confirm gate."},
            },
            "required": ["operator", "confirm"],
            "additionalProperties": False,
        },
        "cli_verb": ["update", "--apply"],
        "tier": "HARD",
    },
    {
        "name": "tp_license_rotate",
        "description": (
            "DESTRUCTIVE. Atomically rotate the federation license key: the parent frame issues a new one (asked through "
            "the operator's registry, on the parent's federation lane). New key written to .env.operator (.bak preserved). "
            "New hash synced to EventStore. Requires explicit confirm:true. New key NOT echoed in response — read it from .env.operator backup."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "reason": {"type": "string", "enum": ["leak_suspected", "scheduled_rotation", "post_incident"]},
                "confirm": {"type": "boolean", "description": "MUST be true. Hard-confirm gate."},
            },
            "required": ["operator", "reason", "confirm"],
            "additionalProperties": False,
        },
        "cli_verb": ["license", "rotate"],
        "tier": "HARD",
    },
    {
        "name": "tp_restore",
        "description": (
            "DESTRUCTIVE. Atomic restore from a backup archive. Verifies manifest SHA-256, refuses cross-operator binding "
            "unless force_cross_operator=true, takes pre-restore snapshot, then stops → restores DBs + configs → starts. "
            "Requires explicit confirm:true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "operator": {"type": "string"},
                "frame": {"type": "string", "description": "A FRAME stack dir instead of an operator (refuses a production frame and another frame's archive)"},
                "archive": {"type": "string", "description": "Path to .tar.gz backup archive"},
                "force_cross_operator": {"type": "boolean", "default": False},
                "confirm": {"type": "boolean", "description": "MUST be true. Hard-confirm gate."},
            },
            "required": ["archive", "confirm"],
            "additionalProperties": False,
        },
        "cli_verb": ["restore"],
        "tier": "HARD",
    },
]

ALL_TOOLS = TOOLS_AUTO + TOOLS_SOFT + TOOLS_HARD


def _find_tp_binary() -> str:
    """Find the `tp` binary the server should subprocess to.

    Resolution order:
      1. $TP_BIN env var
      2. /usr/local/bin/tp
      3. $PATH lookup
      4. Sibling of this Python file (PyInstaller bundle case)
    """
    env_bin = os.environ.get("TP_BIN")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    if os.path.exists("/usr/local/bin/tp"):
        return "/usr/local/bin/tp"
    which = shutil.which("tp")
    if which:
        return which
    # PyInstaller bundle: the binary is being run as `tp mcp serve`, so /proc/self/exe is the binary
    try:
        self_exe = os.readlink("/proc/self/exe")
        if os.path.exists(self_exe):
            return self_exe
    except OSError:
        pass
    raise RuntimeError("Cannot locate `tp` binary — set $TP_BIN or install to /usr/local/bin/tp")


def _build_cli_args(tool: Dict[str, Any], arguments: Dict[str, Any], default_operator: Optional[str]) -> List[str]:
    """Translate MCP tool arguments to CLI args.

    CRITICAL: the `tp` umbrella binary's global flags (--operator, --json, --yes,
    etc.) live on the operator sub-typer, NOT on the top-level umbrella. So the
    correct argument order is:

        tp operator --operator X --json --yes status [verb-args]
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^
                    flags AFTER the sub-typer name

    Putting flags before `operator` triggers "No such option" because the umbrella
    doesn't define them. Bug fixed 2026-05-12 after MCP smoke test.
    """
    # The `operator` sub-typer name comes FIRST, then its global flags, then the verb.
    args: List[str] = ["operator"]

    op = arguments.get("operator") or default_operator
    if arguments.get("frame"):
        args += ["--frame", arguments["frame"]]   # §FRAMEKIT P3.2: a frame stack dir instead of an operator
    elif op:
        args += ["--operator", op]
    elif arguments.get("all_operators"):
        args += ["--all-operators"]

    # Always JSON output for MCP
    args += ["--json"]

    # Soft + Hard tier: pass --yes (we've already validated confirm: true for hard tier)
    if tool["tier"] in ("SOFT", "HARD"):
        args += ["--yes"]

    # Verb (e.g., status / license show / spire enroll)
    args += list(tool["cli_verb"])

    # Tool-specific argument translation
    name = tool["name"]
    if name == "tp_status":
        if arguments.get("detail"):
            args += ["--detail"]
    elif name == "tp_health":
        if arguments.get("strict"):
            args += ["--strict"]
        if arguments.get("include_federation"):
            args += ["--include-federation"]
        if arguments.get("include_eventstore"):
            args += ["--include-eventstore"]
    elif name == "tp_logs":
        args += [arguments["service"], "--tail", str(arguments.get("tail", 100))]
        if arguments.get("since"):
            args += ["--since", arguments["since"]]
    elif name == "tp_restart":
        if arguments.get("service"):
            args += [arguments["service"]]
        if arguments.get("apply_env_changes"):
            args += ["--apply-env-changes"]
        if arguments.get("no_wait"):
            args += ["--no-wait"]
    elif name == "tp_backup":
        if arguments.get("out_path"):
            args += ["--out", arguments["out_path"]]
        if arguments.get("include_volumes"):
            args += ["--include-volumes"]
    elif name == "tp_update_check":
        # --check-only is already in cli_verb
        pass
    elif name == "tp_update_apply":
        # --apply is in cli_verb; add to-version / allow-major
        if arguments.get("to_version"):
            args += ["--to-version", arguments["to_version"]]
        if arguments.get("allow_major"):
            args += ["--allow-major"]
        if not arguments.get("auto_rollback", True):
            args += ["--no-auto-rollback"]
    elif name == "tp_license_rotate":
        args += ["--reason", arguments["reason"]]
    elif name == "tp_spire_enroll":
        args += [arguments["agent_did"]]
        if arguments.get("parent_fingerprint"):
            args += ["--parent-fingerprint", arguments["parent_fingerprint"]]
    elif name == "tp_spire_revoke":
        args += [arguments["agent_did"]]
    elif name == "tp_restore":
        args += [arguments["archive"]]
        if arguments.get("force_cross_operator"):
            args += ["--force-cross-operator"]
    elif name == "tp_validate_config":
        if arguments.get("proposed_path"):
            args += ["--proposed", arguments["proposed_path"]]

    return args


async def _run_cli(tp_bin: str, args: List[str], timeout_s: int = 60) -> Dict[str, Any]:
    """Subprocess the `tp` binary. Returns {ok, stdout, stderr, exit_code}."""
    # Pass through TP_OPERATOR_REMOTE_AUDIT + TP_OPERATOR_MAINFRAME_URL so the
    # subprocess inherits the operator's mainframe routing + audit policy.
    env = os.environ.copy()
    # Mark this invocation as MCP-triggered (used by the CLI's audit log)
    env["TP_OPERATOR_INVOCATION_SOURCE"] = "mcp"

    try:
        proc = await asyncio.create_subprocess_exec(
            tp_bin, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"ok": False, "stdout": "", "stderr": f"Tool timed out after {timeout_s}s", "exit_code": -1}

        return {
            "ok": proc.returncode == 0,
            "stdout": stdout.decode(errors="replace")[:65536],  # 64 KB cap per strategy §3.5
            "stderr": stderr.decode(errors="replace")[:8192],
            "exit_code": proc.returncode,
        }
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": f"`tp` binary not found at {tp_bin}", "exit_code": -1}


def _validate_hard_confirm(tool: Dict[str, Any], arguments: Dict[str, Any]) -> Optional[str]:
    """Return None if validation passes, else a string explaining the violation."""
    if tool["tier"] != "HARD":
        return None
    if arguments.get("confirm") is not True:
        return (
            f"Tool `{tool['name']}` is DESTRUCTIVE and requires explicit `confirm: true`. "
            f"Ask the operator for explicit consent, then re-call with confirm: true."
        )
    return None


async def _serve(default_operator: Optional[str], log_file: Optional[str]) -> None:
    """Run the stdio MCP server."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    import mcp.types as types

    # Find the tp binary upfront (fail fast if missing)
    tp_bin = _find_tp_binary()

    if log_file:
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.info(f"tp mcp serve starting. tp_bin={tp_bin} default_operator={default_operator}")

    server: Server = Server("tp-host-cli")

    @server.list_tools()
    async def list_tools() -> List[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in ALL_TOOLS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: Dict[str, Any]) -> List[types.TextContent]:
        # Find the tool
        tool = next((t for t in ALL_TOOLS if t["name"] == name), None)
        if tool is None:
            return [types.TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}))]

        # Hard-confirm validation
        violation = _validate_hard_confirm(tool, arguments)
        if violation:
            return [types.TextContent(type="text", text=json.dumps({"error": violation, "tier": "HARD"}))]

        # Build CLI args + run
        cli_args = _build_cli_args(tool, arguments, default_operator)
        if log_file:
            logger.info(f"call_tool: {name} → {tp_bin} {' '.join(cli_args)}")

        # Pick a timeout based on tier
        timeout_s = 60 if tool["tier"] == "AUTO" else 300

        result = await _run_cli(tp_bin, cli_args, timeout_s=timeout_s)

        if not result["ok"]:
            payload = {
                "error": result["stderr"] or "tool failed without stderr",
                "exit_code": result["exit_code"],
                "stdout_excerpt": result["stdout"][:1024] if result["stdout"] else None,
            }
            return [types.TextContent(type="text", text=json.dumps(payload))]

        # Try to forward the CLI's JSON as-is; if not parseable, wrap in {raw}
        out = result["stdout"].strip()
        try:
            json.loads(out)  # validate it's parseable JSON
            return [types.TextContent(type="text", text=out)]
        except (json.JSONDecodeError, ValueError):
            return [types.TextContent(type="text", text=json.dumps({"raw": out}))]

    if log_file:
        logger.info("tp mcp serve: ready")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


# ── Typer entrypoint glued to the umbrella's `tp mcp` subcommand ──
mcp_app = typer.Typer(
    help="MCP server — expose tp-operator CLI verbs as MCP tools (stdio transport).",
    no_args_is_help=True,
)


@mcp_app.command(name="serve", help="Run the stdio MCP server (used by .mcp.json bridges).")
def serve(
    operator: Optional[str] = typer.Option(None, "--operator", help="Default operator for tool calls. Optional."),
    log_file: Optional[str] = typer.Option(None, "--log-file", help="Optional path to write debug logs."),
) -> None:
    try:
        asyncio.run(_serve(operator, log_file))
    except KeyboardInterrupt:
        raise typer.Exit(code=0)


@mcp_app.command(name="tools", help="List the tools this MCP server would expose (for debugging).")
def tools_cmd(json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of human-readable.")) -> None:
    if json_output:
        typer.echo(json.dumps([{"name": t["name"], "tier": t["tier"], "description": t["description"][:120]} for t in ALL_TOOLS], indent=2))
        return
    typer.echo(f"tp-host-cli MCP — {len(ALL_TOOLS)} tools total")
    for tier in ("AUTO", "SOFT", "HARD"):
        tools = [t for t in ALL_TOOLS if t["tier"] == tier]
        typer.echo(f"\n[{tier}] {len(tools)} tools")
        for t in tools:
            typer.echo(f"  {t['name']:24s}  {t['description'][:80]}")


@mcp_app.command(name="version", help="Print MCP server version + protocol info.")
def version_cmd() -> None:
    from . import __version__, __schema_version__
    typer.echo(f"tp-host-cli {__version__} (schema {__schema_version__})")
    typer.echo(f"Tools: {len(ALL_TOOLS)} (AUTO={len(TOOLS_AUTO)} SOFT={len(TOOLS_SOFT)} HARD={len(TOOLS_HARD)})")
