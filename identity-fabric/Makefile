.PHONY: help init init-mtls init-jwt-svid up up-full down logs clean status register jwt-svid-test register-agent list-agents

# Default target
help:
	@echo "AgentVault Identity Fabric - Make Targets"
	@echo ""
	@echo "Basic SPIRE Operations:"
	@echo "  make init          - Initialize basic SPIRE infrastructure"
	@echo "  make up            - Start SPIRE server and agent only"
	@echo "  make down          - Stop all services"
	@echo "  make logs          - Show logs from all services"
	@echo "  make status        - Check service health status"
	@echo "  make register      - Show registration entries"
	@echo "  make clean         - Remove all containers and volumes"
	@echo ""
	@echo "Full Stack with mTLS:"
	@echo "  make init-mtls     - Initialize SPIRE with service registrations"
	@echo "  make up-full       - Start full stack (SPIRE + TEG + Registry)"
	@echo "  make test-mtls     - Test mTLS communication"
	@echo "  make status-full   - Check all services including apps"
	@echo ""
	@echo "JWT-SVID Authentication:"
	@echo "  make init-jwt-svid - Add JWT-SVID support to SPIRE"
	@echo "  make jwt-svid-test - Run JWT-SVID authentication tests"
	@echo "  make register-agent EMAIL=user@example.com - Register an agent"
	@echo "  make list-agents   - List registered agents"
	@echo ""
	@echo "OPA Policy Integration:"
	@echo "  make test-policy   - Test OPA policy checks"
	@echo "  make opa-logs      - Show OPA service logs"
	@echo "  make workload-logs - Show sample workload logs"
	@echo ""

# Initialize basic SPIRE infrastructure
init:
	@chmod +x init-spire.sh
	@./init-spire.sh

# Initialize SPIRE with mTLS service registrations
init-mtls:
	@chmod +x init-spire-mtls.sh
	@./init-spire-mtls.sh

# Initialize JWT-SVID support
init-jwt-svid: init-mtls
	@chmod +x init-spire-jwt-svid.sh
	@./init-spire-jwt-svid.sh

# Start basic SPIRE services
up:
	docker-compose -f docker-compose.spire.yml up -d

# Start full stack with applications
up-full:
	docker-compose -f docker-compose.full.yml up -d

# Stop services
down:
	docker-compose -f docker-compose.spire.yml down
	docker-compose -f docker-compose.full.yml down

# Show logs
logs:
	docker-compose -f docker-compose.spire.yml logs -f

# Show logs for full stack
logs-full:
	docker-compose -f docker-compose.full.yml logs -f

# Check basic service status
status:
	@echo "=== SPIRE Service Status ==="
	@docker-compose -f docker-compose.spire.yml ps
	@echo ""
	@echo "=== Health Checks ==="
	@echo -n "SPIRE Server: "
	@curl -s http://localhost:8080/ready > /dev/null && echo "✓ Ready" || echo "✗ Not Ready"
	@echo -n "SPIRE Agent:  "
	@curl -s http://localhost:8082/ready > /dev/null && echo "✓ Ready" || echo "✗ Not Ready"

# Check full stack status
status-full: status
	@echo ""
	@echo "=== Application Status ==="
	@echo -n "TEG Core Service:    "
	@curl -sk https://localhost:8001/health | jq -r '. | "✓ Ready (mTLS: \(.checks.mtls.status), JWT-SVID: \(.checks.jwt_svid_validator.status))"' 2>/dev/null || echo "✗ Not Ready"
	@echo -n "Registry Backend:    "
	@curl -s http://localhost:8000/health | jq -r '. | "✓ Ready (mTLS: \(.mtls_enabled))"' 2>/dev/null || echo "✗ Not Ready"

# Test mTLS communication
test-mtls:
	@echo "=== Testing mTLS Communication ==="
	@echo ""
	@echo "1. Direct TEG access (should fail - no client cert):"
	@curl -s https://localhost:8001/api/v1/token/fee-config --insecure || echo "✓ Correctly rejected - client certificate required"
	@echo ""
	@echo "2. TEG access via Registry (should work - has client cert):"
	@curl -s http://localhost:8000/api/v1/teg/fee-config | jq '.' || echo "✗ Failed - check service logs"

# Show registration entries
register:
	@echo "=== SPIRE Registration Entries ==="
	@docker exec agentvault-spire-server /opt/spire/bin/spire-server entry show || echo "Server not running"

# Clean everything
clean:
	docker-compose -f docker-compose.spire.yml down -v
	docker-compose -f docker-compose.full.yml down -v
	rm -f spire-server/dummy_upstream_ca.* spire-server/bundle.crt

# Additional useful targets
server-logs:
	docker-compose -f docker-compose.spire.yml logs -f spire-server

agent-logs:
	docker-compose -f docker-compose.spire.yml logs -f spire-agent

workload-logs:
	docker-compose -f docker-compose.spire.yml logs -f sample-workload

opa-logs:
	docker-compose -f docker-compose.spire.yml logs -f opa

teg-logs:
	docker-compose -f docker-compose.full.yml logs -f teg-core

registry-logs:
	docker-compose -f docker-compose.full.yml logs -f registry-backend

# Generate new join token
token:
	@docker exec agentvault-spire-server \
		/opt/spire/bin/spire-server token generate \
		-spiffeID spiffe://agentvault.com/spire-agent \
		-ttl 3600

# Test workload attestation
test-attestation:
	@docker exec agentvault-spire-agent \
		/opt/spire/bin/spire-agent api fetch x509 \
		-socketPath /opt/spire/sockets/agent.sock

# Initialize databases
init-db:
	@echo "=== Initializing Databases ==="
	@echo "Initializing TEG database..."
	@docker exec agentvault-teg-core poetry run alembic upgrade head || echo "TEG Core not running"
	@docker exec agentvault-teg-core poetry run python scripts/initialize_db.py || true
	@docker exec agentvault-teg-core poetry run python scripts/issue_initial_tokens.py did:theprotocol:teg_system_treasury 10000.0 || true
	@echo ""
	@echo "Initializing Registry database..."
	@docker exec agentvault-registry-backend poetry run alembic upgrade head || echo "Registry not running"

# Quick start for development
quick-start: init-jwt-svid up-full init-db status-full
	@echo ""
	@echo "=== AgentVault Identity Fabric with mTLS and JWT-SVID is Ready! ==="
	@echo ""
	@echo "Services available at:"
	@echo "  - Registry API:     http://localhost:8000"
	@echo "  - TEG API (mTLS):   https://localhost:8001"
	@echo "  - SPIRE Server API: http://localhost:8081"
	@echo ""
	@echo "Test with: make test-mtls"
	@echo "Test JWT-SVID: make jwt-svid-test"

# Monitor SVID activity
monitor-svids:
	@echo "=== Monitoring SVID Activity ==="
	@echo "Press Ctrl+C to stop"
	@docker-compose -f docker-compose.full.yml logs -f | grep -E "(SVID|SPIFFE|mTLS)"

# Show certificates
show-certs:
	@echo "=== X.509 SVIDs Issued ==="
	@docker exec agentvault-spire-agent \
		/opt/spire/bin/spire-agent api fetch x509 \
		-socketPath /opt/spire/sockets/agent.sock \
		-write /tmp/svids
	@docker exec agentvault-spire-agent ls -la /tmp/svids/

# Run JWT-SVID test suite
jwt-svid-test:
	@echo "=== Running JWT-SVID Authentication Tests ==="
	@python test_jwt_svid_e2e.py

# Register an agent for JWT-SVID
register-agent:
ifndef EMAIL
	$(error EMAIL is required. Usage: make register-agent EMAIL=user@example.com)
endif
	@echo "Registering agent: $(EMAIL)"
	@SAFE_AGENT_ID=$$(echo "$(EMAIL)" | sed 's/@/_at_/g' | sed 's/\./_dot_/g'); \
	docker exec agentvault-spire-server \
		/opt/spire/bin/spire-server entry create \
		-parentID spiffe://agentvault.com/service/registry-backend \
		-spiffeID "spiffe://agentvault.com/agent/$$SAFE_AGENT_ID" \
		-selector "k8s:ns:agentvault" \
		-selector "k8s:sa:agent-$$SAFE_AGENT_ID" \
		-ttl 3600 \
		-jwtSVIDTTL 300
	@echo "✓ Agent registered: spiffe://agentvault.com/agent/$$SAFE_AGENT_ID"

# List registered agents
list-agents:
	@echo "=== Registered Agents ==="
	@docker exec agentvault-spire-server \
		/opt/spire/bin/spire-server entry show | \
		grep -B2 -A3 "spiffe://agentvault.com/agent/" || echo "No agents registered"

# Test OPA policy integration
test-policy:
	@echo "=== Testing OPA Policy Integration ==="
	@echo "Checking sample workload logs for policy decision..."
	@docker-compose -f docker-compose.spire.yml logs sample-workload | grep "Policy decision:" | tail -n 1 || echo "No policy decision found in logs"
	@echo ""
	@echo "For full logs, run: make workload-logs"

# Test JWT-SVID acquisition
test-jwt-acquisition:
	@echo "=== Testing JWT-SVID Acquisition ==="
	@docker exec agentvault-registry-backend python -c "\
from agentvault_registry.core.jwt_svid_provider import acquire_agent_jwt_svid; \
import asyncio; \
try: \
    token = asyncio.run(acquire_agent_jwt_svid('test@example.com')); \
    print('✓ JWT-SVID acquired successfully'); \
    print(f'Token preview: {token[:50]}...'); \
except Exception as e: \
    print(f'✗ Failed: {e}')"

# Debug JWT-SVID operations
debug-jwt-svid:
	@echo "=== JWT-SVID Debug Information ==="
	@echo ""
	@echo "Registry JWT-SVID logs:"
	@docker logs agentvault-registry-backend 2>&1 | grep -i "jwt-svid" | tail -10
	@echo ""
	@echo "TEG JWT-SVID validation logs:"
	@docker logs agentvault-teg-core 2>&1 | grep -i "jwt-svid" | tail -10
