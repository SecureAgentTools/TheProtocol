package workload.access

# §MONITORING S0 (2026-09-28): Rego v1 needs `if` before a rule body (OPA 1.x); the import keeps 0.61.0 parsing it the same way
import future.keywords.if

# Default deny
default allow = false

# Allow access only if the JWT subject matches the expected SPIFFE ID
allow if {
    input.sub == "spiffe://agentvault.com/sample-workload"
}

# Debug rule to help troubleshoot (can be removed in production)
debug_info = {
    "received_subject": input.sub,
    "expected_subject": "spiffe://agentvault.com/sample-workload",
    "all_claims": input
}
