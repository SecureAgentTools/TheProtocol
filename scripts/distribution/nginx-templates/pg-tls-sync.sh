#!/bin/sh
# §MTLSHOPS T3 (2026-09-15, agentvault2-b5): the frame's Postgres serves TLS on the data identity's SVID.
# Runs as root before the image's entrypoint. Postgres refuses a key file that group or others can read, and the
# cert-writer writes the key 0644, so the server reads a postgres-owned copy (key 0600) on a tmpfs. Any change to the three
# files is copied again and the postmaster gets SIGHUP: Postgres reloads its SSL files then, and when the new pair does not
# load it logs "SSL configuration was not reloaded" and keeps serving the previous one (measured, t3lab). The first copy
# waits for the data cert-writer, so the server never starts without TLS.
SRC=/certs; TLS=/run/pgtls/server
stamp() { cat $SRC/svid.0.pem $SRC/svid.0.key $SRC/bundle.0.pem 2>/dev/null | sha256sum | cut -c1-64; }
copy() {
  mkdir -p $TLS && chown postgres:postgres $TLS && chmod 700 $TLS || return 1
  for f in svid.0.pem svid.0.key bundle.0.pem; do cp $SRC/$f $TLS/.$f.new || return 1; done
  chown postgres:postgres $TLS/.svid.0.pem.new $TLS/.svid.0.key.new $TLS/.bundle.0.pem.new || return 1
  chmod 600 $TLS/.svid.0.key.new && chmod 644 $TLS/.svid.0.pem.new $TLS/.bundle.0.pem.new || return 1
  for f in svid.0.pem svid.0.key bundle.0.pem; do mv $TLS/.$f.new $TLS/$f || return 1; done
}
echo "[pg-tls] waiting for the data SVID in $SRC"
until [ -f $SRC/.ready ] && [ -s $SRC/svid.0.pem ] && [ -s $SRC/svid.0.key ] && [ -s $SRC/bundle.0.pem ]; do sleep 1; done
copy || { echo "[pg-tls] the data SVID could not be copied for the server"; exit 1; }
( last=$(stamp)
  while sleep ${TLS_SYNC_SEC:-30}; do
    now=$(stamp); [ "$now" = "$last" ] && continue
    sleep 2; now=$(stamp)
    pid=$(head -1 "${PGDATA:-/var/lib/postgresql/data}/postmaster.pid" 2>/dev/null)
    if copy && [ -n "$pid" ] && kill -HUP "$pid"; then last=$now; echo "[pg-tls] the SVID changed: copied and sent SIGHUP"; fi
  done ) &
exec docker-entrypoint.sh "$@"
