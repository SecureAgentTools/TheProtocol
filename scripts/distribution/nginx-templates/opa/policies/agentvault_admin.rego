package agentvault.admin

# Mirrors security.py:require_admin_flag._check
# Sandbox-only shadow-mode (since 2026-04-30). Until OPA_ENFORCE=true on the
# registry side, this policy is observed but not enforced; mismatches are
# logged + counted as opa_decisions_total{source="mismatch"}.

import future.keywords.if

default allow = false

# must_change_password gate — operator bootstrap denial dominates everything.
allow = false if {
    input.must_change_password == true
}

# Legacy super-flag: is_admin grants every flag check (post-bootstrap-gate).
allow if {
    input.is_admin == true
    not input.must_change_password
}

# Granular per-flag check (post-bootstrap-gate).
# input.flag is the requested flag name; input.admin_flags is a per-developer
# {flag_name: bool} object containing all 5 sub-admin flags.
allow if {
    input.admin_flags[input.flag] == true
    not input.must_change_password
}
