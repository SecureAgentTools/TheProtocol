#!/bin/bash
# Initialize SPIRE with workload registrations for AgentVault services

set -e

echo "=== Initializing SPIRE Server and Agent ==="

# Wait for SPIRE Server to be ready
echo "Waiting for SPIRE Server to be ready..."
sleep 10

# Generate agent join token
echo "Generating agent join token..."
AGENT_TOKEN=$(docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server token generate \
    -spiffeID spiffe://agentvault.com/spire-agent \
    -ttl 3600 | awk '{print $2}')

echo "Agent join token: $AGENT_TOKEN"

# Set the token and restart agent
export SPIRE_AGENT_JOIN_TOKEN=$AGENT_TOKEN
docker-compose -f docker-compose.spire.yml restart spire-agent

# Wait for agent to join
echo "Waiting for agent to join..."
sleep 10

# Register workloads
echo "=== Registering workloads ==="

# Register TEG Core Service
echo "Registering TEG Core Service..."
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/teg-core \
    -selector docker:label:com.agentvault.service:teg-core \
    -ttl 3600

# Register Registry Backend
echo "Registering Registry Backend..."
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/registry-backend \
    -selector docker:label:com.agentvault.service:registry-backend \
    -ttl 3600

# Register Central Registry (for health checks)
echo "Registering Central Registry for health checks..."
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/central-registry \
    -selector docker:label:com.agentvault.service:central-registry \
    -ttl 3600 || true

# Register Central Registry Health Checker (specific SPIFFE ID)
echo "Registering Central Registry Health Checker..."
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/central-registry-health-checker \
    -selector docker:label:com.agentvault.service:central-registry \
    -ttl 3600 || true

# Register Sample Workload (if needed)
echo "Registering Sample Workload..."
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/sample-workload \
    -selector unix:uid:1000 \
    -ttl 3600 || true

# List all registered entries
echo "=== Registered workloads ==="
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry show

echo "=== SPIRE initialization complete ==="
echo ""
echo "To start all services with mTLS:"
echo "  docker-compose -f docker-compose.full.yml up -d"
echo ""
echo "To check service health:"
echo "  curl http://localhost:8000/health  # Registry"
echo "  curl https://localhost:8001/health --insecure  # TEG (with mTLS)"
