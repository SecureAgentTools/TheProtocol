# JWT-SVID Quick Reference Guide

## For Registry Backend Developers

### Acquiring JWT-SVIDs

```python
from agentvault_registry.core.jwt_svid_provider import acquire_agent_jwt_svid

# In your endpoint handler
async def your_teg_endpoint(current_developer: Developer):
    # Get JWT-SVID for the authenticated user
    jwt_svid = await acquire_agent_jwt_svid(
        agent_email=current_developer.email,
        audience="spiffe://agentvault.com/service/teg-core"
    )
    
    # Use in TEG API call
    response = await client.get(
        "https://teg-core:8001/api/v1/token/balance",
        headers={"Authorization": f"Bearer {jwt_svid}"}
    )
```

### Configuration

```bash
# Required environment variables
SPIFFE_ENDPOINT_SOCKET=unix:///spire-agent-socket/agent.sock
TEG_API_BASE_URL=https://teg-core:8001

# Development fallback (MVP only)
JWT_SVID_SIGNING_KEY=mvp-testing-key-replace-in-production
```

## For TEG Core Service Developers

### Using JWT-SVID Authentication

```python
from fastapi import Depends
from typing import Annotated
from teg_core_service.core.jwt_svid import verify_jwt_svid

@router.get("/protected-endpoint")
async def protected_endpoint(
    agent_id: Annotated[str, Depends(verify_jwt_svid)],
    db: Session = Depends(get_db)
):
    # agent_id is automatically extracted from JWT-SVID
    # Format: "agent_user_at_example_dot_com"
    return {"agent_id": agent_id}
```

### JWT-SVID Structure

```json
{
  "aud": ["spiffe://agentvault.com/service/teg-core"],
  "exp": 1234567890,  // 5 minutes from issuance
  "iat": 1234567590,
  "iss": "spiffe://agentvault.com",
  "sub": "spiffe://agentvault.com/agent/user_at_example_dot_com"
}
```

## SPIFFE ID Formats

### Service Identities (X.509 SVIDs)
- Registry Backend: `spiffe://agentvault.com/service/registry-backend`
- TEG Core: `spiffe://agentvault.com/service/teg-core`

### Agent Identities (JWT-SVIDs)
- Pattern: `spiffe://agentvault.com/agent/{safe_email}`
- Example: `spiffe://agentvault.com/agent/user_at_example_dot_com`
- Conversion: `@` → `_at_`, `.` → `_dot_`

## Testing JWT-SVID Flow

### 1. Quick Health Check
```bash
# Check JWT-SVID validator status
curl https://localhost:8001/health | jq '.checks.jwt_svid_validator'
```

### 2. Test Authentication Flow
```bash
# Run the comprehensive test suite
cd identity-fabric
python test_jwt_svid_e2e.py
```

### 3. Debug JWT-SVID Issues
```bash
# Check if Registry can acquire JWT-SVIDs
docker logs agentvault-registry-backend | grep JWT-SVID

# Check TEG validation
docker logs agentvault-teg-core | grep "JWT-SVID validation"

# Decode a JWT-SVID (for debugging)
echo $JWT_SVID | cut -d. -f2 | base64 -d | jq
```

## Common Issues & Solutions

### "Failed to acquire authentication token"
- Check SPIRE Agent is running: `docker ps | grep spire-agent`
- Verify socket mount: `docker inspect agentvault-registry-backend | grep -A2 spire`
- Check agent registration: `docker exec agentvault-spire-server spire-server entry show`

### "Invalid authentication token" from TEG
- Verify audience matches exactly: `spiffe://agentvault.com/service/teg-core`
- Check token expiration (5-minute TTL)
- Ensure trust bundles are synchronized

### "JWT-SVID validation failed"
- Check SPIRE Server is healthy
- Verify pySpiffe is installed: `pip show pyspiffe`
- Check trust domain consistency

## Security Best Practices

1. **Never cache JWT-SVIDs** - Always acquire fresh tokens
2. **Validate audience** - Ensure tokens are for your service
3. **Check expiration** - Tokens expire in 5 minutes
4. **Log authentication events** - Track all auth successes/failures
5. **Use mTLS** - Always combine with service-to-service mTLS

## Monitoring

### Key Metrics to Track
- JWT-SVID acquisition latency
- Validation success/failure rate
- Token expiration events
- Agent authentication patterns

### Log Queries
```bash
# Successful authentications
grep "JWT-SVID.*Success" /var/log/agentvault/*.log

# Failed authentications
grep "JWT-SVID.*fail" /var/log/agentvault/*.log

# Performance metrics
grep "JWT-SVID.*latency" /var/log/agentvault/*.log
```

## Migration from Simple Auth

### Before (Simple Bearer Token)
```python
def verify_agent_token(credentials: HTTPAuthorizationCredentials) -> str:
    token = credentials.credentials
    if not token.startswith("agent_"):
        raise HTTPException(status_code=401)
    return token
```

### After (JWT-SVID)
```python
def verify_jwt_svid(credentials: HTTPAuthorizationCredentials) -> str:
    token = credentials.credentials
    claims = validator.validate_jwt_svid(token)
    agent_spiffe_id = claims["sub"]
    # Convert SPIFFE ID to agent ID
    return extract_agent_id(agent_spiffe_id)
```

## Production Checklist

- [ ] SPIRE Server configured with production CA
- [ ] Agent registration process automated
- [ ] JWT-SVID TTL appropriate for use case
- [ ] Monitoring and alerting configured
- [ ] Audit logging enabled
- [ ] Performance metrics tracked
- [ ] Disaster recovery plan for SPIRE
- [ ] Token rotation tested
