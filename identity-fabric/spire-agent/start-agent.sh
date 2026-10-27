#!/bin/sh
# Spire Agent startup script with automatic token generation

echo "Starting Spire Agent initialization..."

# Wait for Spire server to be healthy
echo "Waiting for Spire server to be healthy..."
until /opt/spire/bin/spire-server healthcheck -socketPath /tmp/spire-server/private/api.sock 2>/dev/null; do
  echo "Spire server not ready, waiting..."
  sleep 2
done

echo "Spire server is healthy!"

# Request join token from server
echo "Requesting join token from Spire server..."
JOIN_TOKEN=$(/opt/spire/bin/spire-server token generate \
  -socketPath /tmp/spire-server/private/api.sock \
  -spiffeID spiffe://agentvault.com/agent \
  | grep "Token:" | cut -d' ' -f2)

if [ -z "$JOIN_TOKEN" ]; then
  echo "ERROR: Failed to generate join token"
  exit 1
fi

echo "Got join token: $JOIN_TOKEN"

# Create agent config with the token
cat > /opt/spire/conf/agent.conf <<EOF
agent {
  data_dir = "/opt/spire/data"
  log_level = "INFO"
  server_address = "spire-server"
  server_port = "8081"
  socket_path = "/opt/spire/sockets/agent.sock"
  trust_bundle_path = "/opt/spire/conf/bundle.crt"
  trust_domain = "agentvault.com"
  
  # Administrative UNIX socket for health checks - moved to different directory
  admin_socket_path = "/opt/spire/admin/admin.sock"
}

plugins {
  NodeAttestor "join_token" {
    plugin_data {
      join_token = "$JOIN_TOKEN"
    }
  }

  KeyManager "disk" {
    plugin_data {
      directory = "/opt/spire/data"
    }
  }

  WorkloadAttestor "unix" {
    plugin_data {
    }
  }

  WorkloadAttestor "docker" {
    plugin_data {
      # Docker daemon socket path
      docker_socket_path = "/var/run/docker.sock"
    }
  }
}

health_checks {
  listener_enabled = true
  bind_address = "0.0.0.0"
  bind_port = "8082"
  live_path = "/live"
  ready_path = "/ready"
}
EOF

echo "Starting Spire agent with token..."
exec /opt/spire/bin/spire-agent run -config /opt/spire/conf/agent.conf
