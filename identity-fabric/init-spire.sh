#!/bin/bash
# Initialize SPIRE infrastructure for AgentVault Identity Fabric

set -e

echo "=== AgentVault Identity Fabric Initialization ==="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if running from correct directory
if [ ! -f "docker-compose.spire.yml" ]; then
    echo -e "${RED}Error: Must run from identity-fabric directory${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Generating dummy CA for MVP...${NC}"
cd spire-server
if [ ! -f "dummy_upstream_ca.key" ]; then
    openssl req -x509 -newkey rsa:2048 -days 365 -keyout dummy_upstream_ca.key -out dummy_upstream_ca.crt -nodes \
        -subj "/C=US/ST=CA/L=San Francisco/O=AgentVault/OU=Identity/CN=AgentVault Dummy CA" 2>/dev/null
    echo -e "${GREEN}✓ Dummy CA generated${NC}"
else
    echo -e "${GREEN}✓ Dummy CA already exists${NC}"
fi

# Create empty bundle file
touch bundle.crt
cd ..

echo -e "${YELLOW}Step 2: Starting SPIRE Server...${NC}"
docker-compose -f docker-compose.spire.yml up -d spire-server
sleep 5

# Check if server is healthy
if curl -s http://localhost:8080/ready > /dev/null; then
    echo -e "${GREEN}✓ SPIRE Server is ready${NC}"
else
    echo -e "${RED}✗ SPIRE Server failed to start${NC}"
    docker-compose -f docker-compose.spire.yml logs spire-server
    exit 1
fi

echo -e "${YELLOW}Step 3: Generating join token for agent...${NC}"
JOIN_TOKEN=$(docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server token generate \
    -spiffeID spiffe://agentvault.com/spire-agent \
    -ttl 3600 2>/dev/null | grep -oP 'Token: \K.*')

if [ -z "$JOIN_TOKEN" ]; then
    echo -e "${RED}✗ Failed to generate join token${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Join token generated: ${JOIN_TOKEN:0:20}...${NC}"

echo -e "${YELLOW}Step 4: Starting SPIRE Agent with join token...${NC}"
export SPIRE_AGENT_JOIN_TOKEN="$JOIN_TOKEN"
docker-compose -f docker-compose.spire.yml up -d spire-agent
sleep 5

# Check if agent is healthy
if curl -s http://localhost:8082/ready > /dev/null; then
    echo -e "${GREEN}✓ SPIRE Agent is ready${NC}"
else
    echo -e "${RED}✗ SPIRE Agent failed to start${NC}"
    docker-compose -f docker-compose.spire.yml logs spire-agent
    exit 1
fi

echo -e "${YELLOW}Step 5: Registering sample workload...${NC}"
# Register with Unix UID selector
docker exec agentvault-spire-server \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://agentvault.com/spire-agent \
    -spiffeID spiffe://agentvault.com/sample-workload \
    -selector unix:uid:1000 \
    -ttl 3600 > /dev/null 2>&1

echo -e "${GREEN}✓ Sample workload registered${NC}"

echo -e "${YELLOW}Step 6: Building sample workload...${NC}"
docker-compose -f docker-compose.spire.yml build sample-workload > /dev/null 2>&1
echo -e "${GREEN}✓ Sample workload built${NC}"

echo -e "${YELLOW}Step 7: Starting sample workload...${NC}"
docker-compose -f docker-compose.spire.yml up -d sample-workload

echo ""
echo -e "${GREEN}=== AgentVault Identity Fabric Initialized Successfully ===${NC}"
echo ""
echo "Next steps:"
echo "  - View sample workload logs: docker-compose -f docker-compose.spire.yml logs -f sample-workload"
echo "  - Check registration entries: docker exec agentvault-spire-server /opt/spire/bin/spire-server entry show"
echo "  - Stop all services: docker-compose -f docker-compose.spire.yml down"
echo ""
echo "The sample workload should now be fetching its SPIFFE identity!"
