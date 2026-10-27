#!/bin/bash
# onboard-operator.sh — Full SPIRE identity onboarding for a new operator
# Usage: ./onboard-operator.sh <operator-name>
# Run on mainframe only. Creates operator-package/<name>/ with all files to ship.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OPERATOR_NAME="$1"

if [ -z "$OPERATOR_NAME" ]; then
    echo "Usage: $0 <operator-name>"
    echo "  Creates operator-package/<name>/ with SPIRE certs, agent config, nginx config"
    exit 1
fi

OUTPUT="${SCRIPT_DIR}/operator-package/${OPERATOR_NAME}"
mkdir -p "${OUTPUT}/spire" "${OUTPUT}/nginx"

echo ""
echo "================================================================"
echo "  Onboarding Operator: ${OPERATOR_NAME}"
echo "================================================================"
echo ""

# Step 1: Generate x509pop attestation certificates
echo "--- Step 1: Generate attestation certificates ---"
bash "${SCRIPT_DIR}/generate-operator-certs.sh" "${OPERATOR_NAME}" "${OUTPUT}/spire"

# Step 2: Export SPIRE trust bundle
echo ""
echo "--- Step 2: Export SPIRE trust bundle ---"
docker exec agentvault-spire-server /opt/spire/bin/spire-server bundle show -format pem > "${OUTPUT}/spire/trust-bundle.crt"
echo "  Trust bundle exported ($(wc -l < "${OUTPUT}/spire/trust-bundle.crt") lines)"

# Step 3: Register workload entries on mainframe
echo ""
echo "--- Step 3: Register workload entries ---"
bash "${SCRIPT_DIR}/register-operator-entries.sh" "${OPERATOR_NAME}" "${OUTPUT}/spire/agent-attestation.crt"

# Step 4: Generate agent.conf from template
echo ""
echo "--- Step 4: Generate agent config ---"
cat > "${OUTPUT}/spire/agent.conf" <<'AGENTEOF'
agent {
  data_dir = "/opt/spire/data"
  log_level = "INFO"
  server_address = "spire.theprotocol.cloud"
  server_port = "8444"
  socket_path = "/opt/spire/sockets/agent.sock"
  trust_bundle_path = "/opt/spire/conf/trust-bundle.crt"
  trust_domain = "agentvault.com"
}

plugins {
  NodeAttestor "x509pop" {
    plugin_data {
      private_key_path = "/opt/spire/conf/agent-attestation.key"
      certificate_path = "/opt/spire/conf/agent-attestation.crt"
    }
  }

  KeyManager "disk" {
    plugin_data {
      directory = "/opt/spire/data"
    }
  }

  WorkloadAttestor "docker" {
    plugin_data {
      docker_socket_path = "unix:///var/run/docker.sock"
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
AGENTEOF
echo "  agent.conf written"

# Step 5: Copy the operator stack's files: the set a frame's provisioner packs into a bundle (nginx-templates). It was
# an older nginx-federation-operator.conf that sent no X-Registry-Proxy-Auth marker and had no nginx-teg beside it, so a
# registry deployed from it counted no forwarded peer certificate and its federation mTLS authenticated nobody
# (CB-227). The generator renders the markers when the operator runs it.
echo ""
echo "--- Step 5: Copy the operator stack files ---"
TEMPLATES="${SCRIPT_DIR}/nginx-templates"
for f in nginx-federation.conf nginx-teg.conf nginx-entrypoint.sh; do
    cp "${TEMPLATES}/${f}" "${OUTPUT}/nginx/${f}"
done
chmod +x "${OUTPUT}/nginx/nginx-entrypoint.sh"
for f in docker-compose.operator.yml generate-operator-env.sh pgbouncer.ini; do
    cp "${TEMPLATES}/${f}" "${OUTPUT}/${f}"
done
chmod +x "${OUTPUT}/generate-operator-env.sh"
echo "  the compose, the env generator, pgbouncer.ini and the nginx confs copied"

# Step 6: Record for tracking
echo ""
FINGERPRINT=$(openssl x509 -in "${OUTPUT}/spire/agent-attestation.crt" -noout -fingerprint -sha1 | sed 's/://g' | awk -F= '{print tolower($2)}')
echo "${OPERATOR_NAME}|${FINGERPRINT}|$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${SCRIPT_DIR}/operator-registry.log"

echo "================================================================"
echo "  Operator package ready: ${OUTPUT}/"
echo ""
echo "  Contents:"
ls -la "${OUTPUT}/spire/" | grep -v "^total\|^\." | awk '{print "    " $NF}'
ls -la "${OUTPUT}/nginx/" | grep -v "^total\|^\." | awk '{print "    " $NF}'
echo ""
echo "  Ship to operator via secure channel."
echo "  In the package's directory the operator runs ./generate-operator-env.sh ${OPERATOR_NAME}"
echo "  (it writes .env.operator and renders the terminators' markers), sets FEDERATION_LICENSE_KEY,"
echo "  then: docker compose -f docker-compose.operator.yml --env-file .env.operator up -d"
echo "================================================================"
