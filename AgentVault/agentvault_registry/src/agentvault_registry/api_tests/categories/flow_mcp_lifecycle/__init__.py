"""flow_mcp_lifecycle — phase 1 MCP tester (2026-05-25).

Walks the live MCP `tools/list` and exercises every tool via JSON-RPC,
falling through to DEFAULT_CONTRACT when no explicit contract exists.

Reuses the API-tester engine's existing infrastructure:
  • multiframe_helpers — exec_in_container, _split_http_body_code, SANDBOX_TARGET
  • sandbox-credentials → fresh sentinel agent + dev JWT
  • flow-values → cross-tool shared state
  • runner + result archive — same pass-rate plumbing

See:
  • PLAN_2026-05-25_MCP_TESTER_REUSE_API_ENGINE.md — architecture
  • contracts/mcp_contracts.py — the contract registry
"""
