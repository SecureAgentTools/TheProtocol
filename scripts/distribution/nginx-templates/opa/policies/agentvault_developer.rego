package agentvault.developer

# Mirrors security.py:get_current_developer
# Sandbox-only shadow-mode since 2026-04-30.

import future.keywords.if

default allow = false

# Developer JWT is valid only when the developer row exists and the account
# is neither soft-deleted (deleted_at IS NOT NULL) nor admin-suspended.
allow if {
    input.developer_exists == true
    input.is_deleted == false
    input.is_suspended == false
}
