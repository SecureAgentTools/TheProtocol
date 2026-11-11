#!/bin/sh
# The SFTP poll source's server tests (tests/test_proxy_source_sftp_server.py) against a real OpenSSH server.
#
#   sh tests/sftp_server/run.sh [python version, default 3.12] [pytest arguments]
#
# Run it from theprotocol-sdk/ on a host with docker and ssh-keygen. What it makes, all removed at the end: a docker
# network of its own; atmoz/sftp (OpenSSH's internal-sftp) on it, configured by sshd_config beside this file, with a
# host key and a login key made now in a temporary folder, the account "proxy" (the key only) and the account "twofa"
# (the key, then a password); a supervisor that restarts the server when the restart test asks (the test writes
# "restart" into a file, the supervisor writes "restarted" once the server listens again); and the test container,
# python:<version>-bookworm, with this SDK installed with the proxy-sftp extra. TP_SFTP_PIP_CACHE=<folder> lends pip a
# cache folder.
set -eu
PY=${1:-3.12}
[ $# -gt 0 ] && shift
command -v docker >/dev/null && command -v ssh-keygen >/dev/null || { echo "run.sh needs docker and ssh-keygen"; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
SDK=$(cd "$HERE/../.." && pwd)
RUN="tp-sftp-test-$$"
SERVER="$RUN-server"
TMP=$(mktemp -d)
SUPERVISOR=""

cleanup() {
    if [ -n "$SUPERVISOR" ]; then kill "$SUPERVISOR" 2>/dev/null || true; fi
    docker rm -f "$SERVER" >/dev/null 2>&1 || true
    docker network rm "$RUN" >/dev/null 2>&1 || true
    rm -rf "$TMP"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

mkdir -p "$TMP/keys" "$TMP/pub" "$TMP/sig"
ssh-keygen -q -t ed25519 -N '' -C "$SERVER" -f "$TMP/host"
ssh-keygen -q -t ed25519 -N '' -C "$RUN-login" -f "$TMP/keys/login"
cp "$TMP/keys/login.pub" "$TMP/pub/login.pub"
echo "$SERVER $(cut -d' ' -f1,2 "$TMP/host.pub")" > "$TMP/keys/known_hosts"
TWOFA_PASSWORD=$(od -An -N12 -tx1 /dev/urandom | tr -d ' \n')
chmod 755 "$TMP" "$TMP/keys" "$TMP/pub"
chmod 644 "$TMP/keys/known_hosts" "$TMP/keys/login.pub" "$TMP/pub/login.pub"
chmod 600 "$TMP/host" "$TMP/keys/login"
chmod 777 "$TMP/sig"
: > "$TMP/sig/restart"
chmod 666 "$TMP/sig/restart"

listening() {   # port 22 in LISTEN, read inside the server (its image has neither ss nor netstat)
    docker exec "$SERVER" sh -c 'grep -q ":0016 00000000:0000 0A" /proc/net/tcp' 2>/dev/null
}

docker network create "$RUN" >/dev/null
docker run -d --name "$SERVER" --network "$RUN" --memory=512m --cpus=1 \
    -v "$HERE/sshd_config:/etc/ssh/sshd_config:ro" \
    -v "$TMP/host:/etc/ssh/ssh_host_ed25519_key:ro" \
    -v "$TMP/pub/login.pub:/home/proxy/.ssh/keys/login.pub:ro" \
    -v "$TMP/pub/login.pub:/home/twofa/.ssh/keys/login.pub:ro" \
    atmoz/sftp:alpine "proxy::1001:100:inbox" "twofa:$TWOFA_PASSWORD:1002:100:inbox" >/dev/null
i=0
until listening; do
    i=$((i + 1))
    if [ "$i" -gt 120 ]; then echo "the SFTP server did not start"; docker logs "$SERVER" 2>&1 | tail -20; exit 1; fi
    sleep 0.5
done

( while :; do
    if [ "$(cat "$TMP/sig/restart" 2>/dev/null)" = "restart" ]; then
        docker restart -t 2 "$SERVER" >/dev/null
        i=0
        until listening || [ "$i" -ge 120 ]; do i=$((i + 1)); sleep 0.5; done
        echo restarted > "$TMP/sig/restart"
    fi
    sleep 0.5
  done ) &
SUPERVISOR=$!

docker run --rm --network "$RUN" --memory=3g --cpus=2 \
    -v "$SDK:/src:ro" -v "$TMP/keys:/keys:ro" -v "$TMP/sig:/sig" \
    ${TP_SFTP_PIP_CACHE:+-v "$TP_SFTP_PIP_CACHE:/root/.cache/pip"} \
    -e TP_SFTP_TEST_HOST="$SERVER" -e TP_SFTP_TEST_USER=proxy -e TP_SFTP_TEST_2FA_USER=twofa \
    -e TP_SFTP_TEST_KEY=/keys/login -e TP_SFTP_TEST_KNOWN_HOSTS=/keys/known_hosts -e TP_SFTP_TEST_DIR=inbox \
    -e TP_SFTP_TEST_RESTART=/sig/restart \
    "python:$PY-bookworm" sh -c 'cp -r /src /sdk && cd /sdk &&
        pip install --quiet --disable-pip-version-check --root-user-action=ignore -e ".[test,proxy,proxy-sftp]" &&
        python -m pytest -q -p no:cacheprovider -rs tests/test_proxy_source_sftp_server.py "$@"' sh "$@"
