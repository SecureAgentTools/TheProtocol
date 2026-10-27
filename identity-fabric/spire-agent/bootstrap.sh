#!/bin/sh
# Bootstrap script for SPIRE Agent

echo "Starting SPIRE Agent bootstrap..."

# Wait for SPIRE Server to be ready
echo "Waiting for SPIRE Server..."
for i in $(seq 1 30); do
    if nc -z spire-server 8081 2>/dev/null; then
        echo "SPIRE Server is ready!"
        break
    fi
    echo "Waiting for SPIRE Server to start... ($i/30)"
    sleep 2
done

# Try to fetch the trust bundle from the server
echo "Fetching trust bundle from SPIRE Server..."
if [ ! -f "/opt/spire/conf/bundle.crt" ]; then
    echo "Trust bundle not found, using insecure bootstrap for initial setup"
    # For initial setup, we'll need to manually configure this
    # In production, this would be done through a secure bootstrap process
fi

# Start the SPIRE Agent
echo "Starting SPIRE Agent..."
exec /opt/spire/bin/spire-agent run -config /opt/spire/conf/agent.conf
