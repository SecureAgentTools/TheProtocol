"""
TheProtocol MCP Server — Exposes registry capabilities as MCP tools.

This module implements the Model Context Protocol (MCP) server for TheProtocol,
enabling Claude Desktop, Claude Code, and any MCP-compatible AI agent to interact
with the sovereign agent registry without requiring knowledge of the A2A protocol.

Architecture:
    - server.py       → FastAPI router with JSON-RPC 2.0 transport
    - auth_bridge.py  → MCP authorization_token → TheProtocol JWT mapping
    - tools_discovery → Tier 1: 5 public discovery tools (no auth)
    - tools_agent     → Tier 2: 5 agent operation tools (agent JWT required)
    - tools_developer → Tier 3: 4 developer operation tools (developer JWT required)

Transport: JSON-RPC 2.0 over HTTP POST at /mcp/rpc
           SSE endpoint at /mcp/sse (for MCP Inspector compatibility)
MCP Methods: initialize, tools/list, tools/call, ping

Usage (Claude Desktop):
    {
      "mcpServers": {
        "theprotocol": {
          "url": "https://api.theprotocol.cloud/mcp/sse",
          "authorization_token": "<developer_jwt>"
        }
      }
    }

Usage (Anthropic API):
    mcp_servers=[{
        "type": "url",
        "url": "https://api.theprotocol.cloud/mcp/sse",
        "name": "theprotocol",
        "authorization_token": "<developer_jwt>"
    }]
"""
