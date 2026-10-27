# AgentVault Identity Fabric - SPIFFE/SPIRE Foundation

This repository contains the foundational implementation of the AgentVault Identity Fabric using SPIFFE/SPIRE for cryptographic workload identity management.

## Quick Start

```bash
# Initialize and start the entire stack
make init

# View sample workload fetching its identity
make workload-logs

# Check service status
make status
```

## Project Structure

```
identity-fabric/
├── docker-compose.spire.yml    # Main orchestration file
├── init-spire.sh              # Automated initialization script
├── Makefile                   # Convenience commands
│
├── spire-server/              # SPIRE Server configuration
│   ├── server.conf           # Server configuration
│   └── generate_dummy_ca.sh  # MVP CA generation
│
├── spire-agent/              # SPIRE Agent configuration
│   └── agent.conf           # Agent configuration
│
├── sample-workload/          # Example workload implementation
│   ├── app.py               # Python workload demonstrating SVID fetch
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile          # Container definition
│
└── docs/                    # Comprehensive documentation
    ├── SPIRE_SETUP_GUIDE.md        # Step-by-step setup instructions
    ├── SAMPLE_WORKLOAD_README.md   # Workload integration patterns
    └── IDENTITY_FABRIC_MVP.md      # Architecture and design decisions
```

## Key Features

- **Zero Trust Identity**: Every workload gets a cryptographic identity
- **Automatic Rotation**: SVIDs are automatically rotated before expiry
- **Standards-Based**: Built on SPIFFE specification for interoperability
- **Docker-Native**: Fully containerized for easy development
- **Production-Ready Path**: Clear upgrade path from MVP to production
- **Policy Enforcement**: OPA integration for fine-grained authorization (NEW)

## Architecture Overview

```
┌─────────────────────┐     ┌─────────────────────┐
│   SPIRE Server      │     │    OPA Server       │
│ Trust Domain:       │────▶│ Policy Decision     │
│ agentvault.com      │     │ Point               │
└──────────┬──────────┘     └──────────▲──────────┘
           │                           │
┌──────────▼──────────┐                │
│   SPIRE Agent       │                │
│ Node Attestation    │                │
│ Workload Attestation│                │
└──────────┬──────────┘                │
           │                           │
┌──────────▼──────────┐                │
│  Sample Workload    │────────────────┘
│ SPIFFE ID:          │ ← Identity + Authorization
│ spiffe://agentvault │
│ .com/sample-workload│
└─────────────────────┘
```

## Available Commands

```bash
make help        # Show all available commands
make init        # First-time setup (automated)
make up          # Start services
make down        # Stop services
make logs        # View all logs
make status      # Check health status
make register    # Show workload registrations
make clean       # Remove everything

# OPA Policy Commands
make test-policy    # Test OPA policy integration
make opa-logs      # View OPA decision logs
make workload-logs # View sample workload logs
```

## Documentation

- **[SPIRE Setup Guide](docs/SPIRE_SETUP_GUIDE.md)**: Complete setup instructions
- **[Sample Workload README](docs/SAMPLE_WORKLOAD_README.md)**: Integration patterns and code examples
- **[Identity Fabric MVP](docs/IDENTITY_FABRIC_MVP.md)**: Architecture decisions and future roadmap
- **[OPA Integration](docs/OPA_INTEGRATION.md)**: Policy layer implementation guide (NEW)

## Integration Example

```python
# Any AgentVault component can now obtain identity:
from pyspiffe.workloadapi import default_workload_api_client

with default_workload_api_client() as client:
    # Get X.509 certificate for mTLS
    x509_context = client.fetch_x509_context()
    x509_svid = x509_context.default_svid()
    
    # Get JWT for API authentication
    jwt_svids = client.fetch_jwt_svid(audiences=["my-service"])
    jwt_token = jwt_svids[0].token
```

## Security Notes

This MVP implementation uses:
- Self-signed CA (replace in production)
- Join token attestation (upgrade to platform-specific in production)
- Conservative TTLs (1h for X.509, 5m for JWT)

## Next Steps

1. Review the comprehensive documentation in `/docs`
2. Run the sample workload to see identity in action
3. Integrate SPIFFE identity into your AgentVault components
4. Plan production deployment with proper PKI

## Requirements

- Docker & Docker Compose
- OpenSSL (for CA generation)
- Make (optional, for convenience commands)

---

**"Excellence Mode" Implementation** - Built with the Warrior Owl philosophy: robust, secure, and ready for scale.
