# SPIRE Setup Guide for AgentVault Identity Fabric

> ⚠️ **MVP / demo guide — NOT the production scheme.** This guide uses **join-token** node attestation
> and a dummy upstream CA. The real production identity fabric uses **x509pop** node attestation (no join
> tokens) and a SPIRE-self-signed CA, with workload entries created by the provisioner /
> `register-operator-entries.sh` and per-agent IRONHAND enrollment at runtime. For a from-source operator,
> follow **[`PUBLIC_DOCS/OPERATOR_SETUP_MANUAL.md`](../../PUBLIC_DOCS/OPERATOR_SETUP_MANUAL.md) §5**; treat
> this file as conceptual background only.

This guide provides step-by-step instructions for setting up SPIFFE/SPIRE as the foundational layer of the AgentVault Identity Fabric.

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
┌──────────▼──────────┐
│  Sample Workload    │
│  (Python + pySpiffe)│
│  SPIFFE ID:         │
│  spiffe://agentvault│
│  .com/sample-workload│
└─────────────────────┘
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

## Step 3: Register the Sample Workload

### 3.1 Create Workload Registration Entry

Register the sample workload with SPIRE Server:

```bash
# Register based on Unix UID selector (UID 1000 = agentvault user in container)
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/sample-workload \
    -selector unix:uid:1000 \
    -ttl 3600

# Alternative: Register based on Docker selector
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/sample-workload \
    -selector docker:image_id:$(docker images -q agentvault-sample-workload) \
    -ttl 3600
```

### 3.2 List Registered Entries

Verify the workload registration:

```bash
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry show
```

## Step 4: Run the Sample Workload

### 4.1 Build and Start the Sample Workload

```bash
# Build the sample workload image
docker-compose -f docker-compose.spire.yml build sample-workload

# Start the sample workload
docker-compose -f docker-compose.spire.yml up -d sample-workload
```

### 4.2 Monitor Workload Logs

Watch the sample workload fetch its SVIDs:

```bash
docker-compose -f docker-compose.spire.yml logs -f sample-workload
```

You should see output similar to:

```
sample-workload_1  | 2024-01-20 10:15:23 - agentvault.sample_workload - INFO - Successfully fetched X.509 SVID
sample-workload_1  | 2024-01-20 10:15:23 - agentvault.sample_workload - INFO - SPIFFE ID: spiffe://agentvault.com/sample-workload
sample-workload_1  | 2024-01-20 10:15:23 - agentvault.sample_workload - INFO - Certificate Serial Number: 123456789
sample-workload_1  | 2024-01-20 10:15:23 - agentvault.sample_workload - INFO - Certificate Not After: 2024-01-20 11:15:23
sample-workload_1  | 2024-01-20 10:15:24 - agentvault.sample_workload - INFO - Successfully fetched JWT SVID
sample-workload_1  | 2024-01-20 10:15:24 - agentvault.sample_workload - INFO - JWT SPIFFE ID: spiffe://agentvault.com/sample-workload
```

## Step 5: Verification and Testing

### 5.1 Verify SVID Issuance

Check that the workload successfully obtained its identity:

```bash
# Check SPIRE Agent attestation status
docker exec agentvault-spire-agent \
    /opt/spire/bin/spire-agent api fetch x509 \
    -socketPath /opt/spire/sockets/agent.sock
```

### 5.2 Health Check Endpoints

Verify service health via HTTP endpoints:

```bash
# SPIRE Server health
curl http://localhost:8080/live
curl http://localhost:8080/ready

# SPIRE Agent health  
curl http://localhost:8082/live
curl http://localhost:8082/ready
```

## Troubleshooting

### Common Issues and Solutions

1. **Agent fails to join**: Ensure the join token is valid and not expired
2. **Workload can't fetch SVID**: Check that the workload registration selectors match
3. **Socket permission errors**: Verify volume mounts and permissions
4. **Certificate errors**: Check that the dummy CA was generated correctly

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
```

## Clean Up

To stop and remove all containers and volumes:

```bash
docker-compose -f docker-compose.spire.yml down -v
```

## Next Steps

- Implement workload attestation for actual AgentVault components
- Configure more sophisticated node attestors (K8s, AWS, etc.)
- Integrate with TEG Core Service for agent authentication
- Implement SVID rotation and monitoring
- Set up federation with external trust domains

## Security Considerations

This MVP setup uses several simplifications that should be addressed for production:

1. **Self-signed CA**: Replace with proper PKI infrastructure
2. **Join Token Attestor**: Consider more secure attestors for production
3. **Default TTLs**: Adjust certificate and token lifetimes based on security requirements
4. **Network Isolation**: Implement proper network segmentation
5. **Persistent Storage**: Use external storage for SPIRE Server data in production
