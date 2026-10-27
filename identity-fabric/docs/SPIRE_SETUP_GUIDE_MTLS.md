# SPIRE Setup Guide for AgentVault Identity Fabric with mTLS Integration

> ⚠️ **MVP / demo guide — NOT the production scheme.** This guide uses **join-token** node attestation
> and a dummy upstream CA. The real production identity fabric uses **x509pop** node attestation (no join
> tokens) and a SPIRE-self-signed CA; nginx mTLS sidecars terminate TLS using a SPIRE SVID written to disk
> by a `cert-writer` sidecar. For a from-source operator, follow
> **[`PUBLIC_DOCS/OPERATOR_SETUP_MANUAL.md`](../../PUBLIC_DOCS/OPERATOR_SETUP_MANUAL.md) §5**; treat this
> file as conceptual background only.

This guide provides step-by-step instructions for setting up SPIFFE/SPIRE as the foundational layer of the AgentVault Identity Fabric, including mTLS configuration for TEG Core Service and Registry Backend.

## Prerequisites

- Docker and Docker Compose installed
- OpenSSL (for generating dummy CA certificates)
- Basic understanding of SPIFFE concepts (SPIFFE IDs, SVIDs, Workload API)

## Architecture Overview

```
┌─────────────────────┐
│   SPIRE Server      │
│  (Trust Domain:     │
│  agentvault.com)    │
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
     ┌─────┴─────┬────────────┐
     │           │            │
┌────▼───┐  ┌───▼────┐  ┌────▼────┐
│  TEG   │  │Registry│  │ Sample  │
│  Core  │  │Backend │  │Workload │
│(Server)│  │(Client)│  │         │
└────────┘  └────────┘  └─────────┘
  mTLS        mTLS
  Server      Client
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

### 2.3 Generate Agent Join Token

Before the agent can attest to the server, we need to create a join token:

```bash
# Generate a join token for the agent
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server token generate \
    -spiffeID spiffe://agentvault.com/spire-agent \
    -ttl 3600
```

Copy the generated token and use it to join the agent:

```bash
# Set the join token as environment variable
export SPIRE_AGENT_JOIN_TOKEN="<generated-token>"

# Restart the agent with the token
docker-compose -f docker-compose.spire.yml restart spire-agent
```

## Step 3: Register AgentVault Services

### 3.1 Register TEG Core Service

The TEG Core Service acts as an mTLS server:

```bash
# Register TEG Core Service
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/teg-core \
    -selector docker:label:com.agentvault.service:teg-core \
    -ttl 3600
```

### 3.2 Register Registry Backend

The Registry Backend acts as an mTLS client when connecting to TEG:

```bash
# Register Registry Backend
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/registry-backend \
    -selector docker:label:com.agentvault.service:registry-backend \
    -ttl 3600
```

### 3.3 Register Sample Workload (Optional)

```bash
# Register based on Unix UID selector (UID 1000 = agentvault user in container)
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/sample-workload \
    -selector unix:uid:1000 \
    -ttl 3600
```

### 3.4 List Registered Entries

Verify all workload registrations:

```bash
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry show
```

## Step 4: Run AgentVault Services with mTLS

### 4.1 Use the Full Stack Compose File

A complete Docker Compose file is provided that includes all services:

```bash
# Start all services including databases
docker-compose -f docker-compose.full.yml up -d
```

This starts:
- SPIRE Server and Agent
- TEG Core Service (with mTLS server)
- Registry Backend (with mTLS client)
- PostgreSQL databases for both services
- Optional sample workload

### 4.2 Initialize Databases

For TEG Core Service:
```bash
# Run migrations
docker exec agentvault-teg-core poetry run alembic upgrade head

# Initialize with treasury tokens
docker exec agentvault-teg-core poetry run python scripts/initialize_db.py
docker exec agentvault-teg-core poetry run python scripts/issue_initial_tokens.py \
    did:agentvault:teg_system_treasury 10000.0
```

For Registry Backend:
```bash
# Run migrations
docker exec agentvault-registry-backend poetry run alembic upgrade head
```

### 4.3 Verify mTLS Configuration

Check TEG Core Service:
```bash
# Should show mtls_enabled: true
curl http://localhost:8001/health
```

Check Registry Backend:
```bash
# Should show mtls_enabled: true
curl http://localhost:8000/health
```

## Step 5: Testing mTLS Communication

### 5.1 Test Direct TEG API Access (Should Fail)

Without a client certificate, direct access should be rejected:

```bash
# This should fail with SSL error
curl https://localhost:8001/api/v1/token/fee-config
```

### 5.2 Test via Registry Backend (Should Succeed)

Access TEG through the Registry which has proper mTLS credentials:

```bash
# Get auth token for Registry
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass"}' \
  | jq -r '.access_token')

# Access TEG via Registry proxy (uses mTLS internally)
curl http://localhost:8000/api/v1/teg/fee-config \
  -H "Authorization: Bearer $TOKEN"
```

### 5.3 Monitor SVID Activity

Watch SVID fetching and renewal:

```bash
# TEG Core Service logs
docker logs agentvault-teg-core | grep SVID

# Registry Backend logs  
docker logs agentvault-registry-backend | grep SVID
```

## Step 6: Verification and Testing

### 6.1 Verify SVID Issuance

Check that workloads successfully obtained their identities:

```bash
# Check SPIRE Agent attestation status
docker exec agentvault-spire-agent \
    /opt/spire/bin/spire-agent api fetch x509 \
    -socketPath /opt/spire/sockets/agent.sock
```

### 6.2 Health Check Endpoints

Verify service health via HTTP endpoints:

```bash
# SPIRE Server health
curl http://localhost:8080/live
curl http://localhost:8080/ready

# SPIRE Agent health  
curl http://localhost:8082/live
curl http://localhost:8082/ready

# TEG Core Service health (with mTLS info)
curl http://localhost:8001/health

# Registry Backend health (with mTLS info)
curl http://localhost:8000/health
```

## Troubleshooting

### Common Issues and Solutions

1. **Agent fails to join**: Ensure the join token is valid and not expired
2. **Workload can't fetch SVID**: Check that the workload registration selectors match
3. **Socket permission errors**: Verify volume mounts and permissions
4. **Certificate errors**: Check that the dummy CA was generated correctly
5. **mTLS connection failures**: Ensure both services have valid SVIDs

### Debug Commands

```bash
# View detailed SPIRE Server configuration
docker exec agentvault-spire-server cat /opt/spire/conf/server.conf

# Check SPIRE Agent attestation
docker exec agentvault-spire-agent \
    /opt/spire/bin/spire-agent api fetch x509 \
    -socketPath /opt/spire/sockets/admin.sock -write /tmp/

# List all registration entries with details
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry show -selector

# Check container labels
docker inspect agentvault-teg-core | jq '.[0].Config.Labels'
```

## Clean Up

To stop and remove all containers and volumes:

```bash
docker-compose -f docker-compose.full.yml down -v
```

## Production Considerations

For production deployment:

1. **Proper CA**: Replace self-signed CA with production PKI
2. **Attestation**: Use platform-specific attestors (K8s, AWS, etc.)
3. **Key Rotation**: Configure appropriate SVID TTLs and rotation
4. **Monitoring**: Set up metrics and alerting for SPIRE components
5. **High Availability**: Deploy SPIRE Server in HA configuration
6. **Network Security**: Implement proper network segmentation
7. **Audit Logging**: Enable comprehensive audit logs

## Next Steps

- Implement workload attestation for additional AgentVault components
- Configure federation with external trust domains
- Set up SVID rotation monitoring
- Implement authorization policies based on SPIFFE IDs
- Extend mTLS to all inter-service communications
