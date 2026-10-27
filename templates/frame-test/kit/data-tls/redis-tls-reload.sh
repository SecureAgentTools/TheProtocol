#!/bin/sh
# §MTLSHOPS T3 (2026-09-15, agentvault2-b5): the frame's Redis serves TLS only, on the data identity's SVID.
# Runs as root before the image's entrypoint. Redis reads its TLS files at start and on CONFIG SET tls-*. The reload user
# exists only in this container's copy of the ACL file, its password only in this shell, and it reaches Redis over the
# unix socket, so a rotated certificate the server does not trust yet can never lock the reloader out (measured, t3lab: a
# mismatched pair is refused and the previous settings stay; pooled connections and a subscription survive a reload).
# CONFIG SET cannot turn into a file write: dir, dbfilename and the other protected configs are refused even for +@all.
SRC=/certs; RUN=/run/redis
echo "[redis-tls] waiting for the data SVID in $SRC"
until [ -f $SRC/.ready ] && [ -s $SRC/svid.0.pem ] && [ -s $SRC/svid.0.key ] && [ -s $SRC/bundle.0.pem ]; do sleep 1; done
PW=$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')
umask 077
cp /usr/local/etc/redis/users.acl $RUN/users.acl || exit 1
printf 'user tlsreload on #%s resetchannels -@all +config|set +ping\n' "$(printf %s "$PW" | sha256sum | cut -c1-64)" >> $RUN/users.acl
chown redis:redis $RUN/users.acl && chmod 600 $RUN/users.acl || exit 1
stamp() { cat $SRC/svid.0.pem $SRC/svid.0.key $SRC/bundle.0.pem 2>/dev/null | sha256sum | cut -c1-64; }
( last=$(stamp)
  while sleep ${TLS_SYNC_SEC:-30}; do
    now=$(stamp); [ "$now" = "$last" ] && continue
    sleep 2; now=$(stamp)
    out=$(REDISCLI_AUTH="$PW" redis-cli -s $RUN/redis.sock --user tlsreload --no-auth-warning CONFIG SET \
          tls-cert-file $SRC/svid.0.pem tls-key-file $SRC/svid.0.key tls-ca-cert-file $SRC/bundle.0.pem 2>&1)
    if [ "$out" = "OK" ]; then last=$now; echo "[redis-tls] the SVID changed: CONFIG SET reloaded it"
    else echo "[redis-tls] not reloaded yet: $(printf %s "$out" | head -c 160)"; fi
  done ) &
exec docker-entrypoint.sh redis-server "$@"
