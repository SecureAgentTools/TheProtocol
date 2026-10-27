# AgentVault Sample SPIFFE Workload

This sample workload demonstrates how AgentVault components can integrate with SPIFFE/SPIRE to obtain and use cryptographic identities (SVIDs).

## Purpose

The sample workload serves as a reference implementation for:

1. **SVID Fetching**: Demonstrates how to fetch both X.509 and JWT SVIDs using pySpiffe
2. **Identity Verification**: Shows how to extract and log SPIFFE ID information
3. **Error Handling**: Implements robust retry logic for identity acquisition
4. **SVID Watching**: Demonstrates how to watch for SVID updates/rotations

## Architecture

```python
AgentVaultWorkload
├── fetch_x509_svid()    # Fetches X.509 certificate-based identity
├── fetch_jwt_svid()     # Fetches JWT-based identity  
└── watch_x509_updates() # Monitors for certificate rotation
```

## Key Components

### pySpiffe Integration

The workload uses the official pySpiffe library to interact with the SPIRE Agent's Workload API:

```python
from pyspiffe.workloadapi import default_workload_api_client
from pyspiffe.svid.x509_svid import X509Svid
from pyspiffe.svid.jwt_svid import JwtSvid

# Fetch X.509 SVID
with default_workload_api_client() as client:
    x509_context = client.fetch_x509_context()
    svid = x509_context.default_svid()
    spiffe_id = svid.spiffe_id
```

### X.509 SVID Fetching

X.509 SVIDs are certificate-based identities used for mTLS communication:

```python
def fetch_x509_svid(self):
    """Fetch X.509 SVID from SPIRE Agent"""
    with default_workload_api_client() as client:
        x509_context = client.fetch_x509_context()
        self.x509_svid = x509_context.default_svid()
        
        # Extract identity information
        logger.info(f"SPIFFE ID: {self.x509_svid.spiffe_id}")
        logger.info(f"Certificate Serial: {self.x509_svid.leaf.serial_number}")
        logger.info(f"Expires: {self.x509_svid.leaf.not_valid_after}")
```

### JWT SVID Fetching

JWT SVIDs are token-based identities used for API authentication:

```python
def fetch_jwt_svid(self):
    """Fetch JWT SVID from SPIRE Agent"""
    with default_workload_api_client() as client:
        # Define audience for the JWT
        audience = ["agentvault-service"]
        
        # Fetch JWT SVID
        jwt_svids = client.fetch_jwt_svid(audiences=audience)
        self.jwt_svid = jwt_svids[0]
        
        logger.info(f"JWT SPIFFE ID: {self.jwt_svid.spiffe_id}")
        logger.info(f"JWT Audience: {self.jwt_svid.audience}")
```

### SVID Rotation Monitoring

The workload can watch for SVID updates to handle certificate rotation:

```python
def watch_x509_updates(self):
    """Watch for X.509 SVID updates"""
    with default_workload_api_client() as client:
        for x509_context in client.watch_x509_context():
            svid = x509_context.default_svid()
            logger.info(f"SVID rotated - New expiry: {svid.leaf.not_valid_after}")
```

## Docker Configuration

### Dockerfile Highlights

```dockerfile
# Run as non-root user for security
RUN useradd -m -u 1000 agentvault
USER agentvault

# Configure Workload API socket location
ENV SPIFFE_ENDPOINT_SOCKET=unix:///spire-agent-socket/agent.sock
```

### Volume Mount Requirements

The workload requires access to the SPIRE Agent's Unix Domain Socket:

```yaml
volumes:
  - spire-agent-socket:/spire-agent-socket
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SPIFFE_ENDPOINT_SOCKET` | Path to SPIRE Agent Workload API socket | `unix:///spire-agent-socket/agent.sock` |

## Error Handling

The workload implements several error handling strategies:

1. **Retry Logic**: Attempts SVID fetching up to 5 times with 5-second intervals
2. **Startup Delay**: Waits 10 seconds for SPIRE Agent readiness
3. **Graceful Degradation**: Logs errors and continues operation even if SVID fetch fails
4. **Exception Handling**: Catches both PySpiffe-specific and general exceptions

## Usage in AgentVault

This pattern can be applied to any AgentVault component that needs SPIFFE identity:

1. **TEG Core Service**: Use X.509 SVIDs for mTLS between TEG instances
2. **Agent Executors**: Use JWT SVIDs for API authentication
3. **Chronicle Service**: Use X.509 SVIDs for secure event streaming
4. **Registry Service**: Validate agent identities using SPIFFE IDs

## Development Tips

### Local Testing

Test the workload without full SPIRE setup:

```bash
# Build the image
docker build -t agentvault-sample-workload ./sample-workload

# Run with mock socket (will fail but allows testing startup)
docker run --rm -e SPIFFE_ENDPOINT_SOCKET=/dev/null agentvault-sample-workload
```

### Debugging SVID Issues

Enable debug logging by modifying the workload:

```python
import logging
logging.getLogger('pyspiffe').setLevel(logging.DEBUG)
```

### Integration with AgentVault Components

To integrate SPIFFE identity into your AgentVault component:

1. Add pyspiffe to requirements
2. Initialize workload API client at startup
3. Fetch SVID before establishing connections
4. Use SVID for mTLS or include JWT in API requests
5. Implement SVID rotation handling for long-running services

## Security Best Practices

1. **Non-root Execution**: Always run workloads as non-root users
2. **Socket Permissions**: Ensure proper permissions on Workload API socket
3. **SVID Validation**: Verify SPIFFE IDs match expected patterns
4. **Rotation Handling**: Implement proper SVID rotation for long-running services
5. **Audience Validation**: Use specific audiences for JWT SVIDs

## Future Enhancements

- Implement mTLS server using X.509 SVID
- Add Prometheus metrics for SVID operations
- Implement SVID-based authorization middleware
- Add support for federated identities
- Integrate with AgentVault's TEG authentication flow
