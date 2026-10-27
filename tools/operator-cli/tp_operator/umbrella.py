"""tp umbrella binary — exposes operator + developer + admin personas under one CLI.

Pattern: same as `aws`, `gh`, `kubectl`. One binary, three top-level sub-commands:

    tp operator status              # day-2 ops on YOUR operator (BL-1 v1.0)
    tp developer agent list         # dev-tier: list YOUR agents
    tp admin treasury mint          # admin-tier: Commander-only ops

The legacy `tp-operator` binary stays — `tp operator <verb>` is the umbrella
entry to the same underlying typer app, no code duplicated.

Auth model per persona:
    operator   — federation-license-key (Mode 3) — already shipped
    developer  — API key OR interactive password prompt → dev JWT
    admin     — same as developer + is_admin flag

For v1.0 of the umbrella:
- `tp operator <verb>` fully works (delegates to existing operator app)
- `tp developer ping` placeholder proves the pattern + identity
- `tp admin ping` placeholder same shape
- Full developer + admin command surfaces come in follow-up sessions
"""
from __future__ import annotations

import typer

from . import __schema_version__, __version__
from .main import app as operator_app
from .mcp_serve import mcp_app


# ── Umbrella root ───────────────────────────────────────────
umbrella = typer.Typer(
    name="tp",
    help=(
        "TheProtocol unified CLI — operator + developer + admin.\n\n"
        "Run `tp operator --help` to see day-2 ops commands (the same surface\n"
        "as the standalone `tp-operator` binary).\n\n"
        "Run `tp developer --help` for dev-tier commands (manage your agents,\n"
        "check balances, view your apps).\n\n"
        "Run `tp admin --help` for admin-tier ops (Commander only)."
    ),
    no_args_is_help=True,
    add_completion=True,
)


# ── operator sub-typer — direct reuse of the existing operator app ──
# typer.add_typer accepts another Typer app and grafts it as a sub-command.
# All existing operator commands (status / health / logs / license / spire /
# backup / restore / update / etc.) work verbatim under `tp operator <verb>`.
umbrella.add_typer(
    operator_app,
    name="operator",
    help="Day-2 ops for THIS operator stack (federation-license auth).",
)


# ── update: the command a registry's release page and reminder print for an operator ──
# They print `tp update --apply --to-version <v>` (release_channel_checker.rollout_command), and the umbrella had only
# `tp operator update` (CB-342). This IS that command: its arguments go to the operator app as `update ...`. The global
# options (--operator, --yes, --json ...) stay where they are: `tp operator --operator X update ...`.
@umbrella.command(name="update", help="The same as `tp operator update` (the command a registry's release page prints).",
                  context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []})
def update_alias(ctx: typer.Context) -> None:
    from typer.main import get_command
    get_command(operator_app).main(args=["update", *ctx.args], prog_name="tp operator", standalone_mode=True)


# ── mcp sub-typer — exposes the CLI verbs as MCP tools for Claude Code ──
# Strategy: PRODUCTION_DOCS/ROADMAP/Operator_MCP_Server_Strategy.md
umbrella.add_typer(
    mcp_app,
    name="mcp",
    help="MCP server (stdio transport) — expose CLI verbs as MCP tools for Claude Code / LLM control.",
)


# ── developer sub-typer — stub for v1.0 ─────────────────────
developer = typer.Typer(
    name="developer",
    help=(
        "Developer-tier ops: list your agents, check balances, view apps.\n\n"
        "Auth: dev JWT (interactive password prompt OR --api-key flag).\n"
        "v1.0 ships a `ping` stub; full command surface lands in follow-up."
    ),
    no_args_is_help=True,
)
umbrella.add_typer(developer, name="developer")


@developer.command(name="ping", help="Verify the developer sub-typer is reachable.")
def developer_ping() -> None:
    """Stub command — confirms `tp developer` is wired."""
    typer.echo("tp developer: reachable. Full command surface ships in v1.1.")
    typer.echo("Auth model: dev JWT (not federation-license-key).")
    typer.echo("Coming soon: agent list, agent balance, agent fund, my-apps, etc.")


@developer.command(name="version", help="Print version info for the developer sub-typer.")
def developer_version() -> None:
    typer.echo(f"tp developer {__version__} (schema {__schema_version__}) — stub v1.0")


# ── admin sub-typer — stub for v1.0 ─────────────────────────
admin = typer.Typer(
    name="admin",
    help=(
        "Admin-tier ops (Commander only): treasury, issuance, federation, governance.\n\n"
        "Auth: dev JWT with admin sub-flag (admin_treasury / admin_federation / etc.).\n"
        "v1.0 ships a `ping` stub; full command surface lands in follow-up."
    ),
    no_args_is_help=True,
)
umbrella.add_typer(admin, name="admin")


@admin.command(name="ping", help="Verify the admin sub-typer is reachable.")
def admin_ping() -> None:
    """Stub command — confirms `tp admin` is wired."""
    typer.echo("tp admin: reachable. Full command surface ships in v1.1.")
    typer.echo("Auth model: dev JWT with admin_* sub-flag.")
    typer.echo("Coming soon: treasury issuance, federation licenses, eigentrust epoch.")


@admin.command(name="version", help="Print version info for the admin sub-typer.")
def admin_version() -> None:
    typer.echo(f"tp admin {__version__} (schema {__schema_version__}) — stub v1.0")


# ── Top-level umbrella version ──────────────────────────────
@umbrella.command(name="version", help="Print umbrella CLI version + persona list.")
def umbrella_version() -> None:
    typer.echo(f"tp {__version__} (schema {__schema_version__})")
    typer.echo("Personas wired:")
    typer.echo("  operator   — federation-license-key auth (FULL surface, 14 commands)")
    typer.echo("  developer  — dev JWT auth (STUB — ping only)")
    typer.echo("  admin      — admin-flagged dev JWT (STUB — ping only)")
