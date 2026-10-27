package agentvault.agent

# Mirrors security.py:get_current_agent
# Sandbox-only shadow-mode since 2026-04-30.

import future.keywords.if

default allow = false

# Agent JWT is valid only when the agent row exists and its status is
# neither "suspended" nor "revoked".
allow if {
    input.agent_exists == true
    input.status != "suspended"
    input.status != "revoked"
}
