#!/bin/bash
# registry-auth-manager.sh — Manage operator access to TheProtocol Docker registry
# Usage:
#   ./registry-auth-manager.sh add <operator-id> <password>
#   ./registry-auth-manager.sh remove <operator-id>
#   ./registry-auth-manager.sh list
#   ./registry-auth-manager.sh init    # Create initial htpasswd file + admin user
set -e

AUTH_DIR="$(dirname "$0")/registry-auth"
HTPASSWD_FILE="${AUTH_DIR}/htpasswd"

case "${1}" in
  init)
    mkdir -p "${AUTH_DIR}"
    # Create admin user (us — for pushing images)
    ADMIN_PASS="${2:-$(openssl rand -hex 16)}"
    docker run --rm --entrypoint htpasswd httpd:2.4-alpine -Bbn "theprotocol-admin" "${ADMIN_PASS}" > "${HTPASSWD_FILE}"
    echo "Admin credentials:"
    echo "  Username: theprotocol-admin"
    echo "  Password: ${ADMIN_PASS}"
    echo "  Login:    docker login images.theprotocol.cloud -u theprotocol-admin -p ${ADMIN_PASS}"
    ;;
  add)
    [ -z "$2" ] && echo "Usage: $0 add <operator-id> <password>" && exit 1
    OPERATOR_ID="$2"
    OPERATOR_PASS="${3:-$(openssl rand -hex 16)}"
    docker run --rm --entrypoint htpasswd httpd:2.4-alpine -Bbn "${OPERATOR_ID}" "${OPERATOR_PASS}" >> "${HTPASSWD_FILE}"
    echo "Operator added:"
    echo "  Username: ${OPERATOR_ID}"
    echo "  Password: ${OPERATOR_PASS}"
    echo "  Login:    docker login images.theprotocol.cloud -u ${OPERATOR_ID} -p ${OPERATOR_PASS}"
    ;;
  remove)
    [ -z "$2" ] && echo "Usage: $0 remove <operator-id>" && exit 1
    # Remove line matching username
    sed -i "/^${2}:/d" "${HTPASSWD_FILE}"
    echo "Removed operator: $2"
    echo "Restart registry to apply: docker restart theprotocol_image_registry"
    ;;
  list)
    echo "Registered operators:"
    cut -d: -f1 "${HTPASSWD_FILE}" 2>/dev/null | while read user; do
      echo "  - ${user}"
    done
    ;;
  *)
    echo "Usage: $0 {init|add|remove|list}"
    exit 1
    ;;
esac
