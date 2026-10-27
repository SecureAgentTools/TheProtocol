# SPIRE Setup Guide for AgentVault Identity Fabric with JWT-SVID Support

> ⚠️ **MVP / demo guide — NOT the production scheme.** This guide uses **join-token** node attestation
> and **k8s** workload selectors. Production uses **x509pop** node attestation (no join tokens) and pure
> **Docker** label selectors (`docker:label:com.theprotocol.agent-did:<did>`), with per-agent entries
> created at runtime by the registry. For a from-source operator, follow
> **[`PUBLIC_DOCS/OPERATOR_SETUP_MANUAL.md`](../../PUBLIC_DOCS/OPERATOR_SETUP_MANUAL.md) §5**; treat this
> file as conceptual background only.

This guide provides comprehensive instructions for setting up SPIFFE/SPIRE as the foundational layer of the AgentVault Identity Fabric, including JWT-SVID configuration for agent authentication.

## Prerequisites

- Docker and Docker Compose installed
- OpenSSL (for generating dummy CA certificates)
- Basic understanding of SPIFFE concepts (SPIFFE IDs, SVIDs, Workload API)
- Python 3.10+ with pySpiffe for testing

## Architecture Overview

```
┌─────────────────────┐
│   SPIRE Server      │
│  (Trust Domain:     │
│  agentvault.com)    │
│  - X.509 SVIDs     │
│  - JWT-SVIDs        │
└──────────┬──────────┘
           │ Registration API
           │ (port 8081)
┌──────────▼──────────┐
│   SPIRE Agent       │
│  (Node Attestor:    │
│   join_token)       │
└──────────┬──────────┘
           │ Workload API
           │ (Unix Socket)
           │
    ┌──────┴──────┬────────────────┐
    ▼             ▼                ▼
┌────────┐  ┌─────────────┐  ┌────────────┐
│Registry │  │TEG Core     │  │Agent       │
│Backend  │  │Service      │  │Identities  │
│X.509 +  │  │X.509 +      │  │JWT-SVIDs   │
│JWT Mint │  │JWT Validate │  │            │
└────────┘  └─────────────┘  └────────────┘
```

## Step 1: Prepare SPIRE Server

### 1.1 Generate Dummy Upstream CA (MVP only)

Navigate to the SPIRE server directory and generate the dummy CA:

```bash
cd identity-fabric/spire-server
chmod +x generate_dummy_ca.sh
./generate_dummy_ca.sh
```

**Note**: This creates a self-signed CA for MVP purposes. In production, use a proper upstream CA or integrate with your PKI infrastructure.

### 1.2 Create Initial Bundle

Create an empty bundle file that will be populated by the SPIRE Server:

```bash
touch spire-server/bundle.crt
```

## Step 2: Start SPIRE Infrastructure

### 2.1 Start SPIRE Server and Agent

```bash
cd identity-fabric
docker-compose -f docker-compose.spire.yml up -d spire-server spire-agent
```

### 2.2 Verify Services are Running

Check that both services are healthy:

```bash
# Check container status
docker-compose -f docker-compose.spire.yml ps

# Check SPIRE Server logs
docker-compose -f docker-compose.spire.yml logs spire-server

# Check SPIRE Agent logs  
docker-compose -f docker-compose.spire.yml logs spire-agent
```

### 2.3 Initialize with mTLS and JWT-SVID Support

Run the enhanced initialization script:

```bash
# Initialize base mTLS support
./init-spire-mtls.sh

# Add JWT-SVID capabilities
./init-spire-jwt-svid.sh
```

## Step 3: Configure JWT-SVID Support

### 3.1 Register Services with JWT-SVID Capabilities

```bash
# Register Registry Backend with JWT-SVID minting capability
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/registry-backend \
    -selector docker:label:com.agentvault.service:registry-backend \
    -ttl 3600 \
    -jwtSVIDTTL 300

# Register TEG Core Service (JWT-SVID audience)
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/teg-core \
    -selector docker:label:com.agentvault.service:teg-core \
    -ttl 3600
```

### 3.2 Agent Registration Pattern

For each v1.0.0 agent that needs TEG access:

```bash
# Register an agent (example)
AGENT_EMAIL="user@example.com"
SAFE_AGENT_ID=$(echo "$AGENT_EMAIL" | sed 's/@/_at_/g' | sed 's/\./_dot_/g')

docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/service/registry-backend \
    -spiffeID "spiffe://agentvault.com/agent/${SAFE_AGENT_ID}" \
    -selector "k8s:ns:agentvault" \
    -selector "k8s:sa:agent-${SAFE_AGENT_ID}" \
    -ttl 3600 \
    -jwtSVIDTTL 300
```

### 3.3 Verify JWT-SVID Configuration

```bash
# List all entries with JWT-SVID support
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry show | grep -B2 -A2 jwtSVIDTTL
```

## Step 4: Test JWT-SVID Flow

### 4.1 Test JWT-SVID Acquisition

Create a test script to verify JWT-SVID acquisition:

```python
# test_jwt_svid.py
from pyspiffe import workload_api
import json

# Connect to Workload API
with workload_api.WorkloadApiClient() as client:
    # Fetch JWT-SVID
    jwt_svid = client.fetch_jwt_svid(
        audiences=["spiffe://agentvault.com/service/teg-core"]
    )
    
    print(f"JWT-SVID Token: {jwt_svid.token[:50]}...")
    print(f"SPIFFE ID: {jwt_svid.spiffe_id}")
    print(f"Audiences: {jwt_svid.audiences}")
```

### 4.2 Test JWT-SVID Validation

```python
# test_jwt_validation.py
from pyspiffe import workload_api
from pyspiffe.bundle import JwtBundle
from pyspiffe.svid import JwtSvid

# Fetch JWT bundle for validation
with workload_api.WorkloadApiClient() as client:
    jwt_bundles = client.fetch_jwt_bundles()
    bundle = jwt_bundles.get("agentvault.com")
    
    # Validate a JWT-SVID
    token = "eyJ0eXAiOiJKV1QiLCJhbGc..."  # Your JWT-SVID
    jwt_svid = JwtSvid.parse_insecure(
        token, 
        ["spiffe://agentvault.com/service/teg-core"]
    )
    
    # Validate signature and claims
    jwt_svid.validate(bundle)
    print(f"Valid JWT-SVID for: {jwt_svid.spiffe_id}")
```

## Step 5: Integration Testing

### 5.1 Start All Services

```bash
# Start full stack with mTLS and JWT-SVID support
docker-compose -f docker-compose.full.yml up -d
```

### 5.2 Test End-to-End Flow

```bash
# 1. Authenticate to Registry
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass"}'

# 2. Get TEG balance (triggers JWT-SVID flow)
curl http://localhost:8000/api/v1/teg/balance \
  -H "Authorization: Bearer <v1-jwt-token>"

# 3. Check logs for JWT-SVID activity
docker logs agentvault-registry-backend | grep JWT-SVID
docker logs agentvault-teg-core | grep JWT-SVID
```

## Step 6: Monitoring and Debugging

### 6.1 Monitor JWT-SVID Issuance

```bash
# Watch SPIRE Server for JWT-SVID requests
docker logs -f agentvault-spire-server | grep -i jwt

# Monitor Registry Backend JWT-SVID acquisition
docker logs -f agentvault-registry-backend | grep -i "jwt-svid"
```

### 6.2 Debug JWT-SVID Issues

```bash
# Check if service can fetch JWT-SVIDs
docker exec agentvault-registry-backend python -c "
from pyspiffe import workload_api
with workload_api.WorkloadApiClient() as client:
    jwt = client.fetch_jwt_svid(['spiffe://agentvault.com/service/teg-core'])
    print(f'Success! Token: {jwt.token[:50]}...')
"

# Verify JWT bundle availability
docker exec agentvault-teg-core python -c "
from pyspiffe import workload_api
with workload_api.WorkloadApiClient() as client:
    bundles = client.fetch_jwt_bundles()
    print(f'Bundles: {list(bundles.keys())}')
"
```

### 6.3 Common JWT-SVID Troubleshooting

1. **"No JWT-SVID for workload"**
   - Check if workload has `jwtSVIDTTL` in registration
   - Verify parent SPIFFE ID can issue JWT-SVIDs

2. **"Invalid audience"**
   - Ensure audience matches TEG Core SPIFFE ID exactly
   - Check for typos in audience configuration

3. **"JWT-SVID expired"**
   - Default TTL is 5 minutes
   - Ensure fresh tokens are acquired for each request

4. **"Failed to validate JWT-SVID"**
   - Check trust bundle synchronization
   - Verify both services use same trust domain

## Security Considerations

### Production Hardening

1. **JWT-SVID TTL**: Keep short (5-10 minutes) for security
2. **Audience Restriction**: Always specify exact audience
3. **No Token Caching**: Acquire fresh for each request in MVP
4. **Audit Logging**: Enable comprehensive JWT-SVID audit logs
5. **Key Rotation**: Implement automatic SPIRE key rotation

### Agent Registration Security

```bash
# Production: Use stricter selectors
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/service/registry-backend \
    -spiffeID "spiffe://agentvault.com/agent/${SAFE_AGENT_ID}" \
    -selector "k8s:ns:agentvault" \
    -selector "k8s:sa:agent-${SAFE_AGENT_ID}" \
    -selector "k8s:pod-label:app:agentvault-agent" \
    -selector "k8s:pod-label:agent-id:${SAFE_AGENT_ID}" \
    -ttl 3600 \
    -jwtSVIDTTL 300
```

## Clean Up

To stop and remove all containers and volumes:

```bash
docker-compose -f docker-compose.full.yml down -v
```

## Next Steps

- Implement dynamic agent registration API
- Add JWT-SVID caching with TTL awareness
- Configure SPIRE federation for multi-region
- Implement custom JWT-SVID claims
- Set up comprehensive audit logging
- Integrate with external IdP for agent registration

## Advanced Configuration

### Custom JWT-SVID Claims (Future)

```hocon
# In server.conf (future enhancement)
jwt_issuer {
    domain = "agentvault.com"
    
    # Custom claims mapping
    custom_claims {
        "agent_tier" = "selector:k8s:pod-label:tier"
        "permissions" = "selector:k8s:pod-label:permissions"
    }
}
```

### Federation Setup (Future)

```bash
# Configure federation with partner domain
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server bundle set \
    -id "spiffe://partner.com" \
    -path /opt/spire/conf/partner-bundle.crt
```

## Summary

This enhanced SPIRE setup provides:

- **X.509 SVIDs** for service-to-service mTLS
- **JWT-SVIDs** for agent authentication
- **Delegated identity** via Registry Backend
- **Short-lived tokens** for security
- **Standard SPIFFE** compliance

The JWT-SVID implementation enables cryptographic agent identity throughout the AgentVault platform while maintaining compatibility with existing v1.0.0 authentication.
