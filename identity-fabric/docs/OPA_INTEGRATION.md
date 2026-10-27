# OPA Policy Integration - Operation GhostNet

## Overview

The Open Policy Agent (OPA) has been successfully integrated into the AgentVault Identity Fabric, providing fine-grained authorization decisions based on SPIFFE identities. This integration completes the Zero-Trust architecture by adding policy enforcement to our cryptographic identity layer.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Sample         │────▶│  SPIRE Agent    │────▶│  SPIRE Server   │
│  Workload       │     │                 │     │                 │
└────────┬────────┘     └─────────────────┘     └─────────────────┘
         │                                                 │
         │ JWT-SVID                                       │
         ▼                                                │
┌─────────────────┐                              Trust Bundle
│      OPA        │◀──────────────────────────────────────┘
│ Policy Engine   │
└─────────────────┘
```

## Components

### 1. OPA Service
- **Container**: `agentvault-opa`
- **Image**: `openpolicyagent/opa:0.61.0`
- **Port**: 8181
- **Policies**: Mounted from `./policies` directory

### 2. Policy Definition
The policy is defined in `policies/workload_access.rego`:
```rego
package workload.access

default allow = false

allow {
    input.sub == "spiffe://agentvault.com/sample-workload"
}
```

### 3. Enhanced Sample Workload
The sample workload now:
1. Fetches its JWT-SVID from SPIRE
2. Extracts JWT claims
3. Queries OPA for authorization decision
4. Logs the policy result

## Usage

### Start the Stack
```bash
# Initialize SPIRE with JWT-SVID support
make init-jwt-svid

# Start all services including OPA
make up

# Check service status
make status
```

### Test Policy Integration
```bash
# Run the policy test
make test-policy

# View detailed workload logs
make workload-logs

# Monitor OPA decisions
make opa-logs
```

## Policy Query Flow

1. **Workload starts** and fetches its SPIFFE identity (X.509 and JWT SVIDs)
2. **JWT claims extracted** from the JWT-SVID token
3. **OPA query** sent to `http://opa:8181/v1/data/workload/access/allow`
4. **Policy evaluation** based on the SPIFFE ID in the `sub` claim
5. **Decision logged** as either `[ALLOW]` or `[DENY]`

## Extending Policies

To add more sophisticated policies:

1. Edit `policies/workload_access.rego`
2. Add new rules based on:
   - SPIFFE ID patterns
   - JWT claims (audience, expiry, custom claims)
   - Time-based access
   - Resource-specific permissions

Example enhanced policy:
```rego
package workload.access

import time.now_ns

default allow = false

# Allow specific workloads
allow {
    input.sub == "spiffe://agentvault.com/sample-workload"
}

# Allow agents with valid expiry
allow {
    startswith(input.sub, "spiffe://agentvault.com/agent/")
    input.exp > time.now_ns() / 1000000000
}

# Resource-specific access
allow_read {
    allow
    input.action == "read"
}

allow_write {
    input.sub == "spiffe://agentvault.com/admin"
    input.action == "write"
}
```

## Debugging

### Check OPA Health
```bash
curl http://localhost:8181/health
```

### Test Policy Manually
```bash
curl -X POST http://localhost:8181/v1/data/workload/access/allow \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "sub": "spiffe://agentvault.com/sample-workload"
    }
  }'
```

### View Policy Compilation
```bash
docker exec agentvault-opa opa eval -d /policies 'data.workload.access.allow'
```

## Next Steps

1. **Bundle Management**: Implement OPA bundle service for dynamic policy updates
2. **Decision Logging**: Configure OPA decision logs for audit trail
3. **Performance**: Add policy caching and optimization
4. **Integration**: Connect OPA to service mesh for request-level authorization

## Victory Conditions Met ✓

- [x] OPA service integrated into docker-compose.spire.yml
- [x] Rego policy created for SPIFFE ID validation
- [x] Sample workload queries OPA for authorization
- [x] Makefile updated with test-policy command
- [x] All services start successfully
- [x] Policy decisions logged clearly

The nervous system is complete. The identity fabric now has both identity (SPIFFE) and authorization (OPA) layers working in harmony.
