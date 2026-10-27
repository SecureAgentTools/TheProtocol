#!/bin/sh
# §MTLSHOPS T3 (2026-09-15, agentvault2-b5): an app's private copy of its own SVID, for Postgres.
# libpq refuses a key file that group or others can read, and the cert-writer writes the key 0644, so the registry and the
# TEG (the migration bridge, alembic, the TEG's runtime sync engine) read their certificate, key and bundle from a copy
# this loop keeps as the app's own uid in a 0700 directory on a tmpfs, key 0600. A copy replaces the previous one only when
# the new certificate and key load together, so a half-written rotation never replaces a working pair (measured, t3lab2).
# asyncpg and libpq read these paths at every connect, so a rotation reaches new connections without a restart. The app's
# command waits for the first copy (its bundle is moved last).
SRC=${SVID_SRC:-/certs}; DST=${PGTLS_DIR:-/run/pgtls/client}; PY=$(command -v python3 || command -v python)
stamp() { cat $SRC/svid.0.pem $SRC/svid.0.key $SRC/bundle.0.pem 2>/dev/null | sha256sum | cut -c1-64; }
copy() {
  umask 077; mkdir -p $DST || return 1
  for f in svid.0.pem svid.0.key bundle.0.pem; do cp $SRC/$f $DST/.$f.new 2>/dev/null || return 1; done
  "$PY" -c 'import ssl, sys; ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_cert_chain(sys.argv[1], sys.argv[2])' \
      $DST/.svid.0.pem.new $DST/.svid.0.key.new 2>/dev/null || return 1
  chmod 600 $DST/.svid.0.key.new; chmod 644 $DST/.svid.0.pem.new $DST/.bundle.0.pem.new
  for f in svid.0.pem svid.0.key bundle.0.pem; do mv $DST/.$f.new $DST/$f; done
}
echo "[pgtls] waiting for a certificate and key that load together in $SRC"
until copy; do sleep 1; done
echo "[pgtls] first copy in place"
last=$(stamp)
while sleep ${TLS_SYNC_SEC:-30}; do
  now=$(stamp); [ "$now" = "$last" ] && continue
  sleep 2; now=$(stamp)
  if copy; then last=$now; echo "[pgtls] copied the rotated SVID"; else echo "[pgtls] the new pair does not load together yet; the previous copy stays"; fi
done
