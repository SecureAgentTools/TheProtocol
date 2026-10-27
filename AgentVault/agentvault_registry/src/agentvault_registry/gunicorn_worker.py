"""Custom gunicorn worker: the Uvicorn ASGI worker with proxy headers ON and a
TRUSTED PROXY SET rather than a blanket "*".

Why a subclass instead of relying on gunicorn's forwarded_allow_ips plumbing:
slowapi's per-IP rate limiting AND the admission-control middleware's lane
classification both key on the REAL client IP (X-Forwarded-For / X-Real-IP set by
the host nginx). If proxy_headers were off, every request would appear to come
from nginx's container IP -> one shared rate-limit bucket + a mislabeled admission
lane.

§XFFTRUST (2026-08-27) — why the value is no longer `"*"`. uvicorn's
ProxyHeadersMiddleware has two different algorithms:

    if self.always_trust:              # this is what "*" selects
        return x_forwarded_for_hosts[0]        # <- the element the CALLER wrote
    for host in reversed(x_forwarded_for_hosts):
        if host not in self: return host       # <- the closest UNTRUSTED hop

nginx sets `X-Forwarded-For $proxy_add_x_forwarded_for`, which APPENDS the real
peer, so the LAST element is ours and every element before it is caller-supplied.
Under `"*"` uvicorn took the FIRST one: measured 2026-08-27, a request carrying
`X-Forwarded-For: 203.0.113.77` was logged by registry-a as coming from
203.0.113.77. That value reaches `request.client.host`, and from there ~15 audit
and log call sites (`actor_ip`, `source_ip`, `submitted_from`) plus
`slowapi.util.get_remote_address`.

Naming the real proxies instead switches uvicorn to the reversed walk, which is
the correct algorithm for an appending edge:

  * external via nginx  -> peer is the docker bridge gateway (trusted), the walk
                           skips our own trusted hops and returns the public
                           address nginx appended. A forged prefix is ignored.
  * external DIRECT to a published container port -> peer is public, therefore
                           untrusted, so the headers are not consulted at all.
  * container-to-container -> no XFF header, nothing is rewritten.

The set is RFC1918 + loopback: every one of this host's 93 docker subnets sits
inside 172.16.0.0/12 (verified), and a packet arriving from the internet cannot
carry an RFC1918 source and still complete a handshake. `FORWARDED_ALLOW_IPS`
overrides it for an operator whose proxy topology differs — a registry behind a
cloud load balancer needs that LB's range here, and getting it WRONG is
self-announcing: every external client collapses into one bucket at the gateway
address. Set it to `*` to restore the old (forgeable) behaviour.

(uvicorn.workers.UvicornWorker is deprecated + gunicorn-coupled; we use the
standalone `uvicorn-worker` package -> uvicorn_worker.UvicornWorker.)
"""
import os

from uvicorn_worker import UvicornWorker

# Loopback + RFC1918. Comma-separated; CIDR is supported by uvicorn's _TrustedHosts.
DEFAULT_FORWARDED_ALLOW_IPS = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

FORWARDED_ALLOW_IPS = os.getenv("FORWARDED_ALLOW_IPS", "").strip() or DEFAULT_FORWARDED_ALLOW_IPS


class RegistryWorker(UvicornWorker):
    CONFIG_KWARGS = {
        "loop": "auto",
        "http": "auto",
        "proxy_headers": True,
        "forwarded_allow_ips": FORWARDED_ALLOW_IPS,
    }
