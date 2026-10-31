"""MCP protocol-version negotiation, one rule for the public and the admin server (§EXTTEST run 2, 2026-10-31).

Measured from an outside client: EU answered `initialize` with protocolVersion 2025-11-25 to a client that asked for
2025-06-18, because both servers returned their own constant whatever was asked. The lifecycle rule of the MCP
specification: a server that supports the requested version answers with that same version; otherwise it answers with
another version it supports (the latest), and the client decides whether to go on. A client pinned to an older
version, which this server serves with the same messages (newer fields are additive), therefore kept a reason to
disconnect.
"""
from typing import Any

SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]


def negotiate_protocol_version(params: Any) -> str:
    """The version `initialize` answers: the client's own when this server supports it, else the latest."""
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION
