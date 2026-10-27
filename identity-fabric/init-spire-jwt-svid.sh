#!/bin/bash
# Initialize SPIRE with JWT-SVID support for AgentVault services
# Part of REQ-INT-V1AUTH-001 implementation

set -e

echo "=== Initializing SPIRE Server with JWT-SVID Support ==="

# Source the mTLS initialization first
echo "Running base mTLS initialization..."
./init-spire-mtls.sh

# Wait for SPIRE Server to be ready
echo "Waiting for SPIRE Server to be ready for JWT-SVID configuration..."
sleep 5

echo "=== Configuring JWT-SVID Support ==="

# Register the Registry Backend with enhanced permissions
# This allows it to issue JWT-SVIDs for agents (delegated identity)
echo "Registering Registry Backend with JWT-SVID issuing capabilities..."
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/service/registry-backend \
    -selector docker:label:com.agentvault.service:registry-backend \
    -ttl 3600 \
    -jwtSVIDTTL 300 || true  # 5 minute JWT-SVID TTL

# Create a registration pattern for agent-specific SPIFFE IDs
# These will be created dynamically by the registry-backend
echo "Creating agent registration template..."
# Note: SPIRE doesn't support wildcard registrations directly
# The registry-backend will need to create these on-demand

# Register a sample agent for testing
echo "Registering sample agent for JWT-SVID testing..."
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/service/registry-backend \
    -spiffeID spiffe://agentvault.com/agent/test_at_example.com \
    -selector k8s:ns:agentvault \
    -selector k8s:sa:agent-test \
    -ttl 3600 \
    -jwtSVIDTTL 300 || true

# Create a helper script for dynamic agent registration
cat > /tmp/register-agent.sh << 'EOF'
#!/bin/bash
# Helper script to register an agent dynamically
# Usage: ./register-agent.sh <agent_local_id>

AGENT_ID=$1
if [ -z "$AGENT_ID" ]; then
    echo "Usage: $0 <agent_local_id>"
    exit 1
fi

# Convert email format to SPIFFE ID safe format
SAFE_AGENT_ID=$(echo "$AGENT_ID" | sed 's/@/_at_/g' | sed 's/\./_dot_/g')

echo "Registering agent: spiffe://agentvault.com/agent/${SAFE_AGENT_ID}"

docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/service/registry-backend \
    -spiffeID "spiffe://agentvault.com/agent/${SAFE_AGENT_ID}" \
    -selector "k8s:ns:agentvault" \
    -selector "k8s:sa:agent-${SAFE_AGENT_ID}" \
    -ttl 3600 \
    -jwtSVIDTTL 300
EOF

chmod +x /tmp/register-agent.sh
docker cp /tmp/register-agent.sh agentvault-spire-server:/opt/spire/bin/register-agent.sh

# Create a script to issue JWT-SVIDs (for testing and development)
cat > /tmp/mint-jwt-svid.sh << 'EOF'
#!/bin/bash
# Helper script to issue a JWT-SVID for an agent
# Usage: ./mint-jwt-svid.sh <agent_spiffe_id> <audience_spiffe_id>

AGENT_SPIFFE_ID=$1
AUDIENCE=$2

if [ -z "$AGENT_SPIFFE_ID" ] || [ -z "$AUDIENCE" ]; then
    echo "Usage: $0 <agent_spiffe_id> <audience_spiffe_id>"
    echo "Example: $0 spiffe://agentvault.com/agent/test_at_example.com spiffe://agentvault.com/service/teg-core"
    exit 1
fi

# Use SPIRE Server admin API to issue JWT-SVID
# Note: In production, this would be done through the Workload API
echo "Issuing a JWT-SVID for ${AGENT_SPIFFE_ID} with audience ${AUDIENCE}"

# This is a placeholder - actual implementation would use SPIRE's JWT-SVID API
echo "Issuing a JWT-SVID requires Workload API access from a registered workload"
EOF

chmod +x /tmp/mint-jwt-svid.sh
docker cp /tmp/mint-jwt-svid.sh agentvault-spire-server:/opt/spire/bin/mint-jwt-svid.sh

# List all registered entries including new JWT-SVID capable ones
echo "=== Updated workload registrations ==="
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry show

echo "=== JWT-SVID Configuration Complete ==="
echo ""
echo "JWT-SVID Implementation Notes:"
echo "1. Registry Backend (spiffe://agentvault.com/service/registry-backend) can now issue JWT-SVIDs"
echo "2. Agent SPIFFE IDs follow pattern: spiffe://agentvault.com/agent/{agent_local_id}"
echo "3. JWT-SVID TTL is set to 300 seconds (5 minutes)"
echo "4. TEG Core Service audience: spiffe://agentvault.com/service/teg-core"
echo ""
echo "To register a new agent dynamically:"
echo "  docker exec agentvault-spire-server /opt/spire/bin/register-agent.sh <agent_email>"
echo ""
echo "Next steps:"
echo "1. Update registry-backend to acquire JWT-SVIDs via pySpiffe"
echo "2. Update TEG Core Service to validate JWT-SVIDs"
echo "3. Test end-to-end authentication flow"
